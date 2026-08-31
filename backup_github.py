"""Backup diario de CÓDIGO + BASE de la app de RR.HH. a un repo git privado
y push a GitHub. Pensado para correr desde la VM (donde vive la base real),
no desde ninguna PC — así no depende de que la PC de nadie esté prendida ni
de una unidad de red.

Qué hace:
  1. Copia CONSISTENTE de rrhh.db (API de backup de SQLite, válida aunque
     alguien esté usando la app en ese momento) dentro de la carpeta del repo.
  2. Sincroniza el CÓDIGO fuente (*.py, templates/, static/) al repo. NO
     copia rrhh.cfg (tiene contraseñas y API keys) ni las carpetas de
     archivos subidos (cvs/, empleados_archivos/, syh_archivos/,
     documentos_repositorio/) — esas son pesadas y regenerables/no
     esenciales para restaurar el código+datos; si hace falta recuperar un
     archivo puntual, está en la base o en el servidor.
  3. git add -A + commit (con fecha) + push, solo si hubo cambios.

Restaurar: copiar rrhh.db (y/o el código) del repo de vuelta a la carpeta
de la app en la VM.
"""
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DB_ORIGEN = APP_DIR / "rrhh.db"
REPO = Path(r"C:\PolyAPP_RR.HH\backup_repo")
DB_DESTINO = REPO / "rrhh.db"

CODE_DIRS = ["templates", "static"]
GIT_EXE = r"C:\Program Files\Git\cmd\git.exe"


def git(*args):
    return subprocess.run([GIT_EXE, *args], cwd=str(REPO), capture_output=True, text=True)


def sync_codigo():
    """Copia el código fuente (*.py del root + templates/ + static/) al repo,
    espejando las carpetas (borra+recopia para reflejar archivos borrados)."""
    for s in glob.glob(str(APP_DIR / "*.py")):
        shutil.copy2(s, REPO / os.path.basename(s))
    for d in CODE_DIRS:
        s = APP_DIR / d
        dst = REPO / d
        if s.is_dir():
            if dst.is_dir():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(s, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def main():
    if not DB_ORIGEN.exists():
        print(f"ERROR: no se encuentra la base: {DB_ORIGEN}")
        sys.exit(1)
    if not (REPO / ".git").is_dir():
        print(f"ERROR: {REPO} todavía no es un repo git (falta el 'git clone' inicial).")
        sys.exit(1)

    # 1) Copia consistente de la base dentro del repo
    src = sqlite3.connect(str(DB_ORIGEN))
    dst = sqlite3.connect(str(DB_DESTINO))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()

    # 2) Sincronizar el código
    try:
        sync_codigo()
    except Exception as e:
        print(f"AVISO: falló la sync de código ({e}); sigo con el backup de la base.")

    # 3) Commit + push solo si hay cambios
    git("add", "-A")
    estado = git("status", "--porcelain")
    if not estado.stdout.strip():
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Sin cambios (código ni base), no se commitea.")
        return

    msg = f"backup {datetime.now():%Y-%m-%d %H:%M}"
    git("commit", "-m", msg)
    push = git("push")
    salida = (push.stdout + push.stderr).strip()
    if push.returncode == 0:
        print(f"OK — {msg}")
    else:
        print(f"COMMIT OK pero el PUSH falló:\n{salida}")
        sys.exit(1)


if __name__ == "__main__":
    main()
