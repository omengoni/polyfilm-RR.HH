import os
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort, session, g

from db import get_db, init_db
from procesar import procesar_carpeta, CVS_DIR, ERRORES_DIR
from config import load_cfg
from mailer import enviar_mail, smtp_configurado
from extractor import extract_text, FORMATOS_SOPORTADOS
from documentos_util import voyage_configurado, embeber_documento, responder_pregunta
from intake_mail import imap_configurado, descargar_cvs_correo
from auth import (
    hash_password, verificar_password, usuario_actual, permisos_usuario,
    tiene_permiso, requiere_item, generar_token,
)

app = Flask(__name__)
app.secret_key = os.environ.get("RRHH_SECRET_KEY", "polyfilm-rrhh-dev")

init_db()

DOCUMENTOS_DIR = Path(__file__).resolve().parent / "documentos_repositorio"
DOCUMENTOS_DIR.mkdir(exist_ok=True)
CATEGORIAS_DOCUMENTOS = ["Reclutamiento", "Empleados", "Seguridad e Higiene", "Capacitaciones", "General"]

EMPLEADOS_ARCHIVOS_DIR = Path(__file__).resolve().parent / "empleados_archivos"
EMPLEADOS_ARCHIVOS_DIR.mkdir(exist_ok=True)
TIPOS_ARCHIVO_EMPLEADO = ["CV", "Licencia", "Certificado", "Justificación", "Otro"]
FORMATOS_ARCHIVO_EMPLEADO = {".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png"}

SYH_ARCHIVOS_DIR = Path(__file__).resolve().parent / "syh_archivos"
SYH_ARCHIVOS_DIR.mkdir(exist_ok=True)
TIPOS_ARCHIVO_SYH = ["Presupuesto", "Resultado", "Otro"]
FORMATOS_ARCHIVO_SYH = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".jpg", ".jpeg", ".png"}

ESTADO_CLASES = {
    "nuevo": "estado-nuevo",
    "en banco": "estado-banco",
    "entrevista": "estado-entrevista",
    "preocupacional": "estado-preocupacional",
    "efectivo": "estado-efectivo",
    "desechado": "estado-desechado",
}


def _score_clase(score):
    if score is None:
        return "score-na"
    if score >= 90:
        return "score-alto"
    if score >= 70:
        return "score-medio"
    if score >= 40:
        return "score-bajo"
    return "score-muybajo"


def _estado_clase(nombre):
    return ESTADO_CLASES.get((nombre or "").strip().lower(), "estado-otro")


app.jinja_env.filters["score_clase"] = _score_clase
app.jinja_env.filters["estado_clase"] = _estado_clase
app.jinja_env.globals["tiene_permiso"] = tiene_permiso

# Fuente única de verdad del menú: módulos de RR.HH. y sus ítems.
# Mismo patrón que MENU_ITEMS en Producción (planificacion.py) — cuando se
# enganche login/permisos, cada "cod" de opción pasa a ser un permiso item_*.
MODULOS = [
    {
        "cod": "reclutamiento", "nombre": "Reclutamiento", "icono": "🧑‍💼", "color": "#2f6fed",
        "descripcion": "Clasificación y gestión de CVs", "href": "/reclutamiento",
        "opciones": [
            {"cod": "item_procesar_cvs", "label": "Procesamiento de CVs", "icono": "📥", "href": "/procesar"},
            {"cod": "item_candidatos", "label": "Candidatos", "icono": "🗂️", "href": "/candidatos"},
            {"cod": "item_roles", "label": "Roles", "icono": "🏷️", "href": "/roles"},
        ],
    },
    {
        "cod": "empleados", "nombre": "Empleados", "icono": "👥", "color": "#7c3aed",
        "descripcion": "Nómina, departamentos y puestos", "href": "/empleados",
        "opciones": [
            {"cod": "item_empleados", "label": "Empleados", "icono": "🪪", "href": "/empleados"},
            {"cod": "item_departamentos", "label": "Departamentos", "icono": "🏭", "href": "/departamentos"},
            {"cod": "item_puestos", "label": "Puestos", "icono": "🧰", "href": "/puestos"},
            {"cod": "item_sedes", "label": "Sedes", "icono": "📍", "href": "/sedes"},
            {"cod": "item_sanciones", "label": "Sanciones", "icono": "⚠️", "href": "/empleados/sanciones"},
        ],
    },
    {
        "cod": "documentos", "nombre": "Documentos", "icono": "📚", "color": "#0e7490",
        "descripcion": "Repositorio + consulta con IA", "href": "/documentos",
        "opciones": [
            {"cod": "item_documentos", "label": "Documentos", "icono": "📚", "href": "/documentos"},
            {"cod": "item_preguntar_documentos", "label": "Preguntar", "icono": "💬", "href": "/documentos/preguntar"},
        ],
    },
    {
        "cod": "seguridad", "nombre": "Seguridad e Higiene", "icono": "🦺", "color": "#c9820a",
        "descripcion": "Cronograma de estudios por sede", "href": "/seguridad-e-higiene",
        "opciones": [
            {"cod": "item_seguridad", "label": "Seguridad e Higiene", "icono": "🦺", "href": "/seguridad-e-higiene"},
        ],
    },
    {
        "cod": "capacitaciones", "nombre": "Capacitaciones", "icono": "🎓", "color": "#1e7e4a",
        "descripcion": "Plan anual y registro de capacitaciones", "href": "/capacitaciones",
        "opciones": [
            {"cod": "item_capacitaciones", "label": "Capacitaciones", "icono": "🎓", "href": "/capacitaciones"},
        ],
    },
    {
        "cod": "cartelera", "nombre": "Cartelera", "icono": "📋", "color": "#be185d",
        "descripcion": "Comunicación interna y tareas pendientes", "href": "/cartelera",
        "opciones": [
            {"cod": "item_cartelera", "label": "Cartelera", "icono": "📋", "href": "/cartelera"},
        ],
    },
    {
        "cod": "administracion", "nombre": "Administración", "icono": "⚙️", "color": "#475569",
        "descripcion": "Usuarios y permisos", "href": "/admin/usuarios", "solo_admin": True,
        "opciones": [
            {"cod": "item_usuarios", "label": "Usuarios", "icono": "👤", "href": "/admin/usuarios"},
        ],
    },
]

RUTAS_POR_MODULO = {
    "reclutamiento": ("/reclutamiento", "/procesar", "/candidatos", "/roles"),
    "empleados": ("/empleados", "/departamentos", "/puestos", "/sedes"),
    "documentos": ("/documentos",),
    "seguridad": ("/seguridad-e-higiene",),
    "capacitaciones": ("/capacitaciones",),
    "cartelera": ("/cartelera",),
    "administracion": ("/admin",),
}


def _modulos_visibles(usuario):
    """Filtra MODULOS a lo que este usuario puede ver: módulos solo_admin ocultos
    para no-admins, e ítems sin permiso ocultos (salvo admin, que ve todo)."""
    visibles = []
    for m in MODULOS:
        if m.get("solo_admin") and not (usuario and usuario["es_admin"]):
            continue
        if usuario and usuario["es_admin"]:
            opciones = m["opciones"]
        else:
            opciones = [op for op in m["opciones"] if tiene_permiso(usuario, op["cod"])]
        if m["opciones"] and not opciones:
            continue  # módulo con ítems pero ninguno habilitado para este usuario: no se muestra
        m2 = dict(m)
        m2["opciones"] = opciones
        visibles.append(m2)
    return visibles


@app.context_processor
def inject_nav():
    path = request.path
    modulo_actual = None
    for cod, prefijos in RUTAS_POR_MODULO.items():
        if any(path == p or path.startswith(p + "/") for p in prefijos):
            modulo_actual = cod
            break
    usuario = usuario_actual()
    return dict(modulos=_modulos_visibles(usuario), modulo_actual=modulo_actual, usuario=usuario)


ENDPOINTS_PUBLICOS = {"login", "olvide_password", "restablecer_password", "static"}


@app.before_request
def exigir_login():
    if request.endpoint in ENDPOINTS_PUBLICOS or request.endpoint is None:
        return
    u = usuario_actual()
    if not u:
        return redirect(url_for("login", next=request.path))
    if u["debe_cambiar_password"] and request.endpoint not in ("cambiar_password", "logout"):
        flash("Tenés que elegir una contraseña propia antes de seguir.", "info")
        return redirect(url_for("cambiar_password"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario_in = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        u = conn.execute(
            "SELECT * FROM usuarios WHERE usuario = ? COLLATE NOCASE AND activo = 1", (usuario_in,)
        ).fetchone()
        conn.close()
        if u and verificar_password(password, u["password_hash"], u["salt"]):
            session.clear()
            session["usuario_id"] = u["id"]
            destino = request.form.get("next") or url_for("index")
            return redirect(destino)
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html", next=request.args.get("next", ""))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/cambiar-password", methods=["GET", "POST"])
def cambiar_password():
    u = usuario_actual()
    forzado = bool(u["debe_cambiar_password"])
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        confirmar = request.form.get("confirmar", "")
        if not forzado and not verificar_password(actual, u["password_hash"], u["salt"]):
            flash("La contraseña actual no es correcta.", "error")
        elif len(nueva) < 6:
            flash("La contraseña nueva tiene que tener al menos 6 caracteres.", "error")
        elif nueva != confirmar:
            flash("La confirmación no coincide.", "error")
        else:
            password_hash, salt = hash_password(nueva)
            conn = get_db()
            conn.execute(
                "UPDATE usuarios SET password_hash=?, salt=?, debe_cambiar_password=0 WHERE id=?",
                (password_hash, salt, u["id"]),
            )
            conn.commit()
            conn.close()
            flash("Contraseña actualizada.", "info")
            return redirect(url_for("index"))
    return render_template("cambiar_password.html", forzado=forzado)


@app.route("/olvide-password", methods=["GET", "POST"])
def olvide_password():
    if request.method == "POST":
        usuario_in = request.form.get("usuario", "").strip()
        conn = get_db()
        u = conn.execute(
            "SELECT * FROM usuarios WHERE usuario = ? COLLATE NOCASE AND activo = 1", (usuario_in,)
        ).fetchone()
        if u and u["email"]:
            token = generar_token()
            expira = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO password_resets (usuario_id, token, expira) VALUES (?, ?, ?)",
                (u["id"], token, expira),
            )
            conn.commit()
            base_url = load_cfg().get("app_base_url", request.url_root.rstrip("/"))
            link = f"{base_url}/restablecer-password/{token}"
            cuerpo = (
                f"<p>Hola {u['nombre']},</p>"
                f"<p>Pediste restablecer tu contraseña de la app de RR.HH. Polyfilm. "
                f'Entrá acá para elegir una nueva (válido por 2 horas): <a href="{link}">{link}</a></p>'
                f"<p>Si no fuiste vos, ignorá este mail.</p>"
            )
            ok, msg = enviar_mail(u["email"], "Restablecer contraseña — RR.HH. Polyfilm", cuerpo)
            if not ok:
                flash(f"No se pudo enviar el mail de recuperación: {msg}", "error")
        conn.close()
        flash("Si el usuario existe y tiene mail cargado, te enviamos un link para restablecer la contraseña.", "info")
        return redirect(url_for("login"))
    return render_template("olvide_password.html", smtp_ok=smtp_configurado())


