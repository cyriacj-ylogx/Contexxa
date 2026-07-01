#!/bin/sh
set -e

export PYTHONPATH=/app/Modular_Code

# Seed the docs volume with initial documents on first run
if [ -z "$(ls -A /app/docs 2>/dev/null)" ]; then
    echo "[entrypoint] Fresh volume detected — seeding /app/docs with initial documents..."
    cp -r /app/initial_docs/. /app/docs/
    echo "[entrypoint] Seeded $(ls /app/docs | wc -l) documents."
else
    echo "[entrypoint] /app/docs already has $(ls /app/docs | wc -l) documents, skipping seed."
fi

exec uvicorn api:app --host 0.0.0.0 --port 8000
