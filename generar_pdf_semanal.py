"""
generar_pdf_semanal.py — V2.0
PDF semanal de Control Metabólico con diseño profesional oscuro.
"""

import os
import re
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.pdfgen import canvas as pdfcanvas

C_NEGRO    = colors.HexColor("#0d1117")
C_CARBON   = colors.HexColor("#161b22")
C_GRAFITO  = colors.HexColor("#21262d")
C_BORDE    = colors.HexColor("#30363d")
C_TEXTO    = colors.HexColor("#e6edf3")
C_TEXTO2   = colors.HexColor("#8b949e")
C_ACENTO   = colors.HexColor("#58a6ff")
C_VERDE    = colors.HexColor("#3fb950")
C_ROJO     = colors.HexColor("#f85149")
C_AMARILLO = colors.HexColor("#d29922")
C_NARANJA  = colors.HexColor("#db6d28")
C_MORADO   = colors.HexColor("#bc8cff")

PW, PH = A4

def E(name, **kw):
    d = dict(fontName="Helvetica", fontSize=10, textColor=C_TEXTO, leading=14)
    d.update(kw)
    return ParagraphStyle(name, **d)

S = {
    "titulo":    E("t",  fontName="Helvetica-Bold", fontSize=24, textColor=C_TEXTO,  leading=28),
    "sub":       E("s",  fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2, leading=13),
    "sec":       E("se", fontName="Helvetica-Bold", fontSize=7,  textColor=C_ACENTO, leading=10, spaceAfter=3),
    "mlab":      E("ml", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2),
    "mval":      E("mv", fontName="Helvetica-Bold", fontSize=11, textColor=C_TEXTO),
    "mdel":      E("md", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2, alignment=TA_RIGHT),
    "alerta":    E("al", fontName="Helvetica",      fontSize=9,  textColor=C_ROJO,   leading=14),
    "cuerpo":    E("cu", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2, leading=14),
    "dia_nom":   E("dn", fontName="Helvetica-Bold", fontSize=10, textColor=C_TEXTO),
    "dia_sub":   E("ds", fontName="Helvetica",      fontSize=8,  textColor=C_TEXTO2, alignment=TA_RIGHT),
    "clab":      E("cl", fontName="Helvetica-Bold", fontSize=8,  textColor=C_ACENTO),
    "ctxt":      E("ct", fontName="Helvetica",      fontSize=8,  textColor=C_TEXTO2, leading=12),
    "score_n":   E("sn", fontName="Helvetica-Bold", fontSize=44, textColor=C_ACENTO, alignment=TA_CENTER, leading=48),
    "score_d":   E("sd", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2, alignment=TA_CENTER),
    "macro_n":   E("mn", fontName="Helvetica-Bold", fontSize=18, textColor=C_TEXTO,  alignment=TA_CENTER, leading=22),
    "macro_l":   E("mml",fontName="Helvetica",      fontSize=7,  textColor=C_TEXTO2, alignment=TA_CENTER),
    "mimo_e":    E("me", fontName="Helvetica-Bold", fontSize=11, textColor=C_TEXTO),
    "mimo_r":    E("mr", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2, leading=13),
}

