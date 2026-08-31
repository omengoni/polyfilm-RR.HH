"""Envío de mail por SMTP (recuperación de contraseña). Requiere que la mailbox
tenga SMTP AUTH habilitado en M365 — la autenticación básica normal no alcanza
para Exchange Online desde fines de 2022. Config en rrhh.cfg (smtp_*)."""
import smtplib
from email.mime.text import MIMEText

from config import load_cfg


def smtp_configurado() -> bool:
    cfg = load_cfg()
    return bool(cfg.get("smtp_host") and cfg.get("smtp_user") and cfg.get("smtp_password"))


def enviar_mail(destinatario: str, asunto: str, cuerpo_html: str) -> tuple[bool, str]:
    """Devuelve (ok, mensaje). Nunca lanza excepción — el llamador decide qué mostrar."""
    cfg = load_cfg({"smtp_port": "587"})
    host = cfg.get("smtp_host")
    user = cfg.get("smtp_user")
    password = cfg.get("smtp_password")
    remitente = cfg.get("smtp_from") or user

    if not (host and user and password):
        return False, "El envío de mail todavía no está configurado (rrhh.cfg, smtp_*)."

    try:
        puerto = int(cfg.get("smtp_port", "587"))
        msg = MIMEText(cuerpo_html, "html", "utf-8")
        msg["Subject"] = asunto
        msg["From"] = remitente
        msg["To"] = destinatario

        with smtplib.SMTP(host, puerto, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(remitente, [destinatario], msg.as_string())
        return True, "Mail enviado."
    except Exception as e:
        return False, f"No se pudo enviar el mail: {e}"
