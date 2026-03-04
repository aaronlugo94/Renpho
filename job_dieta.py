"""
job_dieta.py — V5.2 Production Grade
Fixes V5.2:
  - Proteina: None corregido (pd.notna check)
  - SISO con piso inteligente basado en BMR real (BMR * 1.15)
  - PDF semanal generado y enviado por Telegram cada domingo
  - Import limpio de generar_pdf_semanal con fallback graceful
"""

import os
import sys
import sqlite3
import pandas as pd
import requests
import logging
from datetime import datetime, timedelta
from pytz import timezone
from google import genai

# Garantiza que Python busque en el mismo directorio del script
# — necesario en Railway donde el working directory puede variar
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from generar_pdf_semanal import generar_pdf
    PDF_DISPONIBLE = True
except ImportError as e:
    PDF_DISPONIBLE = False
    logging.warning(f"generar_pdf_semanal.py no encontrado — PDF desactivado. ({e})")


# ─── CONFIG ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
TZ      = timezone(os.getenv("TZ", "America/Phoenix"))
DB_PATH = "/app/data/mis_datos_renpho.db"

REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GOOGLE_API_KEY"]
env_vars = {v: os.getenv(v) for v in REQUIRED_VARS}
faltantes = [v for v, k in env_vars.items() if not k]
if faltantes:
    raise RuntimeError(f"Faltan variables de entorno: {', '.join(faltantes)}")


# ─── RANGOS CLÍNICOS — CALIBRADOS AL PERFIL DE AARON ─────────────────────────
# Mismo estándar que daily_renpho — ambos scripts deben hablar el mismo idioma.
# Ver daily_renpho.py para la lógica completa de calibración.

RANGOS = {
    "bmi":          {"optimo": (18.5, 27.0), "alerta": (27.1, 32.0), "critico": (32.1, 99)},
    "grasa_hombre": {"optimo": (20.0, 27.0), "alerta": (27.1, 32.0), "critico": (32.1, 100)},
    "visceral":     {"optimo": (1,    9),    "alerta": (10,   13),   "critico": (14,   30)},
    "agua":         {"optimo": (53.0, 65.0), "alerta": (49.0, 52.9), "critico": (0,    48.9)},
    "proteina":     {"optimo": (16.5, 20.0), "alerta": (15.0, 16.4), "critico": (0,    14.9)},
}

def clasificar(valor, metrica: str) -> str:
    if valor is None or metrica not in RANGOS:
        return ""
    r = RANGOS[metrica]
    if r["optimo"][0] <= valor <= r["optimo"][1]:   return " 🟢"
    if r["alerta"][0] <= valor <= r["alerta"][1]:   return " 🟡"
    if r["critico"][0] <= valor <= r["critico"][1]: return " 🔴"
    return ""

def calcular_score_composicion(peso, grasa, musculo_pct, agua, visceral) -> tuple[int, str]:
    score = 0
    if grasa <= 15:    score += 35
    elif grasa <= 18:  score += 28
    elif grasa <= 22:  score += 18
    elif grasa <= 27:  score += 8

    if musculo_pct >= 45:   score += 30
    elif musculo_pct >= 40: score += 24
    elif musculo_pct >= 35: score += 15
    elif musculo_pct >= 30: score += 7

    if 55 <= agua <= 65:    score += 20
    elif 50 <= agua < 55:   score += 14
    elif agua >= 45:        score += 7

    if visceral <= 7:    score += 15
    elif visceral <= 9:  score += 11
    elif visceral <= 12: score += 5

    if score >= 80:   desc = "Élite 🏆"
    elif score >= 65: desc = "Muy bueno 💪"
    elif score >= 50: desc = "En progreso 📈"
    elif score >= 35: desc = "Necesita atención ⚠️"
    else:             desc = "Zona de riesgo 🚨"
    return score, desc

def generar_alertas(peso, grasa, agua, visceral, proteina, edad_metabolica) -> str:
    alertas = []
    if visceral and visceral >= 10:
        alertas.append(f"⚠️ Grasa visceral elevada ({visceral}) — riesgo metabólico activo")
    if agua and agua < 50:
        alertas.append(f"💧 Hidratación baja ({agua}%) — prioriza agua esta semana")
    if proteina and proteina < 16:
        alertas.append(f"🥩 Proteína corporal baja ({proteina}%) — revisa ingesta proteica diaria")
    if edad_metabolica and edad_metabolica > 45:
        alertas.append(f"📅 Edad metabólica alta ({edad_metabolica} años) — prioriza hipertrofia")
    if not alertas:
        return ""
    return "\n🚨 <b>Alertas Clínicas:</b>\n" + "\n".join(f"  {a}" for a in alertas) + "\n"


