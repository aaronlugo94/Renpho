#!/bin/bash
# Arranca uvicorn en background y el cron con supercronic
echo "=== Iniciando Control Metabólico ==="

# Instalar supercronic si no existe
if ! command -v supercronic &> /dev/null; then
    curl -fsSL https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 -o /usr/local/bin/supercronic
    chmod +x /usr/local/bin/supercronic
fi

# Crear crontab
echo "0 12-16 * * * cd /app && python main.py" > /tmp/crontab

# Arrancar supercronic en background
supercronic /tmp/crontab &

# Arrancar uvicorn en foreground
uvicorn api:app --host 0.0.0.0 --port 8080
