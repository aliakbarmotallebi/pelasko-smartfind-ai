#!/bin/sh
set -e

if [ ! -f "${DATA_DIR}/index.faiss" ] || [ ! -f "${DATA_DIR}/products.pkl" ]; then
  echo "Index not found in ${DATA_DIR}, building..."
  python -m scripts.build_index
fi

exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
