import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from customer_support import CustomerSupportPipeline
from logging_config import log_app, log_event, setup_logging
from state_store import StateStore
from tools.pageindex_responder import HelpCenterAgent
import tracing

setup_logging()

app = FastAPI(title="Airline Support Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = None
state = StateStore()

# ---------------------------------------------------------------------------
# Knowledge-base upload / rebuild support
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {
    ".docx", ".pdf", ".txt", ".md", ".markdown", ".rst",
    ".csv", ".tsv", ".json", ".html", ".htm", ".log", ".text",
}

try:
    import pptx  # noqa: F401
    ALLOWED_EXTENSIONS.add(".pptx")
except ImportError:
    pass
try:
    import openpyxl  # noqa: F401
    ALLOWED_EXTENSIONS.add(".xlsx")
except ImportError:
    pass

DENIED_EXTENSIONS = {".exe", ".dll", ".sh", ".bat", ".cmd", ".com", ".msi", ".ps1"}
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per file

UNANSWERED_MARKER = "don't have specific information"


def _docs_dir() -> str:
    raw = os.environ.get("DOCX_DOC_PATH")
    if not raw:
        raise RuntimeError("DOCX_DOC_PATH environment variable is required")
    if os.path.isabs(raw):
        return os.path.abspath(raw)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), raw))


def _persist_dir() -> str:
    raw = os.environ.get("PERSIST_DIRECTORY")
    if not raw:
        raise RuntimeError("PERSIST_DIRECTORY environment variable is required")
    base = (
        os.path.abspath(raw)
        if os.path.isabs(raw)
        else os.path.abspath(os.path.join(os.path.dirname(__file__), raw))
    )
    return os.path.join(base, HelpCenterAgent.CHUNKING_VERSION)


def _safe_filename(name: str) -> str:
    """Return a sanitized basename or raise HTTPException if the file is unsafe."""
    if not name:
        raise HTTPException(status_code=400, detail="Empty filename.")
    base = os.path.basename(name.replace("\\", "/")).strip()
    if not base or base in (".", ".."):
        raise HTTPException(status_code=400, detail=f"Invalid filename: {name!r}")
    ext = os.path.splitext(base)[1].lower()
    if ext in DENIED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {ext}")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )
    return base


def _list_documents():
    docs_dir = _docs_dir()
    if not os.path.isdir(docs_dir):
        return []
    return sorted(
        name
        for name in os.listdir(docs_dir)
        if os.path.isfile(os.path.join(docs_dir, name))
    )


def _clear_persist_dir():
    persist_dir = _persist_dir()
    if os.path.isdir(persist_dir):
        shutil.rmtree(persist_dir, ignore_errors=True)


def _finish_index_update(duration_ms: int, kind: str):
    """Common bookkeeping after any successful index change."""
    state.bump_index_version()
    state.set_kb_status(
        "ready", "Knowledge base rebuilt successfully.", len(_list_documents())
    )
    state.incr_metric("rebuilds")
    state.set_metric("last_rebuild_ms", duration_ms)
    log_event("rebuild_done", kind=kind, duration_ms=duration_ms,
              doc_count=len(_list_documents()))
    log_app(f"Index update ({kind}) finished in {duration_ms} ms")


def _full_rebuild_once():
    """One full rebuild pass: wipe persist dir, re-embed everything."""
    global pipeline
    started = time.perf_counter()
    _clear_persist_dir()
    new_agent = HelpCenterAgent()
    if pipeline is not None:
        pipeline._hc_agent = new_agent
        pipeline._index_version = state.get_index_version()
    _finish_index_update(int((time.perf_counter() - started) * 1000), "full")
    # The pipeline's cached version must match the bumped version so this
    # worker doesn't immediately reload the agent it just built.
    if pipeline is not None:
        pipeline._index_version = state.get_index_version()


def _rebuild_worker(incremental_task=None):
    """Background worker holding the cross-process rebuild lock.

    If incremental_task is given it is tried first; any failure falls back to
    a full rebuild. Loops while uploads queued a pending rebuild.
    """
    # Heartbeat keeps the SQLite lock fresh so a crash (no heartbeat for
    # LOCK_TTL seconds) lets another process steal it, while long rebuilds
    # in a healthy process are never interrupted.
    heartbeat_stop = threading.Event()

    def _heartbeat():
        while not heartbeat_stop.wait(30):
            state.refresh_lock("rebuild")

    threading.Thread(target=_heartbeat, daemon=True).start()
    try:
        while True:
            try:
                if incremental_task is not None:
                    started = time.perf_counter()
                    incremental_task()
                    _finish_index_update(
                        int((time.perf_counter() - started) * 1000), "incremental"
                    )
                    if pipeline is not None:
                        pipeline._index_version = state.get_index_version()
                else:
                    _full_rebuild_once()
            except Exception as exc:
                if incremental_task is not None:
                    log_event("incremental_failed", error=str(exc))
                    log_app(f"Incremental indexing failed, falling back to full rebuild: {exc}")
                    try:
                        _full_rebuild_once()
                    except Exception as exc2:
                        state.set_kb_status("error", f"Rebuild failed: {exc2}")
                        log_event("rebuild_error", error=str(exc2))
                else:
                    state.set_kb_status("error", f"Rebuild failed: {exc}")
                    log_event("rebuild_error", error=str(exc))

            incremental_task = None  # queued follow-ups always do a full pass
            if state.consume_pending_rebuild():
                state.set_kb_status("rebuilding", "Rebuilding knowledge base (queued)…")
                continue
            break
    finally:
        heartbeat_stop.set()
        state.release_lock("rebuild")