class ReporteCanvas(pdfcanvas.Canvas):
    def __init__(self, *args, fecha="", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []
        self._fecha = fecha

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for i, state in enumerate(self._saved, 1):
            self.__dict__.update(state)
            self._decorate(i, n)
            super().showPage()
        super().save()

    def _decorate(self, num, total):
        self.setFillColor(C_NEGRO)
        self.rect(0, 0, PW, PH, fill=1, stroke=0)
        self.setStrokeColor(C_ACENTO)
        self.setLineWidth(2.5)
        self.line(0, PH-1.5*mm, PW, PH-1.5*mm)
        self.setFillColor(C_CARBON)
        self.rect(0, 0, PW, 9*mm, fill=1, stroke=0)
        self.setStrokeColor(C_BORDE)
        self.setLineWidth(0.5)
        self.line(0, 9*mm, PW, 9*mm)
        self.setFillColor(C_TEXTO2)
        self.setFont("Helvetica", 7)
        self.drawCentredString(PW/2, 2.8*mm,
            f"CONTROL METABÓLICO AUTÓNOMO  ·  {self._fecha}  ·  {num}/{total}")

def hr(c=C_BORDE, g=0.5):
    return HRFlowable(width="100%", thickness=g, color=c, spaceBefore=3, spaceAfter=3)

def sem_col(v, m):
    R = {
        "grasa":    [(20,27,C_VERDE),(27,32,C_AMARILLO),(32,100,C_ROJO)],
        "visceral": [(1,9,C_VERDE),(10,13,C_AMARILLO),(14,30,C_ROJO)],
        "agua":     [(53,65,C_VERDE),(49,53,C_AMARILLO),(0,49,C_ROJO)],
        "bmi":      [(18.5,27,C_VERDE),(27,32,C_AMARILLO),(32,99,C_ROJO)],
        "proteina": [(16.5,20,C_VERDE),(15,16.5,C_AMARILLO),(0,15,C_ROJO)],
    }
    if v is None or m not in R: return C_TEXTO2
    for lo,hi,col in R[m]:
        if lo<=v<=hi: return col
    return C_TEXTO2

def fmt_d(v, inv=False, u=""):
    if v is None or abs(v)<0.05: return "—"
    c = (C_VERDE if v<0 else C_ROJO) if inv else (C_VERDE if v>0 else C_ROJO)
    f = "▼" if v<0 else "▲"
    s = "+" if v>0 else ""
    return f'<font color="#{c.hexval()[2:]}">{f} {s}{v:.2f}{u}</font>'

def pagina_1(d, story):
    fecha = d.get("fecha","")
    dias  = d.get("dias_entre",7)

    # HEADER
    t_h = Table([[
        Paragraph("CONTROL METABÓLICO", S["titulo"]),
        Table([[Paragraph(fecha, S["sub"])],[Paragraph(f"Comparativa vs {dias} días atrás", S["sub"])]],
              colWidths=[55*mm]),
    ]], colWidths=[110*mm, 60*mm])
    t_h.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"BOTTOM"),
        ("ALIGN",(1,0),(1,-1),"RIGHT"),
        ("TOPPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    story.append(t_h)
    story.append(Spacer(1,4*mm))
    story.append(hr(C_ACENTO,1.5))
    story.append(Spacer(1,4*mm))

    # SCORE + MACROS
    sc   = d.get("score",0)
    desc = d.get("desc_score","")
    kcal = d.get("calorias",0)
    pg   = d.get("proteina_g",0)
    cg   = d.get("carbs_g",0)
    gg   = d.get("grasas_g",0)

    col_s = C_VERDE if sc>=75 else C_AMARILLO if sc>=50 else C_NARANJA if sc>=25 else C_ROJO
    hx_s  = col_s.hexval()[2:]

    blk_score = Table([
        [Paragraph("SCORE", S["sec"])],
        [Paragraph(f'<font color="#{hx_s}">{sc}</font><font size=14 color="#8b949e">/100</font>', S["score_n"])],
        [Paragraph(desc, S["score_d"])],
    ], colWidths=[52*mm])
    blk_score.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),C_GRAFITO),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("BOX",(0,0),(-1,-1),1,C_BORDE),
    ]))

    def bm(num,u,lab,col):
        hx = col.hexval()[2:]
        return Table([
            [Paragraph(f'<font color="#{hx}"><b>{num}</b></font><font size=8 color="#8b949e"> {u}</font>',S["macro_n"])],
            [Paragraph(lab,S["macro_l"])],
        ], colWidths=[28*mm])

    t_mac = Table([[bm(kcal,"kcal","CALORÍAS",C_ACENTO),
                    bm(pg,"g","PROTEÍNA",C_VERDE),
                    bm(cg,"g","CARBOS",C_AMARILLO),
                    bm(gg,"g","GRASAS",C_NARANJA)]],
                  colWidths=[28*mm]*4)
    t_mac.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),C_GRAFITO),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LINEBEFORE",(1,0),(-1,-1),0.5,C_BORDE),
        ("BOX",(0,0),(-1,-1),1,C_BORDE),("ALIGN",(0,0),(-1,-1),"CENTER"),
    ]))

    t_top = Table([[blk_score, t_mac]], colWidths=[54*mm,118*mm])
    t_top.setStyle(TableStyle([
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
        ("INNERGRID",(0,0),(-1,-1),4,C_NEGRO),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(t_top)
    story.append(Spacer(1,5*mm))

    # TELEMETRÍA
    story.append(Paragraph("TELEMETRÍA CORPORAL", S["sec"]))
    def fila(emo,lab,val,u,dv,inv=False,m=None):
        col = sem_col(val,m) if m else C_TEXTO
        vs  = f"{val} {u}".strip() if val is not None else "—"
        return [
            Paragraph(f"{emo}  {lab}", S["mlab"]),
            Paragraph(f'<font color="#{col.hexval()[2:]}"><b>{vs}</b></font>',S["mval"]),
            Paragraph(fmt_d(dv,inv),S["mdel"]),
        ]

    rows = [
        [Paragraph("MÉTRICA",S["sec"]),Paragraph("VALOR",S["sec"]),Paragraph("VARIACIÓN",S["sec"])],
        fila("⚖","Peso",           d.get("peso"),    "kg", d.get("delta_peso"),    inv=True),
        fila("💪","Músculo Esquel.",d.get("musculo"), "%",  d.get("delta_musculo")),
        fila("🥓","Grasa Corporal", d.get("grasa"),   "%",  d.get("delta_grasa"),   inv=True, m="grasa"),
        fila("🫀","Grasa Visceral", d.get("visceral"),"",   d.get("delta_visceral"),inv=True, m="visceral"),
        fila("💧","Agua Corporal",  d.get("agua"),    "%",  d.get("delta_agua"),             m="agua"),
        fila("🧬","Proteína Corp.", d.get("proteina"),"%",  None,                            m="proteina"),
        fila("🦴","Masa Ósea",      d.get("masa_osea"),"kg",None),
        fila("⚡","BMR",            d.get("bmr"),    "kcal",None),
        fila("📅","Edad Metabólica",d.get("edad_meta"),"años",None),
        fila("📐","BMI",            d.get("bmi"),    "",    None,                            m="bmi"),
        fila("🔩","Masa Libre Grasa",d.get("fat_free"),"kg",None),
    ]
    t_tel = Table(rows, colWidths=[62*mm, 62*mm, 48*mm])
    t_tel.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C_CARBON),("TEXTCOLOR",(0,0),(-1,0),C_ACENTO),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[C_GRAFITO,C_CARBON]),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(0,-1),10),("RIGHTPADDING",(0,0),(-1,-1),8),
        ("ALIGN",(2,0),(2,-1),"RIGHT"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LINEBELOW",(0,0),(-1,-2),0.3,C_BORDE),
        ("BOX",(0,0),(-1,-1),1,C_BORDE),
    ]))
    story.append(t_tel)
    story.append(Spacer(1,5*mm))

    # ALERTAS
    alertas = d.get("alertas",[])
    if alertas:
        story.append(Paragraph("ALERTAS CLÍNICAS", S["sec"]))
        t_a = Table([[Paragraph(f"  {a}",S["alerta"])] for a in alertas], colWidths=[172*mm])
        t_a.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#180a0a")),
            ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",(0,0),(-1,-1),10),
            ("BOX",(0,0),(-1,-1),1,C_ROJO),
            ("LINEBELOW",(0,0),(-1,-2),0.3,colors.HexColor("#3a1010")),
        ]))
        story.append(t_a)
        story.append(Spacer(1,5*mm))

    # CONTROL METABÓLICO
    story.append(Paragraph("CONTROL METABÓLICO AUTÓNOMO", S["sec"]))
    em   = d.get("estado_mimo","—")
    rm   = d.get("razon_mimo","")
    rs   = d.get("razon_siso","")
    nm   = d.get("nuevo_mult","—")
    sm   = d.get("shadow_mult","—")
    MC   = {"CATABOLISMO":C_ROJO,"RECOMPOSICION":C_MORADO,"CUTTING_LIMPIO":C_VERDE,
            "ESTANCAMIENTO":C_AMARILLO,"ZONA_GRIS":C_TEXTO2}
    cm   = MC.get(em,C_TEXTO2)
    hcm  = cm.hexval()[2:]

    t_m = Table([[
        Table([[Paragraph("MIMO — DIAGNÓSTICO",S["sec"])],
               [Paragraph(f'<font color="#{hcm}"><b>{em}</b></font>',S["mimo_e"])],
               [Paragraph(rm,S["mimo_r"])],
               [Paragraph(f'Sugerido: <font color="#{hcm}"><b>{sm} kcal/kg</b></font>',S["mimo_r"])]],
              colWidths=[83*mm]),
        Table([[Paragraph("SISO — ACTIVO",S["sec"])],
               [Paragraph(f'<b>{nm} kcal/kg</b>',S["mimo_e"])],
               [Paragraph(rs,S["mimo_r"])]],
              colWidths=[83*mm]),
    ]], colWidths=[85*mm,85*mm])
    t_m.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,-1),C_GRAFITO),("BACKGROUND",(1,0),(1,-1),C_CARBON),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",(0,0),(-1,-1),10),
        ("BOX",(0,0),(-1,-1),1,C_BORDE),("LINEBEFORE",(1,0),(1,-1),1,C_BORDE),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    story.append(t_m)


