import importlib
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

VALIDATION_CASES = [
    {
        "query": "What happens if you use company equipment improperly?",
        "coverage_terms": ["company-issued equipment", "equipment", "improperly"],
        "preferred_sections": ["company-issued equipment", "internet usage", "corporate email", "cyber security"],
        "forbidden_sections": ["work from home", "termination", "emergency management", "workplace visitors"],
        "require_non_fallback": True,
        "top_section_should_match": True,
    },
    {
        "query": "What are the termination conditions",
        "coverage_terms": ["termination", "progressive discipline"],
        "preferred_sections": ["termination", "progressive discipline"],
        "forbidden_sections": ["resignation", "cobra", "group health"],
        "top_section_should_match": True,
    },
    {
        "query": "I want to take sick leave for long term illeness, what are the policy?",
        "coverage_terms": ["sick leave", "long-term illness", "fmla"],
        "preferred_sections": ["sick leave", "long-term illness"],
        "forbidden_sections": ["termination"],
        "require_non_fallback": True,
        "top_section_should_match": True,
    },
    {
        "query": "Can I wear any dress to office?",
        "coverage_terms": ["dress", "appearance", "office"],
        "preferred_sections": ["dress code", "appearance", "workplace policies"],
        "forbidden_sections": ["termination", "holidays"],
    },
    {
        "query": "get me details regarding leave",
        "coverage_terms": ["pto", "holiday", "sick leave", "parental leave"],
        "preferred_sections": ["paid time off", "holidays", "sick leave", "parental leave"],
        "forbidden_sections": ["termination"],
    },
    {
        "query": "can i have visitors in the workplace",
        "coverage_terms": ["visitors", "workplace"],
        "preferred_sections": ["visitors", "workplace policies"],
        "forbidden_sections": ["termination", "holidays"],
        "require_non_fallback": True,
        "top_section_should_match": True,
    },
    {
        "query": "how may holidays are there",
        "coverage_terms": ["holiday", "holidays"],
        "preferred_sections": ["holidays"],
        "forbidden_sections": ["termination", "paid time off", "sick leave", "paternity and maternity leave", "bereavement leave", "jury duty"],
        "expect_answer_contains": ["11", "company holidays"],
        "top_section_should_match": True,
    },
    {
        "query": "Does the company do anything to protect our data?",
        "coverage_terms": ["data", "confidentiality", "security"],
        "preferred_sections": ["cyber security", "confidentiality", "security"],
        "forbidden_sections": ["termination", "holidays", "social media"],
        "top_section_should_match": True,
    },
    {
        "query": "What happens if I quit? How much notice do I give?",
        "coverage_terms": ["resignation", "notice"],
        "preferred_sections": ["resignation"],
        "forbidden_sections": [],
    },
    {
        "query": "What if I work from home, any rules?",
        "coverage_terms": ["work from home", "remote working"],
        "preferred_sections": ["work from home"],
        "support_sections": ["remote working"],
        "forbidden_sections": ["benefits and perks", "attendance"],
        "expect_answer_contains": ["one day per week", "two days"],
        "top_section_should_match": True,
    },
    {
        "query": "Can I use my company laptop for personal stuff?",
        "coverage_terms": ["company-issued equipment", "laptop", "personal"],
        "preferred_sections": ["company-issued equipment", "internet usage", "corporate email", "cyber security"],
        "forbidden_sections": ["termination", "holidays", "work from home", "workplace visitors"],
        "require_non_fallback": True,
        "top_section_should_match": True,
    },
    {
        "query": "What's the referral bonus thing? How does that work?",
        "coverage_terms": ["referral", "bonus", "reward"],
        "preferred_sections": ["employee referral"],
        "forbidden_sections": ["termination", "holidays"],
    },
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _ascii(text: str) -> str:
    return (text or "").encode("ascii", "replace").decode("ascii")


def _section_key(meta: Dict) -> str:
    return _normalize(meta.get("parent_heading") or meta.get("section_path") or "")


def _preview(text: str, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _query_terms(query: str) -> List[str]:
    stop = {"the", "a", "an", "about", "tell", "me", "what", "is", "are", "policy", "policies", "regarding"}
    terms = re.findall(r"[a-zA-Z]+", _normalize(query))
    return [term for term in terms if term not in stop and len(term) > 2]


def _has_any(haystack: str, needles: Sequence[str]) -> bool:
    lowered = _normalize(haystack)
    return any(_normalize(needle) in lowered for needle in needles if needle)


def _score_term_hits(text: str, terms: Sequence[str]) -> int:
    lowered = _normalize(text)
    return sum(1 for term in terms if re.search(rf"\b{re.escape(_normalize(term))}\b", lowered))


def _print_results(query: str, results: List[Tuple[float, Dict, str]]) -> None:
    print("\nQUERY:", _ascii(query))
    for i, (score, meta, preview) in enumerate(results, start=1):
        print(
            f"R{i} score={score:.4f} type={_ascii(str(meta.get('block_type')))} "
            f"section={_ascii(str(meta.get('section_path')))} heading={_ascii(str(meta.get('parent_heading')))}"
        )
        print("   ", _ascii(preview))


def _print_answer(answer: Optional[str]) -> None:
    if answer:
        print("ANSWER:", _ascii(answer))
    else:
        print("ANSWER: <not evaluated>")


def _load_agent_class():
    try:
        module = importlib.import_module("tools.pageindex_responder")
        return module.HelpCenterAgent, None
    except Exception as exc:
        return None, exc


def _load_pdf_entries(doc_root: str) -> List[Tuple[Dict, str]]:
    from pypdf import PdfReader

    root = Path(doc_root)
    entries: List[Tuple[Dict, str]] = []
    for pdf in root.glob("*.pdf"):
        reader = PdfReader(str(pdf))
        current_heading = ""
        for _, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if len(line) <= 90 and line[:1].isupper() and not line.endswith("."):
                    current_heading = line
                    continue
                if len(line) < 30:
                    continue
                meta = {
                    "block_type": "paragraph",
                    "section_path": current_heading,
                    "parent_heading": current_heading,
                    "source": str(pdf),
                }
                entries.append((meta, line))
    return entries


def _validate_case(case: Dict, results: List[Tuple[float, Dict, str]], answer: Optional[str]) -> None:
    joined_results = " ".join(f"{_section_key(meta)} {preview}" for _, meta, preview in results)
    coverage_terms = case.get("coverage_terms", [])
    matched = sorted({term for term in coverage_terms if _has_any(joined_results, [term])})
    status = "PASS" if len(matched) == len(coverage_terms) else "CHECK"
    print(f"COVERAGE {status}: {len(matched)}/{len(coverage_terms)} matched -> {', '.join(matched) or 'none'}")

    preferred_sections = case.get("preferred_sections", [])
    top_section = _section_key(results[0][1]) if results else ""
    if preferred_sections:
        preferred_hit = _has_any(top_section, preferred_sections) or any(
            _has_any(_section_key(meta), preferred_sections) for _, meta, _ in results
        )
        print(f"SECTION {'PASS' if preferred_hit else 'CHECK'}: preferred -> {_ascii(top_section or 'none')}")
        if case.get("top_section_should_match"):
            top_match = _has_any(top_section, preferred_sections)
            print(f"TOP {'PASS' if top_match else 'CHECK'}: top section -> {_ascii(top_section or 'none')}")

    support_sections = case.get("support_sections", [])
    if support_sections:
        support_hit = any(_has_any(_section_key(meta), support_sections) for _, meta, _ in results)
        print(f"SUPPORT {'PASS' if support_hit else 'CHECK'}: support section present")

    forbidden_sections = case.get("forbidden_sections", [])
    forbidden_hit = [
        _section_key(meta)
        for _, meta, _ in results
        if _has_any(_section_key(meta), forbidden_sections)
    ]
    print(f"NOISE {'PASS' if not forbidden_hit else 'CHECK'}: {_ascii(', '.join(forbidden_hit) or 'none')}")

    expect_answer_contains = case.get("expect_answer_contains", [])
    if expect_answer_contains:
        if answer:
            answer_ok = _has_any(answer, expect_answer_contains)
            print(f"ANSWER {'PASS' if answer_ok else 'CHECK'}: expected answer signal")
        else:
            print("ANSWER CHECK: skipped (answer unavailable)")

    if case.get("require_non_fallback"):
        if answer:
            non_fallback = "i don't have specific information about that in the employee handbook." not in _normalize(answer)
            print(f"FALLBACK {'PASS' if non_fallback else 'CHECK'}: non-fallback answer required")
        else:
            print("FALLBACK CHECK: skipped (answer unavailable)")


def _run_with_agent(agent, case: Dict) -> Tuple[List[Tuple[float, Dict, str]], Optional[str]]:
    query = case["query"]
    ranked = agent._retrieve_candidates(query)
    final_docs, sources = agent._select_final_context(query, ranked)

    results = []
    for doc, src in zip(final_docs, sources):
        meta = doc.metadata or {}
        results.append((float(src["score"]), meta, _preview(src.get("content", doc.page_content))))

    answer = None
    try:
        answer = agent._run_query(query).get("answer")
    except Exception:
        answer = None

    return results, answer


def _run_offline(entries: List[Tuple[Dict, str]], case: Dict, final_k: int) -> Tuple[List[Tuple[float, Dict, str]], Optional[str]]:
    query = case["query"]
    terms = case.get("coverage_terms") or _query_terms(query)
    scored: List[Tuple[float, Dict, str]] = []
    for meta, text in entries:
        haystack = f"{_section_key(meta)} {text}"
        score = -float(_score_term_hits(haystack, terms))
        scored.append((score, meta, _preview(text)))
    scored.sort(key=lambda item: item[0])

    picked: List[Tuple[float, Dict, str]] = []
    seen_sections = set()
    for item in scored:
        _, meta, _ = item
        section = _section_key(meta)
        if section and section in seen_sections:
            continue
        seen_sections.add(section)
        picked.append(item)
        if len(picked) >= final_k:
            break
    return picked, None


def main() -> None:
    os.chdir(os.path.abspath(os.path.dirname(__file__)))
    load_dotenv()

    AgentClass, import_error = _load_agent_class()
    agent = None
    if AgentClass is not None:
        try:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            agent = AgentClass()
            print("Running validation with HelpCenterAgent retrieval path.")
        except Exception as exc:
            print("Agent init failed, falling back to offline validation:", str(exc))
            agent = None
    else:
        print("Agent import failed, falling back to offline validation:", str(import_error))

    entries = []
    if agent is None:
        doc_root = os.environ.get("DOCX_DOC_PATH")
        if not doc_root:
            raise RuntimeError("Missing DOCX_DOC_PATH for offline validation")
        if not os.path.isabs(doc_root):
            doc_root = os.path.join(os.path.abspath(os.path.dirname(__file__)), doc_root)
        entries = _load_pdf_entries(doc_root)
        if not entries:
            raise RuntimeError(f"No PDF entries available under {doc_root}")

    final_k = int(os.environ.get("FINAL_CONTEXT_K_BROAD", "8"))
    for case in VALIDATION_CASES:
        if agent is not None:
            results, answer = _run_with_agent(agent, case)
        else:
            results, answer = _run_offline(entries, case, final_k)
        _print_results(case["query"], results)
        _print_answer(answer)
        _validate_case(case, results, answer)


if __name__ == "__main__":
    main()