@app.route("/restablecer-password/<token>", methods=["GET", "POST"])
def restablecer_password(token):
    conn = get_db()
    reset = conn.execute(
        "SELECT * FROM password_resets WHERE token = ? AND usado = 0", (token,)
    ).fetchone()
    valido = reset and reset["expira"] >= datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not valido:
        conn.close()
        flash("Ese link de recuperación no es válido o ya venció. Pedí uno nuevo.", "error")
        return redirect(url_for("olvide_password"))

    if request.method == "POST":
        nueva = request.form.get("nueva", "")
        confirmar = request.form.get("confirmar", "")
        if len(nueva) < 6:
            flash("La contraseña nueva tiene que tener al menos 6 caracteres.", "error")
        elif nueva != confirmar:
            flash("La confirmación no coincide.", "error")
        else:
            password_hash, salt = hash_password(nueva)
            conn.execute(
                "UPDATE usuarios SET password_hash=?, salt=?, debe_cambiar_password=0 WHERE id=?",
                (password_hash, salt, reset["usuario_id"]),
            )
            conn.execute("UPDATE password_resets SET usado = 1 WHERE id = ?", (reset["id"],))
            conn.commit()
            conn.close()
            flash("Contraseña actualizada. Ya podés iniciar sesión.", "info")
            return redirect(url_for("login"))
    conn.close()
    return render_template("restablecer_password.html", token=token)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/reclutamiento")
def reclutamiento():
    return render_template("reclutamiento.html")


def _estado_vencimiento(proximo_vencimiento, dias_aviso=15):
    """(clase_css, etiqueta) para pintar el estudio según qué tan cerca está su vencimiento."""
    from datetime import date
    if not proximo_vencimiento:
        return "syh-sin-dato", "Sin fecha"
    try:
        venc = datetime.strptime(proximo_vencimiento, "%Y-%m-%d").date()
    except ValueError:
        return "syh-sin-dato", "Sin fecha"
    hoy = date.today()
    dias = (venc - hoy).days
    if dias < 0:
        return "syh-vencido", "Vencido"
    if dias <= dias_aviso:
        return "syh-por-vencer", "Por vencer"
    return "syh-ok", "Al día"


@app.route("/seguridad-e-higiene")
@requiere_item("item_seguridad")
def seguridad_e_higiene():
    conn = get_db()
    sede_filtro = request.args.get("sede", "").strip()
    cfg = load_cfg({"syh_dias_aviso": "15"})
    dias_aviso = int(cfg.get("syh_dias_aviso", "15") or 15)

    query = "SELECT * FROM syh_estudios WHERE 1=1"
    params = []
    if sede_filtro:
        query += " AND sede = ?"
        params.append(sede_filtro)
    query += " ORDER BY (proximo_vencimiento IS NULL), proximo_vencimiento ASC"
    estudios = [dict(r) for r in conn.execute(query, params).fetchall()]
    for e in estudios:
        e["clase_vencimiento"], e["etiqueta_vencimiento"] = _estado_vencimiento(e["proximo_vencimiento"], dias_aviso)

    sedes = [r["sede"] for r in conn.execute("SELECT DISTINCT sede FROM syh_estudios ORDER BY sede").fetchall()]
    conn.close()
    return render_template(
        "seguridad_e_higiene.html", estudios=estudios, sedes=sedes, sede_filtro=sede_filtro,
        syh_configurado=bool(cfg.get("syh_sheet_id")),
    )


@app.route("/seguridad-e-higiene/sincronizar", methods=["POST"])
@requiere_item("item_seguridad")
def syh_sincronizar():
    from sync_syh import sincronizar

    try:
        import io
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            sincronizar()
        flash(buffer.getvalue().strip() or "Sincronizado.", "info")
    except Exception as e:
        flash(f"Error sincronizando: {e}", "error")
    return redirect(url_for("seguridad_e_higiene"))


@app.route("/seguridad-e-higiene/estudio/<int:said>")
@requiere_item("item_seguridad")
def syh_estudio_detalle(said):
    conn = get_db()
    estudio = conn.execute("SELECT * FROM syh_estudios WHERE id = ?", (said,)).fetchone()
    if not estudio:
        conn.close()
        abort(404)
    estudio = dict(estudio)
    estudio["clase_vencimiento"], estudio["etiqueta_vencimiento"] = _estado_vencimiento(estudio["proximo_vencimiento"])
    archivos = conn.execute(
        "SELECT * FROM syh_estudio_archivos WHERE estudio_id = ? ORDER BY fecha_carga DESC", (said,)
    ).fetchall()
    conn.close()
    return render_template(
        "syh_estudio_detalle.html", e=estudio, archivos=archivos, tipos_archivo=TIPOS_ARCHIVO_SYH,
    )


@app.route("/seguridad-e-higiene/estudio/<int:said>/archivo/subir", methods=["POST"])
@requiere_item("item_seguridad")
def syh_archivo_subir(said):
    archivo = request.files.get("archivo")
    tipo = request.form.get("tipo", "").strip() or "Otro"
    descripcion = request.form.get("descripcion", "").strip() or None

    if not archivo or not archivo.filename:
        flash("Elegí un archivo para subir.", "error")
        return redirect(url_for("syh_estudio_detalle", said=said))

    from werkzeug.utils import secure_filename
    nombre_seguro = secure_filename(archivo.filename)
    extension = Path(nombre_seguro).suffix.lower()
    if extension not in FORMATOS_ARCHIVO_SYH:
        flash(f"Formato no soportado: {extension}.", "error")
        return redirect(url_for("syh_estudio_detalle", said=said))

    carpeta_estudio = SYH_ARCHIVOS_DIR / str(said)
    carpeta_estudio.mkdir(exist_ok=True)
    destino = _nombre_disponible(carpeta_estudio, nombre_seguro)
    archivo.save(str(destino))

    conn = get_db()
    conn.execute(
        """INSERT INTO syh_estudio_archivos (estudio_id, tipo, descripcion, archivo_filename, archivo_path)
           VALUES (?, ?, ?, ?, ?)""",
        (said, tipo, descripcion, destino.name, str(destino)),
    )
    conn.commit()
    conn.close()
    flash(f"Archivo '{destino.name}' cargado.", "info")
    return redirect(url_for("syh_estudio_detalle", said=said))


@app.route("/seguridad-e-higiene/estudio/<int:said>/archivo/<int:aid>")
@requiere_item("item_seguridad")
def syh_archivo_ver(said, aid):
    conn = get_db()
    archivo = conn.execute(
        "SELECT archivo_path FROM syh_estudio_archivos WHERE id = ? AND estudio_id = ?", (aid, said)
    ).fetchone()
    conn.close()
    if not archivo or not Path(archivo["archivo_path"]).exists():
        abort(404)
    return send_file(archivo["archivo_path"])