def _start_rebuild(incremental_task=None) -> str:
    """Start or queue an index update. Returns 'started'|'queued'|'already_queued'."""
    if state.try_acquire_lock("rebuild"):
        state.set_kb_status("rebuilding", "Rebuilding knowledge base…")
        log_event("rebuild_start", kind="incremental" if incremental_task else "full")
        threading.Thread(
            target=_rebuild_worker, args=(incremental_task,), daemon=True
        ).start()
        return "started"
    state.set_pending_rebuild()
    return "queued"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=64)


class ChatResponse(BaseModel):
    answer: str
    sources: list
    standalone_question: str = ""
    answered_by: str = ""


@app.get("/health")
def health():
    return {"status": "Airline Support Bot API is running"}


@app.get("/allowed-types")
def allowed_types():
    return {"extensions": sorted(ALLOWED_EXTENSIONS)}


@app.get("/status")
def status():
    return state.get_kb_status()


@app.get("/admin/metrics")
def admin_metrics():
    metrics = state.get_metrics()
    queries = metrics.get("queries", 0) or 0
    latency_sum = metrics.get("latency_sum_ms", 0) or 0
    metrics["avg_latency_ms"] = round(latency_sum / queries, 1) if queries else 0
    metrics["doc_count"] = len(_list_documents())
    metrics["index_version"] = state.get_index_version()
    return metrics


@app.get("/documents")
def documents():
    names = _list_documents()
    docs_dir = _docs_dir()
    by_type: dict = {}
    files = []
    for name in names:
        ext = os.path.splitext(name)[1].lower() or "unknown"
        by_type[ext] = by_type.get(ext, 0) + 1
        size = 0
        try:
            size = os.path.getsize(os.path.join(docs_dir, name))
        except OSError:
            pass
        files.append({"name": name, "size": size, "type": ext})
    return {"files": files, "documents": names, "by_type": by_type, "total": len(names)}


@app.delete("/documents/{name}")
def delete_document(name: str):
    safe = _safe_filename(name)
    docs_dir = _docs_dir()
    target = os.path.join(docs_dir, safe)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail=f"Document not found: {safe}")
    os.remove(target)
    log_event("delete", filename=safe)

    target_abs = os.path.abspath(target)

    def _incremental_delete():
        if pipeline is None:
            raise RuntimeError("Pipeline not ready for incremental delete")
        pipeline._hc_agent.remove_file(target_abs)

    rebuild_status = _start_rebuild(incremental_task=_incremental_delete)
    return {"deleted": True, "filename": safe, "rebuild_status": rebuild_status,
            "status": state.get_kb_status()}


@app.post("/upload")
def upload(files: list[UploadFile] = File(...), mode: str = Form("add")):
    mode = (mode or "add").lower()
    if mode not in ("add", "replace"):
        raise HTTPException(status_code=400, detail="mode must be 'add' or 'replace'")
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    docs_dir = _docs_dir()
    os.makedirs(docs_dir, exist_ok=True)

    # Phase 1: validate each file individually (partial rejection supported)
    validated: list[tuple[str, bytes]] = []
    rejected: list[dict] = []
    for f in files:
        try:
            safe = _safe_filename(f.filename)
        except HTTPException as exc:
            rejected.append({"filename": f.filename or "", "error": exc.detail})
            continue
        content = f.file.read()
        if len(content) == 0:
            rejected.append({"filename": safe, "error": "File is empty and was skipped."})
            continue
        mb_limit = MAX_FILE_BYTES // (1024 * 1024)
        if len(content) > MAX_FILE_BYTES:
            rejected.append({"filename": safe, "error": f"File exceeds {mb_limit} MB limit."})
            continue
        validated.append((safe, content))

    for r in rejected:
        log_event("upload_rejected", filename=r["filename"], reason=r["error"])

    if not validated:
        detail = "No valid files to process."
        if rejected:
            detail = "All files rejected: " + "; ".join(r["error"] for r in rejected)
        raise HTTPException(status_code=400, detail=detail)

    # Phase 2: write valid files to disk
    if mode == "replace":
        for existing in _list_documents():
            try:
                os.remove(os.path.join(docs_dir, existing))
            except OSError:
                pass

    saved: list[str] = []
    overwritten: list[str] = []
    for safe, content in validated:
        target = os.path.join(docs_dir, safe)
        if mode == "add" and os.path.isfile(target):
            overwritten.append(safe)
        with open(target, "wb") as out:
            out.write(content)
        saved.append(safe)

    log_event("upload", files=saved, overwritten=overwritten, mode=mode,
              rejected_count=len(rejected))

    # Phase 3: index update.
    # mode=add → incremental per-file (with automatic full-rebuild fallback);
    # mode=replace → full rebuild (persist dir wiped, everything re-embedded).
    incremental_task = None
    if mode == "add":
        add_paths = [os.path.abspath(os.path.join(docs_dir, name)) for name in saved]
        overwrite_set = {
            os.path.abspath(os.path.join(docs_dir, name)) for name in overwritten
        }

        def _incremental_add():
            if pipeline is None:
                raise RuntimeError("Pipeline not ready for incremental add")
            agent = pipeline._hc_agent
            for path in add_paths:
                if path in overwrite_set:
                    agent.remove_file(path)
                agent.add_file(path)

        incremental_task = _incremental_add

    rebuild_status = _start_rebuild(incremental_task=incremental_task)
    return {
        "uploaded": saved,
        "overwritten": overwritten,
        "rejected": rejected,
        "mode": mode,
        "rebuild_status": rebuild_status,
        "status": state.get_kb_status(),
    }


