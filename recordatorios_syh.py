"""Manda un mail diario de recordatorio con los estudios de Seguridad e Higiene
que están vencidos o por vencer (dentro de 'syh_dias_aviso' días). Se manda un
solo mail digest a todos los usuarios activos con permiso sobre el módulo y
mail cargado — no uno por estudio. Dedupe: cada estudio solo dispara un aviso
por cada vencimiento calculado (si se actualiza el vencimiento, vuelve a avisar)."""
import sys
from datetime import date, datetime

from config import load_cfg
from db import get_db, init_db
from mailer import enviar_mail, smtp_configurado


def _destinatarios(conn):
    filas = conn.execute(
        """SELECT DISTINCT u.email FROM usuarios u
           LEFT JOIN usuario_permisos p ON p.usuario_id = u.id AND p.permiso_cod = 'item_seguridad'
           WHERE u.activo = 1 AND u.email IS NOT NULL AND u.email != ''
             AND (u.es_admin = 1 OR p.usuario_id IS NOT NULL)"""
    ).fetchall()
    return [f["email"] for f in filas]


def enviar_recordatorios():
    init_db()
    if not smtp_configurado():
        print("SMTP no configurado (rrhh.cfg) — no se puede enviar el recordatorio.")
        return

    cfg = load_cfg({"syh_dias_aviso": "15", "app_base_url": ""})
    dias_aviso = int(cfg.get("syh_dias_aviso", "15") or 15)
    base_url = cfg.get("app_base_url", "").rstrip("/")
    hoy = date.today()

    conn = get_db()
    estudios = conn.execute("SELECT * FROM syh_estudios WHERE proximo_vencimiento IS NOT NULL").fetchall()

    vencidos = []
    por_vencer = []
    for e in estudios:
        if e["recordatorio_enviado_para"] == e["proximo_vencimiento"]:
            continue
        venc = datetime.strptime(e["proximo_vencimiento"], "%Y-%m-%d").date()
        dias = (venc - hoy).days
        if dias < 0:
            vencidos.append(e)
        elif dias <= dias_aviso:
            por_vencer.append(e)

    if not vencidos and not por_vencer:
        print("Nada para avisar hoy.")
        conn.close()
        return

    destinatarios = _destinatarios(conn)
    if not destinatarios:
        print("No hay destinatarios (nadie con permiso 'item_seguridad' y mail cargado).")
        conn.close()
        return

    def _fila(e):
        link = f"{base_url}/seguridad-e-higiene/estudio/{e['id']}" if base_url else "#"
        return (f"<tr><td>{e['sede']}</td><td><a href='{link}'>{e['nombre']}</a></td>"
                f"<td>{e['proximo_vencimiento']}</td></tr>")

    cuerpo = "<p>Cronograma de Seguridad e Higiene — estudios a revisar:</p>"
    if vencidos:
        cuerpo += "<h3>Vencidos</h3><table border='1' cellpadding='6'>" + "".join(_fila(e) for e in vencidos) + "</table>"
    if por_vencer:
        cuerpo += f"<h3>Por vencer (próximos {dias_aviso} días)</h3><table border='1' cellpadding='6'>" + "".join(_fila(e) for e in por_vencer) + "</table>"

    ok_alguno = False
    for destinatario in destinatarios:
        ok, msg = enviar_mail(destinatario, "Seguridad e Higiene: estudios por vencer", cuerpo)
        print(f"{destinatario}: {msg}")
        ok_alguno = ok_alguno or ok

    if ok_alguno:
        for e in vencidos + por_vencer:
            conn.execute(
                "UPDATE syh_estudios SET recordatorio_enviado_para = ? WHERE id = ?",
                (e["proximo_vencimiento"], e["id"]),
            )
        conn.commit()
    conn.close()


if __name__ == "__main__":
    enviar_recordatorios()
