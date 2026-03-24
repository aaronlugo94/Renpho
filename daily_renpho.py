"""
daily_renpho.py — V7.0
Reporte diario limpio: lo esencial, sin ruido.
Fix score: umbrales corregidos para que reflejen progreso real.
"""

import os
import sqlite3
import requests
import pytz
import time
import logging
from datetime import datetime
from google import genai
from renpho import RenphoClient

# ─── CONFIG ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

TZ      = pytz.timezone(os.getenv("TZ", "America/Phoenix"))
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
DB_PATH = "/app/data/mis_datos_renpho.db"

REQUIRED_VARS = ["RENPHO_EMAIL", "RENPHO_PASSWORD", "GOOGLE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
env_vars = {var: os.getenv(var) for var in REQUIRED_VARS}
faltantes = [v for v, k in env_vars.items() if not k]
if faltantes:
    raise RuntimeError(f"Faltan variables de entorno: {', '.join(faltantes)}")

# ─── RANGOS ───────────────────────────────────────────────────────────────────
RANGOS = {
    "bmi":          {"optimo": (18.5, 27.0), "alerta": (27.1, 32.0), "critico": (32.1, 99)},
    "grasa_hombre": {"optimo": (20.0, 27.0), "alerta": (27.1, 32.0), "critico": (32.1, 100)},
    "visceral":     {"optimo": (1,    9),    "alerta": (10,   13),   "critico": (14,   30)},
    "agua":         {"optimo": (53.0, 65.0), "alerta": (49.0, 52.9), "critico": (0,    48.9)},
    "proteina":     {"optimo": (16.5, 20.0), "alerta": (15.0, 16.4), "critico": (0,    14.9)},
}

def clasificar(valor, metrica):
    if valor is None or metrica not in RANGOS:
        return ""
    r = RANGOS[metrica]
    if r["optimo"][0] <= valor <= r["optimo"][1]:     return " 🟢"
    elif r["alerta"][0] <= valor <= r["alerta"][1]:   return " 🟡"
    elif r["critico"][0] <= valor <= r["critico"][1]: return " 🔴"
    return ""

# ─── SCORE ────────────────────────────────────────────────────────────────────
def calcular_score_composicion(m: dict) -> tuple[int, str]:
    """
    Score 0-100 calibrado al perfil de Aaron.
    FIX V7: los umbrales son acumulativos — siempre se suma algo por estar vivo.
    Punto de partida real: grasa 32.6%, muscular 43.5%, visceral 14, agua 48.6% → ~17pts
    Meta 6 meses: grasa <27%, muscular >45%, visceral <10, agua >53% → ~70pts
    """
    score = 0

    # GRASA CORPORAL (35 pts)
    grasa = m.get("grasa") or m.get("Grasa_Porcentaje") or 99
    if   grasa <= 20:  score += 35
    elif grasa <= 23:  score += 28
    elif grasa <= 26:  score += 21
    elif grasa <= 29:  score += 14
    elif grasa <= 32:  score += 7   # Zona actual de Aaron → siempre suma algo
    else:              score += 3   # Peor que punto de partida

    # MÚSCULO ESQUELÉTICO % (25 pts)
    musc = m.get("musculo_pct") or m.get("Musculo_Pct") or 0
    if   musc >= 47:   score += 25
    elif musc >= 45:   score += 20
    elif musc >= 43:   score += 15  # Zona actual → siempre suma algo
    elif musc >= 40:   score += 9
    elif musc >= 37:   score += 4
    else:              score += 0

    # GRASA VISCERAL (25 pts)
    visc = m.get("grasa_visceral") or m.get("VisFat") or 99
    if   visc <= 7:    score += 25
    elif visc <= 9:    score += 20
    elif visc <= 11:   score += 13
    elif visc <= 13:   score += 6
    elif visc <= 15:   score += 2   # Zona actual de Aaron → siempre suma algo
    else:              score += 0

    # AGUA CORPORAL (15 pts)
    agua = m.get("agua") or m.get("Agua") or 0
    if   55 <= agua <= 65: score += 15
    elif 53 <= agua < 55:  score += 12
    elif 51 <= agua < 53:  score += 8
    elif 49 <= agua < 51:  score += 4
    elif 48 <= agua < 49:  score += 2   # Zona actual → siempre suma algo
    else:                  score += 0

    if   score >= 75: desc = "Élite 🏆"
    elif score >= 58: desc = "Muy bueno 💪"
    elif score >= 42: desc = "En progreso 📈"
    elif score >= 25: desc = "Construyendo base ⚙️"
    else:             desc = "Día 1 — el camino empieza aquí 🚀"

    return score, desc

# ─── BASE DE DATOS ─────────────────────────────────────────────────────────────
def inicializar_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pesajes (
                Fecha TEXT PRIMARY KEY, Timestamp INTEGER UNIQUE,
                Peso_kg REAL, Grasa_Porcentaje REAL, Agua REAL, Musculo_Pct REAL,
                Musculo_kg REAL, BMR INTEGER, VisFat REAL, BMI REAL,
                EdadMetabolica INTEGER, FatFreeWeight REAL, Proteina REAL, MasaOsea REAL
            )
        """)
        columnas = {row[1] for row in conn.execute("PRAGMA table_info(pesajes)")}
        for col, tipo in {"Timestamp":"INTEGER","Musculo_kg":"REAL","FatFreeWeight":"REAL",
                          "Proteina":"REAL","MasaOsea":"REAL","Musculo_Pct":"REAL"}.items():
            if col not in columnas:
                conn.execute(f"ALTER TABLE pesajes ADD COLUMN {col} {tipo}")
        if "Musculo" in columnas and "Musculo_Pct" in columnas:
            conn.execute("UPDATE pesajes SET Musculo_Pct = Musculo WHERE Musculo_Pct IS NULL")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_timestamp ON pesajes (Timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fecha ON pesajes (Fecha)")
        conn.commit()

def guardar_si_es_nuevo(m: dict) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("""
            INSERT OR IGNORE INTO pesajes
            (Fecha, Timestamp, Peso_kg, Grasa_Porcentaje, Agua, Musculo_Pct,
             Musculo_kg, BMR, VisFat, BMI, EdadMetabolica, FatFreeWeight, Proteina, MasaOsea)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (m["fecha_str"], m["time_stamp"], m["peso"], m["grasa"], m["agua"],
              m["musculo_pct"], m["masa_muscular_kg"], m["bmr"], m["grasa_visceral"],
              m["bmi"], m["edad_metabolica"], m["fat_free_weight"], m["proteina"], m["masa_osea"]))
        conn.commit()
        insertado = cur.rowcount == 1
    logging.info("💾 Pesaje persistido." if insertado else "💤 Duplicado ignorado.")
    return insertado

