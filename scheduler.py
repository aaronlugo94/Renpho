"""
scheduler.py — Corre main.py cada hora entre 12:00 y 16:00 MST.
Corre en background junto a uvicorn.
"""
import subprocess
import time
import logging
from datetime import datetime
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SCHEDULER] %(message)s")

TZ = pytz.timezone("America/Phoenix")

def debe_correr() -> bool:
    ahora = datetime.now(TZ)
    return 12 <= ahora.hour <= 16

def correr_main():
    logging.info("Ejecutando main.py...")
    try:
        result = subprocess.run(
            ["/app/.venv/bin/python", "main.py"],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            logging.info("main.py completado OK")
        else:
            logging.error(f"main.py error: {result.stderr[-500:]}")
    except subprocess.TimeoutExpired:
        logging.error("main.py timeout después de 10 min")
    except Exception as e:
        logging.error(f"Error corriendo main.py: {e}")

last_run_hour = -1

logging.info("Scheduler iniciado — main.py correrá cada hora entre 12:00-16:00 MST")

while True:
    ahora = datetime.now(TZ)
    hora_actual = ahora.hour

    if debe_correr() and hora_actual != last_run_hour:
        correr_main()
        last_run_hour = hora_actual

    # Esperar hasta el próximo minuto 0
    segundos_restantes = (60 - ahora.minute) * 60 - ahora.second
    time.sleep(max(segundos_restantes, 60))
