#!/bin/bash
echo "=== Iniciando Control Metabólico ==="

# Crear crontab para main.py
echo "0 12-16 * * * cd /app && /app/.venv/bin/python main.py >> /app/data/cron.log 2>&1" > /tmp/crontab

# Arrancar cron nativo en background
crond -f -d 8 &

# Arrancar uvicorn en foreground  
uvicorn api:app --host 0.0.0.0 --port 8080