def pagina_2(d, story):
    story.append(PageBreak())
    story.append(Paragraph("PLAN SEMANAL — NUTRICIÓN Y ENTRENAMIENTO", S["sec"]))
    story.append(hr(C_ACENTO,1.5))
    story.append(Spacer(1,4*mm))

    an = d.get("analisis_ia","")
    if an:
        an_clean = re.sub(r"<[^>]+>","",an)
        story.append(Paragraph("DIAGNÓSTICO DE LA SEMANA", S["sec"]))
        t_an = Table([[Paragraph(an_clean,S["cuerpo"])]], colWidths=[172*mm])
        t_an.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),C_GRAFITO),
            ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
            ("LEFTPADDING",(0,0),(-1,-1),12),("RIGHTPADDING",(0,0),(-1,-1),12),
            ("BOX",(0,0),(-1,-1),1,C_BORDE),
        ]))
        story.append(t_an)
        story.append(Spacer(1,5*mm))

    dias = d.get("dias_plan",[])
    if not dias:
        story.append(Paragraph("Plan nutricional completo enviado por Telegram.",S["cuerpo"]))
        return

    TC = {"GYM":C_ACENTO,"CASA":C_VERDE,"FIN DE SEMANA":C_NARANJA,"RESETEO":C_TEXTO2}
    for dia in dias:
        col = TC.get(dia.get("tipo","GYM"),C_ACENTO)
        hx  = col.hexval()[2:]
        t_hd = Table([[
            Paragraph(f'<font color="#{hx}"><b>{dia["nombre"]}</b></font>',S["dia_nom"]),
            Paragraph(dia.get("subtitulo",""),S["dia_sub"]),
        ]], colWidths=[100*mm,72*mm])
        t_hd.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),C_CARBON),
            ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
            ("LEFTPADDING",(0,0),(0,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),
            ("LINEBELOW",(0,0),(-1,-1),2,col),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ]))
        rows_c = [[Paragraph(c["label"],S["clab"]),Paragraph(c["texto"],S["ctxt"])]
                  for c in dia.get("comidas",[])]
        t_c = Table(rows_c, colWidths=[26*mm,146*mm])
        t_c.setStyle(TableStyle([
            ("ROWBACKGROUNDS",(0,0),(-1,-1),[C_GRAFITO,C_CARBON]),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("LEFTPADDING",(0,0),(0,-1),10),("RIGHTPADDING",(0,0),(-1,-1),8),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LINEBELOW",(0,0),(-1,-2),0.3,C_BORDE),
        ]))
        story.append(KeepTogether([t_hd,t_c,Spacer(1,4*mm)]))


