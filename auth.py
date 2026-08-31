"""Login y permisos por usuario. Mismo esquema de hash que usa Producción (pbkdf2_hmac)."""
import hashlib
import secrets
from functools import wraps

from flask import g, redirect, request, session, url_for, flash

from db import get_db


def generar_token() -> str:
    return secrets.token_urlsafe(32)


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return h.hex(), salt


def verificar_password(password: str, password_hash: str, salt: str) -> bool:
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return secrets.compare_digest(h.hex(), password_hash)


def usuario_actual():
    if "usuario" in g:
        return g.usuario
    uid = session.get("usuario_id")
    g.usuario = None
    if uid:
        conn = get_db()
        u = conn.execute("SELECT * FROM usuarios WHERE id = ? AND activo = 1", (uid,)).fetchone()
        conn.close()
        g.usuario = u
    return g.usuario


def permisos_usuario(usuario_id: int) -> set:
    conn = get_db()
    rows = conn.execute(
        "SELECT permiso_cod FROM usuario_permisos WHERE usuario_id = ?", (usuario_id,)
    ).fetchall()
    conn.close()
    return {r["permiso_cod"] for r in rows}


def tiene_permiso(usuario, cod: str) -> bool:
    if usuario is None:
        return False
    if usuario["es_admin"]:
        return True
    return cod in permisos_usuario(usuario["id"])


def requiere_item(cod: str):
    """Decorator: bloquea la vista si el usuario logueado no tiene ese permiso de ítem."""
    def decorador(vista):
        @wraps(vista)
        def envoltorio(*args, **kwargs):
            u = usuario_actual()
            if not tiene_permiso(u, cod):
                flash("No tenés acceso a esa pantalla.", "error")
                return redirect(url_for("index"))
            return vista(*args, **kwargs)
        return envoltorio
    return decorador
