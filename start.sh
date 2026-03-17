#!/bin/bash
echo "=== Iniciando Control Metabólico ==="

# Arrancar scheduler Python en background
/app/.venv/bin/python scheduler.py &

# Arrancar uvicorn en foreground
uvicorn api:app --host 0.0.0.0 --port 8080
