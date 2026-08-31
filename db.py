import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "rrhh.db"

ROLES_INICIALES = [
    ("Producción/Operarios", (
        "Operarios de producción en industria plástica, incluyendo recuperado y reciclado de plástico. "
        "Palabras clave: plásticos, polietileno, polipropileno, PVC, film, bobinas, extrusión, extrusora, impresión, "
        "bobinado, triturado, molienda, mezclado, scrap, recuperado, recuperadora, reciclado, reciclaje, plástico recuperado, "
        "material recuperado, scrap plástico, separación de materiales, clasificación, pelletizado, molino, trituradora, "
        "extrusión de recuperado, operario, maquinista, producción, operario de producción, operador de planta, "
        "operador de máquina, producción industrial, planta industrial, línea de producción, procesos productivos, "
        "control de procesos, control de calidad, abastecimiento de línea, embalaje, envasado."
    )),
    ("Mantenimiento", (
        "Mantenimiento industrial: mecánico, eléctrico y electromecánico. "
        "Palabras clave: mantenimiento preventivo, mantenimiento correctivo, mantenimiento predictivo, "
        "técnico de mantenimiento, técnico electromecánico, mecánico, electricista, electromecánico, mecatrónica, "
        "automatización, control de temperatura, variadores de frecuencia, motores, bombas, electricidad industrial, "
        "mecánica industrial, neumática, hidráulica, electrónica, PLC, tableros eléctricos, soldadura, tornería, "
        "reparación de máquinas."
    )),
    ("Logística/Depósito", (
        "Depósito, almacén, logística y manejo de materiales. "
        "Palabras clave: depósito, almacén, expedición, recepción, carga y descarga, picking, zorras eléctricas, "
        "control de stock, inventario, remitos, movimiento de materiales, abastecimiento, pedidos, Klarc, Clarck, "
        "autoelevador, conductor, chofer."
    )),
    ("Administración", "Tareas administrativas, contables, RR.HH., recepción. Palabras clave: administrativo, contable, recepción, RR.HH., liquidación de sueldos."),
    ("Ventas", "Ventas, atención a clientes, comercio exterior. Palabras clave: ventas, comercial, vendedor, atención al cliente."),
    ("Sistemas/IT", "Desarrollo, soporte técnico, infraestructura, datos. Palabras clave: programador, desarrollador, soporte IT, sistemas, redes, datos."),
    ("Otros", "No encaja claramente en ningún otro rol del catálogo."),
]

ESTADOS_INICIALES = [
    ("Nuevo", 1, 0),
    ("En banco", 2, 0),
    ("Entrevista", 3, 0),
    ("Preocupacional", 4, 0),
    ("Efectivo", 5, 1),
    ("Desechado", 6, 1),
]


def _agregar_columna_si_falta(cur, tabla, columna, definicion):
    existentes = {r[1] for r in cur.execute(f"PRAGMA table_info({tabla})").fetchall()}
    if columna not in existentes:
        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")