def obtener_pesaje_anterior(fecha_actual_str: str) -> dict | None:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("""
                SELECT Peso_kg, Grasa_Porcentaje, Musculo_Pct, Musculo_kg, Agua,
                       BMI, VisFat, Proteina, EdadMetabolica, Fecha
                FROM pesajes WHERE Fecha < ? ORDER BY Fecha DESC LIMIT 1
            """, (fecha_actual_str,)).fetchone()
        if row:
            return {"peso":row[0],"grasa":row[1],"musculo_pct":row[2],"masa_muscular_kg":row[3],
                    "agua":row[4],"bmi":row[5],"grasa_visceral":row[6],"proteina":row[7],
                    "edad_metabolica":row[8],"fecha":row[9]}
    except Exception:
        pass
    return None

def obtener_tendencia_7d(fecha_actual_str: str) -> float | None:
    """Retorna pendiente kg/semana por regresión lineal — misma lógica que SISO."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("""
                SELECT Peso_kg FROM pesajes
                WHERE Fecha <= ? AND Fecha >= date(?, '-7 day')
                ORDER BY Fecha ASC
            """, (fecha_actual_str, fecha_actual_str)).fetchall()
        pesos = [r[0] for r in rows if r[0]]
        if len(pesos) < 3:
            return None
        n = len(pesos)
        x_m = (n-1)/2
        y_m = sum(pesos)/n
        num = sum((i-x_m)*(y-y_m) for i,y in enumerate(pesos))
        den = sum((i-x_m)**2 for i in range(n))
        return round((num/den)*7, 2) if den else None
    except Exception:
        return None

# ─── RENPHO ───────────────────────────────────────────────────────────────────
def obtener_datos_renpho() -> dict:
    logging.info("🔄 Extrayendo telemetría de Renpho...")
    cliente = RenphoClient(env_vars["RENPHO_EMAIL"], env_vars["RENPHO_PASSWORD"])
    mediciones = None
    try:
        mediciones = cliente.get_all_measurements()
    except Exception as e:
        logging.warning(f"Fallback por MAC: {e}")
    if not mediciones:
        devices = cliente.get_device_info()
        mac = devices[0].get("mac") if devices else None
        if not mac:
            raise ValueError("No hay dispositivos vinculados.")
        mediciones = cliente.get_measurements(table_name=mac, user_id=cliente.user_id, total_count=10)
    if not mediciones:
        raise ValueError("Renpho devolvió lista vacía.")

    def ts(m):
        return m.get("timeStamp") or m.get("time_stamp") or m.get("timestamp") or \
               m.get("created_at") or m.get("createTime") or m.get("measureTime") or 0

    u = max(mediciones, key=ts)
    t = ts(u)
    if not t:
        raise ValueError(f"Sin timestamp. Campos: {list(u.keys())}")

    datos = {
        "time_stamp": t, "fecha_str": datetime.fromtimestamp(t, TZ).strftime("%Y-%m-%d"),
        "peso": u.get("weight"), "grasa": u.get("bodyfat"), "agua": u.get("water"),
        "bmi": u.get("bmi"), "bmr": u.get("bmr"), "edad_metabolica": u.get("bodyage"),
        "grasa_visceral": u.get("visfat"), "masa_muscular_kg": u.get("sinew"),
        "musculo_pct": u.get("muscle"), "fat_free_weight": u.get("fatFreeWeight"),
        "proteina": u.get("protein"), "masa_osea": u.get("bone"),
    }
    nulos = [c for c in ["peso","grasa","musculo_pct","agua"] if datos.get(c) is None]
    if nulos:
        raise ValueError(f"Datos críticos faltantes: {nulos}")
    return datos

# ─── ANÁLISIS IA — CORTO ──────────────────────────────────────────────────────
def analizar_con_ia(m: dict, anterior: dict | None, tendencia_7d: float | None) -> str:
    logging.info("🧠 Generando análisis IA...")
    client = genai.Client(api_key=env_vars["GOOGLE_API_KEY"])

    ctx_delta = ""
    if anterior:
        dias = (datetime.strptime(m["fecha_str"],"%Y-%m-%d") -
                datetime.strptime(anterior["fecha"],"%Y-%m-%d")).days
        ctx_delta = (f"vs hace {dias}d: peso {m['peso']-anterior['peso']:+.1f}kg, "
                     f"grasa {m['grasa']-anterior['grasa']:+.1f}%, "
                     f"músculo {m['musculo_pct']-anterior['musculo_pct']:+.1f}%")

    tend_str = f"Tendencia 7d: {tendencia_7d:+.2f} kg/sem" if tendencia_7d else ""

    prompt = f"""Eres un experto en recomposición corporal. Analiza estos datos y responde MUY BREVEMENTE.

