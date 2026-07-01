"""PageIndex HelpCenterAgent — vectorless tree-search retrieval.

Replaces tools/rag_responder.py's HelpCenterAgent with a version that:
  - builds a hierarchical tree index from documents (no embeddings/vector DB)
  - at query time, has GPT-4o reason over the tree outline to pick sections
  - answers using only the selected section texts
API surface (class name, public methods, response dict shape) is identical.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import List

from langchain.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from tools import page_index as pi

# ── constants ─────────────────────────────────────────────────────────────────

UNANSWERED_TEXT = (
    "I don't have specific information about that in our airline documents."
)

DOC_ROUTE_SYSTEM = (
    "You are a document routing assistant for an airline support knowledge base. "
    "Given a compact document roster and a question, identify which documents "
    "are most likely to contain the answer."
)

DOC_ROUTE_USER = (
    "Available documents (each identified by [file_key]):\n\n"
    "{roster}\n\n"
    "Question: {question}\n\n"
    "Select at most 4 file_keys of documents most likely to contain the answer, "
    "most relevant first. If no document looks relevant return an empty list.\n"
    "Respond with ONLY valid JSON: {{\"file_keys\": [\"key1\", \"key2\"]}}"
)

TREE_SEARCH_SYSTEM = (
    "You are a document retrieval assistant for an airline support knowledge base. "
    "When given a document outline and a question, select the most relevant sections."
)

TREE_SEARCH_USER = (
    "Document outline (each section identified by [node_id]):\n\n"
    "{outline}\n\n"
    "Question: {question}\n\n"
    "Select at most 5 node_ids whose content is most relevant to the question, "
    "most relevant first. If no section is relevant return an empty list.\n"
    "Respond with ONLY valid JSON: {{\"node_ids\": [\"id1\", \"id2\"]}}"
)

QA_SYSTEM = (
    "You are a helpful airline customer support assistant for IndiGo airline. "
    "The provided context contains excerpts from IndiGo's official policy documents. "
    "Answer the question based on the context excerpts. "
    "Use bullet points for lists. Keep answers concise. "
    "If the context excerpts contain information relevant to the question — even partially — answer from that information. "
    "Only reply with exactly 'I don't have specific information about that in our airline documents.' "
    "if the context contains absolutely nothing related to the question topic."
)

QA_USER = "Context:\n{context}\n\nQuestion: {question}\nAnswer:"


class HelpCenterAgent:
    CHUNKING_VERSION = "pageindex_v1"

    def __init__(self):
        doc_path = os.environ.get("DOCX_DOC_PATH")
        persist_dir = os.environ.get("PERSIST_DIRECTORY")
        if not doc_path:
            raise ValueError("DOCX_DOC_PATH environment variable is required")
        if not persist_dir:
            raise ValueError("PERSIST_DIRECTORY environment variable is required")

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        def resolve_path(value: str) -> str:
            if os.path.isabs(value):
                return os.path.abspath(value)
            return os.path.abspath(os.path.join(base_dir, value))

        self._doc_path = resolve_path(doc_path)
        self._persist_dir = resolve_path(persist_dir)

        if not os.path.isdir(self._doc_path):
            raise ValueError(
                f"DOCX_DOC_PATH does not exist or is not a directory: {self._doc_path}"
            )

        self._llm = AzureChatOpenAI(
            azure_deployment=os.environ["AZURE_DEPLOYMENT_NAME"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            temperature=0,
            max_tokens=1024,
            request_timeout=60,
        )

        # load or build trees for all docs
        self._trees = pi.load_all_trees(self._persist_dir)
        self._sync_trees()

    # ── sync: build missing / stale, prune deleted ────────────────────────────

    def _sync_trees(self) -> None:
        manifest = pi.load_manifest(self._persist_dir)
        existing_files = {
            f: os.path.join(self._doc_path, f)
            for f in os.listdir(self._doc_path)
            if os.path.isfile(os.path.join(self._doc_path, f))
        }

        for fname, fpath in existing_files.items():
            fkey = pi._file_key(fpath)
            mtime = os.path.getmtime(fpath)
            cached_mtime = manifest.get(fkey, {}).get("mtime", 0)
            if fkey not in self._trees or abs(mtime - cached_mtime) > 1:
                print(f"[PageIndex] Building tree for: {fname}")
                try:
                    tree = pi.build_tree(fpath, self._llm)
                    pi.save_tree(self._persist_dir, tree)
                    self._trees[fkey] = tree
                except Exception as e:
                    print(f"[PageIndex] Failed to build tree for {fname}: {e}")

        # prune trees for deleted files
        valid_keys = {pi._file_key(p) for p in existing_files.values()}
        for fkey in list(self._trees.keys()):
            if fkey not in valid_keys:
                del self._trees[fkey]
                _, tdir, _ = pi._persist_paths(self._persist_dir)
                tree_path = os.path.join(tdir, fkey + ".json")
                if os.path.exists(tree_path):
                    os.remove(tree_path)

    # ── incremental index ops (called by api.py closures) ────────────────────

    def add_file(self, file_path: str) -> int:
        try:
            fkey = pi._file_key(file_path)
            tree = pi.build_tree(file_path, self._llm)
            pi.save_tree(self._persist_dir, tree)
            self._trees[fkey] = tree
            return 1
        except Exception as e:
            print(f"[PageIndex] add_file failed for {file_path}: {e}")
            return 0

    def remove_file(self, file_path: str) -> int:
        fkey = pi._file_key(file_path)
        removed = pi.delete_tree(self._persist_dir, file_path)
        if fkey in self._trees:
            del self._trees[fkey]
        return 1 if removed else 0

    @property
    def doc_count(self) -> int:
        return len(self._trees)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _call_llm(self, system: str, user: str) -> str:
        resp = self._llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return resp.content if hasattr(resp, "content") else str(resp)

    def _route_docs(self, question: str) -> List[str]:
        """Stage 1: pick which docs to look at via a compact one-line-per-doc roster.

        Token cost is O(N_docs) flat — one short line per document regardless of
        how many sections each document contains.
        Returns a list of file_keys that exist in self._trees.
        """
        roster = pi.render_doc_roster(self._trees)
        if not roster.strip():
            return list(self._trees.keys())
        user = DOC_ROUTE_USER.format(roster=roster, question=question)
        for attempt in range(2):
            try:
                raw = self._call_llm(DOC_ROUTE_SYSTEM, user)
                raw = re.sub(r"```[a-z]*\n?", "", raw).strip().strip("`")
                data = json.loads(raw)
                keys = [str(k) for k in data.get("file_keys", [])]
                valid = [k for k in keys if k in self._trees]
                if valid:
                    return valid
            except Exception:
                if attempt == 0:
                    user += "\n\nIMPORTANT: Return only raw JSON, no markdown."
        # fallback: route to all docs so no query silently fails
        return list(self._trees.keys())

    def _tree_search(self, question: str) -> List[str]:
        """2-stage hierarchical search: doc routing → section selection.

        Stage 1 (_route_docs): compact roster → LLM picks ≤4 relevant docs.
        Stage 2: full section outline for only those docs → LLM picks node_ids.
        Token cost stays bounded at scale: ~(N_docs × 1 line) + ~(sections in 2-4 docs).
        """
        if not self._trees:
            return []

        # Stage 1 — skip routing if there's only one doc
        if len(self._trees) > 1:
            selected_keys = self._route_docs(question)
            if not selected_keys:
                return []
        else:
            selected_keys = list(self._trees.keys())

        # Stage 2 — section selection within the routed docs only
        outline = pi.render_doc_outline(self._trees, selected_keys)
        if not outline.strip():
            return []
        user = TREE_SEARCH_USER.format(outline=outline, question=question)
        for attempt in range(2):
            try:
                raw = self._call_llm(TREE_SEARCH_SYSTEM, user)
                raw = re.sub(r"```[a-z]*\n?", "", raw).strip().strip("`")
                data = json.loads(raw)
                return [str(nid) for nid in data.get("node_ids", [])]
            except Exception:
                if attempt == 0:
                    user += "\n\nIMPORTANT: Return only raw JSON, no markdown."
        return []

    # ── query ─────────────────────────────────────────────────────────────────

    def _run_query(self, query: str, standalone_question: str = "") -> dict:
        sq = standalone_question or query

        t0 = time.time()
        node_ids = self._tree_search(sq)
        retrieval_ms = int((time.time() - t0) * 1000)

        chunks = pi.collect_node_texts(self._trees, node_ids)
        candidate_count = len(chunks)

        if not chunks:
            return {
                "answer": UNANSWERED_TEXT,
                "sources": [],
                "answered_by": "no_context",
                "retrieval_ms": retrieval_ms,
                "generation_ms": 0,
                "candidate_count": 0,
            }

        context = "\n\n---\n\n".join(
            f"[{c['source']} / {c['section_path']}]\n{c['text']}" for c in chunks
        )

        t1 = time.time()
        try:
            answer = self._call_llm(QA_SYSTEM, QA_USER.format(context=context, question=sq)).strip()
        except Exception:
            answer = UNANSWERED_TEXT
        generation_ms = int((time.time() - t1) * 1000)

        n = len(chunks)
        sources = [
            {
                "content": c["text"],
                "metadata": {
                    "source": c["source"],
                    "section_path": c["section_path"],
                    "node_id": c["node_id"],
                },
                "score": round(1.0 - i * (0.5 / max(n - 1, 1)), 4),
            }
            for i, c in enumerate(chunks)
        ]

        return {
            "answer": answer,
            "sources": sources,
            "answered_by": "llm",
            "retrieval_ms": retrieval_ms,
            "generation_ms": generation_ms,
            "candidate_count": candidate_count,
        }
