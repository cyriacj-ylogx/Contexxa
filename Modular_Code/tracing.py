"""Langfuse tracing — full pipeline traces for every chat request.

All Langfuse SDK usage is isolated here. The rest of the app only passes
plain dicts. Behavior without LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY (or
without the langfuse package installed) is a silent no-op, and any SDK
error is swallowed — observability must never break a chat request.

Uses Langfuse v3/v4 SDK (OTel-based). Compatible with langfuse>=3.0.0.
"""

import os

from logging_config import log_app

_client = None
_init_attempted = False

_MODEL_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4o")


def _get_client():
    """Lazy singleton. Returns None when keys/package are missing."""
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key:
        log_app("Langfuse disabled (no keys configured)")
        return None
    try:
        from langfuse import Langfuse

        host = (
            os.environ.get("LANGFUSE_HOST")
            or os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        )
        _client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        log_app("Langfuse tracing enabled")
    except Exception as exc:
        log_app(f"Langfuse init failed (tracing disabled): {exc}")
        _client = None
    return _client


def record_chat_trace(data: dict) -> None:
    """Build one trace per chat with nested condense/retrieval/answer steps.

    Uses Langfuse v4 context-manager API with propagate_attributes for
    session_id and tags.

    Expected keys in `data` (all optional — missing keys degrade gracefully):
      question, session_id, standalone_question, answer, sources
      [{source, score, preview}], latency_ms, unanswered, doc_count,
      index_version, condense {ran, ms}, rag {retrieval_ms, generation_ms,
      answered_by, candidate_count}
    """
    client = _get_client()
    if client is None:
        return
    try:
        from langfuse import propagate_attributes

        question = data.get("question", "")
        standalone = data.get("standalone_question") or question
        answer = data.get("answer", "")
        session_id = data.get("session_id")
        unanswered = bool(data.get("unanswered"))
        condense = data.get("condense") or {}
        rag = data.get("rag") or {}
        sources = data.get("sources", [])

        tags = ["unanswered"] if unanswered else []

        with propagate_attributes(session_id=session_id, tags=tags):
            with client.start_as_current_observation(
                name="chat",
                as_type="span",
                input=question,
                output=answer[:500],
                metadata={
                    "doc_count": data.get("doc_count"),
                    "index_version": data.get("index_version"),
                    "latency_ms": data.get("latency_ms"),
                    "unanswered": unanswered,
                },
            ) as root:
                # Condense step — only when condensation actually ran
                if condense.get("ran"):
                    with root.start_as_current_observation(
                        name="condense_question",
                        as_type="generation",
                        model=_MODEL_NAME,
                        input=question,
                        output=standalone,
                        metadata={"latency_ms": condense.get("ms")},
                    ):
                        pass

                # Retrieval span
                with root.start_as_current_observation(
                    name="retrieval",
                    as_type="retriever",
                    input=standalone,
                    output=sources,
                    metadata={
                        "latency_ms": rag.get("retrieval_ms"),
                        "candidate_count": rag.get("candidate_count"),
                    },
                ):
                    pass

                # Answer generation
                with root.start_as_current_observation(
                    name="answer",
                    as_type="generation",
                    model=_MODEL_NAME,
                    input={"question": standalone, "context_chunks": len(sources)},
                    output=answer,
                    metadata={
                        "latency_ms": rag.get("generation_ms"),
                        "answered_by": rag.get("answered_by"),
                    },
                ):
                    pass

    except Exception:
        pass


def flush() -> None:
    """Flush pending events (called on FastAPI shutdown). Never raises."""
    try:
        if _client is not None:
            _client.flush()
    except Exception:
        pass