# ─── BASE DE DATOS ─────────────────────────────────────────────────────────────

def inicializar_bd():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config_nutricion (
                clave TEXT PRIMARY KEY,
                valor REAL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO config_nutricion (clave, valor)
            VALUES ('kcal_mult', 24.0)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historico_dietas (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha         TEXT,
                peso          REAL,
                grasa         REAL,
                delta_peso    REAL,
                kcal_mult     REAL,
                calorias      INTEGER,
                proteina      INTEGER,
                carbs         INTEGER,
                grasas        INTEGER,
                dieta_html    TEXT,
                estado_mimo   TEXT,
                shadow_mult   REAL,
                score_comp    INTEGER
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_fecha ON historico_dietas(fecha)")

        # Migraciones en caliente para historico_dietas
        columnas_hist = {row[1] for row in conn.execute("PRAGMA table_info(historico_dietas)")}
        migraciones_hist = {
            "estado_mimo": "TEXT",
            "shadow_mult": "REAL",
            "score_comp":  "INTEGER",
        }
        for col, tipo in migraciones_hist.items():
            if col not in columnas_hist:
                conn.execute(f"ALTER TABLE historico_dietas ADD COLUMN {col} {tipo}")
                logging.info(f"Migración aplicada (historico_dietas): columna {col} añadida.")

        # ── Migración crítica de la tabla pesajes ─────────────────────────────
        # El daily migra Musculo → Musculo_Pct cuando corre, pero si el usuario
        # estuvo de viaje semanas sin pesarse, el job de dieta puede correr el
        # domingo con registros históricos sin migrar. Este bloque lo garantiza.
        columnas_pesajes = {row[1] for row in conn.execute("PRAGMA table_info(pesajes)")}

        if "pesajes" in {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            migraciones_pesajes = {
                "Timestamp":     "INTEGER",
                "Musculo_kg":    "REAL",
                "FatFreeWeight": "REAL",
                "Proteina":      "REAL",
                "MasaOsea":      "REAL",
                "Musculo_Pct":   "REAL",
            }
            for col, tipo in migraciones_pesajes.items():
                if col not in columnas_pesajes:
                    conn.execute(f"ALTER TABLE pesajes ADD COLUMN {col} {tipo}")
                    logging.info(f"Migración aplicada (pesajes): columna {col} añadida.")

            # Copia datos históricos de Musculo → Musculo_Pct donde falten
            if "Musculo" in columnas_pesajes and "Musculo_Pct" in columnas_pesajes:
                resultado = conn.execute(
                    "UPDATE pesajes SET Musculo_Pct = Musculo WHERE Musculo_Pct IS NULL AND Musculo IS NOT NULL"
                )
                if resultado.rowcount > 0:
                    logging.info(f"Migración de datos: {resultado.rowcount} registros Musculo → Musculo_Pct.")

            # Índices por si tampoco los creó el daily
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_timestamp ON pesajes (Timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fecha ON pesajes (Fecha)")

        conn.commit()


def obtener_multiplicador(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT valor FROM config_nutricion WHERE clave='kcal_mult'"
    ).fetchone()
    return float(row[0]) if row else 26.0


def actualizar_multiplicador(conn: sqlite3.Connection, nuevo_mult: float):
    conn.execute(
        "UPDATE config_nutricion SET valor=? WHERE clave='kcal_mult'",
        (nuevo_mult,)
    )


def job_ya_ejecutado_hoy(conn: sqlite3.Connection) -> bool:
    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT 1 FROM historico_dietas WHERE fecha LIKE ? LIMIT 1",
        (f"{hoy}%",)
    ).fetchone()
    return row is not None


def obtener_datos_semana(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Retorna los últimos 28 días de pesajes.
    28 días = 4 semanas — necesario para que el SISO calcule
    tendencia multi-semana en vez de reaccionar a delta puntual.
    """
    return pd.read_sql_query("""
        SELECT Fecha, Peso_kg, Grasa_Porcentaje,
               COALESCE(Musculo_Pct, Musculo) AS Musculo_Pct,
               FatFreeWeight, Agua, VisFat, BMI, EdadMetabolica, Proteina, MasaOsea, BMR
        FROM pesajes
        WHERE Fecha >= date('now', '-28 day')
        ORDER BY Fecha ASC
    """, conn)


# ─── LEYES DE CONTROL ─────────────────────────────────────────────────────────

# Estado MIMO: diagnóstico multi-variable (grasa + músculo + peso)
# Estado SISO: acción de control mono-variable (solo delta_peso → multiplicador)
# Shadow mode: MIMO calcula pero NO actúa todavía — solo se loguea y reporta

ESTADOS_MIMO = {
    "CATABOLISMO":    ("🔴", "Pérdida de músculo sin quema de grasa. Aumenta carbs peri-entrenamiento."),
    "RECOMPOSICION":  ("🟣", "Recomposición activa. Mantén proteína en límite superior."),
    "CUTTING_LIMPIO": ("🟢", "Déficit funcionando correctamente. Mantén el curso."),
    "ESTANCAMIENTO":  ("🟡", "Adaptación metabólica. Forzar oxidación de lípidos."),
    "ZONA_GRIS":      ("⚪", "Señales mixtas o ruido hídrico. Observar tendencia."),
}

def evaluar_mimo(delta_peso: float, delta_grasa: float, delta_musculo: float, mult_actual: float) -> tuple:
    """
    Motor de diagnóstico multi-variable.
    Retorna (estado, mult_sugerido, razon).
    NO modifica la base de datos — solo diagnostica.
    """
    TOL = 0.2
    if delta_peso < -0.8 and delta_musculo < -TOL and delta_grasa > -TOL:
        estado = "CATABOLISMO"
        mult   = mult_actual + 1
        razon  = f"Pérdida de peso ({delta_peso:+.2f}kg) y músculo ({delta_musculo:+.2f}%) sin quema de grasa."
    elif abs(delta_peso) <= 0.3 and delta_grasa < -TOL and delta_musculo > TOL:
        estado = "RECOMPOSICION"
        mult   = mult_actual
        razon  = f"Peso estable. Grasa ({delta_grasa:+.2f}%), Músculo ({delta_musculo:+.2f}%) — recomp. activa."
    elif delta_peso <= -0.3 and delta_grasa < -TOL and abs(delta_musculo) <= TOL:
        estado = "CUTTING_LIMPIO"
        mult   = mult_actual
        razon  = f"Pérdida controlada ({delta_peso:+.2f}kg) de tejido adiposo. Músculo preservado."
    elif delta_peso > -0.2 and delta_grasa >= -TOL and delta_musculo <= TOL:
        estado = "ESTANCAMIENTO"
        mult   = mult_actual - 1
        razon  = "Sin mejora en composición. Adaptación metabólica detectada."
    else:
        estado = "ZONA_GRIS"
        mult   = mult_actual
        razon  = "Señales mixtas. Puede ser ruido hídrico. Requiere más datos."

    mult_seguro = max(20.0, min(mult, 34.0))
    return estado, mult_seguro, razon


def calcular_tendencia_peso(df: pd.DataFrame) -> float | None:
    """
    Calcula la tendencia real de pérdida/ganancia de peso usando
    regresión lineal sobre los últimos 28 días de pesajes.
    Retorna kg/semana. None si hay menos de 3 puntos de datos.

    Por qué regresión lineal y no delta puntual:
    - El peso fluctúa 1-2 kg diarios por agua, glucógeno y sodio
    - Un delta puntual semana-a-semana tiene ~2 kg de ruido
    - La pendiente de regresión sobre 28 días tiene ~0.2 kg de error
    - Es la misma técnica que usan Cronometer, MacroFactor y NOOM
    """
    if df is None or len(df) < 3:
        return None
    import numpy as np
    x = (df["Fecha"] - df["Fecha"].iloc[0]).dt.days.values
    y = df["Peso_kg"].astype(float).values
    # Pendiente en kg/día → convertir a kg/semana
    pendiente = np.polyfit(x, y, 1)[0]
    return round(pendiente * 7, 3)


def aplicar_siso(tendencia_kg_semana: float | None, mult_actual: float,
                 bmr: int = 2000, peso: float = 100) -> tuple:
    """
    Ley de control SISO activa — modifica el multiplicador real.
    Variable de control: tendencia de peso en kg/semana (regresión 28 días).
    Piso inteligente: nunca bajar de BMR × 1.15.

    Umbrales basados en evidencia:
    - Pérdida >1 kg/semana = demasiado rápido, riesgo de catabolismo muscular
    - Pérdida 0.25-0.75 kg/semana = zona óptima para cutting con preservación muscular
    - Pérdida <0.1 kg/semana (o ganancia) = estancamiento real tras 3-4 semanas

    Si tendencia es None (menos de 3 pesajes), no actúa — espera más datos.
    """
    piso_calorias = round(bmr * 1.15)
    piso_mult     = max(round(piso_calorias / peso, 1), 21.0)

    if tendencia_kg_semana is None:
        razon = "⏳ Datos insuficientes para tendencia multi-semana. Multiplicador mantenido."
        return mult_actual, razon, False

    if tendencia_kg_semana < -1.0:
        nuevo  = mult_actual + 1.0
        razon  = (f"📉 Pérdida demasiado rápida ({tendencia_kg_semana:+.2f} kg/sem, tendencia 28d). "
                  f"Aumento multiplicador para proteger músculo.")
        cambio = True
    elif tendencia_kg_semana < -0.25:
        nuevo  = mult_actual
        razon  = (f"✅ Progreso óptimo ({tendencia_kg_semana:+.2f} kg/sem, tendencia 28d). "
                  f"Multiplicador mantenido.")
        cambio = False
    else:
        nuevo  = mult_actual - 1.0
        razon  = (f"🛑 Estancamiento real ({tendencia_kg_semana:+.2f} kg/sem, tendencia 28d). "
                  f"Recorto multiplicador calórico.")
        cambio = True

    nuevo_seguro = max(piso_mult, min(nuevo, 34.0))
    if nuevo_seguro != nuevo:
        if nuevo < piso_mult:
            razon += f" (Piso BMR: mínimo {piso_mult} kcal/kg = {piso_calorias} kcal)"
        else:
            razon += f" (Limitado a {nuevo_seguro})"
    return nuevo_seguro, razon, cambio


# ─── GENERACIÓN DE DIETA ───────────────────────────────────────────────────────

# Estructura JSON esperada de Gemini:
# {
#   "diagnostico": "Texto libre de análisis semanal...",
#   "dias": [
#     {
#       "nombre": "LUNES — Día de Ataque 1",
#       "tipo": "GYM",           // GYM | CASA | FIN DE SEMANA | RESETEO
#       "subtitulo": "Oficina + Gym 45 min — Empuje",
#       "comidas": [
#         { "label": "Desayuno", "texto": "..." },
#         { "label": "Almuerzo", "texto": "..." },
#         { "label": "Colacion", "texto": "..." },
#         { "label": "Cena",     "texto": "..." }
#       ]
#     },
#     ... (7 días)
#   ]
# }

FALLBACK_PLAN = {
    "diagnostico": "Plan de IA no disponible esta semana. Mantén los macros calculados y repite el plan de la semana anterior.",
    "dias": []
}

def generar_dieta_ia(
    peso, grasa, visceral, agua, fat_free_weight,
    calorias, proteina, carbs, grasas, bmr,
    delta_peso, delta_grasa, delta_musculo,
    estado_mimo, razon_mimo
) -> dict:
    """
    Genera el plan semanal de nutrición y entrenamiento en JSON estructurado.
    Retorna dict con claves 'diagnostico' (str) y 'dias' (list).
    GARANTÍA: siempre retorna dict válido, nunca None ni excepción.
    """
    import json, time
    logging.info("🧠 Generando plan semanal con IA (JSON estructurado)...")

    prompt = f"""Eres mi nutriólogo deportivo y entrenador personal de alto rendimiento.
Diseña un plan completo de 7 días basado en mis datos exactos.

PERFIL ACTUAL:
- Peso: {peso} kg | Grasa: {grasa}% (Visceral: {visceral}) | Agua: {agua}%
- Masa libre de grasa (FFM): {fat_free_weight} kg
- Variación semanal: Peso ({delta_peso:+.2f} kg), Grasa ({delta_grasa:+.2f}%), Músculo ({delta_musculo:+.2f}%)
- Diagnóstico metabólico: {estado_mimo} — {razon_mimo}

MACROS DIARIOS CALCULADOS:
- Calorías: {calorias} kcal | Proteína: {proteina}g | Carbohidratos: {carbs}g | Grasas: {grasas}g
- LÍMITE MÍNIMO ABSOLUTO: Nunca recomiendes por debajo de {bmr} kcal/día (BMR real).

RESTRICCIONES DE ESTILO DE VIDA (OBLIGATORIAS):
1. LUNES, MIÉRCOLES, JUEVES (Oficina + Gym pesado 45 min):
   - Salgo a las 4pm, entreno en gym, ceno a las 6pm
   - Cenas muy saciantes y altas en proteína
   - El lonche del día siguiente es SIEMPRE la sobra de la cena anterior

2. MARTES Y VIERNES (Home Office + bebé):
   - Entreno 30 min en casa durante la siesta del bebé
   - Incluye rutina EXACTA de ejercicios (sin equipo pesado)

3. FIN DE SEMANA: Recuperación activa, una comida social permitida el sábado

4. DESAYUNOS: Ultra-rápidos (menos de 5 min), portátiles para el auto

5. COLACIÓN: 1 colación de fruta fresca cada día

6. HIDRATACIÓN: Objetivo específico basado en agua corporal actual ({agua}%)

INSTRUCCIÓN DE FORMATO — MUY IMPORTANTE:
Responde ÚNICAMENTE con un objeto JSON válido. Sin texto antes ni después. Sin bloques markdown. Sin comillas de código.
El JSON debe tener exactamente esta estructura:

{{
  "diagnostico": "Párrafo de análisis de la semana y filosofía del plan. Texto libre, sin HTML.",
  "dias": [
    {{
      "nombre": "LUNES — Día de Ataque 1",
      "tipo": "GYM",
      "subtitulo": "Oficina + Gym 45 min — Empuje",
      "comidas": [
        {{"label": "Desayuno", "texto": "descripción concreta del desayuno"}},
        {{"label": "Almuerzo",  "texto": "descripción concreta del almuerzo"}},
        {{"label": "Colacion",  "texto": "descripción de la colación"}},
        {{"label": "Cena",      "texto": "descripción concreta de la cena"}}
      ]
    }},
    ... 6 días más (Martes, Miércoles, Jueves, Viernes, Sábado, Domingo)
  ]
}}

Tipos válidos para el campo "tipo": GYM, CASA, FIN DE SEMANA, RESETEO
Para MARTES y VIERNES agrega una comida extra con label "Rutina" describiendo el circuito exacto.
El array "dias" debe tener exactamente 7 elementos (Lunes a Domingo)."""

    for intento in range(3):
        try:
            client_ia = genai.Client(api_key=env_vars["GOOGLE_API_KEY"])
            respuesta = client_ia.models.generate_content(
                model="gemini-2.5-pro", contents=prompt
            )
            texto = respuesta.text.strip() if respuesta and respuesta.text else ""
            if not texto:
                logging.warning(f"Intento {intento + 1}: Gemini devolvió respuesta vacía.")
                continue

            # Limpiar posibles bloques markdown que Gemini agrega a veces
            texto = texto.strip()
            if texto.startswith("```"):
                texto = texto.split("\n", 1)[-1]  # quitar primera línea ```json
                texto = texto.rsplit("```", 1)[0]  # quitar cierre ```
                texto = texto.strip()

            plan = json.loads(texto)

            # Validar estructura mínima
            if "diagnostico" not in plan or "dias" not in plan:
                logging.warning(f"Intento {intento + 1}: JSON sin claves requeridas.")
                continue
            if not isinstance(plan["dias"], list) or len(plan["dias"]) < 7:
                logging.warning(f"Intento {intento + 1}: dias tiene {len(plan.get('dias',[]))} elementos, se esperaban 7.")
                continue

            logging.info(f"✅ Plan JSON generado correctamente ({len(plan['dias'])} días).")
            return plan

        except json.JSONDecodeError as e:
            logging.warning(f"Intento {intento + 1}: JSON inválido — {e}")
        except Exception as e:
            logging.warning(f"Intento {intento + 1} fallido: {e}")
        time.sleep(2)

    logging.error("Gemini falló tras 3 intentos — usando plan fallback.")
    return FALLBACK_PLAN


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

_HTML_SANITIZE = [
    ("<br>", "\n"), ("<br/>", "\n"), ("<br />", "\n"),
    ("<ul>", ""), ("</ul>", ""), ("<li>", "• "), ("</li>", "\n"),
    ("<hr>", "---"), ("<hr/>", "---"),
    ("<p>", ""), ("</p>", "\n"),
    ("<strong>", "<b>"), ("</strong>", "</b>"),
    ("<h1>", ""), ("</h1>", "\n"),
    ("<h2>", ""), ("</h2>", "\n"),
    ("<h3>", ""), ("</h3>", "\n"),
]

def enviar_telegram(mensaje: str) -> None:
    if DRY_RUN:
        logging.info(f"[DRY RUN] Telegram:\n{mensaje}")
        return

    for old, new in _HTML_SANITIZE:
        mensaje = mensaje.replace(old, new)

    # Particionado inteligente para mensajes largos (límite Telegram: 4096 chars)
    partes = []
    while mensaje:
        if len(mensaje) <= 3900:
            partes.append(mensaje)
            break
        corte = mensaje.rfind("\n\n", 0, 3900)
        if corte == -1: corte = mensaje.rfind("\n", 0, 3900)
        if corte == -1: corte = 3900
        partes.append(mensaje[:corte])
        mensaje = mensaje[corte:].lstrip()

    url = f"https://api.telegram.org/bot{env_vars['TELEGRAM_BOT_TOKEN']}/sendMessage"
    for i, parte in enumerate(partes, 1):
        suffix = f"\n<i>({i}/{len(partes)})</i>" if len(partes) > 1 else ""
        payload = {
            "chat_id":    env_vars["TELEGRAM_CHAT_ID"],
            "text":       parte + suffix,
            "parse_mode": "HTML",
        }
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            logging.warning(f"Telegram rechazó HTML (parte {i}). Fallback a texto plano...")
            payload.pop("parse_mode")
            res2 = requests.post(url, json=payload, timeout=10)
            if res2.status_code != 200:
                logging.error(f"Error crítico en fallback Telegram parte {i}: {res2.text}")


# ─── JOB PRINCIPAL ────────────────────────────────────────────────────────────

def ejecutar_job():
    logging.info("🚀 Iniciando Job Semanal de Control Metabólico V5.1...")
    inicializar_bd()

    # ── Filtro de día: solo corre los domingos ────────────────────────────────
    # Como el cron es diario, este guardia evita que corra lunes-sábado
    hoy = datetime.now(TZ)
    if hoy.weekday() != 6:  # 6 = domingo
        logging.info(f"Hoy es {hoy.strftime('%A')}. El job de dieta solo corre los domingos. Omitiendo.")
        return

    with sqlite3.connect(DB_PATH) as conn:

        # ── Idempotencia ──────────────────────────────────────────────────────
        if job_ya_ejecutado_hoy(conn):
            logging.warning("Job semanal ya ejecutado hoy. Abortando por idempotencia.")
            return

        # ── Extracción de datos ───────────────────────────────────────────────
        df = obtener_datos_semana(conn)
        if df.empty or len(df) < 2:
            enviar_telegram("⚠️ Necesito al menos 2 pesajes recientes para calcular la dieta.")
            return

        df["Fecha"] = pd.to_datetime(df["Fecha"])
        dato_actual = df.iloc[-1]

        # Dato anterior: el pesaje más cercano a hace 7 días, mínimo 5 días atrás
        # Esto evita comparar contra un pesaje de hace 1 día por error
        fecha_limite = df.iloc[-1]["Fecha"] - timedelta(days=5)
        df_anteriores = df[df["Fecha"] <= fecha_limite].copy()

        if df_anteriores.empty:
            enviar_telegram("⚠️ No hay pesajes con al menos 5 días de antigüedad. Espera más datos.")
            return

        fecha_ref    = dato_actual["Fecha"] - timedelta(days=7)
        df_anteriores["diff"] = (df_anteriores["Fecha"] - fecha_ref).abs()
        dato_anterior = df_anteriores.loc[df_anteriores["diff"].idxmin()]
        dias_entre    = (dato_actual["Fecha"] - dato_anterior["Fecha"]).days

        # ── Variables principales ─────────────────────────────────────────────
        peso_actual      = float(dato_actual["Peso_kg"])
        grasa_actual     = float(dato_actual["Grasa_Porcentaje"])
        musculo_actual   = float(dato_actual["Musculo_Pct"])
        agua_actual      = float(dato_actual["Agua"])
        fat_free_weight  = float(dato_actual["FatFreeWeight"])
        visfat_actual    = float(dato_actual["VisFat"])
        bmi_actual       = float(dato_actual["BMI"]) if dato_actual["BMI"] else None
        edad_metabolica  = int(dato_actual["EdadMetabolica"]) if dato_actual["EdadMetabolica"] else None
        proteina_corp    = float(dato_actual["Proteina"]) if pd.notna(dato_actual["Proteina"]) and dato_actual["Proteina"] else None
        masa_osea        = float(dato_actual["MasaOsea"]) if dato_actual["MasaOsea"] else None
        bmr_actual       = int(dato_actual["BMR"]) if dato_actual.get("BMR") else round(peso_actual * 22)

        delta_peso     = peso_actual    - float(dato_anterior["Peso_kg"])
        delta_grasa    = grasa_actual   - float(dato_anterior["Grasa_Porcentaje"])
        delta_musculo  = musculo_actual - float(dato_anterior["Musculo_Pct"])
        delta_visceral = visfat_actual  - float(dato_anterior["VisFat"])  # Fix: ya no hardcodeado

        # ── Scoring y alertas ─────────────────────────────────────────────────
        score, desc_score = calcular_score_composicion(
            peso_actual, grasa_actual, musculo_actual, agua_actual, visfat_actual
        )
        alertas = generar_alertas(
            peso_actual, grasa_actual, agua_actual,
            visfat_actual, proteina_corp, edad_metabolica
        )

        # ── Control metabólico ────────────────────────────────────────────────
        mult_actual = obtener_multiplicador(conn)

        # Tendencia de peso 28 días (regresión lineal) — input del SISO
        tendencia_kg_semana = calcular_tendencia_peso(df)
        logging.info(f"[TENDENCIA] {tendencia_kg_semana:+.3f} kg/semana (regresión {len(df)} pesajes)")

        # MIMO: diagnóstico multi-variable (shadow — no actúa aún)
        estado_mimo, shadow_mult, razon_mimo = evaluar_mimo(
            delta_peso, delta_grasa, delta_musculo, mult_actual
        )
        emoji_mimo, consejo_mimo = ESTADOS_MIMO.get(estado_mimo, ("⚪", "Sin diagnóstico."))
        logging.info(
            f"[MIMO] estado={estado_mimo} | actual={mult_actual:.1f} | "
            f"sugerido={shadow_mult:.1f} | Δpeso={delta_peso:+.2f} | "
            f"Δgrasa={delta_grasa:+.2f} | Δmúsculo={delta_musculo:+.2f}"
        )

        # SISO: usa tendencia de 28 días en vez de delta puntual
        nuevo_mult, razon_siso, hubo_cambio = aplicar_siso(
            tendencia_kg_semana, mult_actual, bmr_actual, peso_actual
        )
        if hubo_cambio:
            actualizar_multiplicador(conn, nuevo_mult)
            conn.commit()
            logging.info(f"[SISO] Multiplicador actualizado: {mult_actual} → {nuevo_mult}")

        # ── Cálculo de macros ─────────────────────────────────────────────────
        calorias = round(peso_actual * nuevo_mult)
        proteina = round(fat_free_weight * 2.2)
        grasas   = round(peso_actual * 0.7)
        carbs    = max(0, round((calorias - (proteina * 4 + grasas * 9)) / 4))

        # ── Generación del plan ───────────────────────────────────────────────
        plan_ia = generar_dieta_ia(
            peso_actual, grasa_actual, visfat_actual, agua_actual, fat_free_weight,
            calorias, proteina, carbs, grasas, bmr_actual,
            delta_peso, delta_grasa, delta_musculo,
            estado_mimo, razon_mimo,
        )
        diagnostico_texto = plan_ia.get("diagnostico", "")
        dias_plan         = plan_ia.get("dias", [])

        # Serializar para guardar en SQLite (campo heredado dieta_html)
        import json as _json
        dieta_json_str = _json.dumps(plan_ia, ensure_ascii=False)

        # ── Construcción del reporte Telegram (fallback) ──────────────────────
        def delta_str(val, invert=False):
            if abs(val) < 0.05: return f"({val:+.2f}) ⚪"
            if invert: emoji = "🟢" if val < 0 else "🔴"
            else:      emoji = "🟢" if val > 0 else "🔴"
            return f"({val:+.2f}) {emoji}"

        masa_osea_str = f" | Masa Ósea: {masa_osea} kg" if masa_osea else ""

        # Construir texto plano del plan para el fallback de Telegram
        plan_texto = ""
        if dias_plan:
            for dia in dias_plan:
                plan_texto += f"\n<b>{dia.get('nombre','')}</b> — {dia.get('subtitulo','')}\n"
                for c in dia.get("comidas", []):
                    plan_texto += f"  <b>{c.get('label','')}:</b> {c.get('texto','')}\n"
        else:
            plan_texto = diagnostico_texto

        reporte = (
            f"🤖 <b>CONTROL METABÓLICO V5.2 — {datetime.now(TZ).strftime('%d/%m/%Y')}</b>\n"
            f"<i>Comparativa vs hace {dias_entre} días</i>\n"
            f"{'─' * 32}\n\n"
            f"🏆 <b>Score:</b> {score}/100 — {desc_score}\n\n"
            f"📊 <b>Telemetría:</b>\n"
            f"⚖️  Peso:     {peso_actual:.1f} kg  {delta_str(delta_peso, invert=True)}\n"
            f"🥓  Grasa:    {grasa_actual:.1f}%   {delta_str(delta_grasa, invert=True)}{clasificar(grasa_actual, 'grasa_hombre')}\n"
            f"💪  Músculo:  {musculo_actual:.1f}%  {delta_str(delta_musculo)}\n"
            f"🫀  Visceral: {visfat_actual}{clasificar(visfat_actual, 'visceral')}\n"
            f"💧  Agua:     {agua_actual:.1f}%{clasificar(agua_actual, 'agua')}\n"
            f"🧬  Proteína: {proteina_corp}%{clasificar(proteina_corp, 'proteina') if proteina_corp else ''}\n"
            f"📐  BMI:      {bmi_actual}{clasificar(bmi_actual, 'bmi') if bmi_actual else ''}\n"
            f"📅  Ed.Met:   {edad_metabolica} años{masa_osea_str}\n"
            f"🔩  FFM:      {fat_free_weight:.1f} kg\n"
            f"{alertas}\n"
            f"{'─' * 32}\n"
            f"🧠 <b>MIMO:</b> {emoji_mimo} {estado_mimo} — {razon_mimo}\n"
            f"⚙️ <b>SISO:</b> {razon_siso}\n"
            f"Multiplicador: <b>{nuevo_mult} kcal/kg</b>\n\n"
            f"🎯 <b>Macros:</b> {calorias} kcal | P:{proteina}g | C:{carbs}g | G:{grasas}g\n\n"
            f"{'─' * 32}\n"
            f"📋 <b>DIAGNÓSTICO:</b>\n{diagnostico_texto}\n\n"
            f"🥗 <b>PLAN SEMANAL:</b>\n{plan_texto}"
        )

        # ── Persistencia ──────────────────────────────────────────────────────
        conn.execute("""
            INSERT INTO historico_dietas
            (fecha, peso, grasa, delta_peso, kcal_mult, calorias,
             proteina, carbs, grasas, dieta_html, estado_mimo, shadow_mult, score_comp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
            peso_actual, grasa_actual, delta_peso, nuevo_mult,
            calorias, proteina, carbs, grasas,
            dieta_json_str, estado_mimo, shadow_mult, score,
        ))
        conn.commit()
        logging.info("💾 Historial persistido en SQLite.")

    # ── Solo PDF — sin mensaje de texto en Telegram ───────────────────────
    if PDF_DISPONIBLE:
        try:
            fecha_str  = datetime.now(TZ).strftime("%Y-%m-%d")
            carpeta    = "/app/data/reportes"
            os.makedirs(carpeta, exist_ok=True)          # Fix: crea carpeta si no existe
            ruta_pdf   = f"{carpeta}/reporte_{fecha_str}.pdf"

            datos_pdf = {
                "fecha":        datetime.now(TZ).strftime("%d/%m/%Y"),
                "dias_entre":   dias_entre,
                "score":        score,          "desc_score":    desc_score,
                "peso":         peso_actual,    "delta_peso":    delta_peso,
                "grasa":        grasa_actual,   "delta_grasa":   delta_grasa,
                "musculo":      musculo_actual, "delta_musculo": delta_musculo,
                "visceral":     visfat_actual,  "delta_visceral":delta_visceral,  # Fix: calculado
                "agua":         agua_actual,    "delta_agua":    0,
                "proteina":     proteina_corp,
                "masa_osea":    masa_osea,
                "bmr":          bmr_actual,
                "edad_meta":    edad_metabolica,
                "bmi":          bmi_actual,
                "fat_free":     fat_free_weight,
                "alertas":      [a.strip() for a in alertas.split("\n")
                                 if a.strip() and "Alertas" not in a and "🚨" not in a
                                ] if alertas else [],
                "estado_mimo":  estado_mimo,    "emoji_mimo":    emoji_mimo,
                "razon_mimo":   razon_mimo,     "shadow_mult":   shadow_mult,
                "razon_siso":   razon_siso,     "nuevo_mult":    nuevo_mult,
                "calorias":     calorias,       "proteina_g":    proteina,
                "carbs_g":      carbs,          "grasas_g":      grasas,
                "analisis_ia":  diagnostico_texto,
                "dias_plan":    dias_plan,
            }

            ruta_gen = generar_pdf(datos_pdf, ruta_pdf)
            logging.info(f"📄 PDF generado: {ruta_gen}")

            if not DRY_RUN:
                url_doc = f"https://api.telegram.org/bot{env_vars['TELEGRAM_BOT_TOKEN']}/sendDocument"
                with open(ruta_gen, "rb") as f_pdf:
                    res = requests.post(url_doc, data={
                        "chat_id": env_vars["TELEGRAM_CHAT_ID"],
                        "caption": f"📊 Reporte Semanal — {datetime.now(TZ).strftime('%d/%m/%Y')}",
                    }, files={"document": f_pdf}, timeout=30)
                if res.status_code == 200:
                    logging.info("📤 PDF enviado por Telegram correctamente.")
                else:
                    logging.error(f"Error enviando PDF: {res.text}")
        except Exception:
            logging.error("Error generando/enviando PDF semanal.", exc_info=True)
    else:
        # Fallback: si no hay generador de PDF, manda el texto por Telegram
        enviar_telegram(reporte)
        logging.warning("PDF no disponible — fallback a Telegram texto.")

    logging.info("✅ Job semanal ejecutado y notificado exitosamente.")


if __name__ == "__main__":
    ejecutar_job()
