FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install dependencies (cached layer — only re-runs if requirements.txt changes)
COPY Modular_Code/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and frontend
COPY Modular_Code/ ./Modular_Code/
COPY frontend/   ./frontend/

# Snapshot initial docs so the entrypoint can seed the volume on first run
RUN cp -r Modular_Code/assets/Docs /app/initial_docs

# Entrypoint seeds /app/docs and starts uvicorn
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# /app/docs  → knowledge base documents (uploaded files land here too)
# /app/data  → PageIndex tree cache (survives restarts / re-deploys)
VOLUME ["/app/docs", "/app/data"]

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOCX_DOC_PATH=/app/docs \
    PERSIST_DIRECTORY=/app/data

EXPOSE 8000

WORKDIR /app/Modular_Code

ENTRYPOINT ["/app/docker-entrypoint.sh"]