@app.route("/seguridad-e-higiene/estudio/<int:said>/archivo/<int:aid>/eliminar", methods=["POST"])
@requiere_item("item_seguridad")
def syh_archivo_eliminar(said, aid):
    conn = get_db()
    archivo = conn.execute(
        "SELECT archivo_path FROM syh_estudio_archivos WHERE id = ? AND estudio_id = ?", (aid, said)
    ).fetchone()
    if archivo:
        Path(archivo["archivo_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM syh_estudio_archivos WHERE id = ?", (aid,))
        conn.commit()
        flash("Archivo eliminado.", "info")
    conn.close()
    return redirect(url_for("syh_estudio_detalle", said=said))


MESES_ANIO = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
              "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


@app.route("/capacitaciones")
@requiere_item("item_capacitaciones")
def capacitaciones():
    conn = get_db()

    tema_madre_filtro = request.args.get("tema_madre", "").strip()

    dashboard_query = """
        SELECT t.id, t.nombre, t.tipo, t.tema_madre, COUNT(r.id) AS total_registros,
               COUNT(DISTINCT r.empleado_id) AS total_personas,
               MAX(r.fecha) AS ultima_fecha
        FROM capacitaciones_temas t
        LEFT JOIN capacitaciones_registros r ON r.tema_id = t.id
        WHERE t.activo = 1
    """
    dashboard_params = []
    if tema_madre_filtro:
        dashboard_query += " AND t.tema_madre = ?"
        dashboard_params.append(tema_madre_filtro)
    dashboard_query += " GROUP BY t.id ORDER BY t.nombre"
    dashboard = [dict(r) for r in conn.execute(dashboard_query, dashboard_params).fetchall()]
    max_total = max((f["total_registros"] for f in dashboard), default=1) or 1
    for f in dashboard:
        f["pct"] = round(f["total_registros"] / max_total * 100)

    temas_madre = [
        r["tema_madre"] for r in conn.execute(
            "SELECT DISTINCT tema_madre FROM capacitaciones_temas WHERE tema_madre IS NOT NULL ORDER BY tema_madre"
        ).fetchall()
    ]

    conn.close()

    return render_template(
        "capacitaciones.html", dashboard=dashboard, max_total=max_total,
        temas_madre=temas_madre, tema_madre_filtro=tema_madre_filtro,
    )


@app.route("/capacitaciones/detalle")
@requiere_item("item_capacitaciones")
def capacitaciones_detalle():
    conn = get_db()

    tema_id = request.args.get("tema_id", type=int)
    departamento_id = request.args.get("departamento_id", type=int)

    query = """
        SELECT r.*, t.nombre AS tema_nombre, t.tema_madre, e.id AS empleado_id_real, d.nombre AS departamento_nombre
        FROM capacitaciones_registros r
        JOIN capacitaciones_temas t ON t.id = r.tema_id
        LEFT JOIN empleados e ON e.id = r.empleado_id
        LEFT JOIN departamentos d ON d.id = e.departamento_id
        WHERE 1=1
    """
    params = []
    if tema_id:
        query += " AND r.tema_id = ?"
        params.append(tema_id)
    if departamento_id:
        query += " AND e.departamento_id = ?"
        params.append(departamento_id)
    query += " ORDER BY r.fecha DESC"
    registros = conn.execute(query, params).fetchall()

    temas = conn.execute("SELECT * FROM capacitaciones_temas WHERE activo = 1 ORDER BY nombre").fetchall()
    departamentos = conn.execute("SELECT * FROM departamentos WHERE activo = 1 ORDER BY nombre").fetchall()

    conn.close()

    return render_template(
        "capacitaciones_detalle.html", registros=registros, temas=temas, departamentos=departamentos,
        tema_id=tema_id, departamento_id=departamento_id,
    )


@app.route("/capacitaciones/plan")
@requiere_item("item_capacitaciones")
def capacitaciones_plan_anual():
    conn = get_db()

    anios_disponibles = [
        r["anio"] for r in conn.execute("SELECT DISTINCT anio FROM capacitaciones_plan ORDER BY anio DESC").fetchall()
    ]
    hoy_anio = datetime.now().year
    if hoy_anio not in anios_disponibles:
        anios_disponibles.insert(0, hoy_anio)
    anio_plan = request.args.get("anio", type=int) or hoy_anio

    plan_anual = [
        dict(r) for r in conn.execute(
            """SELECT t.id, t.nombre, t.tema_madre,
                      (SELECT COUNT(*) FROM capacitaciones_registros r
                       WHERE r.tema_id = t.id AND strftime('%Y', r.fecha) = ?) AS realizados
               FROM capacitaciones_plan p
               JOIN capacitaciones_temas t ON t.id = p.tema_id
               WHERE p.anio = ?
               ORDER BY t.tema_madre, t.nombre""",
            (str(anio_plan), anio_plan),
        ).fetchall()
    ]
    avance_plan_pct = (
        round(sum(1 for p in plan_anual if p["realizados"] > 0) / len(plan_anual) * 100)
        if plan_anual else 0
    )
    conn.close()

    return render_template(
        "capacitaciones_plan.html", plan_anual=plan_anual, anio_plan=anio_plan,
        anios_disponibles=anios_disponibles, avance_plan_pct=avance_plan_pct,
    )


@app.route("/capacitaciones/temas/nuevo", methods=["POST"])
@requiere_item("item_capacitaciones")
def capacitaciones_tema_nuevo():
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre del tema es obligatorio.", "error")
        return redirect(url_for("capacitaciones"))
    tipo = request.form.get("tipo", "Capacitación").strip()
    tema_madre = request.form.get("tema_madre", "").strip() or None
    area_dicta = request.form.get("area_dicta", "").strip() or None
    planta = request.form.get("planta", "").strip() or None
    modalidad = request.form.get("modalidad", "").strip() or None
    duracion = request.form.get("duracion", "").strip() or None
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO capacitaciones_temas (nombre, tipo, tema_madre, area_dicta, planta, modalidad, duracion)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (nombre, tipo, tema_madre, area_dicta, planta, modalidad, duracion),
    )
    conn.commit()
    tema_id = cur.lastrowid
    conn.close()
    flash(f"Tema '{nombre}' creado.", "info")
    return redirect(url_for("capacitacion_tema_detalle", tid=tema_id))


