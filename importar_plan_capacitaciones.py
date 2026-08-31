"""Importa el Plan Anual de Capacitaciones 2026 desde la hoja 'Propuesta plan
2026' del archivo REG-SGI. Cada fila es una capacitación planificada (tema
descriptivo, quién la dicta, planta, participantes, modalidad, duración),
agrupada por un macro-tema (SYSO, BRIGADA DE EMERGENCIAS, MÉDICO LABORAL) que
mapea a nuestro 'Tema madre'.

El Excel NO tiene datos usables de meses planificados ni % de avance (las
columnas de mes están vacías y el % avance da '#DIV/0!' — nunca se completó a
mano), así que no se inventan esos datos: se crea el registro del plan
(capacitaciones_plan, año 2026) vinculado al tema, y el avance real se calcula
del lado de la app en base a si ya hubo asistencias registradas.

Algunas filas del plan describen la misma capacitación que ya tenemos
cargada desde 'Capacitaciones 2026.xlsx' (con otro nombre, más corto). Para
esos casos hay un mapeo a mano en MATCHES_CONOCIDOS en vez de intentar
adivinar por texto — son pocos y así no se linkean cosas por error."""
import sys
from pathlib import Path

import openpyxl

from db import get_db, init_db
from importar_capacitaciones import _obtener_o_crear_tema

EXCEL_DIR = Path(__file__).resolve().parent / "excel"
ANIO_PLAN = 2026

MACROTEMA_A_TEMA_MADRE = {
    "SYSO": "Seguridad e Higiene",
    "BRIGADA DE EMERGENCIAS": "Seguridad e Higiene",
    "MÉDICO LABORAL": "Medicina Laboral",
}

# Filas del plan cuya descripción corresponde a un tema que ya existe en el
# catálogo (creado desde el historial de 'Capacitaciones 2026.xlsx'), con
# otro nombre. El resto de las filas del plan crea un tema nuevo.
MATCHES_CONOCIDOS = {
    "1)selección, uso y cuidado de elementos de protección personal (epp); 2) manejo seguro y responsable; desplazamientos dentro y fuera del espacio laboral; 3)prevención de incendios - uso de extintores, plan de emergencias general, 4)autocontrol preventivo 5) riesgos especificos acorde al puesto de trabajo": "EPP",
    "plan de emergencias, evacuación y roles, uso de extintores": "PLAN DE EVACUACIÓN Y ROLES",
    "1) autoelevadores certificaciones y recertificaciones. 2) riesgos en manejo de vehículos industriales": "AUTOELEVADOR Y CERTIFICACIONES",
    "riesgos en oficinas - riesgo eléctrico. riesgo ergonómico": "RIESGO EN OFICINAS",
    "vida saludable/hidratación": "HIDRATACIÓN Y VIDA SALUDABLE",
    "efectos del tabaco sobre la salud.": "EFECTOS DEL TABACO",
}


def importar(ruta_excel: Path):
    init_db()
    conn = get_db()

    wb = openpyxl.load_workbook(ruta_excel, data_only=True)
    ws = wb["Propuesta plan 2026"]

    macrotema_actual = None
    nuevos_temas = 0
    matcheados = 0
    planes_creados = 0

    for fila in ws.iter_rows(min_row=7, max_row=38, values_only=True):
        col_macrotema, descripcion, a_dictar_por, planta, participantes, modalidad, duracion = fila[1:8]
        if not descripcion or not str(descripcion).strip():
            continue
        if col_macrotema and str(col_macrotema).strip():
            macrotema_actual = str(col_macrotema).strip()
        if str(descripcion).strip().upper() == "% AVANCE TOTAL":
            continue

        descripcion = str(descripcion).strip()
        tema_madre = MACROTEMA_A_TEMA_MADRE.get(macrotema_actual)
        nombre_existente = MATCHES_CONOCIDOS.get(descripcion.lower())

        if nombre_existente:
            tema_id = _obtener_o_crear_tema(conn, nombre_existente, tema_madre)
            matcheados += 1
        else:
            tema_id = conn.execute(
                "SELECT id FROM capacitaciones_temas WHERE nombre = ?", (descripcion,)
            ).fetchone()
            if tema_id:
                tema_id = tema_id["id"]
            else:
                tema_id = conn.execute(
                    """INSERT INTO capacitaciones_temas (nombre, tipo, tema_madre, area_dicta, planta, modalidad, duracion)
                       VALUES (?, 'Capacitación', ?, ?, ?, ?, ?)""",
                    (descripcion, tema_madre, a_dictar_por, planta, modalidad,
                     str(duracion).strip() if duracion else None),
                ).lastrowid
                nuevos_temas += 1

        cur = conn.execute(
            "SELECT id FROM capacitaciones_plan WHERE tema_id = ? AND anio = ?", (tema_id, ANIO_PLAN)
        ).fetchone()
        if not cur:
            conn.execute(
                "INSERT INTO capacitaciones_plan (tema_id, anio) VALUES (?, ?)", (tema_id, ANIO_PLAN)
            )
            planes_creados += 1

    conn.commit()
    conn.close()
    print(f"Plan {ANIO_PLAN}: {planes_creados} entradas de plan creadas "
          f"({matcheados} vinculadas a temas existentes, {nuevos_temas} temas nuevos creados).")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ruta = Path(sys.argv[1])
    else:
        candidatos = sorted(EXCEL_DIR.glob("REG-SGI*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidatos:
            print(f"No encontré ningún archivo 'REG-SGI*.xls*' en {EXCEL_DIR}")
            sys.exit(1)
        ruta = candidatos[0]
    print(f"Importando desde: {ruta}")
    importar(ruta)
