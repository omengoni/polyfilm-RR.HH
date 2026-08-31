"""Descarga los CVs adjuntos de la casilla de Reclutamiento por IMAP directo
(la casilla vive en un hosting cPanel, no en Microsoft 365 — por eso IMAP con
usuario/contraseña simple funciona, sin OAuth ni Graph API).

No mueve ni borra nada del correo — solo marca como leído lo que ya reviso
(así una corrida siguiente no vuelve a mirar el mismo mail). Corre 100% del
lado de la VM, sin depender de ninguna PC ni de Outlook.

Deduplica por contenido: si alguien reenvía el mismo archivo (mismo hash) en
otro mail, no se vuelve a guardar una copia — evita que se acumulen '_1',
'_2', etc. del mismo CV en la carpeta."""
import hashlib
from pathlib import Path
import email
from email.header import decode_header, make_header

import imaplib

from config import load_cfg
from db import get_db
from procesar import CVS_DIR

EXTENSIONES_VALIDAS = {".pdf", ".doc", ".docx"}


def _hashes_existentes() -> set:
    """Hashes de todo lo que ya está en cvs/ (recursivo) + lo que ya está cargado
    en la base — para no volver a guardar un adjunto cuyo contenido ya tenemos."""
    hashes = set()
    for archivo in CVS_DIR.rglob("*"):
        if archivo.is_file():
            hashes.add(hashlib.sha256(archivo.read_bytes()).hexdigest())
    conn = get_db()
    for (h,) in conn.execute("SELECT cv_hash FROM candidatos WHERE cv_hash IS NOT NULL").fetchall():
        hashes.add(h)
    conn.close()
    return hashes


def imap_configurado() -> bool:
    cfg = load_cfg()
    return bool(cfg.get("imap_host") and cfg.get("imap_user") and cfg.get("imap_password"))


def _nombre_disponible(carpeta: Path, nombre: str) -> Path:
    destino = carpeta / nombre
    stem, suffix = destino.stem, destino.suffix
    contador = 1
    while destino.exists():
        destino = carpeta / f"{stem}_{contador}{suffix}"
        contador += 1
    return destino


def _decodificar(valor: str) -> str:
    try:
        return str(make_header(decode_header(valor)))
    except Exception:
        return valor


def descargar_cvs_correo() -> dict:
    cfg = load_cfg({"imap_port": "993"})
    host = cfg.get("imap_host")
    puerto = int(cfg.get("imap_port", "993"))
    usuario = cfg.get("imap_user")
    password = cfg.get("imap_password")
    if not (host and usuario and password):
        raise RuntimeError("Falta configurar imap_host/imap_user/imap_password en rrhh.cfg.")

    revisados = 0
    guardados = 0
    duplicados = 0
    errores = []
    hashes_vistos = _hashes_existentes()

    conn = imaplib.IMAP4_SSL(host, puerto, timeout=30)
    try:
        conn.login(usuario, password)
        conn.select("INBOX")

        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK":
            raise RuntimeError(f"No se pudo buscar mensajes: {typ}")
        ids = data[0].split()

        for msg_id in ids:
            try:
                typ, msg_data = conn.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                mensaje = email.message_from_bytes(msg_data[0][1])
                revisados += 1

                for parte in mensaje.walk():
                    nombre_archivo = parte.get_filename()
                    if not nombre_archivo:
                        continue
                    nombre_archivo = _decodificar(nombre_archivo)
                    ext = Path(nombre_archivo).suffix.lower()
                    if ext not in EXTENSIONES_VALIDAS:
                        continue
                    contenido = parte.get_payload(decode=True)
                    if not contenido:
                        continue
                    hash_contenido = hashlib.sha256(contenido).hexdigest()
                    if hash_contenido in hashes_vistos:
                        duplicados += 1
                        continue
                    hashes_vistos.add(hash_contenido)
                    destino = _nombre_disponible(CVS_DIR, nombre_archivo)
                    destino.write_bytes(contenido)
                    guardados += 1

                conn.store(msg_id, "+FLAGS", "\\Seen")
            except Exception as e:
                errores.append(f"{msg_id}: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()

    return {"revisados": revisados, "guardados": guardados, "duplicados": duplicados, "errores": errores}


if __name__ == "__main__":
    resultado = descargar_cvs_correo()
    print(f"Mensajes revisados: {resultado['revisados']}. Adjuntos guardados: {resultado['guardados']}. Duplicados omitidos: {resultado['duplicados']}.")
    if resultado["errores"]:
        print(f"Errores ({len(resultado['errores'])}): {resultado['errores'][:5]}")