def generar_pdf(datos: dict, ruta_salida: str) -> str:
    os.makedirs(os.path.dirname(ruta_salida) if os.path.dirname(ruta_salida) else ".", exist_ok=True)
    fecha = datos.get("fecha", datetime.now().strftime("%d/%m/%Y"))

    marco = Frame(12*mm, 12*mm, PW-24*mm, PH-22*mm,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc = BaseDocTemplate(
        ruta_salida, pagesize=A4,
        rightMargin=12*mm, leftMargin=12*mm, topMargin=12*mm, bottomMargin=14*mm,
        title=f"Control Metabólico — {fecha}", author="Sistema Autónomo",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[marco])])

    story = []
    pagina_1(datos, story)
    pagina_2(datos, story)

    class CanvasFactory:
        def __init__(self, filename, pagesize=A4, **kwargs):
            self._c = ReporteCanvas(filename, pagesize=pagesize, fecha=fecha, **kwargs)
        def __call__(self, filename, pagesize=A4, **kwargs):
            return ReporteCanvas(filename, pagesize=pagesize, fecha=fecha, **kwargs)

    doc.build(story, canvasmaker=lambda fn, **kw: ReporteCanvas(fn, fecha=fecha, **kw))
    return ruta_salida


if __name__ == "__main__":
    datos_test = {
        "fecha":"01/03/2026","dias_entre":7,
        "score":31,"desc_score":"Construyendo base",
        "peso":112.5,"delta_peso":0.20,
        "grasa":32.6,"delta_grasa":0.10,
        "musculo":43.5,"delta_musculo":-0.10,
        "visceral":14.0,"delta_visceral":0.0,
        "agua":48.6,"delta_agua":0.10,
        "proteina":15.4,"masa_osea":3.79,
        "bmr":2007,"edad_meta":37,"bmi":32.2,"fat_free":75.8,
        "alertas":[
            "Grasa visceral elevada (14.0) — riesgo metabólico activo",
            "Hidratacion baja (48.6%) — prioriza agua esta semana",
            "Proteina corporal baja (15.4%) — revisa ingesta proteica",
        ],
        "estado_mimo":"ESTANCAMIENTO","emoji_mimo":"",
        "razon_mimo":"Sin mejora en composicion. Adaptacion metabolica detectada.",
        "shadow_mult":20.5,"razon_siso":"Estancamiento. Piso BMR aplicado (2308 kcal minimo).",
        "nuevo_mult":20.5,"calorias":2306,"proteina_g":167,"carbs_g":197,"grasas_g":79,
        "analisis_ia":(
            "Diagnostico claro: estancamiento metabolico. La variacion de peso (+0.20 kg) "
            "con delta de grasa minimo indica retencion hidrica mas que acumulacion real. "
            "La grasa visceral en 14 es el marcador mas urgente. Mision esta semana: ciclar "
            "energia por tipo de dia, maximizar hidratacion (3.8L/dia basado en FFM 75.8 kg), "
            "mantener senal anabolica en los 3 dias de gym para proteger los 72 kg de musculo "
            "mientras atacamos grasa visceral con deficit controlado de 2,306 kcal — siempre "
            "sobre el BMR de 2,007 kcal."
        ),
        "dias_plan":[
            {"nombre":"LUNES — Dia de Ataque 1","tipo":"GYM",
             "subtitulo":"Oficina + Gym 45 min — Empuje",
             "comidas":[
                {"label":"Desayuno","texto":"Batido proteina (auto): 40g whey, platano, crema almendras, 300ml agua. Preparar noche anterior."},
                {"label":"Almuerzo","texto":"200g pechuga plancha, 150g quinoa, hojas verdes, pepino, tomate, 1/4 aguacate."},
                {"label":"Colacion","texto":"1 manzana roja + 2 cdas mantequilla mani natural."},
                {"label":"Cena","texto":"Chili de pavo: 220g carne 93/7, frijoles negros, pimientos. Guarda mitad para lonche martes."},
             ]},
            {"nombre":"MARTES — Dia Metabolico 1","tipo":"CASA",
             "subtitulo":"Home office + circuito 30 min",
             "comidas":[
                {"label":"Desayuno","texto":"Avena overnight: 50g avena, 30g proteina vainilla, chia, 150ml leche almendras."},
                {"label":"Almuerzo","texto":"Sobra cena lunes (Chili de pavo)."},
                {"label":"Colacion","texto":"1 taza fresas + 150g yogurt griego 0%."},
                {"label":"Cena","texto":"Salmon 200g al horno con limon, esparragos y 150g camote."},
                {"label":"Rutina","texto":"4 rondas 45s/15s: Sentadillas tempo 3-1-1, Flexiones inclinadas, Puente gluteos, Plancha toques hombro."},
             ]},
            {"nombre":"MIERCOLES — Dia de Ataque 2","tipo":"GYM",
             "subtitulo":"Oficina + Gym 45 min — Tiron",
             "comidas":[
                {"label":"Desayuno","texto":"Batido proteina (mismo lunes)."},
                {"label":"Almuerzo","texto":"Sobra cena martes (salmon con esparragos)."},
                {"label":"Colacion","texto":"1 naranja + 20 almendras."},
                {"label":"Cena","texto":"Ternera y brocoli: 200g filete, soja baja sodio, jengibre. Arroz integral. Guarda mitad."},
             ]},
            {"nombre":"JUEVES — Dia de Ataque 3","tipo":"GYM",
             "subtitulo":"Oficina + Gym 45 min — Pierna",
             "comidas":[
                {"label":"Desayuno","texto":"Avena overnight (mismo martes)."},
                {"label":"Almuerzo","texto":"Sobra cena miercoles (ternera y brocoli)."},
                {"label":"Colacion","texto":"1 pera + rollitos jamon pavo con queso panela."},
                {"label":"Cena","texto":"Pechuga rellena: 220g mariposa, espinacas, queso cottage, horneada. Ensalada lentejas. Guarda mitad."},
             ]},
            {"nombre":"VIERNES — Dia Metabolico 2","tipo":"CASA",
             "subtitulo":"Home office + circuito 30 min",
             "comidas":[
                {"label":"Desayuno","texto":"Batido proteina (mismo lunes/miercoles)."},
                {"label":"Almuerzo","texto":"Sobra cena jueves (pollo relleno y ensalada)."},
                {"label":"Colacion","texto":"1 taza melon picado."},
                {"label":"Cena","texto":"Tacos de pescado: 200g tilapia plancha, 3 tortillas maiz, col morada, salsa yogurt limon."},
                {"label":"Rutina","texto":"4 rondas 45s/15s: mismo circuito del martes."},
             ]},
            {"nombre":"SABADO — Recuperacion Activa","tipo":"FIN DE SEMANA",
             "subtitulo":"Familia + actividad ligera",
             "comidas":[
                {"label":"Desayuno","texto":"4 claras con espinacas y champinones, 1 rebanada pan integral."},
                {"label":"Almuerzo","texto":"Sopa de lentejas casera con vegetales."},
                {"label":"Colacion","texto":"1 kiwi (omitir si hay cena social)."},
                {"label":"Cena Social","texto":"Prioriza proteina, doble vegetales en vez de papas, 1 agua por bebida alcoholica (max 2 copas)."},
                {"label":"Actividad","texto":"45-60 min caminata o bici con la familia."},
             ]},
            {"nombre":"DOMINGO — Reseteo y Preparacion","tipo":"RESETEO",
             "subtitulo":"Dia limpio para empezar fuerte",
             "comidas":[
                {"label":"Desayuno","texto":"200g yogurt griego con frutos rojos y nueces."},
                {"label":"Almuerzo","texto":"2 latas atun en agua, garbanzos, apio, aderezo ligero."},
                {"label":"Colacion","texto":"1 durazno."},
                {"label":"Cena","texto":"220g pechuga plancha + brocoli, coliflor y zanahoria al vapor. Simple y limpio."},
             ]},
        ],
    }
    ruta = generar_pdf(datos_test, "/mnt/user-data/outputs/reporte_semanal.pdf")
    print(f"PDF: {ruta}")
