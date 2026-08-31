"""Lectura de rrhh.cfg (clave=valor, # comentarios) — compartido por classifier.py y mailer.py."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CFG_PATH = BASE_DIR / "rrhh.cfg"


def load_cfg(defaults: dict | None = None) -> dict:
    cfg = dict(defaults or {})
    if CFG_PATH.exists():
        for line in CFG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip()
    return cfg
