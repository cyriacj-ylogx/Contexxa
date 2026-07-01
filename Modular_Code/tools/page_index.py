"""PageIndex: vectorless hierarchical tree index over loaded document blocks.

Build flow per document:
  1. load_single_file() → blocks with heading/section_path metadata
  2. group blocks into a tree keyed by section_path (pure code, no LLM)
  3. one LLM call per file to generate ≤50-word summaries for each node

Persistence: <PERSIST_DIRECTORY>/pageindex_v1/
    manifest.json          – {file_key: {source, mtime, doc_title}}
    trees/<file_key>.json  – full tree JSON
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Dict, List, Optional, Tuple

from tools.doc_loaders import DocLoaders

# ── constants ─────────────────────────────────────────────────────────────────

VERSION_DIR = "pageindex_v1"
TREES_SUBDIR = "trees"
MANIFEST_FILE = "manifest.json"
LEAF_TEXT_CAP = 2000        # chars before splitting leaf into Part 1/2
# Hierarchical routing means the full flat outline is never sent for large corpora;
# OUTLINE_MAX_CHARS now guards the *per-doc* section outline (stage 2 of routing).
# Env-overridable; default is large enough for any realistic single-doc outline.
OUTLINE_MAX_CHARS = int(os.environ.get("PAGEINDEX_OUTLINE_MAX_CHARS", "40000"))
CONTEXT_MAX_CHARS = 8000
SUMMARY_BATCH_SIZE = 40     # nodes per LLM summary call
SUMMARY_MAX_WORDS = 50


# ── helpers ───────────────────────────────────────────────────────────────────

def _file_key(file_path: str) -> str:
    """SHA1-based 8-char key — same scheme as rag_responder."""
    import hashlib
    return hashlib.sha1(os.path.basename(file_path).encode()).hexdigest()[:8]


def _persist_paths(persist_dir: str) -> Tuple[str, str, str]:
    """Return (version_dir, trees_dir, manifest_path)."""
    vdir = os.path.join(persist_dir, VERSION_DIR)
    tdir = os.path.join(vdir, TREES_SUBDIR)
    mpath = os.path.join(vdir, MANIFEST_FILE)
    return vdir, tdir, mpath


def _atomic_write(path: str, data) -> None:
    """Write JSON atomically via tmp file + os.replace (Windows-safe)."""
    tmp = path + ".tmp." + uuid.uuid4().hex[:8]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ── tree construction (pure Python) ──────────────────────────────────────────

def _section_parts(section_path: str) -> List[str]:
    return [p.strip() for p in section_path.split(" > ") if p.strip()]


def _make_node(node_id: str, title: str, metadata: dict) -> dict:
    return {
        "node_id": node_id,
        "title": title,
        "summary": "",
        "text": "",
        "metadata": metadata,
        "children": [],
    }


def _insert_block(root: dict, parts: List[str], block_text: str,
                  source: str, fkey: str, counters: dict) -> None:
    """Walk/create tree path for `parts`, appending block_text to the leaf."""
    node = root
    path_so_far: List[str] = []
    for part in parts:
        path_so_far.append(part)
        existing = next((c for c in node["children"] if c["title"] == part), None)
        if existing is None:
            cid = f"{fkey}:{counters['n']}"
            counters["n"] += 1
            child = _make_node(
                cid, part,
                {"source": source, "section_path": " > ".join(path_so_far)},
            )
            node["children"].append(child)
            existing = child
        node = existing
    # append text to this leaf node
    if node["text"]:
        node["text"] += "\n" + block_text
    else:
        node["text"] = block_text


def _split_oversized_leaves(node: dict, fkey: str, counters: dict) -> None:
    """Recursively split leaf text > LEAF_TEXT_CAP into Part 1 / Part 2 children."""
    for child in node["children"]:
        _split_oversized_leaves(child, fkey, counters)

    if not node["children"] and len(node["text"]) > LEAF_TEXT_CAP:
        text = node["text"]
        mid = len(text) // 2
        # split at nearest newline
        split_at = text.rfind("\n", 0, mid)
        if split_at < 0:
            split_at = mid
        parts_text = [text[:split_at].strip(), text[split_at:].strip()]
        for i, pt in enumerate(parts_text, 1):
            if not pt:
                continue
            cid = f"{fkey}:{counters['n']}"
            counters["n"] += 1
            child = _make_node(
                cid, f"Part {i}",
                dict(node["metadata"]),
            )
            child["text"] = pt
            node["children"].append(child)
        node["text"] = ""


def _build_tree_structure(blocks: list, file_path: str) -> dict:
    """Convert flat block list → tree dict (no LLM)."""
    fkey = _file_key(file_path)
    source = os.path.basename(file_path)
    counters = {"n": 1}

    root = _make_node(f"{fkey}:0", source, {"source": source, "section_path": ""})

    for blk in blocks:
        meta = blk.metadata if hasattr(blk, "metadata") else {}
        sp = meta.get("section_path", "")
        text = blk.page_content if hasattr(blk, "page_content") else str(blk)
        text = text.strip()
        if not text:
            continue
        parts = _section_parts(sp) if sp else []
        _insert_block(root, parts, text, source, fkey, counters)

    _split_oversized_leaves(root, fkey, counters)
    return root


# ── LLM summary generation ────────────────────────────────────────────────────

def _collect_nodes(node: dict, out: list) -> None:
    out.append(node)
    for c in node["children"]:
        _collect_nodes(c, out)


def _generate_summaries(root: dict, llm) -> None:
    """One LLM call per SUMMARY_BATCH_SIZE nodes; fills node['summary'] in-place."""
    all_nodes: list = []
    _collect_nodes(root, all_nodes)

    # build text preview per node
    def _node_preview(n: dict) -> str:
        txt = n["text"] or " ".join(c["text"][:100] for c in n["children"])
        return txt[:300]

    batches = [all_nodes[i:i + SUMMARY_BATCH_SIZE]
               for i in range(0, len(all_nodes), SUMMARY_BATCH_SIZE)]

    for batch in batches:
        items = "\n".join(
            f'- node_id: "{n["node_id"]}" title: "{n["title"]}" preview: "{_node_preview(n)}"'
            for n in batch
        )
        prompt = (
            f"You are indexing an airline support document. "
            f"For each node below write a summary of at most {SUMMARY_MAX_WORDS} words "
            f"capturing concrete facts (fees, limits, codes, rules). "
            f"Return ONLY valid JSON: {{\"<node_id>\": \"<summary>\", ...}}\n\n{items}"
        )
        try:
            from langchain.messages import HumanMessage
            resp = llm.invoke([HumanMessage(content=prompt)])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            # strip code fences
            raw = re.sub(r"```[a-z]*\n?", "", raw).strip().strip("`")
            data = json.loads(raw)
            for n in batch:
                if n["node_id"] in data:
                    n["summary"] = str(data[n["node_id"]])[:300]
        except Exception:
            # summaries are best-effort; tree still works without them
            pass


# ── public API ────────────────────────────────────────────────────────────────

def build_tree(file_path: str, llm) -> dict:
    """Load file, build tree structure, generate LLM summaries. Return tree dict."""
    blocks = DocLoaders.load_single_file(file_path)
    root = _build_tree_structure(blocks, file_path)
    _generate_summaries(root, llm)
    return {
        "file_key": _file_key(file_path),
        "source": os.path.basename(file_path),
        "doc_title": os.path.splitext(os.path.basename(file_path))[0].replace("_", " ").title(),
        "mtime": os.path.getmtime(file_path),
        "root": root,
    }


def save_tree(persist_dir: str, tree: dict) -> None:
    """Persist tree JSON + update manifest."""
    _, tdir, mpath = _persist_paths(persist_dir)
    tree_path = os.path.join(tdir, tree["file_key"] + ".json")
    _atomic_write(tree_path, tree)

    manifest = load_manifest(persist_dir)
    manifest[tree["file_key"]] = {
        "source": tree["source"],
        "mtime": tree["mtime"],
        "doc_title": tree["doc_title"],
    }
    _atomic_write(mpath, manifest)


def load_manifest(persist_dir: str) -> dict:
    _, _, mpath = _persist_paths(persist_dir)
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_all_trees(persist_dir: str) -> Dict[str, dict]:
    """Return {file_key: tree_dict} for all persisted trees."""
    _, tdir, _ = _persist_paths(persist_dir)
    trees: Dict[str, dict] = {}
    if not os.path.isdir(tdir):
        return trees
    for fname in os.listdir(tdir):
        if not fname.endswith(".json"):
            continue
        fkey = fname[:-5]
        try:
            with open(os.path.join(tdir, fname), encoding="utf-8") as f:
                trees[fkey] = json.load(f)
        except Exception:
            pass
    return trees


def delete_tree(persist_dir: str, file_path: str) -> bool:
    """Remove tree JSON + manifest entry for file_path. Returns True if removed."""
    fkey = _file_key(file_path)
    _, tdir, mpath = _persist_paths(persist_dir)
    tree_path = os.path.join(tdir, fkey + ".json")
    removed = False
    if os.path.exists(tree_path):
        os.remove(tree_path)
        removed = True
    manifest = load_manifest(persist_dir)
    if fkey in manifest:
        del manifest[fkey]
        _atomic_write(mpath, manifest)
    return removed


# ── outline rendering ─────────────────────────────────────────────────────────

def _render_node(node: dict, depth: int, lines: list, char_budget: list) -> None:
    indent = "  " * depth
    title = node["title"]
    nid = node["node_id"]
    summary = node["summary"]
    line = f"{indent}[{nid}] {title}"
    if summary:
        line += f" — {summary}"
    lines.append(line)
    char_budget[0] -= len(line) + 1
    if char_budget[0] <= 0:
        return
    for child in node["children"]:
        if char_budget[0] <= 0:
            break
        _render_node(child, depth + 1, lines, char_budget)


def render_outline(trees: Dict[str, dict], max_chars: int = OUTLINE_MAX_CHARS) -> str:
    """Render a combined outline of all trees as a string for the tree-search prompt."""
    lines: list = []
    budget = [max_chars]
    for tree in trees.values():
        if budget[0] <= 0:
            break
        _render_node(tree["root"], 0, lines, budget)
    return "\n".join(lines)


def render_doc_roster(trees: Dict[str, dict]) -> str:
    """One-line-per-document listing for the doc-routing stage (Stage 1).

    Format: [file_key] doc_title — root_summary
    Cost is O(N_docs) regardless of tree depth — stays flat at any corpus size.
    """
    lines: list = []
    for fkey, tree in trees.items():
        title = tree.get("doc_title", tree.get("source", fkey))
        root_summary = tree["root"].get("summary", "")
        line = f"[{fkey}] {title}"
        if root_summary:
            line += f" — {root_summary}"
        lines.append(line)
    return "\n".join(lines)


def render_doc_outline(trees: Dict[str, dict], file_keys: List[str],
                       max_chars: int = OUTLINE_MAX_CHARS) -> str:
    """Full section outline for a *subset* of docs (Stage 2 of hierarchical routing).

    Only renders trees whose file_key is in file_keys, so the prompt is bounded
    to the sections of the 2-4 docs the router already selected.
    """
    lines: list = []
    budget = [max_chars]
    for fkey in file_keys:
        tree = trees.get(fkey)
        if tree is None:
            continue
        _render_node(tree["root"], 0, lines, budget)
        if budget[0] <= 0:
            break
    return "\n".join(lines)


# ── context collection ────────────────────────────────────────────────────────

def _find_node(root: dict, node_id: str) -> Optional[dict]:
    if root["node_id"] == node_id:
        return root
    for child in root["children"]:
        found = _find_node(child, node_id)
        if found:
            return found
    return None


def _collect_leaf_texts(node: dict, out: list) -> None:
    if not node["children"]:
        if node["text"]:
            out.append((node["node_id"], node["metadata"].get("source", ""),
                        node["metadata"].get("section_path", ""), node["text"]))
        return
    for child in node["children"]:
        _collect_leaf_texts(child, out)


def collect_node_texts(
    trees: Dict[str, dict],
    node_ids: List[str],
    max_chars: int = CONTEXT_MAX_CHARS,
) -> List[dict]:
    """Resolve node_ids → leaf texts. Internal node → pulls all leaf descendants.

    Returns list of {node_id, source, section_path, text} dicts, capped at max_chars.
    """
    results: list = []
    seen_ids: set = set()
    total_chars = 0

    for nid in node_ids:
        fkey = nid.split(":")[0] if ":" in nid else None
        root = trees.get(fkey, {}).get("root") if fkey else None
        if root is None:
            # search all trees
            for tree in trees.values():
                n = _find_node(tree["root"], nid)
                if n:
                    root = n
                    break
        else:
            root = _find_node(root, nid)

        if root is None:
            continue

        leaf_tuples: list = []
        _collect_leaf_texts(root, leaf_tuples)

        for lid, src, sp, txt in leaf_tuples:
            if lid in seen_ids:
                continue
            seen_ids.add(lid)
            if total_chars >= max_chars:
                break
            chunk = txt[:max_chars - total_chars]
            results.append({
                "node_id": lid,
                "source": src,
                "section_path": sp,
                "text": chunk,
            })
            total_chars += len(chunk)

        if total_chars >= max_chars:
            break

    return results