@app.on_event("startup")
def startup_event():
    global pipeline

    # Crash recovery: a stale "rebuilding" status with no live lock means a
    # previous process died mid-rebuild.
    current = state.get_kb_status()
    if current.get("state") == "rebuilding" and not state.lock_is_held("rebuild"):
        log_app("Recovered from stale 'rebuilding' status (previous crash)")
        state.set_kb_status("ready", "Knowledge base ready.", len(_list_documents()))

    if pipeline is None:
        pipeline = CustomerSupportPipeline()
        pipeline.run("")
    state.set_kb_status("ready", "Knowledge base ready.", len(_list_documents()))
    log_app("API started; knowledge base ready")

    # A pending rebuild queued before a crash would otherwise be lost —
    # pick it up now that we can hold the lock.
    if state.consume_pending_rebuild():
        log_app("Pending rebuild found at startup — running full rebuild")
        _start_rebuild()


@app.on_event("shutdown")
def shutdown_event():
    tracing.flush()


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if state.get_kb_status().get("state") == "rebuilding":
        return ChatResponse(
            answer="The knowledge base is currently updating. Please try again in a moment.",
            sources=[],
        )

    if pipeline is None:
        return ChatResponse(
            answer="Service is starting up. Please try again in a moment.", sources=[]
        )

    started = time.perf_counter()
    _, _, response = pipeline.run(req.message, session_id=req.session_id)
    latency_ms = int((time.perf_counter() - started) * 1000)

    if response is None:
        return ChatResponse(answer="I'm ready to help! Please ask me a question.", sources=[])

    answer = response.get("answer", "")
    raw_sources = response.get("sources", [])

    if not answer.strip():
        answer = (
            "I'm sorry, I couldn't find specific information about that in our documents. "
            "Please contact our support team for further assistance."
        )

    sources = []
    for s in raw_sources:
        if not isinstance(s, dict):
            continue
        metadata = s.get("metadata", {})
        raw_score = s.get("score", 0.0)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        raw_path = (
            metadata.get("source", "Unknown") if isinstance(metadata, dict) else "Unknown"
        )
        source_name = os.path.basename(raw_path) if raw_path not in ("", "Unknown") else "Unknown"
        sources.append({
            "content": s.get("content", ""),
            "source": source_name,
            "score": score,
        })

    unanswered = UNANSWERED_MARKER in answer.lower()
    log_event(
        "chat",
        session_id=req.session_id,
        question=req.message,
        standalone_question=response.get("standalone_question", ""),
        answer_preview=answer[:200],
        answer_len=len(answer),
        sources=sorted({s["source"] for s in sources}),
        latency_ms=latency_ms,
        doc_count=state.get_kb_status().get("doc_count", 0),
        unanswered=unanswered,
    )
    state.incr_metric("queries")
    state.incr_metric("latency_sum_ms", latency_ms)
    if unanswered:
        state.incr_metric("unanswered")

    tracing.record_chat_trace({
        "question": req.message,
        "session_id": req.session_id,
        "standalone_question": response.get("standalone_question", ""),
        "answer": answer,
        "sources": [
            {"source": s["source"], "score": s["score"],
             "preview": (s["content"] or "")[:150]}
            for s in sources
        ],
        "latency_ms": latency_ms,
        "unanswered": unanswered,
        "doc_count": state.get_kb_status().get("doc_count", 0),
        "index_version": state.get_index_version(),
        "condense": response.get("trace_condense"),
        "rag": response.get("trace"),
    })

    return ChatResponse(
        answer=answer,
        sources=sources,
        standalone_question=response.get("standalone_question", ""),
        answered_by=response.get("answered_by", ""),
    )


# Serve static frontend last so API routes take precedence
_frontend_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
