"""Importación puntual de Sede y Tipo de contrato por empleado desde el Excel
de RR.HH. ('Ubicación' y 'Condición'), cruzando por legajo contra la tabla
empleados ya cargada. El resto de las columnas del archivo (Banco, Sector,
Área) son solo para liquidación de sueldos y no se cargan acá.

A diferencia de importar_nomina.py, esto no tiene botón en la app todavía —
Oscar no tiene claro si va a hacer falta repetir esto más adelante ("vemos el
ida y vuelta"). Se corre a mano cuando haga falta: py importar_sedes.py
"""
import sys
from pathlib import Path

import pandas as pd

from db import get_db, init_db

EXCEL_DIR = Path(__file__).resolve().parent / "excel"


def importar(ruta_excel: Path):
    init_db()
    conn = get_db()

    df = pd.read_excel(ruta_excel)
    columnas_esperadas = {"Número de legajo", "Ubicación", "Condición"}
    faltantes = columnas_esperadas - set(df.columns)
    if faltantes:
        raise ValueError(f"Al Excel le faltan columnas esperadas: {faltantes}")

    asignados = 0
    sin_empleado = []

    for _, fila in df.iterrows():
        legajo = int(fila["Número de legajo"])
        sede_nombre = str(fila["Ubicación"]).strip()
        tipo_contrato = str(fila["Condición"]).strip() or None

        sede_id = None
        if sede_nombre:
            sede_row = conn.execute("SELECT id FROM sedes WHERE nombre = ?", (sede_nombre,)).fetchone()
            if sede_row:
                sede_id = sede_row["id"]
            else:
                sede_id = conn.execute("INSERT INTO sedes (nombre) VALUES (?)", (sede_nombre,)).lastrowid

        cur = conn.execute(
            "UPDATE empleados SET sede_id = COALESCE(?, sede_id), tipo_contrato = ? WHERE legajo = ?",
            (sede_id, tipo_contrato, legajo),
        )
        if cur.rowcount:
            asignados += 1
        else:
            sin_empleado.append(legajo)

    conn.commit()
    conn.close()
    print(f"Sedes asignadas: {asignados}. Legajos sin empleado correspondiente: {len(sin_empleado)}")
    if sin_empleado:
        print(f"  -> {sin_empleado}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ruta = Path(sys.argv[1])
    else:
        candidatos = sorted(EXCEL_DIR.glob("Sede*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidatos:
            print(f"No encontré ningún archivo 'Sede*.xls*' en {EXCEL_DIR}")
            sys.exit(1)
        ruta = candidatos[0]
    print(f"Importando desde: {ruta}")
    importar(ruta)