DATOS HOY ({m['fecha_str']}):
Peso: {m['peso']}kg | Grasa: {m['grasa']}% | Músculo: {m['musculo_pct']}% | Visceral: {m['grasa_visceral']} | Agua: {m['agua']}% | BMR: {m['bmr']} kcal
{ctx_delta}
{tend_str}

FORMATO OBLIGATORIO — máximo 3 líneas cortas, sin listas, solo texto:
Línea 1: qué dicen los datos HOY (distingue ruido hídrico de cambio real)
Línea 2: una acción concreta para las próximas 24 horas
Línea 3 (opcional): frase motivadora MUY CORTA si aplica

USA SOLO <b> e <i>. PROHIBIDO cualquier otra etiqueta HTML. MÁXIMO 150 palabras."""

    for intento in range(3):
        try:
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            texto = resp.text.strip() if resp and resp.text else ""
            if texto:
                return texto
        except Exception as e:
            logging.warning(f"Intento {intento+1}: {e}")
            time.sleep(2)
    return "<i>⚠️ Análisis no disponible.</i>"

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
_SANITIZE = [("<br>","\n"),("<br/>","\n"),("<ul>",""),("</ul>",""),("<li>","• "),("</li>","\n"),
             ("<p>",""),("</p>","\n"),("<strong>","<b>"),("</strong>","</b>"),
             ("<h1>",""),("</h1>","\n"),("<h2>",""),("</h2>","\n"),("<h3>",""),("</h3>","\n")]

def enviar_telegram(msg: str):
    if DRY_RUN:
        logging.info(f"[DRY RUN]\n{msg}"); return
    for old, new in _SANITIZE:
        msg = msg.replace(old, new)
    url = f"https://api.telegram.org/bot{env_vars['TELEGRAM_BOT_TOKEN']}/sendMessage"
    res = requests.post(url, json={"chat_id":env_vars["TELEGRAM_CHAT_ID"],"text":msg,"parse_mode":"HTML"}, timeout=10)
    if res.status_code != 200:
        requests.post(url, json={"chat_id":env_vars["TELEGRAM_CHAT_ID"],"text":msg}, timeout=10)

# ─── FLUJO PRINCIPAL ──────────────────────────────────────────────────────────
def ejecutar_diario() -> bool:
    try:
        inicializar_db()
        m = obtener_datos_renpho()

        if not guardar_si_es_nuevo(m):
            return True

        logging.info("🚀 Nuevo pesaje — generando reporte...")

        anterior    = obtener_pesaje_anterior(m["fecha_str"])
        tend_7d     = obtener_tendencia_7d(m["fecha_str"])
        score, desc = calcular_score_composicion(m)
        analisis    = analizar_con_ia(m, anterior, tend_7d)

        # Deltas
        def d(hoy, ant_val, inv=False):
            if ant_val is None: return ""
            diff = hoy - ant_val
            if abs(diff) < 0.05: return " ⚪"
            ok = diff < 0 if inv else diff > 0
            return f" ({diff:+.1f}) {'🟢' if ok else '🔴'}"

        ant = anterior
        dias_str = ""
        if ant:
            dias = (datetime.strptime(m["fecha_str"],"%Y-%m-%d") -
                    datetime.strptime(ant["fecha"],"%Y-%m-%d")).days
            dias_str = f" <i>vs hace {dias}d</i>"

        # Tendencia label
        if tend_7d:
            icon = "📉" if tend_7d < -0.1 else "📈" if tend_7d > 0.1 else "➡️"
            tend_str = f" {icon} {tend_7d:+.1f} kg/sem"
        else:
            tend_str = ""

        # Alertas — solo las críticas, en una línea
        alertas = []
        if m.get("grasa_visceral") and m["grasa_visceral"] >= 14: alertas.append(f"visceral {m['grasa_visceral']} 🔴")
        if m.get("agua") and m["agua"] < 49:    alertas.append(f"agua {m['agua']}% 🔴")
        if m.get("proteina") and m["proteina"] < 15: alertas.append(f"proteína {m['proteina']}% 🔴")
        alertas_str = f"\n⚠️ {' · '.join(alertas)}" if alertas else ""

        # Macros
        try:
            with sqlite3.connect(DB_PATH) as c:
                row = c.execute("SELECT valor FROM config_nutricion WHERE clave='kcal_mult'").fetchone()
                mult = float(row[0]) if row else 25.0
        except: mult = 25.0

        bmr  = m.get("bmr") or round(m["peso"] * 22)
        ffm  = m.get("fat_free_weight") or (m["peso"] * (1 - m["grasa"]/100))
        kcal = max(round(m["peso"] * mult), round(bmr * 1.15))
        prot = round(ffm * 2.2)
        gras = round(m["peso"] * 0.7)
        carb = max(0, round((kcal - (prot*4 + gras*9)) / 4))

        # Día
        DIAS = {0:("Lunes","🏋️ Gym — Empuje"),1:("Martes","🏠 Casa — Circuito 30 min"),
                2:("Miércoles","🏋️ Gym — Tirón"),3:("Jueves","🏋️ Gym — Pierna"),
                4:("Viernes","🏠 Casa — Circuito 30 min"),5:("Sábado","🚶 Recuperación"),
                6:("Domingo","🔄 Reseteo")}
        dia_n, dia_t = DIAS.get(datetime.now(TZ).weekday(), ("",""))

        reporte = (
            f"📊 <b>{m['fecha_str']}</b> — {dia_n} {dia_t}{dias_str}\n"
            f"🏆 Score: <b>{score}/100</b> — {desc}{tend_str}\n"
            f"{'─'*28}\n"
            f"⚖️ <b>{m['peso']} kg</b>{d(m['peso'], ant['peso'] if ant else None, inv=True)}  "
            f"🥓 <b>{m['grasa']}%</b>{d(m['grasa'], ant['grasa'] if ant else None, inv=True)}{clasificar(m['grasa'],'grasa_hombre')}\n"
            f"💪 <b>{m['musculo_pct']}%</b>{d(m['musculo_pct'], ant['musculo_pct'] if ant else None)}  "
            f"🫀 <b>{m['grasa_visceral']}</b>{clasificar(m['grasa_visceral'],'visceral')}  "
            f"💧 <b>{m['agua']}%</b>{clasificar(m['agua'],'agua')}\n"
            f"{alertas_str}\n"
            f"🎯 <b>{kcal} kcal</b> · P:{prot}g C:{carb}g G:{gras}g\n"
            f"{'─'*28}\n"
            f"{analisis}"
        )

        enviar_telegram(reporte)
        logging.info("✅ Reporte diario enviado.")
        return True

    except Exception:
        logging.error("Error crítico.", exc_info=True)
        enviar_telegram("🔴 <b>Error — Reporte Diario</b>: Revisa logs.")
        return False

if __name__ == "__main__":
    ejecutar_diario()
