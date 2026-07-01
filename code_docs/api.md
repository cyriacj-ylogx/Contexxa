# API Documentation — api.py

## Overview

`api.py` is the FastAPI backend entry point. It exposes HTTP endpoints for the chat UI to communicate with the RAG pipeline.

**File:** `Modular_Code/api.py`
**Runs on:** `http://localhost:8000`

---

## Startup Behaviour

When the server starts, it automatically:
1. Loads environment variables from `.env`
2. Initialises `CustomerSupportPipeline`
3. Runs an empty query (`pipeline.run("")`) to:
   - Trigger the greeting node
   - Build or load the ChromaDB vector index
   - Load the embedding model and cross-encoder into memory

```python
@app.on_event("startup")
def startup_event():
    global pipeline
    if pipeline is None:
        pipeline = CustomerSupportPipeline()
        pipeline.run("")   # Initialises pipeline and loads index
```

> ⚠️ First startup takes 2-5 minutes as it indexes all documents.
> Subsequent startups are fast as the index is loaded from disk.

---

## CORS Configuration

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Allow any origin (file://, localhost, etc.)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Allows the frontend HTML (served from any port or file://) to communicate with the backend without browser CORS errors.

---

## Endpoints

### GET /
Health check endpoint.

**Request:** None

**Response:**
```json
{
  "status": "Airline Support Bot API is running"
}
```

---

### POST /chat
Main chat endpoint. Accepts user message, returns AI answer with source citations.

**Request Body:**
```json
{
  "message": "What is the baggage allowance?"
}
```

**Response Body:**
```json
{
  "answer": "The baggage allowance for domestic flights is...",
  "sources": [
    {
      "content": "15kg per person, 1 piece only...",
      "source": "Baggage Allowance.docx",
      "score": 0.97
    },
    {
      "content": "Hand bag up to 7kg and 115cm...",
      "source": "Baggage Allowance.docx",
      "score": 0.91
    }
  ]
}
```

**Logic:**
```
1. Receive message from frontend
2. Pass to pipeline.run(message)
3. Extract answer and raw sources from response
4. Format sources (extract metadata, handle score type errors)
5. Return ChatResponse with answer + sources
```

**Fallback behaviour:**
- If pipeline not ready → returns "Service is starting up..."
- If answer is empty → returns default fallback message
- If score cannot be parsed → defaults to 0.0

---

## Data Models

### ChatRequest
```python
class ChatRequest(BaseModel):
    message: str   # The user's question
```

### Source
```python
class Source(BaseModel):
    content: str   # Excerpt from the source document
    source:  str   # Source document filename
    score:   float # Cross-encoder relevance score
```

### ChatResponse
```python
class ChatResponse(BaseModel):
    answer:  str   # AI-generated answer
    sources: list  # List of source citations
```

---

## Running the API

```bash
# From Modular_Code/ directory with venv activated
uvicorn api:app --host 0.0.0.0 --port 8000

# With auto-reload (development only)
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Pipeline not initialised | Returns "Service is starting up" message |
| Empty answer from RAG | Returns default fallback message |
| Invalid score value | Defaults score to 0.0 |
| Source metadata missing | Returns "Unknown" as source name |
