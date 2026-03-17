"""
api.py — FastAPI backend para el dashboard web.
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

DB_PATH    = os.getenv("DB_PATH", "/app/data/mis_datos_renpho.db")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
META_GRASA = 22.0
PESO_INICIO = 120.0

app = FastAPI(title="Control Metabólico", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_conn():
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def tendencia_lineal(pesos, dias):
    if len(pesos) < 3:
        return None
    x = np.array(dias, dtype=float)
    y = np.array(pesos, dtype=float)
    return round(np.polyfit(x, y, 1)[0] * 7, 3)


def calcular_proyeccion(peso_act, grasa_pct, ffm):
    kg_grasa_actual = peso_act * (grasa_pct / 100)
    peso_meta       = ffm / (1 - META_GRASA / 100)
    kg_grasa_meta   = peso_meta * (META_GRASA / 100)
    kg_a_quemar     = max(kg_grasa_actual - kg_grasa_meta, 0)
    ritmo_optimo_kg = round(0.005 * peso_act, 2)
    sem_optimo      = round(kg_a_quemar / ritmo_optimo_kg, 1) if ritmo_optimo_kg > 0 else None
    fecha_optimo    = (date.today() + timedelta(weeks=sem_optimo)).strftime("%b %Y") if sem_optimo else "—"
    return {
        "kg_grasa_actual": round(kg_grasa_actual, 1),
        "kg_grasa_meta":   round(kg_grasa_meta, 1),
        "kg_a_quemar":     round(kg_a_quemar, 1),
        "peso_meta":       round(peso_meta, 1),
        "ritmo_optimo_kg": ritmo_optimo_kg,
        "sem_optimo":      sem_optimo,
        "fecha_optimo":    fecha_optimo,
        "pp_faltan":       round(grasa_pct - META_GRASA, 1),
    }


def semaforo(val, metrica):
    RANGOS = {
        "grasa":    [(0,24,"verde"),(24,28,"amarillo"),(28,100,"rojo")],
        "visceral": [(0,9,"verde"),(9,13,"amarillo"),(13,30,"rojo")],
        "agua":     [(53,100,"verde"),(49,53,"amarillo"),(0,49,"rojo")],
        "proteina": [(16.5,100,"verde"),(15,16.5,"amarillo"),(0,15,"rojo")],
        "bmi":      [(0,25,"verde"),(25,30,"amarillo"),(30,100,"rojo")],
    }
    if val is None or metrica not in RANGOS:
        return "neutro"
    for lo, hi, color in RANGOS[metrica]:
        if lo <= val < hi:
            return color
    return "neutro"


@app.get("/")
def index():
    from fastapi.responses import FileResponse, HTMLResponse
    idx = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return HTMLResponse("<h2>API Control Metabólico</h2><p><a href='/api/dashboard'>GET /api/dashboard</a></p>")


@app.get("/api/dashboard")
def dashboard():
    conn = get_conn()
    try:
        ultimo = conn.execute("""
            SELECT Fecha, Peso_kg, Grasa_Porcentaje, Musculo_Pct, FatFreeWeight,
                   Agua, VisFat, BMI, EdadMetabolica, Proteina, MasaOsea, BMR
            FROM pesajes ORDER BY Fecha DESC LIMIT 1
        """).fetchone()
        if not ultimo:
            raise HTTPException(status_code=404, detail="Sin datos")

        peso     = float(ultimo["Peso_kg"])
        grasa    = float(ultimo["Grasa_Porcentaje"])
        musculo  = float(ultimo["Musculo_Pct"]) if ultimo["Musculo_Pct"] else None
        ffm      = float(ultimo["FatFreeWeight"]) if ultimo["FatFreeWeight"] else peso*(1-grasa/100)
        agua     = float(ultimo["Agua"]) if ultimo["Agua"] else None
        visfat   = float(ultimo["VisFat"]) if ultimo["VisFat"] else None
        bmi      = float(ultimo["BMI"]) if ultimo["BMI"] else None
        proteina = float(ultimo["Proteina"]) if ultimo["Proteina"] else None
        masa_osea= float(ultimo["MasaOsea"]) if ultimo["MasaOsea"] else None
        bmr      = int(ultimo["BMR"]) if ultimo["BMR"] else round(peso*22)
        edad_met = int(ultimo["EdadMetabolica"]) if ultimo["EdadMetabolica"] else None

        hist = conn.execute("""
            SELECT Fecha, Peso_kg FROM pesajes
            WHERE Fecha >= date('now','-28 day') ORDER BY Fecha ASC
        """).fetchall()
        pesos_h = [float(r["Peso_kg"]) for r in hist]
        fechas_h = [r["Fecha"] for r in hist]
        dias_h  = [(datetime.strptime(r["Fecha"],"%Y-%m-%d").date() -
                    datetime.strptime(fechas_h[0],"%Y-%m-%d").date()).days
                   for r in hist] if fechas_h else []
        tendencia = tendencia_lineal(pesos_h, dias_h)

        grafica = conn.execute("""
            SELECT Fecha, Peso_kg, Grasa_Porcentaje FROM pesajes
            WHERE Fecha >= date('now','-90 day') ORDER BY Fecha ASC
        """).fetchall()

        reporte = conn.execute("""
            SELECT fecha, score_comp, estado_mimo, shadow_mult,
                   kcal_mult, calorias, proteina, carbs, grasas, dieta_html
            FROM historico_dietas ORDER BY fecha DESC LIMIT 1
        """).fetchone()

        score       = int(reporte["score_comp"]) if reporte else 0
        estado_mimo = reporte["estado_mimo"] if reporte else "—"
        mult        = float(reporte["kcal_mult"]) if reporte else 25.0
        calorias    = int(reporte["calorias"]) if reporte else round(peso*mult)
        prot_g      = int(reporte["proteina"]) if reporte else round(ffm*2.2)
        carbs_g     = int(reporte["carbs"]) if reporte else 0
        grasas_g    = int(reporte["grasas"]) if reporte else 0

        dias_plan = []
        if reporte and reporte["dieta_html"]:
            try:
                plan = json.loads(reporte["dieta_html"])
                dias_plan = plan.get("dias", [])
            except: pass

        tdee    = round(bmr * 1.45)
        deficit = calorias - tdee
        proy    = calcular_proyeccion(peso, grasa, ffm)

        if tendencia and tendencia < -0.05:
            kg_grasa_sem = abs(tendencia) * 0.7
            sem_actual   = round(proy["kg_a_quemar"] / kg_grasa_sem, 1)
            fecha_actual = (date.today() + timedelta(weeks=sem_actual)).strftime("%b %Y")
        else:
            sem_actual, fecha_actual = None, "calculando..."

        alertas = []
        if visfat and visfat >= 14:
            alertas.append({"tipo":"rojo","texto":f"Grasa visceral elevada ({visfat}) — riesgo metabólico activo"})
        elif visfat and visfat >= 10:
            alertas.append({"tipo":"amarillo","texto":f"Grasa visceral moderada ({visfat}) — monitorear"})
        if agua and agua < 49:
            alertas.append({"tipo":"rojo","texto":f"Hidratación baja ({agua}%) — prioriza agua esta semana"})
        elif agua and agua < 53:
            alertas.append({"tipo":"amarillo","texto":f"Hidratación límite ({agua}%) — aumenta consumo"})
        if proteina and proteina < 15:
            alertas.append({"tipo":"rojo","texto":f"Proteína corporal baja ({proteina}%) — revisa ingesta"})
        elif proteina and proteina < 16.5:
            alertas.append({"tipo":"amarillo","texto":f"Proteína corporal límite ({proteina}%) — mantén ingesta alta"})

        return {
            "sync": ultimo["Fecha"], "fecha_hoy": date.today().strftime("%d/%m/%Y"),
            "telemetria": {
                "peso":peso,"grasa":grasa,"grasa_sem":semaforo(grasa,"grasa"),
                "musculo":musculo,"ffm":round(ffm,1),
                "agua":agua,"agua_sem":semaforo(agua,"agua"),
                "visfat":visfat,"visfat_sem":semaforo(visfat,"visceral"),
                "bmi":bmi,"bmi_sem":semaforo(bmi,"bmi"),
                "proteina":proteina,"prot_sem":semaforo(proteina,"proteina"),
                "masa_osea":masa_osea,"bmr":bmr,"edad_met":edad_met,
            },
            "composicion": {"score":score,"estado_mimo":estado_mimo,"mult":mult,"tendencia_kg_sem":tendencia},
            "energia": {"calorias":calorias,"proteina_g":prot_g,"carbs_g":carbs_g,"grasas_g":grasas_g,"bmr":bmr,"tdee":tdee,"deficit":deficit},
            "proyeccion": {**proy,"tendencia_kg_sem":tendencia,"sem_actual":sem_actual,"fecha_actual":fecha_actual,"meta_grasa":META_GRASA,"peso_inicio":PESO_INICIO},
            "alertas":alertas,"dias_plan":dias_plan,
            "grafica": {
                "labels":[r["Fecha"] for r in grafica],
                "pesos": [float(r["Peso_kg"]) for r in grafica],
                "grasas":[float(r["Grasa_Porcentaje"]) for r in grafica],
            },
        }
    finally:
        conn.close()


@app.get("/api/historial")
def historial(dias: int = 90):
    conn = get_conn()
    try:
        rows = conn.execute(f"""
            SELECT Fecha, Peso_kg, Grasa_Porcentaje, Musculo_Pct, Agua, VisFat
            FROM pesajes WHERE Fecha >= date('now','-{int(dias)} day')
            ORDER BY Fecha ASC
        """).fetchall()
        return {"datos": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/reportes")
def reportes():
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT fecha, score_comp, estado_mimo, calorias, kcal_mult, delta_peso
            FROM historico_dietas ORDER BY fecha DESC LIMIT 20
        """).fetchall()
        return {"reportes": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/pdf/{fecha}")
def descargar_pdf(fecha: str):
    from fastapi.responses import FileResponse
    ruta = f"/app/data/reportes/reporte_{fecha}.pdf"
    if not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail=f"PDF no encontrado para {fecha}")
    return FileResponse(ruta, media_type="application/pdf", filename=f"reporte_{fecha}.pdf")


@app.get("/health")
def health():
    return {"status": "ok", "db": os.path.exists(DB_PATH)}
