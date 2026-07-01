# Evaluation System — eval_rag.py

## Overview

`eval_rag.py` is an automated testing suite for the RAG pipeline. It runs a set of predefined queries against the `HelpCenterAgent` and validates retrieval quality using multiple criteria.

**File:** `Modular_Code/eval_rag.py`

> ⚠️ Note: The current test cases are written for the Employee Handbook knowledge base. If you have switched to airline documents, update `VALIDATION_CASES` with airline-specific queries.

---

## VALIDATION_CASES

A list of test dictionaries. Each test case defines:

```python
{
    "query": str,                   # The question to ask
    "coverage_terms": List[str],    # Keywords that must appear in retrieved content
    "preferred_sections": List[str],# Section names expected in top results
    "forbidden_sections": List[str],# Sections that should NOT appear in results
    "require_non_fallback": bool,   # True = answer must not be a fallback/generic response
    "top_section_should_match": bool, # True = top result must be from a preferred section
    "expect_answer_contains": List[str], # Substrings expected in the final answer
}
```

### Example Test Cases

```python
{
    "query": "How many holidays are there?",
    "coverage_terms": ["holiday", "holidays"],
    "preferred_sections": ["holidays"],
    "forbidden_sections": ["termination", "paid time off", "sick leave"],
    "expect_answer_contains": ["11", "company holidays"],
    "top_section_should_match": True,
}
```

```python
{
    "query": "What if I work from home, any rules?",
    "coverage_terms": ["work from home", "remote working"],
    "preferred_sections": ["work from home"],
    "expect_answer_contains": ["one day per week", "two days"],
    "top_section_should_match": True,
}
```

---

## Evaluation Criteria

### 1. Coverage Terms Check
Verifies that the retrieved context actually contains the relevant keywords.

```python
# All coverage_terms must appear somewhere in retrieved chunks
all(term in retrieved_text for term in coverage_terms)
```

### 2. Preferred Section Match
Checks that retrieved chunks come from the expected document sections.

```python
# At least one retrieved chunk should be from a preferred section
any(pref in chunk["metadata"]["section"] for pref in preferred_sections)
```

### 3. Forbidden Section Check
Ensures irrelevant sections are not returned (measures precision, not just recall).

```python
# No retrieved chunk should be from a forbidden section
not any(forb in chunk["metadata"]["section"] for forb in forbidden_sections)
```

### 4. Top Section Match (`top_section_should_match`)
When `True`, the **highest-scoring** retrieved chunk must come from a preferred section.

```python
# Tightest constraint — top result must be relevant
top_chunk_section in preferred_sections
```

### 5. Non-Fallback Requirement (`require_non_fallback`)
When `True`, the answer must not be a generic "I don't know" response.

```python
# Answer must not contain fallback phrases
not any(phrase in answer for phrase in FALLBACK_PHRASES)
```

### 6. Answer Content Check (`expect_answer_contains`)
When provided, checks that specific facts appear in the generated answer.

```python
# All expected substrings must appear in the final answer
all(phrase.lower() in answer.lower() for phrase in expect_answer_contains)
```

---

## Running the Evaluation

```bash
# From Modular_Code/ with venv activated
cd Modular_Code
python eval_rag.py
```

### Expected Output

```
Running 12 validation tests...
────────────────────────────────
✅ PASS: What happens if you use company equipment improperly?
✅ PASS: What are the termination conditions
❌ FAIL: How many holidays are there?
     → top_section_should_match: expected "holidays", got "paid time off"
...
────────────────────────────────
Results: 10/12 passed
```

---

## Adding New Test Cases

To add a test for airline documents:

```python
{
    "query": "What is the baggage allowance for domestic flights?",
    "coverage_terms": ["baggage", "allowance", "domestic"],
    "preferred_sections": ["domestic travel", "check-in baggage", "baggage allowance"],
    "forbidden_sections": ["refund policy", "check-in process"],
    "require_non_fallback": True,
    "top_section_should_match": True,
    "expect_answer_contains": ["15kg", "7kg"],
}
```

---

## What Good Evaluation Scores Mean

| Score | Interpretation |
|---|---|
| 100% pass | RAG pipeline correctly retrieves and answers all test cases |
| 80-99% | Minor retrieval misses — adjust `RETRIEVAL_K` or chunk size |
| 60-79% | Systematic issues — consider re-indexing or tuning BM25 vs dense weights |
| Below 60% | Fundamental problem — check document loading, embeddings, or `.env` config |

---

## Tuning Based on Evaluation Results

| Failure type | Fix |
|---|---|
| Coverage terms missing | Increase `RETRIEVAL_K` in `.env` |
| Wrong top section | Adjust `SIMILARITY_THRESHOLD` or re-check chunking strategy |
| Forbidden sections appearing | Reduce `FINAL_CONTEXT_K_BROAD`, tighten section metadata |
| Fallback answers | Verify documents loaded correctly; check `DOCX_DOC_PATH` in `.env` |
| Answer missing expected content | Increase `FINAL_CONTEXT_K_BROAD` or `FINAL_CONTEXT_K_FOCUSED` |
