import os
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    print(mensaje)
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje})

def escanear_modulos():
    reporte = "🔍 *Reporte del Escáner Renpho:*\n\n"
    
    # Intento 1: renpho
    try:
        import renpho
        reporte += f"✅ Módulo `renpho` existe.\n"
        reporte += f"Contenido: `{dir(renpho)}`\n\n"
    except Exception as e:
        reporte += f"❌ Módulo `renpho` falló: {e}\n\n"
        
    # Intento 2: renpho_api
    try:
        import renpho_api
        reporte += f"✅ Módulo `renpho_api` existe.\n"
        reporte += f"Contenido: `{dir(renpho_api)}`\n\n"
    except Exception as e:
        reporte += f"❌ Módulo `renpho_api` falló: {e}\n\n"

    enviar_telegram(reporte)

if __name__ == "__main__":
    escanear_modulos()