@app.route("/capacitaciones/nueva", methods=["GET", "POST"])
@requiere_item("item_capacitaciones")
def capacitacion_nueva():
    conn = get_db()
    if request.method == "POST":
        tema_id = request.form.get("tema_id", type=int)
        fecha = request.form.get("fecha", "").strip()
        observaciones = request.form.get("observaciones", "").strip() or None
        empleado_id = request.form.get("empleado_id", type=int)
        departamento_id = request.form.get("departamento_id", type=int)
        puntuacion_raw = request.form.get("puntuacion", "").strip()
        puntuacion = float(puntuacion_raw) if puntuacion_raw else None

        tema = conn.execute("SELECT nombre FROM capacitaciones_temas WHERE id = ?", (tema_id,)).fetchone()
        if not (tema and fecha):
            flash("Elegí un tema y una fecha.", "error")
        elif departamento_id:
            empleados_depto = conn.execute(
                "SELECT id, nombre FROM empleados WHERE departamento_id = ? AND activo = 1", (departamento_id,)
            ).fetchall()
            if not empleados_depto:
                flash("Ese departamento no tiene empleados activos.", "error")
            else:
                cargados = 0
                for emp in empleados_depto:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO capacitaciones_registros
                           (tema_id, empleado_id, nombre_original, fecha, observaciones)
                           VALUES (?, ?, ?, ?, ?)""",
                        (tema_id, emp["id"], emp["nombre"], fecha, observaciones),
                    )
                    cargados += cur.rowcount
                conn.commit()
                conn.close()
                omitidos = len(empleados_depto) - cargados
                msg = f"Cargados {cargados} registros de '{tema['nombre']}'."
                if omitidos:
                    msg += f" ({omitidos} ya tenían esta capacitación en esa fecha.)"
                flash(msg, "info")
                return redirect(url_for("capacitacion_tema_detalle", tid=tema_id))
        elif empleado_id:
            empleado = conn.execute("SELECT nombre FROM empleados WHERE id = ?", (empleado_id,)).fetchone()
            if not empleado:
                flash("Elegí un empleado válido.", "error")
            else:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO capacitaciones_registros
                       (tema_id, empleado_id, nombre_original, fecha, puntuacion, observaciones)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (tema_id, empleado_id, empleado["nombre"], fecha, puntuacion, observaciones),
                )
                conn.commit()
                conn.close()
                if cur.rowcount:
                    flash(f"Registro cargado para {empleado['nombre']}.", "info")
                else:
                    flash(f"{empleado['nombre']} ya tenía esta capacitación cargada en esa fecha.", "error")
                return redirect(url_for("capacitacion_tema_detalle", tid=tema_id))
        else:
            flash("Elegí un empleado o un departamento.", "error")

    temas = conn.execute("SELECT * FROM capacitaciones_temas WHERE activo = 1 ORDER BY nombre").fetchall()
    empleados_lista = conn.execute("SELECT id, nombre, legajo FROM empleados WHERE activo = 1 ORDER BY nombre").fetchall()
    departamentos = conn.execute("SELECT * FROM departamentos WHERE activo = 1 ORDER BY nombre").fetchall()
    tema_id_preseleccionado = request.args.get("tema_id", type=int)
    conn.close()
    return render_template(
        "capacitacion_nueva.html", temas=temas, empleados=empleados_lista, departamentos=departamentos,
        tema_id_preseleccionado=tema_id_preseleccionado,
    )


@app.route("/capacitaciones/tema/<int:tid>")
@requiere_item("item_capacitaciones")
def capacitacion_tema_detalle(tid):
    conn = get_db()
    tema = conn.execute("SELECT * FROM capacitaciones_temas WHERE id = ?", (tid,)).fetchone()
    if not tema:
        conn.close()
        abort(404)
    registros = conn.execute(
        """SELECT r.*, e.id AS empleado_id_real, d.nombre AS departamento_nombre
           FROM capacitaciones_registros r
           LEFT JOIN empleados e ON e.id = r.empleado_id
           LEFT JOIN departamentos d ON d.id = e.departamento_id
           WHERE r.tema_id = ? ORDER BY r.fecha DESC""",
        (tid,),
    ).fetchall()
    anio_actual = datetime.now().year
    plan = conn.execute(
        "SELECT * FROM capacitaciones_plan WHERE tema_id = ? AND anio = ?", (tid, anio_actual)
    ).fetchone()
    meses_planificados = set((plan["meses"] or "").split(",")) if plan else set()
    conn.close()
    return render_template(
        "capacitacion_tema_detalle.html", tema=tema, registros=registros, anio_actual=anio_actual,
        meses_planificados=meses_planificados, meses=MESES_ANIO,
        observaciones_plan=plan["observaciones"] if plan else "",
    )


@app.route("/capacitaciones/tema/<int:tid>/editar", methods=["POST"])
@requiere_item("item_capacitaciones")
def capacitacion_tema_editar(tid):
    nombre = request.form.get("nombre", "").strip()
    tipo = request.form.get("tipo", "Capacitación").strip()
    tema_madre = request.form.get("tema_madre", "").strip() or None
    area_dicta = request.form.get("area_dicta", "").strip() or None
    planta = request.form.get("planta", "").strip() or None
    modalidad = request.form.get("modalidad", "").strip() or None
    duracion = request.form.get("duracion", "").strip() or None
    activo = 1 if request.form.get("activo") == "on" else 0
    conn = get_db()
    conn.execute(
        """UPDATE capacitaciones_temas SET nombre=?, tipo=?, tema_madre=?, area_dicta=?, planta=?, modalidad=?,
           duracion=?, activo=? WHERE id = ?""",
        (nombre, tipo, tema_madre, area_dicta, planta, modalidad, duracion, activo, tid),
    )
    conn.commit()
    conn.close()
    flash("Tema actualizado.", "info")
    return redirect(url_for("capacitacion_tema_detalle", tid=tid))


@app.route("/capacitaciones/tema/<int:tid>/plan", methods=["POST"])
@requiere_item("item_capacitaciones")
def capacitacion_plan_guardar(tid):
    anio = request.form.get("anio", type=int) or datetime.now().year
    meses = ",".join(m for m in MESES_ANIO if request.form.get(f"mes_{m}") == "on")
    observaciones = request.form.get("observaciones", "").strip() or None
    conn = get_db()
    conn.execute(
        """INSERT INTO capacitaciones_plan (tema_id, anio, meses, observaciones)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(tema_id, anio) DO UPDATE SET meses = excluded.meses, observaciones = excluded.observaciones""",
        (tid, anio, meses, observaciones),
    )
    conn.commit()
    conn.close()
    flash("Plan anual actualizado.", "info")
    return redirect(url_for("capacitacion_tema_detalle", tid=tid))


@app.route("/capacitaciones/registro/<int:rid>/eliminar", methods=["POST"])
@requiere_item("item_capacitaciones")
def capacitacion_registro_eliminar(rid):
    conn = get_db()
    row = conn.execute("SELECT tema_id FROM capacitaciones_registros WHERE id = ?", (rid,)).fetchone()
    if row:
        conn.execute("DELETE FROM capacitaciones_registros WHERE id = ?", (rid,))
        conn.commit()
    conn.close()
    flash("Registro eliminado.", "info")
    return redirect(url_for("capacitacion_tema_detalle", tid=row["tema_id"]) if row else url_for("capacitaciones"))


@app.route("/procesar")
@requiere_item("item_procesar_cvs")
def procesar():
    conn = get_db()
    resumen_historial = conn.execute(
        """SELECT DATE(fecha) AS dia,
                  SUM(CASE WHEN resultado = 'nuevo' THEN 1 ELSE 0 END) AS nuevos,
                  SUM(CASE WHEN resultado = 'actualizado' THEN 1 ELSE 0 END) AS actualizados,
                  SUM(CASE WHEN resultado = 'duplicado_hash' THEN 1 ELSE 0 END) AS duplicados,
                  SUM(CASE WHEN resultado = 'error' THEN 1 ELSE 0 END) AS errores,
                  COUNT(*) AS total
           FROM log_procesamiento
           GROUP BY dia
           ORDER BY dia DESC"""
    ).fetchall()
    cant_archivos = len([
        f for f in CVS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".txt"}
    ])
    archivos_con_error = sorted(
        (f for f in ERRORES_DIR.iterdir() if f.is_file()) if ERRORES_DIR.exists() else [],
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    conn.close()
    return render_template(
        "procesar.html", resumen_historial=resumen_historial, cant_archivos=cant_archivos, cvs_dir=str(CVS_DIR),
        imap_ok=imap_configurado(), archivos_con_error=[f.name for f in archivos_con_error],
    )


@app.route("/procesar/errores/<nombre>")
@requiere_item("item_procesar_cvs")
def procesar_error_ver(nombre):
    if "/" in nombre or "\\" in nombre or nombre in (".", ".."):
        abort(404)
    destino = ERRORES_DIR / nombre
    if not destino.is_file():
        abort(404)
    return send_file(destino)


@app.route("/procesar/errores/eliminar", methods=["POST"])
@requiere_item("item_procesar_cvs")
def procesar_errores_eliminar():
    nombres = request.form.getlist("nombre")
    if not nombres:
        flash("No marcaste ningún archivo.", "error")
        return redirect(url_for("procesar"))
    borrados = 0
    for nombre in nombres:
        if "/" in nombre or "\\" in nombre or nombre in (".", ".."):
            continue
        destino = ERRORES_DIR / nombre
        if destino.is_file():
            destino.unlink()
            borrados += 1
    flash(f"{borrados} archivo(s) eliminado(s).", "info")
    return redirect(url_for("procesar"))


@app.route("/procesar/historial/<dia>")
@requiere_item("item_procesar_cvs")
def procesar_historial_dia(dia):
    conn = get_db()
    logs = conn.execute(
        "SELECT * FROM log_procesamiento WHERE DATE(fecha) = ? ORDER BY fecha DESC", (dia,)
    ).fetchall()
    conn.close()
    return render_template("procesar_historial_dia.html", dia=dia, logs=logs)


@app.route("/procesar/historial/eliminar", methods=["POST"])
@requiere_item("item_procesar_cvs")
def procesar_historial_eliminar():
    dias = request.form.getlist("dia")
    if not dias:
        flash("No marcaste ninguna fecha.", "error")
        return redirect(url_for("procesar"))
    conn = get_db()
    conn.executemany("DELETE FROM log_procesamiento WHERE DATE(fecha) = ?", [(d,) for d in dias])
    conn.commit()
    conn.close()
    flash(f"Historial eliminado para {len(dias)} fecha(s).", "info")
    return redirect(url_for("procesar"))


@app.route("/procesar/ejecutar", methods=["POST"])
@requiere_item("item_procesar_cvs")
def procesar_ejecutar():
    resumen = procesar_carpeta()
    flash(
        f"Procesado: {resumen['nuevos']} nuevos, {resumen['actualizados']} actualizados, "
        f"{resumen['duplicados']} duplicados, {resumen['errores']} errores.",
        "info",
    )
    for linea in resumen["detalle"]:
        flash(linea, "detalle")
    return redirect(url_for("procesar"))


@app.route("/procesar/descargar-mail", methods=["POST"])
@requiere_item("item_procesar_cvs")
def descargar_mail_ejecutar():
    if not imap_configurado():
        flash("Falta configurar el acceso IMAP en rrhh.cfg.", "error")
        return redirect(url_for("procesar"))
    try:
        resumen = descargar_cvs_correo()
        flash(
            f"Mail revisado: {resumen['revisados']} mensajes, {resumen['guardados']} adjuntos bajados "
            f"({resumen['duplicados']} duplicados omitidos).",
            "info",
        )
        if resumen["errores"]:
            flash(f"{len(resumen['errores'])} mensajes con error al leer (no se perdieron, quedan sin marcar).", "error")
    except Exception as e:
        flash(f"Error bajando del mail: {e}", "error")
    return redirect(url_for("procesar"))


COLUMNAS_ORDEN = {
    "nombre": "c.nombre",
    "localidad": "c.localidad",
    "rol": "rol_nombre",
    "score": "c.score",
    "estado": "estado_nombre",
    "ingreso": "c.fecha_ingreso",
}


@app.route("/candidatos")
@requiere_item("item_candidatos")
def candidatos():
    conn = get_db()
    roles = conn.execute("SELECT * FROM roles ORDER BY orden").fetchall()
    estados = conn.execute("SELECT * FROM estados ORDER BY orden").fetchall()

    rol_id = request.args.get("rol_id", type=int)
    estado_id = request.args.get("estado_id", type=int)
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    orden = request.args.get("orden", "ingreso")
    direccion = request.args.get("dir", "desc")
    if orden not in COLUMNAS_ORDEN:
        orden = "ingreso"
    if direccion not in ("asc", "desc"):
        direccion = "desc"

    query = """
        SELECT c.*, r.nombre AS rol_nombre, e.nombre AS estado_nombre
        FROM candidatos c
        LEFT JOIN roles r ON r.id = c.rol_id
        JOIN estados e ON e.id = c.estado_id
        WHERE 1=1
    """
    params = []
    if rol_id:
        query += " AND c.rol_id = ?"
        params.append(rol_id)
    if estado_id:
        query += " AND c.estado_id = ?"
        params.append(estado_id)
    if desde:
        query += " AND DATE(c.fecha_ingreso) >= DATE(?)"
        params.append(desde)
    if hasta:
        query += " AND DATE(c.fecha_ingreso) <= DATE(?)"
        params.append(hasta)
    query += f" ORDER BY {COLUMNAS_ORDEN[orden]} {direccion.upper()}"

    lista = conn.execute(query, params).fetchall()
    conn.close()
    return render_template(
        "candidatos.html", candidatos=lista, roles=roles, estados=estados,
        rol_id=rol_id, estado_id=estado_id, desde=desde, hasta=hasta, orden=orden, direccion=direccion,
    )


def _eliminar_candidato(conn, cid):
    """Borra el candidato de la base y, si existe, su archivo de CV en disco."""
    candidato = conn.execute("SELECT cv_path FROM candidatos WHERE id = ?", (cid,)).fetchone()
    if not candidato:
        return False
    if candidato["cv_path"]:
        Path(candidato["cv_path"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM candidatos WHERE id = ?", (cid,))
    return True


@app.route("/candidatos/<int:cid>/eliminar", methods=["POST"])
@requiere_item("item_candidatos")
def candidato_eliminar(cid):
    conn = get_db()
    ok = _eliminar_candidato(conn, cid)
    conn.commit()
    conn.close()
    flash("Candidato eliminado." if ok else "No se encontró el candidato.", "info" if ok else "error")
    return redirect(url_for("candidatos"))


@app.route("/candidatos/eliminar-masivo", methods=["POST"])
@requiere_item("item_candidatos")
def candidatos_eliminar_masivo():
    ids = request.form.getlist("candidato_id", type=int)
    if not ids:
        flash("No seleccionaste ningún candidato.", "error")
        return redirect(url_for("candidatos"))
    conn = get_db()
    eliminados = 0
    for cid in ids:
        if _eliminar_candidato(conn, cid):
            eliminados += 1
    conn.commit()
    conn.close()
    flash(f"{eliminados} candidato(s) eliminado(s).", "info")
    return redirect(url_for("candidatos"))


@app.route("/candidatos/<int:cid>")
@requiere_item("item_candidatos")
def candidato_detalle(cid):
    conn = get_db()
    candidato = conn.execute(
        """SELECT c.*, r.nombre AS rol_nombre, e.nombre AS estado_nombre
           FROM candidatos c
           LEFT JOIN roles r ON r.id = c.rol_id
           JOIN estados e ON e.id = c.estado_id
           WHERE c.id = ?""",
        (cid,),
    ).fetchone()
    if not candidato:
        abort(404)
    roles = conn.execute("SELECT * FROM roles WHERE activo = 1 ORDER BY orden").fetchall()
    estados = conn.execute("SELECT * FROM estados ORDER BY orden").fetchall()
    empleado_vinculado = conn.execute("SELECT id FROM empleados WHERE candidato_id = ?", (cid,)).fetchone()
    conn.close()
    return render_template(
        "candidato_detalle.html", c=candidato, roles=roles, estados=estados,
        empleado_vinculado=empleado_vinculado,
    )


@app.route("/candidatos/<int:cid>/actualizar", methods=["POST"])
@requiere_item("item_candidatos")
def candidato_actualizar(cid):
    estado_id = request.form.get("estado_id", type=int)
    rol_id = request.form.get("rol_id", type=int)
    notas = request.form.get("notas", "").strip() or None
    conn = get_db()
    conn.execute(
        """UPDATE candidatos SET estado_id = ?, rol_id = ?, notas = ?, fecha_actualizacion = datetime('now','localtime')
           WHERE id = ?""",
        (estado_id, rol_id, notas, cid),
    )
    conn.commit()
    conn.close()
    flash("Candidato actualizado.", "info")
    return redirect(url_for("candidato_detalle", cid=cid))


@app.route("/candidatos/<int:cid>/destacar", methods=["POST"])
@requiere_item("item_candidatos")
def candidato_destacar(cid):
    conn = get_db()
    conn.execute("UPDATE candidatos SET destacado = 1 - destacado WHERE id = ?", (cid,))
    conn.commit()
    conn.close()
    return ("", 204)


@app.route("/candidatos/<int:cid>/cv")
@requiere_item("item_candidatos")
def candidato_cv(cid):
    conn = get_db()
    candidato = conn.execute("SELECT cv_path FROM candidatos WHERE id = ?", (cid,)).fetchone()
    conn.close()
    if not candidato or not Path(candidato["cv_path"]).exists():
        abort(404)
    return send_file(candidato["cv_path"])


@app.route("/roles")
@requiere_item("item_roles")
def roles():
    conn = get_db()
    lista = conn.execute("SELECT * FROM roles ORDER BY orden").fetchall()
    conn.close()
    return render_template("roles.html", roles=lista)


@app.route("/roles/nuevo", methods=["POST"])
@requiere_item("item_roles")
def roles_nuevo():
    nombre = request.form.get("nombre", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    if nombre:
        conn = get_db()
        orden = conn.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM roles").fetchone()[0]
        conn.execute(
            "INSERT INTO roles (nombre, descripcion, orden) VALUES (?, ?, ?)",
            (nombre, descripcion, orden),
        )
        conn.commit()
        conn.close()
        flash(f"Rol '{nombre}' creado.", "info")
    return redirect(url_for("roles"))


@app.route("/roles/<int:rid>/editar", methods=["POST"])
@requiere_item("item_roles")
def roles_editar(rid):
    nombre = request.form.get("nombre", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    activo = 1 if request.form.get("activo") == "on" else 0
    conn = get_db()
    conn.execute(
        "UPDATE roles SET nombre = ?, descripcion = ?, activo = ? WHERE id = ?",
        (nombre, descripcion, activo, rid),
    )
    conn.commit()
    conn.close()
    flash(f"Rol '{nombre}' actualizado.", "info")
    return redirect(url_for("roles"))


@app.route("/empleados")
@requiere_item("item_empleados")
def empleados():
    conn = get_db()
    departamentos = conn.execute("SELECT * FROM departamentos ORDER BY nombre").fetchall()
    puestos = conn.execute("SELECT * FROM puestos ORDER BY nombre").fetchall()
    sedes = conn.execute("SELECT * FROM sedes ORDER BY nombre").fetchall()

    departamento_id = request.args.get("departamento_id", type=int)
    puesto_id = request.args.get("puesto_id", type=int)
    sede_id = request.args.get("sede_id", type=int)
    tipo_contrato = request.args.get("tipo_contrato", "").strip()
    buscar = request.args.get("buscar", "").strip()
    solo_activos = request.args.get("activos", "1") == "1"

    query = """
        SELECT e.*, d.nombre AS departamento_nombre, p.nombre AS puesto_nombre, c.nombre AS compania_nombre,
               s.nombre AS sede_nombre
        FROM empleados e
        LEFT JOIN departamentos d ON d.id = e.departamento_id
        LEFT JOIN puestos p ON p.id = e.puesto_id
        LEFT JOIN companias c ON c.id = e.compania_id
        LEFT JOIN sedes s ON s.id = e.sede_id
        WHERE 1=1
    """
    params = []
    if departamento_id:
        query += " AND e.departamento_id = ?"
        params.append(departamento_id)
    if puesto_id:
        query += " AND e.puesto_id = ?"
        params.append(puesto_id)
    if sede_id:
        query += " AND e.sede_id = ?"
        params.append(sede_id)
    if tipo_contrato:
        query += " AND e.tipo_contrato = ?"
        params.append(tipo_contrato)
    if buscar:
        query += " AND (e.nombre LIKE ? OR e.dni LIKE ? OR e.cuil LIKE ? OR CAST(e.legajo AS TEXT) LIKE ?)"
        params += [f"%{buscar}%", f"%{buscar}%", f"%{buscar}%", f"%{buscar}%"]
    if solo_activos:
        query += " AND e.activo = 1"
    query += " ORDER BY e.nombre"

    lista = conn.execute(query, params).fetchall()
    conn.close()
    return render_template(
        "empleados.html", empleados=lista, departamentos=departamentos, puestos=puestos, sedes=sedes,
        departamento_id=departamento_id, puesto_id=puesto_id, sede_id=sede_id, tipo_contrato=tipo_contrato,
        buscar=buscar, solo_activos=solo_activos,
    )


@app.route("/empleados/<int:eid>")
@requiere_item("item_empleados")
def empleado_detalle(eid):
    conn = get_db()
    empleado = conn.execute(
        """SELECT e.*, d.nombre AS departamento_nombre, p.nombre AS puesto_nombre, c.nombre AS compania_nombre,
                  s.nombre AS sede_nombre
           FROM empleados e
           LEFT JOIN departamentos d ON d.id = e.departamento_id
           LEFT JOIN puestos p ON p.id = e.puesto_id
           LEFT JOIN companias c ON c.id = e.compania_id
           LEFT JOIN sedes s ON s.id = e.sede_id
           WHERE e.id = ?""",
        (eid,),
    ).fetchone()
    if not empleado:
        abort(404)
    departamentos = conn.execute("SELECT * FROM departamentos WHERE activo = 1 ORDER BY nombre").fetchall()
    puestos = conn.execute("SELECT * FROM puestos WHERE activo = 1 ORDER BY nombre").fetchall()
    companias = conn.execute("SELECT * FROM companias ORDER BY nombre").fetchall()
    sedes = conn.execute("SELECT * FROM sedes WHERE activo = 1 ORDER BY nombre").fetchall()
    sanciones_empleado = conn.execute(
        "SELECT * FROM sanciones WHERE empleado_id = ? ORDER BY fecha_registro DESC", (eid,)
    ).fetchall()
    archivos_empleado = conn.execute(
        "SELECT * FROM empleado_archivos WHERE empleado_id = ? ORDER BY fecha_carga DESC", (eid,)
    ).fetchall()
    capacitaciones_empleado = conn.execute(
        """SELECT r.*, t.nombre AS tema_nombre
           FROM capacitaciones_registros r
           JOIN capacitaciones_temas t ON t.id = r.tema_id
           WHERE r.empleado_id = ? ORDER BY r.fecha DESC""",
        (eid,),
    ).fetchall()
    conn.close()
    return render_template(
        "empleado_detalle.html", e=empleado, departamentos=departamentos, puestos=puestos,
        companias=companias, sedes=sedes, sanciones_empleado=sanciones_empleado,
        archivos_empleado=archivos_empleado, tipos_archivo=TIPOS_ARCHIVO_EMPLEADO,
        capacitaciones_empleado=capacitaciones_empleado,
    )


@app.route("/empleados/<int:eid>/actualizar", methods=["POST"])
@requiere_item("item_empleados")
def empleado_actualizar(eid):
    nombre = request.form.get("nombre", "").strip()
    dni = request.form.get("dni", "").strip() or None
    cuil = request.form.get("cuil", "").strip() or None
    legajo = request.form.get("legajo", type=int)
    turno = request.form.get("turno", "").strip() or None
    fecha_ingreso = request.form.get("fecha_ingreso", "").strip() or None
    compania_id = request.form.get("compania_id", type=int)
    departamento_id = request.form.get("departamento_id", type=int)
    puesto_id = request.form.get("puesto_id", type=int)
    sede_id = request.form.get("sede_id", type=int)
    tipo_contrato = request.form.get("tipo_contrato", "").strip() or None
    activo = 1 if request.form.get("estado") == "Activo" else 0

    conn = get_db()
    conn.execute(
        """UPDATE empleados SET nombre=?, dni=?, cuil=?, legajo=?, turno=?, fecha_ingreso=?, compania_id=?,
           departamento_id=?, puesto_id=?, sede_id=?, tipo_contrato=?, activo=?,
           fecha_actualizacion=datetime('now','localtime')
           WHERE id=?""",
        (nombre, dni, cuil, legajo, turno, fecha_ingreso, compania_id, departamento_id, puesto_id,
         sede_id, tipo_contrato, activo, eid),
    )
    conn.commit()
    conn.close()
    flash("Empleado actualizado.", "info")
    return redirect(url_for("empleado_detalle", eid=eid))


@app.route("/empleados/<int:eid>/archivos/subir", methods=["POST"])
@requiere_item("item_empleados")
def empleado_archivo_subir(eid):
    archivo = request.files.get("archivo")
    tipo = request.form.get("tipo", "").strip() or "Otro"
    descripcion = request.form.get("descripcion", "").strip() or None

    if not archivo or not archivo.filename:
        flash("Elegí un archivo para subir.", "error")
        return redirect(url_for("empleado_detalle", eid=eid))

    from werkzeug.utils import secure_filename
    nombre_seguro = secure_filename(archivo.filename)
    extension = Path(nombre_seguro).suffix.lower()
    if extension not in FORMATOS_ARCHIVO_EMPLEADO:
        flash(f"Formato no soportado: {extension}. Usá PDF, DOC/DOCX o una imagen (JPG/PNG).", "error")
        return redirect(url_for("empleado_detalle", eid=eid))

    carpeta_empleado = EMPLEADOS_ARCHIVOS_DIR / str(eid)
    carpeta_empleado.mkdir(exist_ok=True)
    destino = _nombre_disponible(carpeta_empleado, nombre_seguro)
    archivo.save(str(destino))

    conn = get_db()
    conn.execute(
        """INSERT INTO empleado_archivos (empleado_id, tipo, descripcion, archivo_filename, archivo_path)
           VALUES (?, ?, ?, ?, ?)""",
        (eid, tipo, descripcion, destino.name, str(destino)),
    )
    conn.commit()
    conn.close()
    flash(f"Archivo '{destino.name}' cargado.", "info")
    return redirect(url_for("empleado_detalle", eid=eid))


@app.route("/empleados/<int:eid>/archivos/<int:aid>")
@requiere_item("item_empleados")
def empleado_archivo_ver(eid, aid):
    conn = get_db()
    archivo = conn.execute(
        "SELECT archivo_path FROM empleado_archivos WHERE id = ? AND empleado_id = ?", (aid, eid)
    ).fetchone()
    conn.close()
    if not archivo or not Path(archivo["archivo_path"]).exists():
        abort(404)
    return send_file(archivo["archivo_path"])


@app.route("/empleados/<int:eid>/archivos/<int:aid>/eliminar", methods=["POST"])
@requiere_item("item_empleados")
def empleado_archivo_eliminar(eid, aid):
    conn = get_db()
    archivo = conn.execute(
        "SELECT archivo_path FROM empleado_archivos WHERE id = ? AND empleado_id = ?", (aid, eid)
    ).fetchone()
    if archivo:
        Path(archivo["archivo_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM empleado_archivos WHERE id = ?", (aid,))
        conn.commit()
        flash("Archivo eliminado.", "info")
    conn.close()
    return redirect(url_for("empleado_detalle", eid=eid))


@app.route("/empleados/nuevo", methods=["GET", "POST"])
@requiere_item("item_empleados")
def empleado_nuevo():
    conn = get_db()
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        legajo = request.form.get("legajo", type=int)
        dni = request.form.get("dni", "").strip() or None
        cuil = request.form.get("cuil", "").strip() or None
        turno = request.form.get("turno", "").strip() or None
        fecha_ingreso = request.form.get("fecha_ingreso", "").strip() or None
        compania_id = request.form.get("compania_id", type=int)
        departamento_id = request.form.get("departamento_id", type=int)
        puesto_id = request.form.get("puesto_id", type=int)
        sede_id = request.form.get("sede_id", type=int)
        tipo_contrato = request.form.get("tipo_contrato", "").strip() or None
        candidato_id = request.form.get("candidato_id", type=int)

        if not (nombre and legajo):
            flash("Nombre y legajo son obligatorios.", "error")
        else:
            try:
                cur = conn.execute(
                    """INSERT INTO empleados (nombre, legajo, dni, cuil, turno, fecha_ingreso, compania_id,
                       departamento_id, puesto_id, sede_id, tipo_contrato, candidato_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (nombre, legajo, dni, cuil, turno, fecha_ingreso, compania_id, departamento_id,
                     puesto_id, sede_id, tipo_contrato, candidato_id),
                )
                nuevo_empleado_id = cur.lastrowid

                if candidato_id:
                    candidato = conn.execute(
                        "SELECT cv_path, cv_filename FROM candidatos WHERE id = ?", (candidato_id,)
                    ).fetchone()
                    if candidato and candidato["cv_path"] and Path(candidato["cv_path"]).exists():
                        carpeta_legajo = EMPLEADOS_ARCHIVOS_DIR / str(nuevo_empleado_id)
                        carpeta_legajo.mkdir(exist_ok=True)
                        origen = Path(candidato["cv_path"])
                        destino = _nombre_disponible(carpeta_legajo, origen.name)
                        origen.rename(destino)
                        conn.execute(
                            """INSERT INTO empleado_archivos (empleado_id, tipo, descripcion, archivo_filename, archivo_path)
                               VALUES (?, 'CV', 'CV de Reclutamiento', ?, ?)""",
                            (nuevo_empleado_id, destino.name, str(destino)),
                        )
                        conn.execute("UPDATE candidatos SET cv_path = ? WHERE id = ?", (str(destino), candidato_id))

                conn.commit()
                flash(f"Empleado '{nombre}' dado de alta.", "info")
                conn.close()
                return redirect(url_for("empleado_detalle", eid=nuevo_empleado_id))
            except Exception as e:
                flash(f"No se pudo dar de alta: {e}", "error")

    departamentos = conn.execute("SELECT * FROM departamentos WHERE activo = 1 ORDER BY nombre").fetchall()
    puestos = conn.execute("SELECT * FROM puestos WHERE activo = 1 ORDER BY nombre").fetchall()
    companias = conn.execute("SELECT * FROM companias ORDER BY nombre").fetchall()
    sedes = conn.execute("SELECT * FROM sedes WHERE activo = 1 ORDER BY nombre").fetchall()

    candidato_id = request.args.get("desde_candidato", type=int)
    candidato = None
    if candidato_id:
        candidato = conn.execute("SELECT * FROM candidatos WHERE id = ?", (candidato_id,)).fetchone()
    conn.close()
    return render_template(
        "empleado_nuevo.html", departamentos=departamentos, puestos=puestos, companias=companias,
        sedes=sedes, candidato=candidato,
    )


