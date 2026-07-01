# HelpCenterAgent — tools/rag_responder.py

## Overview

`rag_responder.py` is the core RAG (Retrieval-Augmented Generation) engine. It handles everything from document loading and indexing to query processing and answer generation.

**File:** `Modular_Code/tools/rag_responder.py`
**Lines:** ~2841

---

## Class: HelpCenterAgent

The central class that orchestrates the entire RAG pipeline.

---

## Key Constants

```python
EMBEDDING_MODEL   = "all-MiniLM-L6-v2"              # Sentence Transformer
RERANKER_MODEL    = "cross-encoder/ms-marco-MiniLM-L-6-v2"
COLLECTION_NAME   = "parent_child_semantic_v10"      # ChromaDB collection
SIMILARITY_THRESHOLD = 0.82                          # Min cosine similarity
```

---

## Initialisation — `__init__()`

```python
def __init__(self):
    # 1. Load environment variables
    self.doc_path        = os.environ["DOCX_DOC_PATH"]
    self.persist_dir     = os.environ["PERSIST_DIRECTORY"]
    self.retrieval_k     = int(os.environ.get("RETRIEVAL_K", 12))
    self.context_k_focused = int(os.environ.get("FINAL_CONTEXT_K_FOCUSED", 4))
    self.context_k_broad   = int(os.environ.get("FINAL_CONTEXT_K_BROAD", 8))

    # 2. Load embedding model
    self.embedding_model = SentenceTransformer(EMBEDDING_MODEL)

    # 3. Load or build ChromaDB index
    self._create_index()

    # 4. Load cross-encoder re-ranker
    self.reranker = CrossEncoder(RERANKER_MODEL)

    # 5. Build BM25 keyword index
    self._build_bm25_parent_index()
```

---

## Core Methods

### `_create_index()`
Builds or loads the ChromaDB vector index.

```
IF chroma_db folder exists AND has data:
    Load existing index from disk  ← Fast (~2s)
ELSE:
    Load all .docx/.pdf from DOCX_DOC_PATH
    Split into parent/child chunks
    Embed all child chunks
    Store in ChromaDB
    Persist to disk               ← Slow (2-5 mins first time)
```

**Why persist?**
- Embedding 35+ documents takes minutes
- Persisting to disk means this only happens once
- All subsequent startups load instantly

---

### `load_docs(directory) → List[Document]`
Loads all supported documents from a directory.

```python
for file in directory:
    if file.endswith(".docx"):
        docs += cls._load_docx(file)
    elif file.endswith(".pdf"):
        docs += cls._load_pdf(file)
```

**Metadata attached to each document chunk:**
```python
{
    "source": "Baggage Allowance.docx",
    "section": "Domestic Travel > Check-in Baggage",
    "doc_index": 0
}
```

---

### `_load_docx(file_path) → List[Document]`
Reads a `.docx` file paragraph by paragraph using `python-docx`.

```
Open .docx file
      ↓
Iterate through paragraphs and tables
      ↓
Track heading hierarchy (section path)
      ↓
Create LangChain Document per paragraph with:
  - text content
  - source filename
  - section path (heading > subheading > ...)
```

**Why paragraph-level?**
- Preserves natural document structure
- Each paragraph has its own context
- Heading tracking enables better citations

---

### `_load_pdf(file_path) → List[Document]`
Reads a `.pdf` file using LangChain's `PyPDFLoader`.

```
PyPDFLoader reads all pages
      ↓
Detect TOC pages (scan first N pages)
      ↓
Split content into blocks
      ↓
Return List[Document] with page metadata
```

---

### `split_docs(documents) → Tuple[List, List]`
Splits documents into parent and child chunks.

```
Full document text
      ↓
PARENT CHUNKS (1000 chars, 200 overlap)
  → Larger, full-context blocks
  → Sent to GPT-4o for answer generation
      ↓
CHILD CHUNKS (240-400 chars, 40 overlap)
  → Smaller, precise segments
  → Used for vector similarity search
```

**Why parent-child?**
- Child chunks → small = better search precision
- Parent chunks → large = better answer context
- Search on child, answer from parent

---

### `_run_query(query) → dict`
Main query execution method. Called for every user question.

```python
def _run_query(self, query: str) -> dict:
    # 1. Detect query type (focused vs broad)
    is_broad = self._is_broad_query(query)
    k = self.context_k_broad if is_broad else self.context_k_focused

    # 2. Retrieve candidates (hybrid search)
    candidates = self._retrieve_candidates(query)

    # 3. Re-rank candidates
    reranked = self._rerank_parent_candidates(query, candidates)

    # 4. Select final context
    context = self._select_final_context(reranked, k)

    # 5. Generate answer
    answer = self._answer_from_context(query, context)

    return {"answer": answer, "sources": context}
```

