"""
api.py — FastAPI backend para el dashboard web.
Corre en paralelo al orquestador (main.py).
Lee de la misma SQLite en /app/data/mis_datos_renpho.db
"""

import os
import json
import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DB_PATH    = os.getenv("DB_PATH", "/app/data/mis_datos_renpho.db")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
META_GRASA = 22.0      # % grasa objetivo
PESO_INICIO = 120.0    # peso de referencia inicial

app = FastAPI(title="Control Metabólico", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Servir archivos estáticos — solo si la carpeta existe
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def get_conn():
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def tendencia_lineal(pesos: list[float], dias: list[int]) -> Optional[float]:
    """Pendiente kg/semana por regresión lineal. None si <3 puntos."""
    if len(pesos) < 3:
        return None
    x = np.array(dias, dtype=float)
    y = np.array(pesos, dtype=float)
    pendiente = np.polyfit(x, y, 1)[0]
    return round(pendiente * 7, 3)


def calcular_proyeccion(peso_act: float, grasa_pct: float, ffm: float):
    """
    Proyecta fecha a 22% de grasa preservando FFM actual.
    Usa 0.5% de grasa por semana como ritmo óptimo.
    """
    kg_grasa_actual = peso_act * (grasa_pct / 100)
    # Peso meta preservando FFM: FFM / (1 - meta/100)
    peso_meta       = ffm / (1 - META_GRASA / 100)
    kg_grasa_meta   = peso_meta * (META_GRASA / 100)
    kg_a_quemar     = max(kg_grasa_actual - kg_grasa_meta, 0)

    # Ritmo óptimo: 0.5% grasa/semana = 0.005 * peso_act kg/semana aprox
    ritmo_optimo_kg = round(0.005 * peso_act, 2)
    sem_optimo      = round(kg_a_quemar / ritmo_optimo_kg, 1) if ritmo_optimo_kg > 0 else None
    fecha_optimo    = (date.today() + timedelta(weeks=sem_optimo)).strftime("%b %Y") if sem_optimo else "—"

    return {
        "kg_grasa_actual":  round(kg_grasa_actual, 1),
        "kg_grasa_meta":    round(kg_grasa_meta, 1),
        "kg_a_quemar":      round(kg_a_quemar, 1),
        "peso_meta":        round(peso_meta, 1),
        "ritmo_optimo_kg":  ritmo_optimo_kg,
        "sem_optimo":       sem_optimo,
        "fecha_optimo":     fecha_optimo,
        "pp_faltan":        round(grasa_pct - META_GRASA, 1),
    }


def semaforo(val, metrica: str) -> str:
    """Retorna 'verde' | 'amarillo' | 'rojo' | 'neutro'."""
    RANGOS = {
        "grasa":    [(0, 24, "verde"), (24, 28, "amarillo"), (28, 100, "rojo")],
        "visceral": [(0, 9,  "verde"), (9,  13, "amarillo"), (13, 30,  "rojo")],
        "agua":     [(53, 100,"verde"),(49, 53, "amarillo"), (0,  49,  "rojo")],
        "proteina": [(16.5,100,"verde"),(15, 16.5,"amarillo"),(0, 15, "rojo")],
        "bmi":      [(0, 25,  "verde"), (25, 30, "amarillo"), (30, 100,"rojo")],
    }
    if val is None or metrica not in RANGOS:
        return "neutro"
    for lo, hi, color in RANGOS[metrica]:
        if lo <= val < hi:
            return color
    return "neutro"


# ─── ENDPOINTS ────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    """Sirve el dashboard o confirma que la API está viva."""
    from fastapi.responses import FileResponse, HTMLResponse
    idx = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return HTMLResponse("<h2>API Control Metabólico</h2><p><a href='/api/dashboard'>GET /api/dashboard</a></p>")


@app.get("/api/dashboard")
def dashboard():
    """
    Endpoint principal — todo lo que necesita el dashboard en una sola llamada.
    """
    conn = get_conn()
    try:
        # ── Último pesaje ────────────────────────────────────────────────────
        ultimo = conn.execute("""
            SELECT Fecha, Peso_kg, Grasa_Porcentaje,
                   Musculo_Pct, FatFreeWeight, Agua, VisFat,
                   BMI, EdadMetabolica, Proteina, MasaOsea, BMR
            FROM pesajes
            ORDER BY Fecha DESC LIMIT 1
        """).fetchone()

        if not ultimo:
            raise HTTPException(status_code=404, detail="Sin datos de pesajes")

        peso    = float(ultimo["Peso_kg"])
        grasa   = float(ultimo["Grasa_Porcentaje"])
        musculo = float(ultimo["Musculo_Pct"]) if ultimo["Musculo_Pct"] else None
        ffm     = float(ultimo["FatFreeWeight"]) if ultimo["FatFreeWeight"] else peso * (1 - grasa/100)
        agua    = float(ultimo["Agua"]) if ultimo["Agua"] else None
        visfat  = float(ultimo["VisFat"]) if ultimo["VisFat"] else None
        bmi     = float(ultimo["BMI"]) if ultimo["BMI"] else None
        proteina= float(ultimo["Proteina"]) if ultimo["Proteina"] else None
        masa_osea=float(ultimo["MasaOsea"]) if ultimo["MasaOsea"] else None
        bmr     = int(ultimo["BMR"]) if ultimo["BMR"] else round(peso * 22)
        edad_met= int(ultimo["EdadMetabolica"]) if ultimo["EdadMetabolica"] else None

        # ── Historial 28d para tendencia ─────────────────────────────────────
        hist = conn.execute("""
            SELECT Fecha, Peso_kg, Grasa_Porcentaje
            FROM pesajes
            WHERE Fecha >= date('now', '-28 day')
            ORDER BY Fecha ASC
        """).fetchall()

        pesos_hist = [float(r["Peso_kg"]) for r in hist]
        fechas_hist = [r["Fecha"] for r in hist]
        dias_hist   = [(datetime.strptime(r["Fecha"], "%Y-%m-%d").date() -
                        datetime.strptime(fechas_hist[0], "%Y-%m-%d").date()).days
                       for r in hist] if fechas_hist else []
        tendencia   = tendencia_lineal(pesos_hist, dias_hist)

        # ── Historial 90d para gráfica ────────────────────────────────────────
        grafica = conn.execute("""
            SELECT Fecha, Peso_kg, Grasa_Porcentaje
            FROM pesajes
            WHERE Fecha >= date('now', '-90 day')
            ORDER BY Fecha ASC
        """).fetchall()

        # ── Último reporte semanal ────────────────────────────────────────────
        reporte = conn.execute("""
            SELECT fecha, score_comp, estado_mimo, shadow_mult,
                   kcal_mult, calorias, proteina, carbs, grasas,
                   dieta_html
            FROM historico_dietas
            ORDER BY fecha DESC LIMIT 1
        """).fetchone()

        score      = int(reporte["score_comp"]) if reporte else 0
        estado_mimo= reporte["estado_mimo"] if reporte else "—"
        mult       = float(reporte["kcal_mult"]) if reporte else 25.0
        calorias   = int(reporte["calorias"]) if reporte else round(peso * mult)
        prot_g     = int(reporte["proteina"]) if reporte else round(ffm * 2.2)
        carbs_g    = int(reporte["carbs"]) if reporte else 0
        grasas_g   = int(reporte["grasas"]) if reporte else 0

        # Plan semanal — parsear JSON si está disponible
        dias_plan = []
        if reporte and reporte["dieta_html"]:
            try:
                plan = json.loads(reporte["dieta_html"])
                dias_plan = plan.get("dias", [])
            except (json.JSONDecodeError, TypeError):
                pass

        # ── Cálculos energía ─────────────────────────────────────────────────
        tdee    = round(bmr * 1.45)
        deficit = calorias - tdee

        # ── Proyección ───────────────────────────────────────────────────────
        proy = calcular_proyeccion(peso, grasa, ffm)

        # ETA a ritmo actual
        if tendencia and tendencia < -0.05:
            # ~70% de pérdida de peso = grasa
            kg_grasa_sem = abs(tendencia) * 0.7
            sem_actual   = round(proy["kg_a_quemar"] / kg_grasa_sem, 1)
            fecha_actual = (date.today() + timedelta(weeks=sem_actual)).strftime("%b %Y")
        else:
            sem_actual   = None
            fecha_actual = "calculando..."

        # ── Alertas ──────────────────────────────────────────────────────────
        alertas = []
        if visfat and visfat >= 14:
            alertas.append({"tipo": "rojo", "texto": f"Grasa visceral elevada ({visfat}) — riesgo metabólico activo"})
        elif visfat and visfat >= 10:
            alertas.append({"tipo": "amarillo", "texto": f"Grasa visceral moderada ({visfat}) — monitorear"})
        if agua and agua < 49:
            alertas.append({"tipo": "rojo", "texto": f"Hidratación baja ({agua}%) — prioriza agua esta semana"})
        elif agua and agua < 53:
            alertas.append({"tipo": "amarillo", "texto": f"Hidratación límite ({agua}%) — aumenta consumo de agua"})
        if proteina and proteina < 15:
            alertas.append({"tipo": "rojo", "texto": f"Proteína corporal baja ({proteina}%) — revisa ingesta proteica"})
        elif proteina and proteina < 16.5:
            alertas.append({"tipo": "amarillo", "texto": f"Proteína corporal límite ({proteina}%) — mantén ingesta alta"})

        # ── Último sync ──────────────────────────────────────────────────────
        ultimo_sync = ultimo["Fecha"]

        return {
            "sync":     ultimo_sync,
            "fecha_hoy": date.today().strftime("%d/%m/%Y"),

            "telemetria": {
                "peso":      peso,
                "grasa":     grasa,
                "grasa_sem": semaforo(grasa, "grasa"),
                "musculo":   musculo,
                "ffm":       round(ffm, 1),
                "agua":      agua,
                "agua_sem":  semaforo(agua, "agua"),
                "visfat":    visfat,
                "visfat_sem":semaforo(visfat, "visceral"),
                "bmi":       bmi,
                "bmi_sem":   semaforo(bmi, "bmi"),
                "proteina":  proteina,
                "prot_sem":  semaforo(proteina, "proteina"),
                "masa_osea": masa_osea,
                "bmr":       bmr,
                "edad_met":  edad_met,
            },

            "composicion": {
                "score":       score,
                "estado_mimo": estado_mimo,
                "mult":        mult,
                "tendencia_kg_sem": tendencia,
            },

            "energia": {
                "calorias": calorias,
                "proteina_g": prot_g,
                "carbs_g":    carbs_g,
                "grasas_g":   grasas_g,
                "bmr":        bmr,
                "tdee":       tdee,
                "deficit":    deficit,
            },

            "proyeccion": {
                **proy,
                "tendencia_kg_sem": tendencia,
                "sem_actual":  sem_actual,
                "fecha_actual":fecha_actual,
                "meta_grasa":  META_GRASA,
                "peso_inicio": PESO_INICIO,
            },

            "alertas": alertas,
            "dias_plan": dias_plan,

            "grafica": {
                "labels": [r["Fecha"] for r in grafica],
                "pesos":  [float(r["Peso_kg"]) for r in grafica],
                "grasas": [float(r["Grasa_Porcentaje"]) for r in grafica],
            },
        }

    finally:
        conn.close()


@app.get("/api/historial")
def historial(dias: int = 90):
    """Historial de pesajes para la sección Progreso."""
    conn = get_conn()
    try:
        rows = conn.execute(f"""
            SELECT Fecha, Peso_kg, Grasa_Porcentaje,
                   Musculo_Pct, Agua, VisFat
            FROM pesajes
            WHERE Fecha >= date('now', '-{int(dias)} day')
            ORDER BY Fecha ASC
        """).fetchall()
        return {"datos": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/reportes")
def reportes():
    """Lista de reportes semanales para historial."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT fecha, score_comp, estado_mimo,
                   calorias, kcal_mult, delta_peso
            FROM historico_dietas
            ORDER BY fecha DESC
            LIMIT 20
        """).fetchall()
        return {"reportes": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/health")
def health():
    return {"status": "ok", "db": os.path.exists(DB_PATH)}
