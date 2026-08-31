"""Importa/actualiza empleados desde el Excel de nómina (carpeta excel/).
Upsert por Legajo: si ya existe, actualiza sus datos; si no, lo crea.
No borra empleados que falten en una corrida nueva (para eso se los da de baja
a mano, desactivándolos, no se asume que "no está en el Excel" = baja)."""
import sys
from pathlib import Path

import pandas as pd

from db import get_db, init_db

EXCEL_DIR = Path(__file__).resolve().parent / "excel"


def _o_ninguno(valor):
    if pd.isna(valor):
        return None
    return str(valor).strip() or None


def _numero_texto(valor):
    """Convierte un número leído como float (por los NaN) a texto sin decimales."""
    if pd.isna(valor):
        return None
    return str(int(valor))


def _obtener_o_crear(conn, tabla, nombre):
    if not nombre:
        return None
    fila = conn.execute(f"SELECT id FROM {tabla} WHERE nombre = ?", (nombre,)).fetchone()
    if fila:
        return fila["id"]
    cur = conn.execute(f"INSERT INTO {tabla} (nombre) VALUES (?)", (nombre,))
    return cur.lastrowid


def importar(ruta_excel: Path):
    init_db()
    conn = get_db()

    df = pd.read_excel(ruta_excel)
    columnas_esperadas = {"Nombre", "Turno", "Puesto", "Departamento", "Compañía", "DNI", "CUIL", "Legajo"}
    faltantes = columnas_esperadas - set(df.columns)
    if faltantes:
        raise ValueError(f"Al Excel le faltan columnas esperadas: {faltantes}")

    nuevos = 0
    actualizados = 0

    for _, fila in df.iterrows():
        legajo = int(fila["Legajo"])
        nombre = str(fila["Nombre"]).strip()
        dni = _numero_texto(fila["DNI"])
        cuil = _numero_texto(fila["CUIL"])
        turno = _o_ninguno(fila["Turno"])

        compania_id = _obtener_o_crear(conn, "companias", _o_ninguno(fila["Compañía"]))
        departamento_id = _obtener_o_crear(conn, "departamentos", _o_ninguno(fila["Departamento"]))
        puesto_id = _obtener_o_crear(conn, "puestos", _o_ninguno(fila["Puesto"]))

        existente = conn.execute("SELECT id FROM empleados WHERE legajo = ?", (legajo,)).fetchone()
        if existente:
            conn.execute(
                """UPDATE empleados SET nombre=?, dni=?, cuil=?, compania_id=?, departamento_id=?,
                   puesto_id=?, turno=?, fecha_actualizacion=datetime('now','localtime')
                   WHERE legajo=?""",
                (nombre, dni, cuil, compania_id, departamento_id, puesto_id, turno, legajo),
            )
            actualizados += 1
        else:
            conn.execute(
                """INSERT INTO empleados (legajo, dni, cuil, nombre, compania_id, departamento_id,
                   puesto_id, turno) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (legajo, dni, cuil, nombre, compania_id, departamento_id, puesto_id, turno),
            )
            nuevos += 1

    conn.commit()
    conn.close()
    print(f"Importación completa: {nuevos} nuevos, {actualizados} actualizados.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ruta = Path(sys.argv[1])
    else:
        candidatos = sorted(EXCEL_DIR.glob("nomina*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidatos:
            print(f"No encontré ningún archivo 'nomina*.xls*' en {EXCEL_DIR}")
            sys.exit(1)
        ruta = candidatos[0]
    print(f"Importando desde: {ruta}")
    importar(ruta)
