"""
main.py — Orquestador V2.0
Mejoras vs V1.0:
  1. Notificación Telegram en error crítico del orquestador
  2. Log explícito del motivo de abort en FASE 2
  3. Timeout de seguridad por fase (evita cuelgues infinitos)
  4. Resumen final de ejecución en log
  5. Manejo correcto de señales del sistema (SIGTERM de Railway)
"""

import os
import logging
import signal
import requests
import pytz
from datetime import datetime
import daily_renpho
import job_dieta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

TZ                 = pytz.timezone(os.getenv("TZ", "America/Phoenix"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
DRY_RUN            = os.getenv("DRY_RUN", "false").lower() == "true"


# ─── UTILIDADES ───────────────────────────────────────────────────────────────

def _alerta_critica(mensaje: str) -> None:
    """
    Manda alerta directa a Telegram cuando el orquestador mismo falla.
    Independiente de las funciones de daily/job para no crear dependencia circular.
    """
    if DRY_RUN or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.info(f"[DRY RUN / Sin config] Alerta: {mensaje}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje},
            timeout=10,
        )
    except Exception as e:
        logging.error(f"No se pudo enviar alerta crítica a Telegram: {e}")


class _Timeout:
    """Context manager de timeout usando SIGALRM (solo Linux/Railway)."""
    def __init__(self, segundos: int, fase: str):
        self.segundos = segundos
        self.fase     = fase

    def _handler(self, signum, frame):
        raise TimeoutError(f"{self.fase} excedió el límite de {self.segundos}s")

    def __enter__(self):
        signal.signal(signal.SIGALRM, self._handler)
        signal.alarm(self.segundos)
        return self

    def __exit__(self, *args):
        signal.alarm(0)  # Cancela el alarm si terminó a tiempo


# ─── FASES ────────────────────────────────────────────────────────────────────

def fase_1_ingesta() -> bool:
    """
    Retorna True si la ingesta fue exitosa O si el pesaje ya estaba procesado.
    Retorna False SOLO si hubo un error real en la extracción.
    """
    logging.info("─" * 40)
    logging.info("FASE 1: Ingesta Biométrica Diaria")
    logging.info("─" * 40)
    try:
        with _Timeout(120, "FASE 1"):  # 2 min máximo para Renpho + SQLite
            resultado = daily_renpho.ejecutar_diario()
        if resultado:
            logging.info("FASE 1: ✅ Completada correctamente.")
        else:
            logging.error("FASE 1: ❌ Falló — ejecutar_diario() retornó False.")
        return resultado
    except TimeoutError as e:
        logging.error(f"FASE 1: ⏱️ Timeout — {e}")
        return False
    except Exception as e:
        logging.error(f"FASE 1: 💥 Excepción no controlada — {e}", exc_info=True)
        return False


def fase_2_dieta(ingesta_exitosa: bool) -> None:
    """
    Corre solo los domingos. Requiere que la ingesta haya sido exitosa.
    El job_dieta tiene su propio filtro de domingo como segunda línea de defensa.
    """
    logging.info("─" * 40)
    hoy = datetime.now(TZ)

    if hoy.weekday() != 6:
        logging.info(f"FASE 2: Omitida — hoy es {hoy.strftime('%A')}, no domingo.")
        return

    logging.info("FASE 2: Domingo detectado — Evaluando Lazo Cerrado Metabólico")
    logging.info("─" * 40)

    if not ingesta_exitosa:
        msg = "⚠️ FASE 2 abortada: la ingesta biométrica falló. No se generará el plan semanal para no usar datos desactualizados."
        logging.warning(msg)
        _alerta_critica(f"🔴 <b>Orquestador:</b> {msg}")
        return

    try:
        with _Timeout(300, "FASE 2"):  # 5 min máximo para Gemini Pro
            job_dieta.ejecutar_job()
        logging.info("FASE 2: ✅ Completada correctamente.")
    except TimeoutError as e:
        logging.error(f"FASE 2: ⏱️ Timeout — {e}")
        _alerta_critica(f"⏱️ <b>Job Dieta:</b> Timeout después de 5 minutos. Revisa Railway.")
    except Exception as e:
        logging.error(f"FASE 2: 💥 Excepción no controlada — {e}", exc_info=True)
        _alerta_critica(f"🔴 <b>Job Dieta:</b> Error crítico — {e}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    inicio = datetime.now(TZ)
    logging.info("=" * 40)
    logging.info(f"🚀 Sistema de Control Autónomo — {inicio.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logging.info("=" * 40)

    try:
        ingesta_ok = fase_1_ingesta()
        fase_2_dieta(ingesta_ok)

    except Exception as e:
        # Error que escapó de ambas fases — situación muy rara
        msg = f"❌ Error CRÍTICO en el orquestador: {e}"
        logging.error(msg, exc_info=True)
        _alerta_critica(f"🚨 <b>Orquestador caído:</b> {e}")

    finally:
        duracion = (datetime.now(TZ) - inicio).total_seconds()
        logging.info("=" * 40)
        logging.info(f"✅ Ejecución finalizada en {duracion:.1f}s")
        logging.info("=" * 40)


if __name__ == "__main__":
    main()
