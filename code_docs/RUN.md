# Running the Airline Support Bot

## Prerequisites

- Python 3.9+
- Git
- Azure OpenAI access (API key + endpoint)

---

## 1. Clone the Repository

```bash
git clone https://github.com/recruitmentbricks/customer_support_bot.git
cd customer_support_bot
git checkout airline_bot_ui
```

---

## 2. Create a Virtual Environment

```bash
cd Modular_Code

# Create venv
python -m venv .venv

# Activate — Windows
.venv\Scripts\activate

# Activate — macOS/Linux
source .venv/bin/activate
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> ⏳ This may take a few minutes — installs PyTorch, sentence-transformers, chromadb, langchain, and other ML libraries.

---

## 4. Configure Environment Variables

Copy the example env file and fill in your Azure credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Azure OpenAI credentials
AZURE_OPENAI_API_KEY=your_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
OPENAI_API_VERSION=2024-12-01-preview
OPENAI_API_TYPE=azure
AZURE_DEPLOYMENT_NAME=gpt-4o

# Knowledge base — full absolute path to Docs folder
DOCX_DOC_PATH=C:\full\path\to\customer_support_bot\Modular_Code\assets\Docs

# ChromaDB persistence directory (relative to Modular_Code/)
PERSIST_DIRECTORY=chroma_db/docs

# Retrieval tuning (optional — defaults shown)
RETRIEVAL_K=12
FINAL_CONTEXT_K_FOCUSED=4
FINAL_CONTEXT_K_BROAD=8
TOC_PAGE_SCAN_LIMIT=4
```

> ⚠️ `DOCX_DOC_PATH` must be the **full absolute path** on your machine, not a relative path.

---

## 5. Start the Backend (FastAPI)

```bash
# From inside Modular_Code/ with venv activated
uvicorn api:app --host 0.0.0.0 --port 8000
```

### First Startup

The **first startup** takes **2–5 minutes** because it:
1. Loads all `.docx` files from `assets/Docs/`
2. Splits them into parent/child chunks
3. Embeds all child chunks using Sentence Transformers
4. Stores the vector index in `chroma_db/docs/`

You will see:
```
INFO: Loading documents...
INFO: Building ChromaDB index...
INFO: Index built and persisted.
INFO: Application startup complete.
```

### Subsequent Startups

Subsequent startups load the persisted index from disk and are fast (~5–10 seconds).

---

## 6. Start the Frontend

Open a **new terminal** (keep the backend running):

```bash
cd customer_support_bot/frontend
python -m http.server 8080
```

---

## 7. Open the Chat UI

Visit: **http://localhost:8080**

The bot should greet you:
> "Hi, I'm the Airline Support Agent. Ask me anything about flights, baggage, check-in, refunds, or other travel services."

---

## Adding New Documents

To add new `.docx` or `.pdf` files to the knowledge base:

1. Place the file in `Modular_Code/assets/Docs/`

2. Delete the existing ChromaDB index so it rebuilds with the new document:
   ```bash
   # Windows
   rmdir /s /q Modular_Code\chroma_db\docs

   # macOS/Linux
   rm -rf Modular_Code/chroma_db/docs
   ```

3. Restart the backend:
   ```bash
   uvicorn api:app --host 0.0.0.0 --port 8000
   ```

The index will rebuild automatically (2–5 minutes) including the new document.

---

## Switching Knowledge Base

To point the bot at a different folder of documents:

1. Update `DOCX_DOC_PATH` in `.env` to the new folder path
2. Update `PERSIST_DIRECTORY` to a new path (so the old index is not reused)
3. Delete the old ChromaDB folder if it exists
4. Restart the backend

---

## Troubleshooting

### Backend won't start
- Check that `.env` exists and all required variables are set
- Verify the virtual environment is activated (`which python` / `where python`)
- Check port 8000 is free: `netstat -ano | findstr :8000` (Windows)

### "Service is starting up" in chat
- The backend is still initialising. Wait 30–60 seconds and try again.

### First query is slow (~30 seconds)
- Normal behaviour. The cross-encoder re-ranker model loads on the first query. Subsequent queries are faster (~3–5 seconds).

### No sources returned / fallback answer
- Verify `DOCX_DOC_PATH` points to the correct folder with `.docx` files
- Check that `chroma_db/docs/` was created successfully after startup
- Ensure the ChromaDB index wasn't built from the wrong document folder

### ChromaDB lock errors (Windows)
- The backend process is still holding ChromaDB files. Kill it before deleting:
  ```powershell
  Stop-Process -Name "python" -Force
  ```

### Frontend shows "Could not reach the backend"
- Make sure the backend is running on port 8000
- Check `<meta name="api-url">` in `frontend/index.html` matches your backend URL
- Disable any browser extensions blocking localhost requests

---

## Running the Evaluation Suite

```bash
# From Modular_Code/ with venv activated
python eval_rag.py
```

See `docs/evaluation.md` for details on adding and interpreting test cases.

---

## Project Structure

```
customer_support_bot/
├── Modular_Code/           # Backend
│   ├── api.py              # FastAPI entry point
│   ├── customer_support.py # Pipeline orchestrator
│   ├── eval_rag.py         # Evaluation tests
│   ├── requirements.txt    # Dependencies
│   ├── .env                # Your credentials (not in git)
│   ├── .env.example        # Template
│   ├── tools/
│   │   └── rag_responder.py  # Core RAG engine
│   └── assets/
│       └── Docs/           # Knowledge base (.docx files)
├── frontend/               # Chat UI
│   ├── index.html
│   ├── script.js
│   └── style.css
└── docs/                   # Documentation
    ├── README.md
    ├── architecture.md
    ├── api.md
    ├── pipeline.md
    ├── rag_responder.md
    ├── frontend.md
    ├── graph.md
    ├── data_models.md
    └── evaluation.md
```