@app.route("/empleados/importar", methods=["POST"])
@requiere_item("item_empleados")
def empleados_importar():
    from importar_nomina import EXCEL_DIR, importar as importar_nomina_fn

    candidatos_excel = sorted(EXCEL_DIR.glob("nomina*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidatos_excel:
        flash(f"No encontré ningún archivo 'nomina*.xls*' en {EXCEL_DIR}", "error")
        return redirect(url_for("empleados"))
    try:
        import io
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            importar_nomina_fn(candidatos_excel[0])
        flash(f"Importado desde {candidatos_excel[0].name}: {buffer.getvalue().strip()}", "info")
    except Exception as e:
        flash(f"Error importando: {e}", "error")
    return redirect(url_for("empleados"))


@app.route("/departamentos")
@requiere_item("item_departamentos")
def departamentos():
    conn = get_db()
    lista = conn.execute("SELECT * FROM departamentos ORDER BY nombre").fetchall()
    conn.close()
    return render_template("departamentos.html", departamentos=lista)


@app.route("/departamentos/<int:did>/editar", methods=["POST"])
@requiere_item("item_departamentos")
def departamentos_editar(did):
    nombre = request.form.get("nombre", "").strip()
    activo = 1 if request.form.get("activo") == "on" else 0
    conn = get_db()
    conn.execute("UPDATE departamentos SET nombre = ?, activo = ? WHERE id = ?", (nombre, activo, did))
    conn.commit()
    conn.close()
    flash(f"Departamento '{nombre}' actualizado.", "info")
    return redirect(url_for("departamentos"))


@app.route("/puestos")
@requiere_item("item_puestos")
def puestos():
    conn = get_db()
    lista = conn.execute("SELECT * FROM puestos ORDER BY nombre").fetchall()
    conn.close()
    return render_template("puestos.html", puestos=lista)


@app.route("/puestos/<int:pid>/editar", methods=["POST"])
@requiere_item("item_puestos")
def puestos_editar(pid):
    nombre = request.form.get("nombre", "").strip()
    activo = 1 if request.form.get("activo") == "on" else 0
    conn = get_db()
    conn.execute("UPDATE puestos SET nombre = ?, activo = ? WHERE id = ?", (nombre, activo, pid))
    conn.commit()
    conn.close()
    flash(f"Puesto '{nombre}' actualizado.", "info")
    return redirect(url_for("puestos"))


@app.route("/sedes")
@requiere_item("item_sedes")
def sedes():
    conn = get_db()
    lista = conn.execute("SELECT * FROM sedes ORDER BY nombre").fetchall()
    conn.close()
    return render_template("sedes.html", sedes=lista)


@app.route("/sedes/nueva", methods=["POST"])
@requiere_item("item_sedes")
def sedes_nueva():
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO sedes (nombre) VALUES (?)", (nombre,))
        conn.commit()
        conn.close()
        flash(f"Sede '{nombre}' creada.", "info")
    return redirect(url_for("sedes"))


@app.route("/sedes/<int:sid>/editar", methods=["POST"])
@requiere_item("item_sedes")
def sedes_editar(sid):
    nombre = request.form.get("nombre", "").strip()
    activo = 1 if request.form.get("activo") == "on" else 0
    conn = get_db()
    conn.execute("UPDATE sedes SET nombre = ?, activo = ? WHERE id = ?", (nombre, activo, sid))
    conn.commit()
    conn.close()
    flash(f"Sede '{nombre}' actualizada.", "info")
    return redirect(url_for("sedes"))


@app.route("/empleados/sanciones")
@requiere_item("item_sanciones")
def sanciones():
    conn = get_db()

    tipo = request.args.get("tipo", "").strip()
    departamento_id = request.args.get("departamento_id", type=int)

    dashboard = conn.execute(
        """SELECT d.nombre AS departamento, COALESCE(d.nombre, 'Sin departamento') AS departamento_nombre,
                  SUM(CASE WHEN s.tipo = 'Apercibimiento' THEN 1 ELSE 0 END) AS apercibimientos,
                  SUM(CASE WHEN s.tipo = 'Suspensión' THEN 1 ELSE 0 END) AS suspensiones,
                  COUNT(*) AS total
           FROM sanciones s
           LEFT JOIN empleados e ON e.id = s.empleado_id
           LEFT JOIN departamentos d ON d.id = e.departamento_id
           GROUP BY d.id
           ORDER BY total DESC"""
    ).fetchall()
    max_total = max((f["total"] for f in dashboard), default=1)

    dashboard_motivo = conn.execute(
        """SELECT COALESCE(motivo, 'Sin motivo') AS motivo, COUNT(*) AS total
           FROM sanciones
           GROUP BY motivo
           ORDER BY total DESC"""
    ).fetchall()
    max_total_motivo = max((f["total"] for f in dashboard_motivo), default=1)

    query = """
        SELECT s.*, e.id AS empleado_id_real, e.nombre AS empleado_nombre, d.nombre AS departamento_nombre
        FROM sanciones s
        LEFT JOIN empleados e ON e.id = s.empleado_id
        LEFT JOIN departamentos d ON d.id = e.departamento_id
        WHERE 1=1
    """
    params = []
    if tipo:
        query += " AND s.tipo = ?"
        params.append(tipo)
    if departamento_id:
        query += " AND e.departamento_id = ?"
        params.append(departamento_id)
    query += " ORDER BY s.fecha_registro DESC"
    lista = conn.execute(query, params).fetchall()

    departamentos_lista = conn.execute("SELECT * FROM departamentos ORDER BY nombre").fetchall()
    tipos = conn.execute("SELECT * FROM tipos_sancion ORDER BY nombre").fetchall()
    motivos = conn.execute("SELECT * FROM motivos_sancion ORDER BY nombre").fetchall()
    conn.close()

    return render_template(
        "sanciones.html", dashboard=dashboard, max_total=max_total,
        dashboard_motivo=dashboard_motivo, max_total_motivo=max_total_motivo,
        sanciones=lista, departamentos=departamentos_lista, tipo=tipo, departamento_id=departamento_id,
        tipos=tipos, motivos=motivos,
    )


@app.route("/empleados/sanciones/nueva", methods=["GET", "POST"])
@requiere_item("item_sanciones")
def sanciones_nueva():
    conn = get_db()
    if request.method == "POST":
        empleado_id = request.form.get("empleado_id", type=int)
        tipo_id = request.form.get("tipo_id", type=int)
        motivo_id = request.form.get("motivo_id", type=int)
        dias_suspension = request.form.get("dias_suspension", "").strip() or None
        fecha_desde = request.form.get("fecha_desde", "").strip() or None

        empleado = conn.execute("SELECT nombre FROM empleados WHERE id = ?", (empleado_id,)).fetchone()
        tipo_row = conn.execute("SELECT nombre FROM tipos_sancion WHERE id = ?", (tipo_id,)).fetchone()
        motivo_row = conn.execute("SELECT nombre FROM motivos_sancion WHERE id = ?", (motivo_id,)).fetchone() if motivo_id else None

        if not (empleado and tipo_row):
            flash("Elegí un empleado y un tipo de sanción válidos.", "error")
        else:
            conn.execute(
                """INSERT INTO sanciones
                   (empleado_id, nombre_original, tipo, tipo_id, motivo, motivo_id,
                    dias_suspension, fecha_desde, fecha_registro)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
                (empleado_id, empleado["nombre"], tipo_row["nombre"], tipo_id,
                 motivo_row["nombre"] if motivo_row else None, motivo_id,
                 dias_suspension, fecha_desde),
            )
            conn.commit()
            conn.close()
            flash(f"Sanción cargada para {empleado['nombre']}.", "info")
            return redirect(url_for("sanciones"))

    empleados_lista = conn.execute("SELECT id, nombre, legajo FROM empleados WHERE activo = 1 ORDER BY nombre").fetchall()
    tipos = conn.execute("SELECT * FROM tipos_sancion WHERE activo = 1 ORDER BY nombre").fetchall()
    motivos = conn.execute("SELECT * FROM motivos_sancion WHERE activo = 1 ORDER BY nombre").fetchall()
    conn.close()
    return render_template("sancion_nueva.html", empleados=empleados_lista, tipos=tipos, motivos=motivos)


@app.route("/empleados/sanciones/tipos/nuevo", methods=["POST"])
@requiere_item("item_sanciones")
def tipos_sancion_nuevo():
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO tipos_sancion (nombre) VALUES (?)", (nombre,))
        conn.commit()
        conn.close()
        flash(f"Tipo '{nombre}' creado.", "info")
    return redirect(url_for("sanciones"))


@app.route("/empleados/sanciones/tipos/<int:tid>/editar", methods=["POST"])
@requiere_item("item_sanciones")
def tipos_sancion_editar(tid):
    nombre = request.form.get("nombre", "").strip()
    activo = 1 if request.form.get("activo") == "on" else 0
    conn = get_db()
    conn.execute("UPDATE tipos_sancion SET nombre = ?, activo = ? WHERE id = ?", (nombre, activo, tid))
    conn.commit()
    conn.close()
    return redirect(url_for("sanciones"))


@app.route("/empleados/sanciones/motivos/nuevo", methods=["POST"])
@requiere_item("item_sanciones")
def motivos_sancion_nuevo():
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO motivos_sancion (nombre) VALUES (?)", (nombre,))
        conn.commit()
        conn.close()
        flash(f"Motivo '{nombre}' creado.", "info")
    return redirect(url_for("sanciones"))


@app.route("/empleados/sanciones/motivos/<int:mid>/editar", methods=["POST"])
@requiere_item("item_sanciones")
def motivos_sancion_editar(mid):
    nombre = request.form.get("nombre", "").strip()
    activo = 1 if request.form.get("activo") == "on" else 0
    conn = get_db()
    conn.execute("UPDATE motivos_sancion SET nombre = ?, activo = ? WHERE id = ?", (nombre, activo, mid))
    conn.commit()
    conn.close()
    return redirect(url_for("sanciones"))


@app.route("/empleados/sanciones/importar", methods=["POST"])
@requiere_item("item_sanciones")
def sanciones_importar():
    from importar_sanciones import EXCEL_DIR, importar as importar_sanciones_fn

    candidatos_excel = sorted(EXCEL_DIR.glob("Aperc*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidatos_excel:
        flash(f"No encontré ningún archivo 'Aperc*.xls*' en {EXCEL_DIR}", "error")
        return redirect(url_for("sanciones"))
    try:
        import io
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            importar_sanciones_fn(candidatos_excel[0])
        primera_linea = buffer.getvalue().strip().splitlines()[0]
        flash(f"Importado desde {candidatos_excel[0].name}: {primera_linea}", "info")
    except Exception as e:
        flash(f"Error importando: {e}", "error")
    return redirect(url_for("sanciones"))


@app.route("/capacitaciones/importar", methods=["POST"])
@requiere_item("item_capacitaciones")
def capacitaciones_importar():
    from importar_capacitaciones import EXCEL_DIR, importar as importar_capacitaciones_fn

    candidatos_excel = sorted(EXCEL_DIR.glob("Capacitaciones*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidatos_excel:
        flash(f"No encontré ningún archivo 'Capacitaciones*.xls*' en {EXCEL_DIR}", "error")
        return redirect(url_for("capacitaciones"))
    try:
        import io
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            importar_capacitaciones_fn(candidatos_excel[0])
        primera_linea = buffer.getvalue().strip().splitlines()[0]
        flash(f"Importado desde {candidatos_excel[0].name}: {primera_linea}", "info")
    except Exception as e:
        flash(f"Error importando: {e}", "error")
    return redirect(url_for("capacitaciones"))


@app.route("/capacitaciones/importar-plan", methods=["POST"])
@requiere_item("item_capacitaciones")
def capacitaciones_importar_plan():
    from importar_plan_capacitaciones import EXCEL_DIR, importar as importar_plan_fn

    candidatos_excel = sorted(EXCEL_DIR.glob("REG-SGI*.xls*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidatos_excel:
        flash(f"No encontré ningún archivo 'REG-SGI*.xls*' en {EXCEL_DIR}", "error")
        return redirect(url_for("capacitaciones"))
    try:
        import io
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            importar_plan_fn(candidatos_excel[0])
        primera_linea = buffer.getvalue().strip().splitlines()[0]
        flash(f"Importado desde {candidatos_excel[0].name}: {primera_linea}", "info")
    except Exception as e:
        flash(f"Error importando: {e}", "error")
    return redirect(url_for("capacitaciones"))


ESTADOS_TAREA = ["Pendiente", "En curso", "Completada", "Demorada"]


def _progreso_tarea(fecha_inicio, fecha_fin, estado):
    """Devuelve (porcentaje, clase_css) de una barra de cumplimiento EN BASE AL TIEMPO
    transcurrido entre fecha_inicio y fecha_fin — no es % de trabajo hecho, es cuánto
    del plazo ya pasó. Completada = barra llena verde. Vencida (pasó fecha_fin y no
    está completada) = barra llena roja."""
    from datetime import date
    hoy = date.today()
    if estado == "Completada":
        return 100, "completada"
    if not fecha_fin:
        return 0, "sin-fecha"
    try:
        ini = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        fin = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 0, "normal"

    if hoy > fin:
        return 100, "vencida"

    total_dias = (fin - ini).days or 1
    transcurridos = (hoy - ini).days
    pct = max(0, min(100, round(transcurridos / total_dias * 100)))
    return pct, "normal"


@app.route("/cartelera")
@requiere_item("item_cartelera")
def cartelera():
    conn = get_db()
    estado_filtro = request.args.get("estado", "").strip()
    query = """
        SELECT t.*, u.nombre AS responsable_nombre
        FROM tareas_cartelera t
        LEFT JOIN usuarios u ON u.id = t.responsable_id
        WHERE 1=1
    """
    params = []
    if estado_filtro:
        query += " AND t.estado = ?"
        params.append(estado_filtro)
    query += " ORDER BY t.fecha_fin IS NULL, t.fecha_fin ASC"
    tareas = [dict(r) for r in conn.execute(query, params).fetchall()]
    for t in tareas:
        t["progreso"], t["progreso_clase"] = _progreso_tarea(t["fecha_inicio"], t["fecha_fin"], t["estado"])
    usuarios_lista = conn.execute("SELECT id, nombre FROM usuarios WHERE activo = 1 ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "cartelera.html", tareas=tareas, usuarios=usuarios_lista,
        estados_tarea=ESTADOS_TAREA, estado_filtro=estado_filtro,
    )


@app.route("/cartelera/nueva", methods=["GET", "POST"])
@requiere_item("item_cartelera")
def cartelera_nueva():
    conn = get_db()
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        responsable_id = request.form.get("responsable_id", type=int)
        fecha_inicio = request.form.get("fecha_inicio", "").strip()
        fecha_fin = request.form.get("fecha_fin", "").strip() or None

        if not (nombre and fecha_inicio):
            flash("Nombre y fecha de inicio son obligatorios.", "error")
        else:
            conn.execute(
                """INSERT INTO tareas_cartelera (nombre, responsable_id, fecha_inicio, fecha_fin)
                   VALUES (?, ?, ?, ?)""",
                (nombre, responsable_id, fecha_inicio, fecha_fin),
            )
            conn.commit()
            conn.close()
            flash(f"Tarea '{nombre}' creada.", "info")
            return redirect(url_for("cartelera"))

    usuarios_lista = conn.execute("SELECT id, nombre FROM usuarios WHERE activo = 1 ORDER BY nombre").fetchall()
    conn.close()
    return render_template("cartelera_nueva.html", usuarios=usuarios_lista)


@app.route("/cartelera/<int:tid>")
@requiere_item("item_cartelera")
def cartelera_detalle(tid):
    conn = get_db()
    tarea = conn.execute(
        """SELECT t.*, u.nombre AS responsable_nombre
           FROM tareas_cartelera t
           LEFT JOIN usuarios u ON u.id = t.responsable_id
           WHERE t.id = ?""",
        (tid,),
    ).fetchone()
    if not tarea:
        abort(404)
    tarea = dict(tarea)
    tarea["progreso"], tarea["progreso_clase"] = _progreso_tarea(tarea["fecha_inicio"], tarea["fecha_fin"], tarea["estado"])

    actividad = conn.execute(
        """SELECT a.*, u.nombre AS usuario_nombre
           FROM tareas_actividad a
           LEFT JOIN usuarios u ON u.id = a.usuario_id
           WHERE a.tarea_id = ?
           ORDER BY a.fecha DESC""",
        (tid,),
    ).fetchall()
    usuarios_lista = conn.execute("SELECT id, nombre FROM usuarios WHERE activo = 1 ORDER BY nombre").fetchall()
    conn.close()
    return render_template(
        "cartelera_detalle.html", t=tarea, actividad=actividad, usuarios=usuarios_lista,
        estados_tarea=ESTADOS_TAREA,
    )


@app.route("/cartelera/<int:tid>/actualizar", methods=["POST"])
@requiere_item("item_cartelera")
def cartelera_actualizar(tid):
    nombre = request.form.get("nombre", "").strip()
    responsable_id = request.form.get("responsable_id", type=int)
    fecha_inicio = request.form.get("fecha_inicio", "").strip()
    fecha_fin = request.form.get("fecha_fin", "").strip() or None
    estado = request.form.get("estado", "Pendiente").strip()

    conn = get_db()
    conn.execute(
        """UPDATE tareas_cartelera SET nombre=?, responsable_id=?, fecha_inicio=?, fecha_fin=?, estado=?,
           fecha_actualizacion=datetime('now','localtime') WHERE id=?""",
        (nombre, responsable_id, fecha_inicio, fecha_fin, estado, tid),
    )
    conn.commit()
    conn.close()
    flash("Tarea actualizada.", "info")
    return redirect(url_for("cartelera_detalle", tid=tid))


@app.route("/cartelera/<int:tid>/actividad", methods=["POST"])
@requiere_item("item_cartelera")
def cartelera_actividad_nueva(tid):
    comentario = request.form.get("comentario", "").strip()
    if comentario:
        u = usuario_actual()
        conn = get_db()
        conn.execute(
            "INSERT INTO tareas_actividad (tarea_id, usuario_id, comentario) VALUES (?, ?, ?)",
            (tid, u["id"] if u else None, comentario),
        )
        conn.commit()
        conn.close()
        flash("Actualización agregada.", "info")
    return redirect(url_for("cartelera_detalle", tid=tid))


@app.route("/cartelera/<int:tid>/eliminar", methods=["POST"])
@requiere_item("item_cartelera")
def cartelera_eliminar(tid):
    conn = get_db()
    conn.execute("DELETE FROM tareas_cartelera WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    flash("Tarea eliminada.", "info")
    return redirect(url_for("cartelera"))


def _nombre_disponible(carpeta: Path, nombre: str) -> Path:
    destino = carpeta / nombre
    stem, suffix = destino.stem, destino.suffix
    contador = 1
    while destino.exists():
        destino = carpeta / f"{stem}_{contador}{suffix}"
        contador += 1
    return destino


@app.route("/documentos")
@requiere_item("item_documentos")
def documentos():
    conn = get_db()
    categoria = request.args.get("categoria", "").strip()
    query = "SELECT * FROM documentos WHERE 1=1"
    params = []
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    query += " ORDER BY fecha_carga DESC"
    lista = conn.execute(query, params).fetchall()
    conn.close()
    return render_template(
        "documentos.html", documentos=lista, categorias=CATEGORIAS_DOCUMENTOS,
        categoria=categoria, voyage_ok=voyage_configurado(),
    )


@app.route("/documentos/subir", methods=["POST"])
@requiere_item("item_documentos")
def documentos_subir():
    if not voyage_configurado():
        flash("Falta configurar la API key de Voyage AI (rrhh.cfg) para poder procesar documentos.", "error")
        return redirect(url_for("documentos"))

    archivo = request.files.get("archivo")
    titulo = request.form.get("titulo", "").strip()
    categoria = request.form.get("categoria", "").strip() or None

    if not archivo or not archivo.filename:
        flash("Elegí un archivo para subir.", "error")
        return redirect(url_for("documentos"))

    from werkzeug.utils import secure_filename
    nombre_seguro = secure_filename(archivo.filename)
    extension = Path(nombre_seguro).suffix.lower()
    if extension not in FORMATOS_SOPORTADOS:
        flash(f"Formato no soportado: {extension}. Usá PDF, DOCX o TXT.", "error")
        return redirect(url_for("documentos"))

    destino = _nombre_disponible(DOCUMENTOS_DIR, nombre_seguro)
    archivo.save(str(destino))

    try:
        texto = extract_text(destino)
        if not texto.strip():
            raise ValueError("No se pudo extraer texto del archivo.")
        chunks_embebidos = embeber_documento(texto)
        if not chunks_embebidos:
            raise ValueError("El documento no generó ningún fragmento para indexar.")

        conn = get_db()
        cur = conn.execute(
            """INSERT INTO documentos (titulo, categoria, archivo_filename, archivo_path)
               VALUES (?, ?, ?, ?)""",
            (titulo or destino.stem, categoria, destino.name, str(destino)),
        )
        documento_id = cur.lastrowid
        for orden, (texto_chunk, embedding) in enumerate(chunks_embebidos):
            conn.execute(
                "INSERT INTO documento_chunks (documento_id, orden, texto, embedding) VALUES (?, ?, ?, ?)",
                (documento_id, orden, texto_chunk, embedding),
            )
        conn.commit()
        conn.close()
        flash(f"Documento '{titulo or destino.stem}' cargado e indexado ({len(chunks_embebidos)} fragmentos).", "info")
    except Exception as e:
        destino.unlink(missing_ok=True)
        flash(f"No se pudo procesar el documento: {e}", "error")

    return redirect(url_for("documentos"))


@app.route("/documentos/<int:did>/desactivar", methods=["POST"])
@requiere_item("item_documentos")
def documentos_desactivar(did):
    conn = get_db()
    activo = 1 if request.form.get("activo") == "on" else 0
    conn.execute("UPDATE documentos SET activo = ? WHERE id = ?", (activo, did))
    conn.commit()
    conn.close()
    return redirect(url_for("documentos"))


@app.route("/documentos/<int:did>/archivo")
@requiere_item("item_documentos")
def documentos_archivo(did):
    conn = get_db()
    doc = conn.execute("SELECT archivo_path FROM documentos WHERE id = ?", (did,)).fetchone()
    conn.close()
    if not doc or not Path(doc["archivo_path"]).exists():
        abort(404)
    return send_file(doc["archivo_path"])


@app.route("/documentos/preguntar", methods=["GET", "POST"])
@requiere_item("item_preguntar_documentos")
def documentos_preguntar():
    respuesta = None
    fuentes = []
    pregunta = ""
    categoria = request.values.get("categoria", "").strip()

    if request.method == "POST":
        pregunta = request.form.get("pregunta", "").strip()
        if not voyage_configurado():
            flash("Falta configurar la API key de Voyage AI (rrhh.cfg) para poder buscar en los documentos.", "error")
        elif pregunta:
            try:
                resultado = responder_pregunta(pregunta, categoria=categoria or None)
                respuesta = resultado["respuesta"]
                fuentes = resultado["fuentes"]
            except Exception as e:
                flash(f"Error al consultar: {e}", "error")

    return render_template(
        "documentos_preguntar.html", categorias=CATEGORIAS_DOCUMENTOS, categoria=categoria,
        pregunta=pregunta, respuesta=respuesta, fuentes=fuentes, voyage_ok=voyage_configurado(),
    )


def _todos_los_items():
    """Todos los cod/label/módulo de ítems del menú, para el picker de permisos."""
    items = []
    for m in MODULOS:
        for op in m["opciones"]:
            items.append({"cod": op["cod"], "label": op["label"], "modulo": m["nombre"]})
    return items


def _requiere_admin():
    u = usuario_actual()
    if not u["es_admin"]:
        flash("Solo un administrador puede entrar ahí.", "error")
        return redirect(url_for("index"))
    return None


@app.route("/admin/usuarios")
def admin_usuarios():
    redir = _requiere_admin()
    if redir:
        return redir
    conn = get_db()
    lista = conn.execute("SELECT * FROM usuarios ORDER BY nombre").fetchall()
    cant_permisos = {
        u["id"]: len(permisos_usuario(u["id"])) for u in lista
    }
    conn.close()
    return render_template(
        "admin_usuarios.html", usuarios=lista, cant_permisos=cant_permisos,
        items=_todos_los_items(), smtp_ok=smtp_configurado(),
    )


@app.route("/admin/usuarios/nuevo", methods=["POST"])
def admin_usuarios_nuevo():
    redir = _requiere_admin()
    if redir:
        return redir
    nombre = request.form.get("nombre", "").strip()
    usuario_in = request.form.get("usuario", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    es_admin = 1 if request.form.get("es_admin") == "on" else 0
    forzar_cambio = 1 if request.form.get("forzar_cambio") == "on" else 0
    if not (nombre and usuario_in and password):
        flash("Nombre, usuario y contraseña son obligatorios.", "error")
        return redirect(url_for("admin_usuarios"))

    password_hash, salt = hash_password(password)
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO usuarios (nombre, usuario, email, password_hash, salt, es_admin, debe_cambiar_password)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (nombre, usuario_in, email, password_hash, salt, es_admin, forzar_cambio),
        )
        nuevo_id = cur.lastrowid
        for item in _todos_los_items():
            if request.form.get(f"permiso_{item['cod']}") == "on":
                conn.execute(
                    "INSERT INTO usuario_permisos (usuario_id, permiso_cod) VALUES (?, ?)",
                    (nuevo_id, item["cod"]),
                )
        conn.commit()
        flash(f"Usuario '{usuario_in}' creado.", "info")
    except Exception as e:
        conn.rollback()
        flash(f"No se pudo crear el usuario: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:uid>/editar", methods=["GET", "POST"])
def admin_usuarios_editar(uid):
    redir = _requiere_admin()
    if redir:
        return redir

    if request.method == "GET":
        conn = get_db()
        usuario_row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
        if not usuario_row:
            conn.close()
            abort(404)
        permisos = permisos_usuario(uid)
        conn.close()
        return render_template(
            "admin_usuario_editar.html", u=usuario_row, items=_todos_los_items(), permisos=permisos,
        )

    nombre = request.form.get("nombre", "").strip()
    email = request.form.get("email", "").strip()
    activo = 1 if request.form.get("activo") == "on" else 0
    es_admin = 1 if request.form.get("es_admin") == "on" else 0
    forzar_cambio = 1 if request.form.get("forzar_cambio") == "on" else 0
    password_nueva = request.form.get("password", "").strip()

    conn = get_db()
    if password_nueva:
        password_hash, salt = hash_password(password_nueva)
        conn.execute(
            """UPDATE usuarios SET nombre=?, email=?, activo=?, es_admin=?, debe_cambiar_password=?,
               password_hash=?, salt=? WHERE id=?""",
            (nombre, email, activo, es_admin, forzar_cambio, password_hash, salt, uid),
        )
    else:
        conn.execute(
            "UPDATE usuarios SET nombre=?, email=?, activo=?, es_admin=?, debe_cambiar_password=? WHERE id=?",
            (nombre, email, activo, es_admin, forzar_cambio, uid),
        )

    conn.execute("DELETE FROM usuario_permisos WHERE usuario_id = ?", (uid,))
    for item in _todos_los_items():
        if request.form.get(f"permiso_{item['cod']}") == "on":
            conn.execute(
                "INSERT INTO usuario_permisos (usuario_id, permiso_cod) VALUES (?, ?)",
                (uid, item["cod"]),
            )
    conn.commit()
    conn.close()
    flash("Usuario actualizado.", "info")
    return redirect(url_for("admin_usuarios_editar", uid=uid))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("RRHH_DEBUG") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
