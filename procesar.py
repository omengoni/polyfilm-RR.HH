"""Escanea la carpeta cvs/ y procesa los archivos nuevos: extrae, clasifica y carga en la DB."""
import hashlib
import shutil
from pathlib import Path

from db import get_db
from extractor import extract_text, FORMATOS_SOPORTADOS
from classifier import classify_cv

BASE_DIR = Path(__file__).resolve().parent
CVS_DIR = BASE_DIR / "cvs"
PROCESADOS_DIR = CVS_DIR / "procesados"
DUPLICADOS_DIR = CVS_DIR / "duplicados"
ERRORES_DIR = CVS_DIR / "errores"


def _hash_archivo(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _log(conn, filename: str, cv_hash: str | None, resultado: str, detalle: str = ""):
    conn.execute(
        "INSERT INTO log_procesamiento (cv_filename, cv_hash, resultado, detalle) VALUES (?, ?, ?, ?)",
        (filename, cv_hash, resultado, detalle),
    )


def _archivar(archivo: Path, carpeta_destino: Path) -> Path:
    """Mueve el archivo a carpeta_destino (creándola si hace falta) y devuelve la ruta final.
    Nunca borra: si ya existe un archivo con ese nombre, agrega un sufijo numérico."""
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    destino = carpeta_destino / archivo.name
    contador = 1
    while destino.exists():
        destino = carpeta_destino / f"{archivo.stem}_{contador}{archivo.suffix}"
        contador += 1
    shutil.move(str(archivo), str(destino))
    return destino


def procesar_carpeta() -> dict:
    """Devuelve un resumen: {nuevos, duplicados, actualizados, errores, detalle: [...]}."""
    conn = get_db()
    roles = [dict(r) for r in conn.execute("SELECT * FROM roles WHERE activo = 1 ORDER BY orden").fetchall()]
    estado_nuevo_id = conn.execute("SELECT id FROM estados WHERE nombre = 'Nuevo'").fetchone()["id"]

    resumen = {"nuevos": 0, "duplicados": 0, "actualizados": 0, "errores": 0, "detalle": []}

    archivos = [f for f in CVS_DIR.iterdir() if f.is_file() and f.suffix.lower() in FORMATOS_SOPORTADOS]

    for archivo in sorted(archivos):
        try:
            cv_hash = _hash_archivo(archivo)

            ya_existe = conn.execute(
                "SELECT id FROM candidatos WHERE cv_hash = ?", (cv_hash,)
            ).fetchone()
            if ya_existe:
                _archivar(archivo, DUPLICADOS_DIR)
                _log(conn, archivo.name, cv_hash, "duplicado_hash")
                resumen["duplicados"] += 1
                resumen["detalle"].append(f"{archivo.name}: ya procesado (mismo archivo)")
                conn.commit()
                continue

            texto = extract_text(archivo)
            if not texto.strip():
                _archivar(archivo, ERRORES_DIR)
                _log(conn, archivo.name, cv_hash, "error", "sin texto extraíble")
                resumen["errores"] += 1
                resumen["detalle"].append(f"{archivo.name}: no se pudo extraer texto")
                conn.commit()
                continue

            datos = classify_cv(texto, roles)

            rol_id = None
            for r in roles:
                if r["nombre"].strip().lower() == (datos.get("rol_sugerido") or "").strip().lower():
                    rol_id = r["id"]
                    break

            candidato_existente = None
            email = (datos.get("email") or "").strip().lower()
            telefono = (datos.get("telefono") or "").strip()
            if email:
                candidato_existente = conn.execute(
                    "SELECT id FROM candidatos WHERE lower(email) = ?", (email,)
                ).fetchone()
            if not candidato_existente and telefono:
                candidato_existente = conn.execute(
                    "SELECT id FROM candidatos WHERE telefono = ? AND telefono != ''", (telefono,)
                ).fetchone()

            archivo_final = _archivar(archivo, PROCESADOS_DIR)

            if candidato_existente:
                conn.execute(
                    """UPDATE candidatos SET nombre=?, email=?, telefono=?, localidad=?, rol_id=?, rol_sugerido=?,
                       score=?, justificacion=?, resumen=?, cv_filename=?, cv_path=?, cv_hash=?,
                       fecha_actualizacion=datetime('now','localtime')
                       WHERE id=?""",
                    (
                        datos.get("nombre", ""), datos.get("email", ""), datos.get("telefono", ""),
                        datos.get("localidad", ""), rol_id, datos.get("rol_sugerido", ""), datos.get("score"),
                        datos.get("justificacion", ""), datos.get("resumen", ""),
                        archivo.name, str(archivo_final), cv_hash, candidato_existente["id"],
                    ),
                )
                _log(conn, archivo.name, cv_hash, "actualizado", f"candidato_id={candidato_existente['id']}")
                resumen["actualizados"] += 1
                resumen["detalle"].append(f"{archivo.name}: actualiza candidato existente ({datos.get('nombre','')})")
            else:
                conn.execute(
                    """INSERT INTO candidatos
                       (nombre, email, telefono, localidad, rol_id, rol_sugerido, estado_id, score,
                        justificacion, resumen, cv_filename, cv_path, cv_hash, origen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'carpeta_test')""",
                    (
                        datos.get("nombre", ""), datos.get("email", ""), datos.get("telefono", ""),
                        datos.get("localidad", ""), rol_id, datos.get("rol_sugerido", ""), estado_nuevo_id,
                        datos.get("score"), datos.get("justificacion", ""), datos.get("resumen", ""),
                        archivo.name, str(archivo_final), cv_hash,
                    ),
                )
                _log(conn, archivo.name, cv_hash, "nuevo")
                resumen["nuevos"] += 1
                resumen["detalle"].append(f"{archivo.name}: candidato nuevo ({datos.get('nombre','')}) -> {datos.get('rol_sugerido','')} ({datos.get('score')})")

            conn.commit()

        except Exception as e:
            conn.rollback()
            _log(conn, archivo.name, None, "error", str(e))
            conn.commit()
            resumen["errores"] += 1
            resumen["detalle"].append(f"{archivo.name}: error - {e}")

    conn.close()
    return resumen