---

### `_retrieve_candidates(query) → List[Document]`
Hybrid retrieval combining two search strategies.

**Strategy 1 — Dense Semantic Search (ChromaDB):**
```
Query → Embed → Vector
      ↓
ChromaDB HNSW search
      ↓
Top 12 most similar child chunks (cosine similarity)
      ↓
Map child → parent chunks
```

**Strategy 2 — Sparse Keyword Search (BM25):**
```
Query → Tokenise → BM25 scoring
      ↓
Top K matching parent chunks (exact keyword match)
```

**Merge:**
```
Dense results + Sparse results
      ↓
Deduplicate by source + section
      ↓
Combined candidate list
```

**Why hybrid?**
- Dense search → finds semantic matches ("luggage limit" matches "baggage allowance")
- Sparse search → finds exact keyword matches ("FMLA", "PTO", specific terms)
- Together → better recall, fewer missed answers

---

### `_rerank_parent_candidates(query, candidates) → List`
Uses Cross-Encoder to re-score all candidates.

```
For each candidate chunk:
    Input: [query, chunk_text]  ← both together
    CrossEncoder scores relevance
    Returns raw logit score (-∞ to +∞)

Sort by score (highest first)
```

**Why re-rank?**
- ChromaDB bi-encoder is fast but approximate
- Cross-encoder reads query + chunk together = deeper understanding
- Removes false positives from initial retrieval

**Score interpretation:**
```
Score > 0    → Positively relevant
Score < 0    → Less relevant (but still in top K by rank)
More negative = less relevant
```

---

### `_select_final_context(reranked, k) → List`
Selects and deduplicates the top K chunks for GPT-4o.

```
Take top K chunks from re-ranked list
      ↓
Deduplicate overlapping content
      ↓
Return final context window
```

---

### `_answer_from_context(query, context) → str`
Constructs the prompt and calls Azure OpenAI GPT-4o.

```python
system_prompt = """
You are an airline customer support agent.
Answer ONLY using the context provided.
If the answer is not in the context, say you don't know.
Be clear, structured, and helpful.
"""

user_prompt = f"""
Context:
{formatted_context}

Question: {query}
"""

response = azure_openai.chat(system_prompt + user_prompt)
return response.content
```

**Why "answer ONLY from context"?**
- Prevents hallucination
- Every answer is grounded in actual documents
- Makes answers auditable and trustworthy

---

### `_build_bm25_parent_index()`
Builds a BM25 keyword index over all parent chunks.

```
Tokenise all parent chunk texts
      ↓
BM25 index built in memory
      ↓
Used alongside ChromaDB for hybrid retrieval
```

BM25 = Best Match 25 — a classical information retrieval algorithm that scores documents based on term frequency and inverse document frequency.

---

### `_is_broad_query(query) → bool`
Determines whether to use focused (4 chunks) or broad (8 chunks) retrieval.

```
Broad signals: "explain", "what is", "tell me about", "overview"
Focused signals: "how much", "what time", "how many", specific terms

Returns True  → use FINAL_CONTEXT_K_BROAD (8 chunks)
Returns False → use FINAL_CONTEXT_K_FOCUSED (4 chunks)
```

---

### `_query_topics(query) → List[str]`
Detects policy topic from the query to improve retrieval routing.

```
Query: "Can I travel if I'm pregnant?"
      ↓
Detects: ["expectant_mother", "medical"]
      ↓
Boosts retrieval from relevant document sections
```

---

## Retrieval Parameters

| Parameter | Default | Description |
|---|---|---|
| `RETRIEVAL_K` | 12 | Initial candidates from ChromaDB |
| `FINAL_CONTEXT_K_FOCUSED` | 4 | Final chunks for specific queries |
| `FINAL_CONTEXT_K_BROAD` | 8 | Final chunks for broad queries |
| Chunk size (child) | 240-400 chars | For search precision |
| Chunk size (parent) | 1000 chars | For answer context |
| Chunk overlap | 200 chars | To avoid sentence cutoffs |
| Similarity threshold | 0.82 | Min cosine similarity for ChromaDB |

---

## Index Storage Structure

```
chroma_db/
└── docs/
    └── parent_child_semantic_v10/
        ├── chroma.sqlite3          ← Metadata and chunk text
        ├── parent_docs.json        ← Parent chunk store
        └── {uuid}/
            ├── data_level0.bin     ← HNSW vector data
            ├── header.bin          ← HNSW header
            ├── length.bin          ← HNSW lengths
            └── link_lists.bin      ← HNSW graph links
```
