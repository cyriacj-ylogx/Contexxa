# System Architecture

## Overview

The Airline Support Bot is a multi-layered RAG (Retrieval-Augmented Generation) system that enables users to ask natural language questions and receive accurate, sourced answers from airline policy documents.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      USER (Browser)                         │
│                  frontend/index.html                        │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP POST /chat
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend (api.py)                   │
│              Runs on http://localhost:8000                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           CustomerSupportPipeline (customer_support.py)     │
│     Manages conversation state and memory                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              HelpCenterAgent (tools/rag_responder.py)       │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  ChromaDB   │  │   BM25 Index │  │  Cross-Encoder    │  │
│  │  (Vectors)  │  │  (Keywords)  │  │  (Re-ranker)      │  │
│  └─────────────┘  └──────────────┘  └───────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                 Azure OpenAI (GPT-4o)                        │
│            Generates final grounded answer                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

| Component | File | Responsibility |
|---|---|---|
| **REST API** | `api.py` | Expose HTTP endpoints, handle requests/responses |
| **Pipeline** | `customer_support.py` | Conversation orchestration, memory management |
| **RAG Engine** | `tools/rag_responder.py` | Document retrieval, re-ranking, answer generation |
| **Graph Nodes** | `graph/` | Conversation flow logic (greeting, transitions) |
| **Data Models** | `data/` | Message structures, roles, conversation history |
| **Agents** | `agents/` | Greeting node, helper utilities |
| **Frontend** | `frontend/` | Chat UI (HTML + CSS + JS) |
| **Evaluation** | `eval_rag.py` | RAG quality testing |

---

## Data Flow

### Indexing (One-time at startup)
```
assets/Docs/*.docx
      ↓ python-docx loader
Raw text per paragraph + metadata
      ↓ Parent-Child chunking (1000 chars / 200 overlap)
Child chunks (small, precise)
      ↓ Sentence Transformer (all-MiniLM-L6-v2)
384-dimensional vectors
      ↓
ChromaDB HNSW index (persisted to chroma_db/docs/)
```

### Query (Every user request)
```
User question
      ↓ Sentence Transformer embedding
Query vector (384-dim)
      ↓ ChromaDB HNSW search
Top 12 candidate chunks
      ↓ BM25 keyword search (merged)
Combined candidates
      ↓ Cross-Encoder reranking
Top 4 (focused) or Top 8 (broad) chunks
      ↓ Fetch parent chunks for full context
Context window
      ↓ Azure OpenAI GPT-4o
Grounded answer + source citations
```

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| LLM | Azure OpenAI GPT-4o | 2024-12-01-preview | Answer generation |
| Embedding | Sentence Transformers | all-MiniLM-L6-v2 | Text vectorisation |
| Re-ranking | Cross-Encoder | ms-marco-MiniLM-L-6-v2 | Candidate re-ranking |
| RAG Framework | LangChain | 0.0.336 | Pipeline orchestration |
| Vector DB | ChromaDB | 0.4.17 | Vector storage & search |
| Backend | FastAPI | — | REST API |
| Server | Uvicorn | — | ASGI server |
| Frontend | HTML/CSS/JS | — | Chat interface |
| Doc Loader | python-docx | — | .docx parsing |

---

## Folder Structure

```
customer_support_bot/
├── Modular_Code/               # Backend application
│   ├── api.py                  # FastAPI entry point
│   ├── customer_support.py     # Pipeline orchestrator
│   ├── llm_app.py              # Streamlit UI (alternative)
│   ├── eval_rag.py             # RAG evaluation tests
│   ├── requirements.txt        # Python dependencies
│   ├── .env                    # Environment variables (not in git)
│   ├── .env.example            # Template for .env
│   ├── agents/
│   │   ├── support.py          # Greeting node
│   │   └── helpers.py          # Memory utilities
│   ├── data/
│   │   ├── chat.py             # Message data models
│   │   └── graph.py            # Graph output models
│   ├── graph/
│   │   ├── node.py             # Base node class
│   │   ├── edge.py             # Base edge class
│   │   ├── chain_based_node.py # LLM-driven node
│   │   ├── chain_based_edge.py # LLM-driven edge
│   │   ├── text_based_edge.py  # Pattern-matching edge
│   │   └── static_text_node.py # Fixed response node
│   ├── tools/
│   │   └── rag_responder.py    # Core RAG engine (HelpCenterAgent)
│   └── assets/
│       ├── Docs/               # Airline knowledge base (.docx files)
│       └── chroma_db/          # Persisted vector index
├── frontend/                   # Web chat UI
│   ├── index.html
│   ├── script.js
│   └── style.css
└── docs/                       # Documentation
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `AZURE_OPENAI_API_KEY` | ✅ | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | ✅ | Azure endpoint URL |
| `OPENAI_API_VERSION` | ✅ | API version (e.g. 2024-12-01-preview) |
| `OPENAI_API_TYPE` | ✅ | Must be `azure` |
| `AZURE_DEPLOYMENT_NAME` | ✅ | Deployment name (e.g. gpt-4o) |
| `DOCX_DOC_PATH` | ✅ | Full path to knowledge base folder |
| `PERSIST_DIRECTORY` | ✅ | ChromaDB storage path |
| `RETRIEVAL_K` | ⚙️ | Number of candidates to retrieve (default: 12) |
| `FINAL_CONTEXT_K_FOCUSED` | ⚙️ | Top K for focused queries (default: 4) |
| `FINAL_CONTEXT_K_BROAD` | ⚙️ | Top K for broad queries (default: 8) |
| `TOC_PAGE_SCAN_LIMIT` | ⚙️ | Pages to scan for TOC in PDFs (default: 4) |
