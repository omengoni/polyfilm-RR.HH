"""Importa Apercibimientos y Suspensiones (export de un formulario de Google
Forms) y los linkea con la tabla empleados por nombre (no hay legajo en este
archivo). Reimportable: se dedupe por (fecha de registro + nombre), así que
correrlo de nuevo sobre un archivo que creció no duplica lo que ya estaba.
Los que no matchean por nombre (ex-empleados, error de tipeo) igual se
guardan, con empleado_id en null — no se pierde el registro."""
import sys
from pathlib import Path

import pandas as pd

from db import get_db, init_db

EXCEL_DIR = Path(__file__).resolve().parent / "excel"


def _obtener_o_crear(conn, tabla, nombre):
    if not nombre:
        return None
    fila = conn.execute(f"SELECT id FROM {tabla} WHERE nombre = ?", (nombre,)).fetchone()
    if fila:
        return fila["id"]
    return conn.execute(f"INSERT INTO {tabla} (nombre) VALUES (?)", (nombre,)).lastrowid


def importar(ruta_excel: Path):
    init_db()
    conn = get_db()

    df = pd.read_excel(ruta_excel)
    columnas_esperadas = {
        "Marca temporal", "Nombre:", "Tipo de Sanción:",
        "Motivo de la sanción:", "Motivo de la sanción:.1",
        "Días de suspensión:", "Desde la fecha:",
    }
    faltantes = columnas_esperadas - set(df.columns)
    if faltantes:
        raise ValueError(f"Al Excel le faltan columnas esperadas: {faltantes}")

    nuevos = 0
    duplicados = 0
    sin_empleado = []

    for _, fila in df.iterrows():
        nombre = str(fila["Nombre:"]).strip()
        tipo = str(fila["Tipo de Sanción:"]).strip()
        motivo_ap = fila["Motivo de la sanción:"]
        motivo_susp = fila["Motivo de la sanción:.1"]
        motivo = motivo_ap if not pd.isna(motivo_ap) else motivo_susp
        motivo = str(motivo).strip() if not pd.isna(motivo) else None
        dias = fila["Días de suspensión:"]
        dias = str(dias).strip() if not pd.isna(dias) else None
        fecha_desde = fila["Desde la fecha:"]
        fecha_desde = fecha_desde.strftime("%Y-%m-%d") if pd.notna(fecha_desde) else None
        fecha_registro = fila["Marca temporal"].strftime("%Y-%m-%d %H:%M:%S")

        empleado = conn.execute(
            "SELECT id FROM empleados WHERE UPPER(TRIM(nombre)) = ?", (nombre.upper(),)
        ).fetchone()
        empleado_id = empleado["id"] if empleado else None
        if not empleado_id:
            sin_empleado.append(nombre)

        tipo_id = _obtener_o_crear(conn, "tipos_sancion", tipo)
        motivo_id = _obtener_o_crear(conn, "motivos_sancion", motivo)

        cur = conn.execute(
            """INSERT OR IGNORE INTO sanciones
               (empleado_id, nombre_original, tipo, motivo, tipo_id, motivo_id, dias_suspension, fecha_desde, fecha_registro)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (empleado_id, nombre, tipo, motivo, tipo_id, motivo_id, dias, fecha_desde, fecha_registro),
        )
        if cur.rowcount:
            nuevos += 1
        else:
            duplicados += 1

    conn.commit()
    conn.close()
    print(f"Sanciones: {nuevos} nuevas, {duplicados} ya existentes (sin duplicar).")
    if sin_empleado:
        print(f"Sin match de empleado ({len(set(sin_empleado))} nombres distintos): {sorted(set(sin_empleado))}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ruta = Path(sys.argv[1])
    else:
        candidatos = sorted(EXCEL_DIR.glob("Aperc*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidatos:
            print(f"No encontré ningún archivo 'Aperc*.xls*' en {EXCEL_DIR}")
            sys.exit(1)
        ruta = candidatos[0]
    print(f"Importando desde: {ruta}")
    importar(ruta)