def _renombrar_columna_si_hace_falta(cur, tabla, actual, nuevo):
    existentes = {r[1] for r in cur.execute(f"PRAGMA table_info({tabla})").fetchall()}
    if actual in existentes and nuevo not in existentes:
        cur.execute(f"ALTER TABLE {tabla} RENAME COLUMN {actual} TO {nuevo}")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            descripcion TEXT,
            activo INTEGER NOT NULL DEFAULT 1,
            orden INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS estados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0,
            es_final INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidatos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            email TEXT,
            telefono TEXT,
            rol_id INTEGER REFERENCES roles(id),
            rol_sugerido TEXT,
            estado_id INTEGER NOT NULL REFERENCES estados(id),
            score INTEGER,
            justificacion TEXT,
            resumen TEXT,
            cv_filename TEXT NOT NULL,
            cv_path TEXT NOT NULL,
            cv_hash TEXT UNIQUE NOT NULL,
            origen TEXT NOT NULL DEFAULT 'carpeta_test',
            fecha_ingreso TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    _agregar_columna_si_falta(cur, "candidatos", "notas", "TEXT")
    _agregar_columna_si_falta(cur, "candidatos", "localidad", "TEXT")
    _agregar_columna_si_falta(cur, "candidatos", "destacado", "INTEGER NOT NULL DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS log_procesamiento (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cv_filename TEXT NOT NULL,
            cv_hash TEXT,
            resultado TEXT NOT NULL,
            detalle TEXT,
            fecha TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            usuario TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            es_admin INTEGER NOT NULL DEFAULT 0,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_creacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuario_permisos (
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            permiso_cod TEXT NOT NULL,
            PRIMARY KEY (usuario_id, permiso_cod)
        )
    """)

    _agregar_columna_si_falta(cur, "usuarios", "email", "TEXT")
    _agregar_columna_si_falta(cur, "usuarios", "debe_cambiar_password", "INTEGER NOT NULL DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            token TEXT UNIQUE NOT NULL,
            fecha_creacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            expira TEXT NOT NULL,
            usado INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS companias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS departamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS puestos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sedes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS empleados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            legajo INTEGER UNIQUE NOT NULL,
            id_externo INTEGER,
            nombre TEXT NOT NULL,
            dni TEXT,
            compania_id INTEGER REFERENCES companias(id),
            departamento_id INTEGER REFERENCES departamentos(id),
            puesto_id INTEGER REFERENCES puestos(id),
            turno TEXT,
            candidato_id INTEGER REFERENCES candidatos(id),
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_ingreso TEXT,
            fecha_creacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # id_externo en realidad es el DNI, y dni en realidad es el CUIL (Excel de nómina
    # tenía las columnas cambiadas de nombre). Se renombra en 2 pasos para no pisar.
    _renombrar_columna_si_hace_falta(cur, "empleados", "dni", "cuil")
    _renombrar_columna_si_hace_falta(cur, "empleados", "id_externo", "dni")

    _agregar_columna_si_falta(cur, "empleados", "sede_id", "INTEGER REFERENCES sedes(id)")
    _agregar_columna_si_falta(cur, "empleados", "tipo_contrato", "TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS empleado_archivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
            tipo TEXT NOT NULL,
            descripcion TEXT,
            archivo_filename TEXT NOT NULL,
            archivo_path TEXT NOT NULL,
            fecha_carga TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tareas_cartelera (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            responsable_id INTEGER REFERENCES usuarios(id),
            fecha_inicio TEXT NOT NULL,
            fecha_fin TEXT,
            estado TEXT NOT NULL DEFAULT 'Pendiente',
            fecha_creacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # fecha_fin empezó como NOT NULL; ahora Cartelera permite tareas sin fecha de fin.
    # SQLite no deja quitar un NOT NULL con ALTER, así que se recrea la tabla si hace falta.
    _col_fecha_fin = next(
        (c for c in cur.execute("PRAGMA table_info(tareas_cartelera)").fetchall() if c[1] == "fecha_fin"), None
    )
    if _col_fecha_fin and _col_fecha_fin[3] == 1:
        cur.execute("PRAGMA foreign_keys = OFF")
        # legacy_alter_table evita que SQLite "seguí" el rename y reescriba la
        # referencia FK de tareas_actividad hacia tareas_cartelera_old (que
        # después se borra, dejando esa referencia colgada de una tabla fantasma).
        cur.execute("PRAGMA legacy_alter_table = ON")
        cur.execute("ALTER TABLE tareas_cartelera RENAME TO tareas_cartelera_old")
        cur.execute("PRAGMA legacy_alter_table = OFF")
        cur.execute("""
            CREATE TABLE tareas_cartelera (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                responsable_id INTEGER REFERENCES usuarios(id),
                fecha_inicio TEXT NOT NULL,
                fecha_fin TEXT,
                estado TEXT NOT NULL DEFAULT 'Pendiente',
                fecha_creacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        cur.execute("""
            INSERT INTO tareas_cartelera (id, nombre, responsable_id, fecha_inicio, fecha_fin, estado, fecha_creacion, fecha_actualizacion)
            SELECT id, nombre, responsable_id, fecha_inicio, fecha_fin, estado, fecha_creacion, fecha_actualizacion FROM tareas_cartelera_old
        """)
        cur.execute("DROP TABLE tareas_cartelera_old")
        cur.execute("PRAGMA foreign_keys = ON")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tareas_actividad (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarea_id INTEGER NOT NULL REFERENCES tareas_cartelera(id) ON DELETE CASCADE,
            usuario_id INTEGER REFERENCES usuarios(id),
            comentario TEXT NOT NULL,
            fecha TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # Reparación: la migración de fecha_fin (antes de tener legacy_alter_table)
    # dejó tareas_actividad apuntando a "tareas_cartelera_old", una tabla que
    # ya no existe. Se recrea con la referencia corregida si hace falta.
    _sql_actividad = cur.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'tareas_actividad'"
    ).fetchone()
    if _sql_actividad and "tareas_cartelera_old" in _sql_actividad[0]:
        cur.execute("PRAGMA foreign_keys = OFF")
        cur.execute("ALTER TABLE tareas_actividad RENAME TO tareas_actividad_old")
        cur.execute("""
            CREATE TABLE tareas_actividad (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tarea_id INTEGER NOT NULL REFERENCES tareas_cartelera(id) ON DELETE CASCADE,
                usuario_id INTEGER REFERENCES usuarios(id),
                comentario TEXT NOT NULL,
                fecha TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        cur.execute("""
            INSERT INTO tareas_actividad (id, tarea_id, usuario_id, comentario, fecha)
            SELECT id, tarea_id, usuario_id, comentario, fecha FROM tareas_actividad_old
        """)
        cur.execute("DROP TABLE tareas_actividad_old")
        cur.execute("PRAGMA foreign_keys = ON")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tipos_sancion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS motivos_sancion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("SELECT COUNT(*) FROM tipos_sancion")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO tipos_sancion (nombre) VALUES (?)",
            [("Apercibimiento",), ("Suspensión",)],
        )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sanciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER REFERENCES empleados(id),
            nombre_original TEXT NOT NULL,
            tipo TEXT NOT NULL,
            motivo TEXT,
            dias_suspension TEXT,
            fecha_desde TEXT,
            fecha_registro TEXT NOT NULL,
            fecha_carga TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(fecha_registro, nombre_original)
        )
    """)

    _agregar_columna_si_falta(cur, "sanciones", "tipo_id", "INTEGER REFERENCES tipos_sancion(id)")
    _agregar_columna_si_falta(cur, "sanciones", "motivo_id", "INTEGER REFERENCES motivos_sancion(id)")

    # Backfill: poblar catálogos con los valores de texto ya cargados (import viejo o
    # nuevo) y linkear tipo_id/motivo_id — idempotente, no hace nada si ya está linkeado.
    for (nombre,) in cur.execute("SELECT DISTINCT tipo FROM sanciones WHERE tipo_id IS NULL AND tipo IS NOT NULL").fetchall():
        cur.execute("INSERT OR IGNORE INTO tipos_sancion (nombre) VALUES (?)", (nombre,))
    for (nombre,) in cur.execute("SELECT DISTINCT motivo FROM sanciones WHERE motivo_id IS NULL AND motivo IS NOT NULL").fetchall():
        cur.execute("INSERT OR IGNORE INTO motivos_sancion (nombre) VALUES (?)", (nombre,))
    cur.execute("""
        UPDATE sanciones SET tipo_id = (SELECT id FROM tipos_sancion WHERE nombre = sanciones.tipo)
        WHERE tipo_id IS NULL AND tipo IS NOT NULL
    """)
    cur.execute("""
        UPDATE sanciones SET motivo_id = (SELECT id FROM motivos_sancion WHERE nombre = sanciones.motivo)
        WHERE motivo_id IS NULL AND motivo IS NOT NULL
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS capacitaciones_temas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'Capacitación',
            tema_madre TEXT,
            area_dicta TEXT,
            planta TEXT,
            modalidad TEXT,
            duracion TEXT,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    _agregar_columna_si_falta(cur, "capacitaciones_temas", "tema_madre", "TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS capacitaciones_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tema_id INTEGER NOT NULL REFERENCES capacitaciones_temas(id) ON DELETE CASCADE,
            anio INTEGER NOT NULL,
            meses TEXT,
            observaciones TEXT,
            UNIQUE(tema_id, anio)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS capacitaciones_registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tema_id INTEGER NOT NULL REFERENCES capacitaciones_temas(id) ON DELETE CASCADE,
            empleado_id INTEGER REFERENCES empleados(id),
            nombre_original TEXT NOT NULL,
            fecha TEXT NOT NULL,
            puntuacion REAL,
            observaciones TEXT,
            fecha_carga TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(tema_id, nombre_original, fecha)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS syh_estudios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sede TEXT NOT NULL,
            categoria TEXT,
            nombre TEXT NOT NULL,
            frecuencia TEXT,
            comentario TEXT,
            ultima_fecha_realizado TEXT,
            proximo_vencimiento TEXT,
            recordatorio_enviado_para TEXT,
            fecha_sync TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(sede, nombre)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS syh_estudio_archivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estudio_id INTEGER NOT NULL REFERENCES syh_estudios(id) ON DELETE CASCADE,
            tipo TEXT NOT NULL,
            descripcion TEXT,
            archivo_filename TEXT NOT NULL,
            archivo_path TEXT NOT NULL,
            fecha_carga TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            categoria TEXT,
            archivo_filename TEXT NOT NULL,
            archivo_path TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_carga TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documento_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
            orden INTEGER NOT NULL,
            texto TEXT NOT NULL,
            embedding BLOB NOT NULL
        )
    """)

    cur.execute("SELECT COUNT(*) FROM roles")
    if cur.fetchone()[0] == 0:
        for i, (nombre, descripcion) in enumerate(ROLES_INICIALES):
            cur.execute(
                "INSERT INTO roles (nombre, descripcion, orden) VALUES (?, ?, ?)",
                (nombre, descripcion, i),
            )

    cur.execute("SELECT COUNT(*) FROM estados")
    if cur.fetchone()[0] == 0:
        for nombre, orden, es_final in ESTADOS_INICIALES:
            cur.execute(
                "INSERT INTO estados (nombre, orden, es_final) VALUES (?, ?, ?)",
                (nombre, orden, es_final),
            )

    cur.execute("SELECT COUNT(*) FROM usuarios")
    if cur.fetchone()[0] == 0:
        from auth import hash_password
        password_hash, salt = hash_password("polyfilm2026")
        cur.execute(
            """INSERT INTO usuarios (nombre, usuario, password_hash, salt, es_admin, debe_cambiar_password)
               VALUES (?, ?, ?, ?, 1, 1)""",
            ("Administrador", "admin", password_hash, salt),
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB inicializada en {DB_PATH}")
