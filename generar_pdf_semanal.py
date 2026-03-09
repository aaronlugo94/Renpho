"""
generar_pdf_semanal.py — V3.0
Diseño claro profesional — compatible con todos los visores de PDF.
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

# ─── PALETA CLARA ─────────────────────────────────────────────────────────────
C_BLANCO     = colors.white
C_FONDO      = colors.HexColor("#f8fafc")   # gris muy claro para fondos alternos
C_FONDO2     = colors.HexColor("#f1f5f9")   # gris claro para filas pares
C_BORDE      = colors.HexColor("#e2e8f0")   # borde sutil
C_TEXTO      = colors.HexColor("#0f172a")   # negro azulado — texto principal
C_TEXTO2     = colors.HexColor("#475569")   # gris medio — texto secundario
C_ACENTO     = colors.HexColor("#1d4ed8")   # azul profundo — acento principal
C_ACENTO_BG  = colors.HexColor("#eff6ff")   # azul muy claro — fondos acento
C_VERDE      = colors.HexColor("#15803d")   # verde oscuro
C_VERDE_BG   = colors.HexColor("#f0fdf4")   # verde muy claro
C_ROJO       = colors.HexColor("#dc2626")   # rojo
C_ROJO_BG    = colors.HexColor("#fef2f2")   # rojo muy claro
C_AMARILLO   = colors.HexColor("#b45309")   # ámbar oscuro (legible)
C_AMARILLO_BG= colors.HexColor("#fffbeb")   # ámbar muy claro
C_NARANJA    = colors.HexColor("#c2410c")   # naranja oscuro
C_MORADO     = colors.HexColor("#6d28d9")   # morado

PW, PH = A4

# ─── ESTILOS ──────────────────────────────────────────────────────────────────
def E(name, **kw):
    d = dict(fontName="Helvetica", fontSize=10, textColor=C_TEXTO, leading=14)
    d.update(kw)
    return ParagraphStyle(name, **d)

S = {
    "titulo":   E("t",  fontName="Helvetica-Bold", fontSize=22, textColor=C_BLANCO,    leading=26),
    "sub":      E("s",  fontName="Helvetica",      fontSize=9,  textColor=colors.HexColor("#bfdbfe"), leading=13),
    "sec":      E("se", fontName="Helvetica-Bold", fontSize=7,  textColor=C_ACENTO,    leading=10, spaceAfter=3),
    "mlab":     E("ml", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2),
    "mval":     E("mv", fontName="Helvetica-Bold", fontSize=11, textColor=C_TEXTO),
    "mdel":     E("md", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2,    alignment=TA_RIGHT),
    "alerta":   E("al", fontName="Helvetica",      fontSize=9,  textColor=C_ROJO,      leading=14),
    "cuerpo":   E("cu", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2,    leading=14),
    "dia_nom":  E("dn", fontName="Helvetica-Bold", fontSize=10, textColor=C_BLANCO),
    "dia_sub":  E("ds", fontName="Helvetica",      fontSize=8,  textColor=colors.HexColor("#bfdbfe"), alignment=TA_RIGHT),
    "clab":     E("cl", fontName="Helvetica-Bold", fontSize=8,  textColor=C_ACENTO),
    "ctxt":     E("ct", fontName="Helvetica",      fontSize=8,  textColor=C_TEXTO2,    leading=12),
    "score_n":  E("sn", fontName="Helvetica-Bold", fontSize=44, textColor=C_ACENTO,    alignment=TA_CENTER, leading=48),
    "score_d":  E("sd", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2,    alignment=TA_CENTER),
    "macro_n":  E("mn", fontName="Helvetica-Bold", fontSize=18, textColor=C_TEXTO,     alignment=TA_CENTER, leading=22),
    "macro_l":  E("mml",fontName="Helvetica",      fontSize=7,  textColor=C_TEXTO2,    alignment=TA_CENTER),
    "mimo_e":   E("me", fontName="Helvetica-Bold", fontSize=11, textColor=C_TEXTO),
    "mimo_r":   E("mr", fontName="Helvetica",      fontSize=9,  textColor=C_TEXTO2,    leading=13),
}

# ─── CANVAS ───────────────────────────────────────────────────────────────────
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
        # Header azul sólido
        self.setFillColor(C_ACENTO)
        self.rect(0, PH - 14*mm, PW, 14*mm, fill=1, stroke=0)
        # Línea decorativa bajo el header
        self.setStrokeColor(colors.HexColor("#1e40af"))
        self.setLineWidth(0.5)
        self.line(0, PH - 14*mm, PW, PH - 14*mm)
        # Texto del header
        self.setFillColor(C_BLANCO)
        self.setFont("Helvetica-Bold", 9)
        self.drawString(12*mm, PH - 9*mm, "CONTROL METABÓLICO AUTÓNOMO")
        self.setFont("Helvetica", 8)
        self.drawRightString(PW - 12*mm, PH - 9*mm, self._fecha)
        # Footer línea + número de página
        self.setStrokeColor(C_BORDE)
        self.setLineWidth(0.5)
        self.line(12*mm, 10*mm, PW - 12*mm, 10*mm)
        self.setFillColor(C_TEXTO2)
        self.setFont("Helvetica", 7)
        self.drawCentredString(PW/2, 6*mm, f"Página {num} de {total}")

# ─── HELPERS ──────────────────────────────────────────────────────────────────
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

def fmt_d(v, inv=False):
    if v is None or abs(v) < 0.05: return "—"
    c = (C_VERDE if v<0 else C_ROJO) if inv else (C_VERDE if v>0 else C_ROJO)
    f = "▼" if v<0 else "▲"
    s = "+" if v>0 else ""
    return f'<font color="#{c.hexval()[2:]}">{f} {s}{v:.2f}</font>'

# ─── PÁGINA 1 ─────────────────────────────────────────────────────────────────
def pagina_1(d, story):
    fecha = d.get("fecha","")
    dias  = d.get("dias_entre",7)

    # BLOQUE HERO — score + macros sobre fondo blanco con borde azul
    sc   = d.get("score", 0)
    desc = d.get("desc_score","")
    kcal = d.get("calorias", 0)
    pg   = d.get("proteina_g", 0)
    cg   = d.get("carbs_g", 0)
    gg   = d.get("grasas_g", 0)

    col_s = C_VERDE if sc>=75 else C_AMARILLO if sc>=50 else C_NARANJA if sc>=25 else C_ROJO
    hx_s  = col_s.hexval()[2:]

    blk_score = Table([
        [Paragraph("SCORE SEMANAL", S["sec"])],
        [Paragraph(f'<font color="#{hx_s}"><b>{sc}</b></font><font size=16 color="#475569">/100</font>', S["score_n"])],
        [Paragraph(desc, S["score_d"])],
        [Paragraph(f'<font color="#475569" size=8>vs {dias} días atrás</font>', S["score_d"])],
    ], colWidths=[52*mm])
    blk_score.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_ACENTO_BG),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ("BOX",           (0,0),(-1,-1), 1.5, C_ACENTO),
    ]))

    def bm(num, u, lab, col):
        hx = col.hexval()[2:]
        bg = C_VERDE_BG if col==C_VERDE else C_ROJO_BG if col==C_ROJO else C_AMARILLO_BG if col==C_AMARILLO else C_ACENTO_BG
        t = Table([
            [Paragraph(f'<font color="#{hx}"><b>{num}</b></font><font size=8 color="#475569"> {u}</font>', S["macro_n"])],
            [Paragraph(lab, S["macro_l"])],
        ], colWidths=[28*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1), bg),
            ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
            ("BOX",(0,0),(-1,-1),0.5,C_BORDE),("ALIGN",(0,0),(-1,-1),"CENTER"),
        ]))
        return t

    t_mac = Table([[bm(kcal,"kcal","CALORÍAS",C_ACENTO),
                    bm(pg,"g","PROTEÍNA",C_VERDE),
                    bm(cg,"g","CARBOS",C_AMARILLO),
                    bm(gg,"g","GRASAS",C_NARANJA)]],
                  colWidths=[28*mm]*4)
    t_mac.setStyle(TableStyle([
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
        ("INNERGRID",(0,0),(-1,-1),3,C_BLANCO),
    ]))

    t_hero = Table([[blk_score, t_mac]], colWidths=[54*mm, 118*mm])
    t_hero.setStyle(TableStyle([
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
        ("INNERGRID",(0,0),(-1,-1),4,C_BLANCO),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(t_hero)
    story.append(Spacer(1, 5*mm))

    # TELEMETRÍA
    story.append(Paragraph("TELEMETRÍA CORPORAL", S["sec"]))

    def fila(emo, lab, val, u, dv, inv=False, m=None):
        col = sem_col(val, m) if m else C_TEXTO
        vs  = f"{val} {u}".strip() if val is not None else "—"
        hx  = col.hexval()[2:]
        return [
            Paragraph(f"{emo}  {lab}", S["mlab"]),
            Paragraph(f'<font color="#{hx}"><b>{vs}</b></font>', S["mval"]),
            Paragraph(fmt_d(dv, inv), S["mdel"]),
        ]

    rows = [
        [Paragraph("MÉTRICA",   S["sec"]),
         Paragraph("VALOR",     S["sec"]),
         Paragraph("VARIACIÓN", S["sec"])],
        fila("⚖",  "Peso",            d.get("peso"),    "kg",   d.get("delta_peso"),    inv=True),
        fila("💪", "Músculo Esquel.", d.get("musculo"),  "%",    d.get("delta_musculo")),
        fila("🥓", "Grasa Corporal",  d.get("grasa"),    "%",    d.get("delta_grasa"),   inv=True, m="grasa"),
        fila("🫀", "Grasa Visceral",  d.get("visceral"), "",     d.get("delta_visceral"),inv=True, m="visceral"),
        fila("💧", "Agua Corporal",   d.get("agua"),     "%",    d.get("delta_agua"),             m="agua"),
        fila("🧬", "Proteína Corp.",  d.get("proteina"), "%",    None,                            m="proteina"),
        fila("🦴", "Masa Ósea",       d.get("masa_osea"),"kg",   None),
        fila("⚡", "BMR",             d.get("bmr"),     "kcal",  None),
        fila("📅", "Edad Metabólica", d.get("edad_meta"),"años", None),
        fila("📐", "BMI",             d.get("bmi"),      "",     None,                            m="bmi"),
        fila("🔩", "Masa Libre Grasa",d.get("fat_free"), "kg",   None),
    ]
    t_tel = Table(rows, colWidths=[62*mm, 62*mm, 48*mm])
    t_tel.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  C_ACENTO),
        ("TEXTCOLOR",     (0,0),(-1,0),  C_BLANCO),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [C_BLANCO, C_FONDO]),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(0,-1),  10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
        ("ALIGN",         (2,0),(2,-1),  "RIGHT"),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("LINEBELOW",     (0,0),(-1,-2), 0.3, C_BORDE),
        ("BOX",           (0,0),(-1,-1), 0.5, C_BORDE),
    ]))
    story.append(t_tel)
    story.append(Spacer(1, 5*mm))

    # ALERTAS
    alertas = d.get("alertas", [])
    if alertas:
        story.append(Paragraph("ALERTAS CLÍNICAS", S["sec"]))
        t_a = Table([[Paragraph(f"  ⚠  {a}", S["alerta"])] for a in alertas],
                    colWidths=[172*mm])
        t_a.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C_ROJO_BG),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
            ("BOX",           (0,0),(-1,-1), 1, C_ROJO),
            ("LINEBELOW",     (0,0),(-1,-2), 0.3, colors.HexColor("#fecaca")),
        ]))
        story.append(t_a)
        story.append(Spacer(1, 5*mm))

    # CONTROL METABÓLICO
    story.append(Paragraph("CONTROL METABÓLICO AUTÓNOMO", S["sec"]))

    em  = d.get("estado_mimo", "—")
    rm  = d.get("razon_mimo", "")
    rs  = d.get("razon_siso", "")
    nm  = d.get("nuevo_mult", "—")
    sm  = d.get("shadow_mult", "—")

    MC  = {"CATABOLISMO":C_ROJO,"RECOMPOSICION":C_MORADO,
           "CUTTING_LIMPIO":C_VERDE,"ESTANCAMIENTO":C_AMARILLO,"ZONA_GRIS":C_TEXTO2}
    cm  = MC.get(em, C_ACENTO)
    hcm = cm.hexval()[2:]

    t_mimo = Table([[
        Table([
            [Paragraph("MIMO — DIAGNÓSTICO", S["sec"])],
            [Paragraph(f'<font color="#{hcm}"><b>{em}</b></font>', S["mimo_e"])],
            [Paragraph(rm, S["mimo_r"])],
            [Paragraph(f'Sugerido: <font color="#{hcm}"><b>{sm} kcal/kg</b></font>', S["mimo_r"])],
        ], colWidths=[83*mm]),
        Table([
            [Paragraph("SISO — CONTROL ACTIVO", S["sec"])],
            [Paragraph(f'<b>{nm} kcal/kg</b>', S["mimo_e"])],
            [Paragraph(rs, S["mimo_r"])],
        ], colWidths=[83*mm]),
    ]], colWidths=[85*mm, 85*mm])
    t_mimo.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(0,-1), C_ACENTO_BG),
        ("BACKGROUND",    (1,0),(1,-1), C_FONDO),
        ("TOPPADDING",    (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 10),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("BOX",           (0,0),(-1,-1), 0.5, C_BORDE),
        ("LINEBEFORE",    (1,0),(1,-1),  1,   C_BORDE),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))
    story.append(t_mimo)


# ─── PÁGINA 2+ ────────────────────────────────────────────────────────────────
def pagina_2(d, story):
    story.append(PageBreak())
    story.append(Paragraph("PLAN SEMANAL — NUTRICIÓN Y ENTRENAMIENTO", S["sec"]))
    story.append(hr(C_ACENTO, 1.5))
    story.append(Spacer(1, 4*mm))

    an = d.get("analisis_ia", "")
    if an:
        an_clean = re.sub(r"<[^>]+>", "", an)
        story.append(Paragraph("DIAGNÓSTICO DE LA SEMANA", S["sec"]))
        t_an = Table([[Paragraph(an_clean, S["cuerpo"])]], colWidths=[172*mm])
        t_an.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C_ACENTO_BG),
            ("TOPPADDING",    (0,0),(-1,-1), 10),
            ("BOTTOMPADDING", (0,0),(-1,-1), 10),
            ("LEFTPADDING",   (0,0),(-1,-1), 12),
            ("RIGHTPADDING",  (0,0),(-1,-1), 12),
            ("BOX",           (0,0),(-1,-1), 1, C_ACENTO),
        ]))
        story.append(t_an)
        story.append(Spacer(1, 5*mm))

    dias = d.get("dias_plan", [])
    if not dias:
        story.append(Paragraph("Plan nutricional no disponible esta semana.", S["cuerpo"]))
        return

    TIPO_COL = {
        "GYM":          C_ACENTO,
        "CASA":         C_VERDE,
        "FIN DE SEMANA":C_NARANJA,
        "RESETEO":      C_TEXTO2,
    }
    TIPO_BG = {
        "GYM":          C_ACENTO_BG,
        "CASA":         C_VERDE_BG,
        "FIN DE SEMANA":C_AMARILLO_BG,
        "RESETEO":      C_FONDO,
    }

    for dia in dias:
        tipo = dia.get("tipo", "GYM")
        col  = TIPO_COL.get(tipo, C_ACENTO)
        bg   = TIPO_BG.get(tipo, C_ACENTO_BG)
        hx   = col.hexval()[2:]

        t_hd = Table([[
            Paragraph(f'<font color="white"><b>{dia["nombre"]}</b></font>', S["dia_nom"]),
            Paragraph(f'<font color="white">{dia.get("subtitulo","")}</font>', S["dia_sub"]),
        ]], colWidths=[100*mm, 72*mm])
        t_hd.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), col),
            ("TOPPADDING",    (0,0),(-1,-1), 8),
            ("BOTTOMPADDING", (0,0),(-1,-1), 8),
            ("LEFTPADDING",   (0,0),(0,-1),  10),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ]))

        rows_c = [[Paragraph(c["label"], S["clab"]),
                   Paragraph(c["texto"],  S["ctxt"])]
                  for c in dia.get("comidas", [])]
        t_c = Table(rows_c, colWidths=[26*mm, 146*mm])
        t_c.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0,0),(-1,-1), [C_BLANCO, C_FONDO]),
            ("TOPPADDING",     (0,0),(-1,-1), 5),
            ("BOTTOMPADDING",  (0,0),(-1,-1), 5),
            ("LEFTPADDING",    (0,0),(0,-1),  10),
            ("RIGHTPADDING",   (0,0),(-1,-1), 8),
            ("VALIGN",         (0,0),(-1,-1), "TOP"),
            ("LINEBELOW",      (0,0),(-1,-2), 0.3, C_BORDE),
            ("BOX",            (0,0),(-1,-1), 0.5, C_BORDE),
        ]))
        story.append(KeepTogether([t_hd, t_c, Spacer(1, 4*mm)]))


# ─── FUNCIÓN PRINCIPAL ────────────────────────────────────────────────────────
def generar_pdf(datos: dict, ruta_salida: str) -> str:
    os.makedirs(os.path.dirname(ruta_salida) if os.path.dirname(ruta_salida) else ".", exist_ok=True)
    fecha = datos.get("fecha", datetime.now().strftime("%d/%m/%Y"))

    marco = Frame(12*mm, 14*mm, PW-24*mm, PH-30*mm,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc = BaseDocTemplate(
        ruta_salida, pagesize=A4,
        rightMargin=12*mm, leftMargin=12*mm,
        topMargin=18*mm, bottomMargin=16*mm,
        title=f"Control Metabólico — {fecha}",
        author="Sistema Autónomo",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[marco])])

    story = []
    pagina_1(datos, story)
    pagina_2(datos, story)

    doc.build(story,
              canvasmaker=lambda fn, **kw: ReporteCanvas(fn, fecha=fecha, **kw))
    return ruta_salida


# ─── TEST ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    datos_test = {
        "fecha":"08/03/2026","dias_entre":6,
        "score":31,"desc_score":"Construyendo base",
        "peso":111.1,"delta_peso":-2.60,
        "grasa":32.2,"delta_grasa":-0.70,
        "musculo":43.8,"delta_musculo":0.40,
        "visceral":14.0,"delta_visceral":-1.0,
        "agua":48.9,"delta_agua":0,
        "proteina":15.4,"masa_osea":3.8,
        "bmr":1995,"edad_meta":37,"bmi":31.8,"fat_free":75.3,
        "alertas":[
            "Grasa visceral elevada (14.0) — riesgo metabólico activo",
            "Hidratacion baja (48.9%) — prioriza agua esta semana",
            "Proteina corporal baja (15.4%) — revisa ingesta proteica",
        ],
        "estado_mimo":"ZONA_GRIS","emoji_mimo":"",
        "razon_mimo":"Senales mixtas. Puede ser ruido hidrico.",
        "shadow_mult":24.0,"razon_siso":"Perdida demasiado rapida (-2.49 kg/sem). Aumento multiplicador.",
        "nuevo_mult":25.0,"calorias":2778,"proteina_g":166,"carbs_g":353,"grasas_g":78,
        "analisis_ia":(
            "Excelente semana. La perdida de 2.6 kg combinada con reduccion de 0.7% de grasa "
            "y aumento de 0.4% de musculo es un resultado de elite. El SISO ajusto el multiplicador "
            "a 25 kcal/kg para proteger la masa muscular ante la velocidad de perdida. "
            "Objetivo de hidratacion: 4.5 litros diarios basado en agua corporal actual de 48.9%."
        ),
        "dias_plan":[
            {"nombre":"LUNES — Día de Ataque 1","tipo":"GYM",
             "subtitulo":"Oficina + Gym 45 min — Empuje",
             "comidas":[
                {"label":"Desayuno","texto":"Licuado: 45g proteina, 80g avena, 1 platano, 30g crema cacahuate, 400ml agua. Llevar en termo."},
                {"label":"Almuerzo","texto":"Sobra cena del domingo."},
                {"label":"Colacion","texto":"1 manzana grande."},
                {"label":"Cena","texto":"400g pechuga al horno, 450g camote asado, brocoli al vapor. Preparar doble para lonche martes."},
             ]},
            {"nombre":"MARTES — Fortaleza en Casa","tipo":"CASA",
             "subtitulo":"Home Office + 30 min Full Body",
             "comidas":[
                {"label":"Desayuno","texto":"Licuado (mismo lunes)."},
                {"label":"Almuerzo","texto":"Sobra cena lunes."},
                {"label":"Colacion","texto":"1 taza fresas frescas."},
                {"label":"Rutina","texto":"AMRAP 30 min: Sentadillas x15, Flexiones x10, Zancadas x10/pierna, Plancha 45s. Descanso 60s entre rondas."},
                {"label":"Cena","texto":"Chili: 350g res 90/10, frijoles negros, arroz integral. Preparar doble."},
             ]},
            {"nombre":"DOMINGO — Preparacion y Reseteo","tipo":"RESETEO",
             "subtitulo":"Descanso, hidratacion y preparacion",
             "comidas":[
                {"label":"Desayuno","texto":"3 huevos + 2 claras con espinacas, 2 rebanadas pan integral."},
                {"label":"Almuerzo","texto":"Ensalada Cobb: lechuga, 150g pollo, huevo duro, tomate, 1/4 aguacate."},
                {"label":"Colacion","texto":"1 pera."},
                {"label":"Cena","texto":"Lentejas estofadas con verduras + 200g pechuga pavo. Preparar doble para lonche lunes."},
             ]},
        ],
    }
    ruta = generar_pdf(datos_test, "/mnt/user-data/outputs/reporte_semanal.pdf")
    print(f"PDF: {ruta}")
