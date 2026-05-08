from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, send_file, jsonify
from flask_wtf.csrf import CSRFProtect
import os
import json
import logging
from datetime import timedelta, datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import io
import pandas as pd
import re
import secrets

from extensions import db

# Cargar variables de entorno (opcional - funciona sin .env)
load_dotenv()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Seguridad base de entorno
IS_PRODUCTION = (
    os.environ.get('FLASK_ENV', '').lower() == 'production'
    or os.environ.get('RENDER', '').lower() == 'true'
)

# SECRET_KEY: obligatoria en producción, fallback aleatorio solo local/dev
secret_key = os.environ.get('SECRET_KEY')
if IS_PRODUCTION and not secret_key:
    raise RuntimeError("Falta SECRET_KEY en entorno de producción.")
app.secret_key = secret_key or os.urandom(24).hex()

# Configuración de sesión
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = IS_PRODUCTION
# Límite de subida para evitar abusos por archivos muy grandes
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_UPLOAD_MB', '8')) * 1024 * 1024
# El token CSRF no expira por tiempo; así el formulario de login no falla si se deja la página abierta
app.config['WTF_CSRF_TIME_LIMIT'] = None

# Habilitar protección CSRF
csrf = CSRFProtect(app)

# ---------------------------------------------------------------------------
# Base de datos (Supabase / Postgres)
# DATABASE_URL se lee del entorno (.env local o variables de Render/VPS).
# ---------------------------------------------------------------------------
_db_url = os.environ.get('DATABASE_URL', '')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url or 'sqlite:///sistema_local.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}
db.init_app(app)

from sqlalchemy import update  # noqa: E402 — after app config

from models import (  # noqa: E402 — after app config
    Usuario, Perfil, ObraSocial, Estudio,
    ObraSocialHistorial, ModificacionProgramada, Instructivo,
)
from services.sync_excel import preview_precios_google_sheet, sync_precios_google_sheet  # noqa: E402
from services.supabase_storage import (  # noqa: E402
    supabase_storage_configured,
    upload_profile_image,
)
from services.perfil_assets import resolve_perfil_image, cleanup_temp_paths  # noqa: E402


def _migrate_perfil_usuario_id():
    """
    Reemplaza perfil.username (FK legado) por perfil.usuario_id -> usuario.id
    y elimina la columna username de perfil.
    Idempotente: si ya no hay columna username, no hace nada.
    """
    from sqlalchemy import inspect, text

    try:
        insp = inspect(db.engine)
        if "perfil" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("perfil")}
    except Exception as e:
        logger.debug("inspect perfil: %s", e)
        return

    if "usuario_id" in cols and "username" not in cols:
        return

    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    is_pg = "postgres" in uri.lower()

    try:
        with db.engine.begin() as conn:
            if "usuario_id" not in cols:
                try:
                    conn.execute(text("ALTER TABLE perfil ADD COLUMN usuario_id INTEGER"))
                except Exception:
                    pass

            if "username" in cols:
                if is_pg:
                    conn.execute(
                        text(
                            "UPDATE perfil AS p SET usuario_id = u.id FROM usuario AS u "
                            "WHERE p.username = u.username AND p.usuario_id IS NULL"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "UPDATE perfil SET usuario_id = (SELECT id FROM usuario "
                            "WHERE usuario.username = perfil.username) "
                            "WHERE usuario_id IS NULL"
                        )
                    )
                conn.execute(text("DELETE FROM perfil WHERE usuario_id IS NULL"))

                if is_pg:
                    conn.execute(text("ALTER TABLE perfil ALTER COLUMN usuario_id SET NOT NULL"))
                    conn.execute(
                        text("ALTER TABLE perfil DROP CONSTRAINT IF EXISTS perfil_username_fkey")
                    )
                    conn.execute(
                        text("ALTER TABLE perfil DROP CONSTRAINT IF EXISTS perfil_username_key")
                    )
                    conn.execute(text("ALTER TABLE perfil DROP COLUMN username"))
                    try:
                        conn.execute(
                            text(
                                "ALTER TABLE perfil ADD CONSTRAINT perfil_usuario_id_fkey "
                                "FOREIGN KEY (usuario_id) REFERENCES usuario(id) ON DELETE CASCADE"
                            )
                        )
                    except Exception:
                        logger.debug("FK perfil_usuario_id_fkey ya existente o omitido.")
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS ix_perfil_usuario_id "
                            "ON perfil (usuario_id)"
                        )
                    )
                else:
                    try:
                        conn.execute(text("ALTER TABLE perfil DROP COLUMN username"))
                    except Exception as ex:
                        logger.warning(
                            "SQLite: no se pudo DROP COLUMN username (versión antigua?): %s",
                            ex,
                        )
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS ix_perfil_usuario_id "
                            "ON perfil (usuario_id)"
                        )
                    )

        logger.info("Migración perfil: enlazado a usuario.id; columna username eliminada.")
    except Exception as e:
        logger.error("Migración perfil usuario_id falló: %s", e, exc_info=True)


def _migrate_usuario_codigo_registro():
    """Añade usuario.codigo_registro si la tabla existe y aún no tiene la columna."""
    from sqlalchemy import inspect, text

    try:
        insp = inspect(db.engine)
        if "usuario" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("usuario")}
        if "codigo_registro" in cols:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuario ADD COLUMN codigo_registro VARCHAR(20)"))
        logger.info("Columna usuario.codigo_registro añadida.")
    except Exception as e:
        logger.error("Migración codigo_registro falló: %s", e, exc_info=True)


def _upgrade_perfil_image_columns_to_text():
    """Postgres: ampliar logo_path/firma_path a TEXT para URLs de Storage (idempotente si ya es TEXT)."""
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if "postgres" not in uri.lower():
        return
    try:
        from sqlalchemy import text

        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE perfil ALTER COLUMN logo_path TYPE TEXT USING logo_path::text"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE perfil ALTER COLUMN firma_path TYPE TEXT USING firma_path::text"
                )
            )
        logger.info("Columnas perfil logo_path/firma_path verificadas como TEXT.")
    except Exception as e:
        logger.debug("ALTER perfil image columns (puede ser ya TEXT o SQLite): %s", e)


with app.app_context():
    db.create_all()
    _migrate_perfil_usuario_id()
    _migrate_usuario_codigo_registro()
    _upgrade_perfil_image_columns_to_text()
    logger.info("Tablas DB verificadas/creadas.")


def strip_html(text):
    """Quita etiquetas HTML y normaliza espacios. Para mostrar texto plano en tablas/resúmenes."""
    if not text:
        return ''
    s = re.sub(r'<[^>]+>', '', str(text))
    return re.sub(r'\s+', ' ', s).strip()


app.jinja_env.filters['strip_html'] = strip_html


@app.template_global()
def perfil_imagen_src(path_value):
    """URL para previsualizar logo/firma: Storage (https) o archivo en static/logos."""
    if not path_value:
        return ""
    s = str(path_value).strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    return url_for("serve_logo", filename=s)


@app.errorhandler(400)
def bad_request_csrf(e):
    """Si el 400 viene del login (CSRF expirado), redirigir con mensaje amigable."""
    if request.method == 'POST' and request.path.rstrip('/') in ('', '/login'):
        flash('El formulario expiró. Volvé a intentar iniciar sesión.', 'error')
        return redirect(url_for('login'))
    if e.description:
        return e.description, 400
    return 'Bad Request', 400


# Carpeta para logos
LOGO_FOLDER = 'static/logos'
# Configuración de Asociación Bioquímica (aparecerá en todos los PDFs)
ASOCIACION_BIOQUIMICA = {
    'logo_path': 'logo_asociacion_bioquimica.png',
    'nombre': 'Asociacion Bioquimica del Ne del Chubut',
    'direccion': 'Paraguay 37, U9100 Trelew, Chubut',
    'telefono': '02804420440'
}
# Archivo con códigos de anexo (fallback si la DB está vacía)
ANEXO_CODIGOS_FILE = 'Anexo_Codigos.txt'

def _seed_admin_users():
    """Asegura que los usuarios admin existan en la DB al arrancar."""
    admins = [
        ('Gaito', os.environ.get('ADMIN_GAITO_PASSWORD'), os.environ.get('ADMIN_GAITO_EMAIL', '')),
        ('3', os.environ.get('ADMIN_3_PASSWORD'), os.environ.get('ADMIN_3_EMAIL', '')),
        ('DanielABNECH', os.environ.get('ADMIN_DANIEL_PASSWORD'), os.environ.get('ADMIN_DANIEL_EMAIL', '')),
    ]
    for username, pw, email in admins:
        if Usuario.query.filter_by(username=username).first():
            continue
        if not pw:
            logger.warning(
                f"No se creó admin '{username}' porque falta variable de entorno de password."
            )
            continue
        if not isinstance(pw, str) or len(pw) < 8:
            logger.warning(
                f"No se creó admin '{username}': password inválida o demasiado corta."
            )
            continue
        db.session.add(Usuario(
            username=username,
            password=generate_password_hash(pw),
            email=email,
            habilitado=True
        ))
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al seed usuarios admin: {e}")


def load_users():
    """Devuelve dict {username: {password, email, habilitado, codigo_registro}} desde la DB."""
    try:
        return {
            u.username: {
                'password': u.password,
                'email': u.email or '',
                'habilitado': u.habilitado,
                'codigo_registro': (u.codigo_registro or ''),
            }
            for u in Usuario.query.all()
        }
    except Exception as e:
        logger.error(f"Error al cargar usuarios: {e}")
        return {}


def save_users(users_dict):
    """Persiste cambios de usuarios en la DB."""
    try:
        usernames_nuevos = set(users_dict.keys())
        for u in Usuario.query.all():
            if u.username not in usernames_nuevos:
                db.session.delete(u)
        for username, data in users_dict.items():
            u = Usuario.query.filter_by(username=username).first()
            if not u:
                u = Usuario(username=username)
                db.session.add(u)
            u.password = data.get('password', '')
            u.email = data.get('email', '')
            u.habilitado = bool(data.get('habilitado', True))
            if 'codigo_registro' in data:
                cr = data.get('codigo_registro')
                u.codigo_registro = (cr.strip() if cr else None) or None
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar usuarios: {e}")
        return False


REGISTER_MAX_ATTEMPTS = 15


def _nuevo_codigo_registro():
    """Genera un código de 6 dígitos único en la tabla usuario."""
    for _ in range(80):
        c = f"{secrets.randbelow(10**6):06d}"
        if not Usuario.query.filter_by(codigo_registro=c).first():
            return c
    return f"{secrets.randbelow(10**6):06d}"


def load_perfiles():
    """Devuelve dict {username: {...campos perfil}} desde la DB."""
    try:
        out = {}
        for p in Perfil.query.all():
            u = db.session.get(Usuario, p.usuario_id)
            if not u:
                continue
            out[u.username] = {
                'nombre_lab': p.nombre_lab,
                'subtitulo': p.subtitulo,
                'profesionales': p.profesionales,
                'direccion': p.direccion,
                'ciudad': p.ciudad,
                'telefono': p.telefono,
                'logo_path': p.logo_path,
                'info_bancaria': p.info_bancaria,
                'firma_texto': p.firma_texto,
                'firma_path': p.firma_path,
            }
        return out
    except Exception as e:
        logger.error(f"Error al cargar perfiles: {e}")
        return {}


def save_perfiles(perfiles_dict):
    """Persiste perfiles en la DB (upsert por username del usuario dueño)."""
    try:
        for username, data in perfiles_dict.items():
            u = Usuario.query.filter_by(username=username).first()
            if not u:
                logger.warning("save_perfiles: usuario inexistente %s", username)
                continue
            p = Perfil.query.filter_by(usuario_id=u.id).first()
            if not p:
                p = Perfil(usuario_id=u.id)
                db.session.add(p)
            for k, v in data.items():
                if k == 'username':
                    continue
                if hasattr(p, k):
                    setattr(p, k, v)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar perfiles: {e}")
        return False


def get_lab_profile(username):
    """Devuelve perfil del lab para un usuario (fallback a valores por defecto)."""
    defaults = {
        'nombre_lab': 'Laboratorio',
        'subtitulo': 'Análisis Clínicos',
        'profesionales': 'Bioquímico: - MP: -',
        'direccion': '',
        'ciudad': 'Trelew',
        'telefono': '',
        'logo_path': '',
        'info_bancaria': '',
        'firma_texto': '',
        'firma_path': '',
    }
    try:
        u = Usuario.query.filter_by(username=username).first()
        if not u:
            return defaults
        p = Perfil.query.filter_by(usuario_id=u.id).first()
        if p:
            return {
                'nombre_lab': p.nombre_lab,
                'subtitulo': p.subtitulo,
                'profesionales': p.profesionales,
                'direccion': p.direccion,
                'ciudad': p.ciudad,
                'telefono': p.telefono,
                'logo_path': p.logo_path,
                'info_bancaria': p.info_bancaria,
                'firma_texto': p.firma_texto,
                'firma_path': p.firma_path,
            }
    except Exception as e:
        logger.error(f"Error al cargar perfil de {username}: {e}")
    return defaults

def require_login(f):
    """Decorador para proteger rutas que requieren login"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Debes iniciar sesión para acceder a esta página.', 'error')
            return redirect(url_for('login'))
        
        # Verificar que el usuario siga habilitado en cada petición
        username = session.get('username')
        if username:
            users = load_users()
            if username not in users or not users[username].get('habilitado', False):
                # Usuario fue deshabilitado o eliminado, cerrar sesión
                session.clear()
                flash('Tu cuenta ha sido deshabilitada. Contacta al administrador.', 'error')
                logger.warning(f"Intento de acceso de usuario deshabilitado: {username}")
                return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    return decorated_function

# Seed de usuarios admin al arrancar (crea si no existen en DB)
with app.app_context():
    _seed_admin_users()

# Crear carpeta de logos si no existe
os.makedirs(LOGO_FOLDER, exist_ok=True)

# Ruta para servir el favicon
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static', 'images'),
        'favicon.png',
        mimetype='image/png'
    )

# Ruta para servir logos
@app.route('/static/logos/<filename>')
def serve_logo(filename):
    return send_from_directory(LOGO_FOLDER, filename)

# Ruta principal - Login
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    # Si ya está logueado, verificar que siga habilitado antes de redirigir
    if session.get('logged_in'):
        username = session.get('username')
        if username:
            users = load_users()
            # Si el usuario fue deshabilitado o eliminado, cerrar sesión
            if username not in users or not users[username].get('habilitado', False):
                session.clear()
                flash('Tu cuenta ha sido deshabilitada. Contacta al administrador.', 'error')
                logger.warning(f"Usuario deshabilitado intentó acceder: {username}")
            else:
                # Usuario sigue habilitado, redirigir según si es admin o no
                if is_gaito_admin():
                    return redirect(url_for('admin_usuarios'))
                else:
                    return redirect(url_for('presupuestos'))
        else:
            # No hay username en sesión, limpiar sesión
            session.clear()
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Por favor completa todos los campos.', 'error')
            return redirect(url_for('login'))
        
        users = load_users()
        
        if username in users:
            user = users[username]
            # Verificar si el usuario está habilitado
            if not user.get('habilitado', False):
                flash('Tu cuenta no está habilitada. Contacta al administrador.', 'error')
                return redirect(url_for('login'))
            
            # Verificar contraseña
            if check_password_hash(user.get('password', ''), password):
                session['logged_in'] = True
                session['username'] = username
                session.permanent = True
                logger.info(f"Usuario {username} inició sesión")
                flash(f'¡Bienvenido, {username}!', 'success')
                # Redirigir a admin si es admin, sino a presupuestos
                if is_gaito_admin():
                    return redirect(url_for('admin_usuarios'))
                else:
                    return redirect(url_for('presupuestos'))
            else:
                flash('Usuario o contraseña incorrectos.', 'error')
        else:
            flash('Usuario o contraseña incorrectos.', 'error')
        
        return redirect(url_for('login'))
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Activación en dos pasos: código de 6 dígitos → usuario y contraseña definitivos."""
    if session.get('logged_in'):
        flash('Ya iniciaste sesión.', 'info')
        return redirect(url_for('presupuestos'))

    if request.method == 'GET' and request.args.get('reiniciar'):
        session.pop('register_user_id', None)
        session.pop('register_codigo_ok', None)
        flash('Volvé a ingresar el código de activación.', 'info')
        return redirect(url_for('register'))

    def _render(
        step_cuenta,
        *,
        prefill_codigo='',
        prefill_username='',
        prefill_password='',
        prefill_password2='',
    ):
        return render_template(
            'register.html',
            step_cuenta=step_cuenta,
            prefill_codigo=prefill_codigo,
            prefill_username=prefill_username,
            prefill_password=prefill_password,
            prefill_password2=prefill_password2,
        )

    if request.method == 'POST':
        step = request.form.get('step', 'codigo')

        if step == 'codigo':
            fails = session.get('register_fails', 0)
            if fails >= REGISTER_MAX_ATTEMPTS:
                flash('Demasiados intentos. Probá más tarde.', 'error')
                return redirect(url_for('register'))

            raw = request.form.get('codigo', '').strip()
            digits = re.sub(r'\D', '', raw)
            if len(digits) != 6:
                session['register_fails'] = fails + 1
                flash('El código debe tener 6 dígitos.', 'error')
                return _render(False, prefill_codigo=raw)

            u = Usuario.query.filter_by(codigo_registro=digits).first()
            if not u:
                session['register_fails'] = fails + 1
                flash('Código incorrecto.', 'error')
                return _render(False, prefill_codigo=raw)
            if not u.habilitado:
                flash('Esta cuenta no está habilitada. Contactá al administrador.', 'error')
                return _render(False, prefill_codigo=raw)

            session['register_user_id'] = u.id
            session['register_codigo_ok'] = digits
            session.pop('register_fails', None)
            flash('Código correcto. Elegí tu usuario y contraseña.', 'success')
            return redirect(url_for('register'))

        if step == 'cuenta':
            uid = session.get('register_user_id')
            code_ok = session.get('register_codigo_ok')
            if not uid or not code_ok:
                flash('Empezá de nuevo ingresando el código.', 'error')
                return redirect(url_for('register'))

            u_row = db.session.get(Usuario, uid)
            if not u_row or u_row.codigo_registro != code_ok:
                session.pop('register_user_id', None)
                session.pop('register_codigo_ok', None)
                flash('La sesión de registro expiró o el código ya fue usado. Pedí uno nuevo.', 'error')
                return redirect(url_for('register'))

            new_user = request.form.get('username', '').strip()
            pw1 = request.form.get('password', '')
            pw2 = request.form.get('password2', '')

            def _cuenta_again(msg):
                flash(msg, 'error')
                return _render(
                    True,
                    prefill_username=new_user,
                    prefill_password=pw1,
                    prefill_password2=pw2,
                )

            if len(new_user) < 2 or len(new_user) > 80:
                return _cuenta_again('El usuario debe tener entre 2 y 80 caracteres.')

            if not re.match(r'^[\w.-]+$', new_user, re.UNICODE):
                return _cuenta_again(
                    'Usuario: solo letras, números, guiones bajos, puntos o guiones (sin espacios).'
                )

            existing = Usuario.query.filter_by(username=new_user).first()
            if existing and existing.id != uid:
                return _cuenta_again('Ese nombre de usuario ya existe.')

            if len(pw1) < 6:
                return _cuenta_again('La contraseña debe tener al menos 6 caracteres.')

            if pw1 != pw2:
                return _cuenta_again('Las contraseñas no coinciden.')

            old_username = u_row.username
            try:
                stmt = (
                    update(Usuario)
                    .where(Usuario.id == uid)
                    .values(
                        username=new_user,
                        password=generate_password_hash(pw1),
                        codigo_registro=None,
                    )
                )
                db.session.execute(stmt)
                db.session.commit()
                logger.info(
                    "Registro completado (UPDATE id=%s): %s -> %s",
                    uid,
                    old_username,
                    new_user,
                )
            except Exception as e:
                db.session.rollback()
                logger.error("Error al completar registro: %s", e)
                flash('Error al guardar. Probá de nuevo.', 'error')
                return _render(
                    True,
                    prefill_username=new_user,
                    prefill_password=pw1,
                    prefill_password2=pw2,
                )

            session.pop('register_user_id', None)
            session.pop('register_codigo_ok', None)
            session['logged_in'] = True
            session['username'] = new_user
            session.permanent = True
            flash(f'¡Listo, {new_user}! Ya podés usar la calculadora.', 'success')
            return redirect(url_for('presupuestos'))

    show_cuenta = bool(session.get('register_user_id') and session.get('register_codigo_ok'))
    if show_cuenta:
        u_chk = db.session.get(Usuario, session['register_user_id'])
        if not u_chk or u_chk.codigo_registro != session.get('register_codigo_ok'):
            session.pop('register_user_id', None)
            session.pop('register_codigo_ok', None)
            show_cuenta = False

    return _render(show_cuenta)


# Ruta para logout
@app.route('/logout')
def logout():
    username = session.get('username', 'Usuario')
    session.clear()
    logger.info(f"Usuario {username} cerró sesión")
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('login'))

# Ruta para la calculadora de presupuestos (protegida)
@app.route('/presupuestos', methods=['GET', 'POST'])
@require_login
def presupuestos():
    if request.method == 'POST':
        estudios_json = request.form.get('estudios_json')
        if estudios_json:
            try:
                estudios_list = json.loads(estudios_json)
                flash(f'Se recibieron {len(estudios_list)} estudios en el presupuesto.', 'success')
                logger.info(f"Presupuesto creado con {len(estudios_list)} estudios")
            except json.JSONDecodeError as e:
                logger.error(f"Error al decodificar JSON de estudios: {e}")
                flash('Error al procesar los estudios enviados.', 'error')
            except Exception as e:
                logger.error(f"Error inesperado en presupuestos POST: {e}")
                flash('Error inesperado al procesar el presupuesto.', 'error')
        return redirect(url_for('presupuestos'))

    aplicar_modificaciones_programadas()

    # Cargar obras sociales desde la DB
    obras = {}
    obras_estado = {}
    try:
        for o in ObraSocial.query.order_by(ObraSocial.nombre).all():
            p = precio_str_a_float(o.precio) if o.precio else None
            obras[o.nombre] = str(p) if p is not None else (o.precio or '0')
            obras_estado[o.nombre] = o.estado or 'vigente'
    except Exception as e:
        logger.error(f"Error al cargar obras desde DB: {e}")

    # Cargar estudios desde la DB; fallback a TXT si tabla vacía (antes de migración)
    estudios = {}
    def _codigo_sort_key(c):
        s = (c or '').strip()
        try:
            return (0, int(s))
        except Exception:
            return (1, s.lower())
    try:
        count = Estudio.query.count()
        if count > 0:
            # Orden estético: por código (numérico si aplica)
            rows = Estudio.query.all()
            rows = sorted(rows, key=lambda r: _codigo_sort_key(r.codigo))
            for e in rows:
                estudios[e.codigo] = {'nombre': e.nombre, 'ub': e.ub}
        else:
            raise ValueError("Tabla estudio vacía, usando TXT como fallback")
    except Exception as e:
        logger.warning(f"Cargando estudios desde TXT (fallback): {e}")
        try:
            with open('CODIGO_ESTUDIO_UB.txt', 'r', encoding='utf-8') as f:
                for line in f:
                    if ':' in line:
                        parts = line.strip().split(':', 2)
                        if len(parts) == 3:
                            codigo, nombre_e, ub = parts
                            estudios[codigo] = {'nombre': nombre_e, 'ub': ub.replace(',', '.')}
        except Exception as e2:
            logger.error(f"Error al leer CODIGO_ESTUDIO_UB.txt: {e2}")
        try:
            with open(ANEXO_CODIGOS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if ':' in line:
                        parts = line.strip().split(':', 2)
                        if len(parts) == 3:
                            codigo, nombre_e, ub = parts
                            if codigo not in estudios:
                                estudios[codigo] = {'nombre': nombre_e, 'ub': ub.replace(',', '.')}
        except FileNotFoundError:
            pass

    # Asegurar orden por código también en fallback TXT
    estudios = dict(sorted(estudios.items(), key=lambda kv: _codigo_sort_key(kv[0])))

    # Configuración de anexo
    anexo_config = load_anexo_config()
    codigos_anexo = load_anexo_codigos()
    precio_particular = get_precio_particular()
    codigos_anexo_list = list(codigos_anexo)

    return render_template('presupuestos.html', 
                         obras=obras, 
                         obras_estado=obras_estado, 
                         estudios=estudios, 
                         username=session.get('username'),
                         obras_sin_cobertura_anexo=anexo_config.get('obras_sin_cobertura', []),
                         codigos_anexo=codigos_anexo_list,
                         precio_particular=precio_particular)

def normalizar_precio_argentino(precio_str):
    """
    Normaliza un precio a formato argentino (punto para miles, coma para decimales).
    Maneja formatos: inglés (1335.60), argentino (1.335,60), o sin formato (1335).
    Acepta también números que vienen de Excel (int/float).
    """
    if precio_str is None or (isinstance(precio_str, str) and (precio_str.strip() == '' or precio_str.strip().lower() == 'nan')):
        return None
    # Si viene como número de pandas/Excel, convertir a string de forma consistente
    if isinstance(precio_str, (int, float)):
        if precio_str != precio_str:  # NaN
            return None
        precio_str = str(int(precio_str)) if isinstance(precio_str, float) and precio_str == int(precio_str) else str(precio_str)
    
    # Limpiar espacios y símbolos de moneda
    precio_limpio = str(precio_str).strip().replace(' ', '').replace('$', '').replace('€', '')
    
    # Si está vacío después de limpiar, retornar None
    if not precio_limpio:
        return None
    
    # Intentar convertir a float primero para normalizar
    try:
        # Si tiene coma, puede ser formato argentino o inglés con coma como separador de miles
        if ',' in precio_limpio and '.' in precio_limpio:
            # Tiene ambos: determinar cuál es decimal
            # Si hay más dígitos después de la coma que del punto, la coma es decimal (formato argentino)
            partes_coma = precio_limpio.split(',')
            partes_punto = precio_limpio.split('.')
            if len(partes_coma[-1]) <= 2 and len(partes_punto[-1]) > 2:
                # Formato argentino: 1.335,60
                return precio_limpio
            elif len(partes_punto[-1]) <= 2 and len(partes_coma[-1]) > 2:
                # Formato inglés con coma como miles: 1,335.60 -> convertir a 1.335,60
                precio_limpio = precio_limpio.replace(',', 'X').replace('.', ',').replace('X', '.')
                return precio_limpio
            else:
                # Ambos podrían ser válidos, asumir formato argentino si la coma tiene 2 dígitos después
                if len(partes_coma[-1]) == 2:
                    return precio_limpio
                else:
                    # Convertir formato inglés a argentino
                    precio_limpio = precio_limpio.replace(',', 'X').replace('.', ',').replace('X', '.')
                    return precio_limpio
        elif ',' in precio_limpio:
            # Solo tiene coma
            partes = precio_limpio.split(',')
            if len(partes[-1]) <= 2:
                # Coma es decimal (formato argentino sin puntos de miles)
                return precio_limpio
            else:
                # Coma es separador de miles (formato inglés), convertir
                precio_limpio = precio_limpio.replace(',', '.')
                # Ahora tiene punto, procesar como formato inglés
        elif '.' in precio_limpio:
            # Solo tiene punto
            partes = precio_limpio.split('.')
            if len(partes[-1]) <= 2:
                # Punto es decimal (formato inglés), convertir a argentino
                precio_limpio = precio_limpio.replace('.', ',')
                return precio_limpio
            else:
                # Punto es separador de miles (formato argentino sin decimales)
                # Agregar decimales
                return precio_limpio + ',00'
        
        # No tiene ni punto ni coma, es un número entero
        # Convertir a float y luego a formato argentino
        precio_float = float(precio_limpio)
        # Formatear con 2 decimales en formato argentino
        precio_formateado = f"{precio_float:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return precio_formateado
        
    except (ValueError, AttributeError):
        # Si no se puede convertir, intentar procesar como string
        # Validar que solo tenga números, puntos y comas
        if not re.match(r'^[\d.,]+$', precio_limpio):
            return None
        
        # Si tiene punto y no tiene coma, el punto probablemente es decimal (formato inglés)
        if '.' in precio_limpio and ',' not in precio_limpio:
            precio_limpio = precio_limpio.replace('.', ',')
            return precio_limpio
        
        # Si tiene coma y no tiene punto, mantener (formato argentino)
        if ',' in precio_limpio and '.' not in precio_limpio:
            return precio_limpio
        
        # Si no tiene ni punto ni coma, agregar decimales
        if '.' not in precio_limpio and ',' not in precio_limpio:
            return precio_limpio + ',00'
        
        return precio_limpio

def normalizar_nombre_obra(nombre):
    """Normaliza nombre de obra: strip y un solo espacio entre palabras (para que coincida Excel vs archivo)."""
    if nombre is None:
        return None
    return re.sub(r'\s+', ' ', str(nombre).strip()) if str(nombre).strip() else None

def load_current_obras():
    """Devuelve {nombre_normalizado: precio} desde la DB (obras con precio válido)."""
    obras = {}
    try:
        for o in ObraSocial.query.all():
            if es_precio_real(o.precio):
                key = normalizar_nombre_obra(o.nombre)
                if key:
                    obras[key] = o.precio
    except Exception as e:
        logger.error(f"Error al cargar obras actuales desde DB: {e}")
    return obras

def precio_str_a_float(precio_str):
    """
    Convierte precio (formato argentino o US) a float.
    Formato argentino: "1.253,28" o "1253,28" (punto=miles, coma=decimal).
    IMPORTANTE: si tiene coma, primero quitar puntos, luego coma->punto.
    Orden inverso convertiría "1.253,28" en 125328 en vez de 1253.28.
    """
    if precio_str is None or precio_str == '':
        return None
    s = str(precio_str).strip().replace(' ', '').replace('$', '').replace('€', '')
    if not s or s.lower() == 'nan':
        return None
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        val = float(s)
        return val
    except (ValueError, TypeError):
        return None

def es_precio_real(precio):
    """Devuelve True si el precio es un número mayor que 0 (no None, 0, '-', vacío)."""
    if precio is None:
        return False
    try:
        s = str(precio).strip().replace(' ', '').replace('.', '').replace(',', '.')
        if not s:
            return False
        return float(s) > 0
    except (ValueError, TypeError):
        return False


def comparar_precios(precio_actual, precio_nuevo):
    """
    Compara dos precios en formato argentino.
    Retorna True si son diferentes, False si son iguales.
    """
    try:
        # Convertir ambos precios a float para comparar
        def precio_a_float(precio_str):
            if not precio_str:
                return None
            # Remover espacios y convertir formato argentino a float
            precio_limpio = str(precio_str).strip().replace(' ', '').replace('.', '').replace(',', '.')
            return float(precio_limpio)
        
        precio_actual_float = precio_a_float(precio_actual)
        precio_nuevo_float = precio_a_float(precio_nuevo)
        
        if precio_actual_float is None or precio_nuevo_float is None:
            return True  # Si alguno es None, consideramos que hay cambio
        
        # Comparar con tolerancia de 0.01 para evitar problemas de precisión
        return abs(precio_actual_float - precio_nuevo_float) > 0.01
    except Exception as e:
        logger.warning(f"Error al comparar precios: {e}")
        return True  # En caso de error, asumimos que hay cambio

def is_gaito_admin():
    """Verifica si el usuario actual es admin (Gaito, usuario 3 o DanielABNECH)"""
    username = session.get('username')
    return username in ('Gaito', '3', 'DanielABNECH')

def load_obras_estado():
    """Devuelve estructura de obras compatible con el código existente."""
    try:
        obras_db = ObraSocial.query.all()
        obras_dict = {
            o.nombre: {
                'precio': o.precio or '',
                'estado': o.estado or 'vigente',
                'ultima_actualizacion': o.ultima_actualizacion or '',
            }
            for o in obras_db
        }
        vigentes = sum(1 for o in obras_db if o.estado == 'vigente')
        sin_conv = sum(1 for o in obras_db if o.estado == 'sin_convenio')
        suspendidas = sum(1 for o in obras_db if o.estado == 'suspendida')
        return {
            'fecha_actualizacion': datetime.now().isoformat(),
            'total_obras': len(obras_db),
            'obras_vigentes': vigentes,
            'obras_sin_convenio': sin_conv,
            'obras_suspendidas': suspendidas,
            'obras': obras_dict,
        }
    except Exception as e:
        logger.error(f"Error al cargar estado de obras: {e}")
        return {
            'fecha_actualizacion': None,
            'total_obras': 0,
            'obras_vigentes': 0,
            'obras_sin_convenio': 0,
            'obras_suspendidas': 0,
            'obras': {},
        }

def load_obras_list_para_vista():
    """Lista de obras para Aranceles y Gestión de obras desde la DB."""
    try:
        obras_db = ObraSocial.query.order_by(ObraSocial.nombre).all()
        obras_list = [
            {
                'nombre': o.nombre,
                'precio': o.precio or '',
                'estado': o.estado or 'vigente',
                'ultima_actualizacion': o.ultima_actualizacion or '',
                'no_cubre_anexo': not o.cubre_anexo,
            }
            for o in obras_db
        ]
        vigentes = sum(1 for o in obras_db if o.estado == 'vigente')
        sin_conv = sum(1 for o in obras_db if o.estado == 'sin_convenio')
        suspendidas = sum(1 for o in obras_db if o.estado == 'suspendida')
        estado_data = {
            'fecha_actualizacion': datetime.now().isoformat(),
            'total_obras': len(obras_db),
            'obras_vigentes': vigentes,
            'obras_sin_convenio': sin_conv,
            'obras_suspendidas': suspendidas,
            'obras': {o['nombre']: o for o in obras_list},
        }
        return obras_list, estado_data
    except Exception as e:
        logger.error(f"Error al cargar lista de obras: {e}")
        return [], {}


def _regenerar_obras_entero(obras_estado_dict):
    """Ya no escribe a disco; la DB es la única fuente de verdad."""
    pass

def save_obra_individual(nombre_obra, precio, estado):
    """Actualiza una obra en la DB. Devuelve (True, None) o (False, mensaje)."""
    if estado not in ('vigente', 'sin_convenio', 'suspendida'):
        return False, "Estado inválido."
    try:
        obra = ObraSocial.query.filter_by(nombre=nombre_obra).first()
        if not obra:
            return False, "Obra no encontrada."
        precio_anterior = obra.precio
        estado_anterior = obra.estado or 'vigente'
        precio_str = None
        if precio is not None and str(precio).strip() != '':
            p = precio_str_a_float(precio)
            precio_str = str(p).replace('.', ',') if p is not None else str(precio).strip()
        precio_nuevo = precio_str or obra.precio
        obra.precio = precio_nuevo
        obra.estado = estado
        obra.ultima_actualizacion = datetime.now().isoformat()

        # Historial para cambios manuales/lote (no solo sync)
        precio_cambio = comparar_precios(precio_anterior, precio_nuevo)
        estado_cambio = estado_anterior != (estado or 'vigente')
        if precio_cambio or estado_cambio:
            ahora = datetime.now(ZoneInfo('America/Argentina/Buenos_Aires')).replace(tzinfo=None)
            db.session.add(ObraSocialHistorial(
                obra_nombre=nombre_obra,
                fecha=ahora,
                precio_anterior=precio_anterior,
                precio_nuevo=precio_nuevo,
                estado_anterior=estado_anterior,
                estado_nuevo=estado,
            ))
        db.session.commit()
        return True, None
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar obra individual: {e}")
        return False, str(e)

def load_modificaciones_programadas():
    """Carga modificaciones programadas desde la DB."""
    try:
        return [
            {
                'nombre_obra': m.nombre_obra,
                'fecha_aplicar': m.fecha_aplicar,
                'precio': m.precio,
                'estado': m.estado,
                'no_cubre_anexo': m.no_cubre_anexo,
            }
            for m in ModificacionProgramada.query.order_by(ModificacionProgramada.fecha_aplicar).all()
        ]
    except Exception as e:
        logger.error(f"Error al cargar modificaciones programadas: {e}")
        return []


def save_modificaciones_programadas(lista):
    """Reemplaza todas las modificaciones en la DB con la lista nueva."""
    try:
        ModificacionProgramada.query.delete()
        for item in lista:
            db.session.add(ModificacionProgramada(
                nombre_obra=item.get('nombre_obra', ''),
                fecha_aplicar=item.get('fecha_aplicar', ''),
                precio=item.get('precio'),
                estado=item.get('estado'),
                no_cubre_anexo=bool(item.get('no_cubre_anexo', False)),
            ))
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar modificaciones programadas: {e}")
        return False

def aplicar_modificaciones_programadas():
    """
    Aplica las modificaciones programadas cuya fecha_aplicar <= hoy.
    Actualiza obras_estado, obras_entero y anexo_config según cada ítem y elimina los aplicados.
    """
    hoy = datetime.now().date()
    lista = load_modificaciones_programadas()
    pendientes = []
    aplicadas = 0
    for item in lista:
        fecha_str = item.get('fecha_aplicar')
        if not fecha_str:
            pendientes.append(item)
            continue
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            pendientes.append(item)
            continue
        if fecha > hoy:
            pendientes.append(item)
            continue
        nombre = item.get('nombre_obra', '').strip()
        if not nombre:
            continue
        estado_data = load_obras_estado()
        if nombre not in estado_data.get('obras', {}):
            continue
        precio = item.get('precio')
        estado = item.get('estado') or estado_data['obras'][nombre].get('estado', 'vigente')
        if estado not in ('vigente', 'sin_convenio', 'suspendida'):
            estado = 'vigente'
        ok, _ = save_obra_individual(nombre, precio, estado)
        if not ok:
            pendientes.append(item)
            continue
        no_cubre = item.get('no_cubre_anexo')
        if no_cubre is not None:
            anexo_config = load_anexo_config()
            obras_sin = anexo_config.get('obras_sin_cobertura', [])
            if no_cubre and nombre not in obras_sin:
                obras_sin.append(nombre)
                anexo_config['obras_sin_cobertura'] = obras_sin
                save_anexo_config(anexo_config)
            elif not no_cubre and nombre in obras_sin:
                obras_sin = [o for o in obras_sin if o != nombre]
                anexo_config['obras_sin_cobertura'] = obras_sin
                save_anexo_config(anexo_config)
        aplicadas += 1
    if aplicadas > 0:
        save_modificaciones_programadas(pendientes)
        logger.info(f"Se aplicaron {aplicadas} modificaciones programadas.")

def load_anexo_config():
    """Devuelve dict con lista de obras que NO cubren anexo (cubre_anexo=False en DB)."""
    try:
        obras_sin = ObraSocial.query.filter_by(cubre_anexo=False).all()
        return {'obras_sin_cobertura': [o.nombre for o in obras_sin]}
    except Exception as e:
        logger.error(f"Error al cargar configuración de anexo: {e}")
        return {'obras_sin_cobertura': []}


def save_anexo_config(config):
    """Actualiza cubre_anexo en la DB según la lista obras_sin_cobertura."""
    try:
        sin_cobertura = set(config.get('obras_sin_cobertura', []))
        for obra in ObraSocial.query.all():
            obra.cubre_anexo = obra.nombre not in sin_cobertura
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar configuración de anexo: {e}")
        return False


def load_anexo_codigos():
    """Devuelve set de códigos de estudios con es_anexo=True desde la DB.
    Fallback al archivo TXT si la tabla estudio está vacía (antes de la migración)."""
    try:
        count = Estudio.query.filter_by(es_anexo=True).count()
        if count > 0:
            return {e.codigo for e in Estudio.query.filter_by(es_anexo=True).all()}
    except Exception as e:
        logger.warning(f"Error al cargar códigos de anexo desde DB, usando TXT: {e}")
    # Fallback: leer del archivo TXT original
    codigos_anexo = set()
    try:
        if os.path.exists(ANEXO_CODIGOS_FILE):
            with open(ANEXO_CODIGOS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if ':' in line:
                        parts = line.strip().split(':', 1)
                        codigo = parts[0].strip()
                        if codigo:
                            codigos_anexo.add(codigo)
        logger.info(f"Cargados {len(codigos_anexo)} códigos de anexo desde TXT (fallback)")
    except Exception as e:
        logger.error(f"Error al cargar códigos de anexo desde TXT: {e}")
    return codigos_anexo


def get_precio_particular():
    """Obtiene el NBU de PARTICULAR desde la DB."""
    try:
        obra = ObraSocial.query.filter_by(nombre='PARTICULAR').first()
        if obra and obra.precio:
            precio = precio_str_a_float(obra.precio)
            if precio is not None:
                return precio
    except Exception as e:
        logger.warning(f"Error al obtener precio de Particular desde DB: {e}")
    return 3000.0

# Ruta admin para gestionar usuarios (solo para Gaito)
@app.route('/admin/usuarios', methods=['GET', 'POST'])
@require_login
def admin_usuarios():
    # Solo Gaito puede acceder a esta ruta
    if not is_gaito_admin():
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('presupuestos'))
    aplicar_modificaciones_programadas()
    users = load_users()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'agregar':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            
            if not username or not password:
                flash('Usuario y contraseña son obligatorios.', 'error')
                return redirect(url_for('admin_usuarios'))
            
            if username in users:
                flash('El usuario ya existe.', 'error')
                return redirect(url_for('admin_usuarios'))
            
            codigo = _nuevo_codigo_registro()
            users[username] = {
                'password': generate_password_hash(password),
                'habilitado': True,
                'email': '',
                'codigo_registro': codigo,
            }

            if save_users(users):
                flash(
                    f'Usuario {username} agregado. Código de activación (un solo uso): {codigo}. '
                    f'Compartilo para que active en /register.',
                    'success',
                )
                logger.info(f"Usuario {username} agregado por {session.get('username')} (código registro generado)")
            else:
                flash('Error al guardar el usuario.', 'error')
        
        elif action == 'habilitar':
            username = request.form.get('username', '').strip()
            if username in users:
                users[username]['habilitado'] = True
                if save_users(users):
                    flash(f'Usuario {username} habilitado.', 'success')
                else:
                    flash('Error al guardar los cambios.', 'error')
        
        elif action == 'deshabilitar':
            username = request.form.get('username', '').strip()
            if username in users:
                # No permitir deshabilitar a Gaito ni al usuario 3 (admins)
                if username in ('Gaito', '3', 'DanielABNECH'):
                    flash('No puedes deshabilitar la cuenta de administrador.', 'error')
                else:
                    users[username]['habilitado'] = False
                    if save_users(users):
                        flash(f'Usuario {username} deshabilitado.', 'success')
                    else:
                        flash('Error al guardar los cambios.', 'error')
        
        elif action == 'eliminar':
            username = request.form.get('username', '').strip()
            if username in users:
                if username == session.get('username'):
                    flash('No puedes eliminar tu propia cuenta.', 'error')
                elif username in ('Gaito', '3', 'DanielABNECH'):
                    flash('No puedes eliminar la cuenta de administrador.', 'error')
                else:
                    del users[username]
                    if save_users(users):
                        flash(f'Usuario {username} eliminado.', 'success')
                    else:
                        flash('Error al guardar los cambios.', 'error')
        
        return redirect(url_for('admin_usuarios'))
    
    # Cargar configuración de anexo y obras sociales para el panel
    anexo_config = load_anexo_config()
    estado_data = load_obras_estado()
    todas_las_obras = []
    
    # Obtener todas las obras sociales (vigentes, sin convenio, suspendidas)
    if estado_data and 'obras' in estado_data:
        todas_las_obras = sorted(estado_data['obras'].keys())
    
    # Obtener precio de Particular para mostrar en el template
    precio_particular = get_precio_particular()
    
    modificaciones_programadas = load_modificaciones_programadas()
    return render_template('admin_usuarios.html', 
                         users=users, 
                         current_user=session.get('username'),
                         obras_sin_cobertura_anexo=anexo_config.get('obras_sin_cobertura', []),
                         todas_las_obras=todas_las_obras,
                         precio_particular=precio_particular,
                         modificaciones_programadas=modificaciones_programadas)


# Ruta para obtener preview de precios antes de sincronizar (solo para Gaito)
@app.route('/admin/sync_precios/preview', methods=['GET'])
@require_login
def admin_sync_precios_preview():
    # Solo Gaito puede acceder a esta ruta
    if not is_gaito_admin():
        return jsonify({'success': False, 'message': 'No tienes permiso para acceder a esta sección.'}), 403
    
    success, message, cambios_dict, count = preview_precios_google_sheet()
    
    if success:
        # Convertir a lista para JSON (mostrar todos los cambios, o máximo 50)
        cambios_list = []
        for nombre, datos in list(cambios_dict.items())[:50]:
            cambios_list.append({
                'nombre': nombre,
                'precio_actual': datos.get('precio_actual', 'N/A'),
                'precio_nuevo': datos.get('precio_nuevo', 'N/A'),
                'cambio': datos.get('cambio', 'modificado')
            })
        
        return jsonify({
            'success': True,
            'message': message,
            'count': count,
            'cambios': cambios_list,
            'total_cambios': count
        })
    else:
        return jsonify({
            'success': False,
            'message': message
        })

# Ruta para sincronizar precios desde Google Sheet (solo para Gaito)
@app.route('/admin/sync_precios', methods=['POST'])
@require_login
def admin_sync_precios():
    # Solo Gaito puede acceder a esta ruta
    if not is_gaito_admin():
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('presupuestos'))
    
    success, message, count = sync_precios_google_sheet()
    
    if success:
        flash(message, 'success')
        logger.info(f"Precios sincronizados por {session.get('username')}: {count} obras sociales")
    else:
        flash(message, 'error')
        logger.error(f"Error al sincronizar precios: {message}")
    
    return redirect(url_for('admin_obras'))

# Ruta para editar perfil de laboratorio (solo Gaito)
@app.route('/admin/perfil/<username>', methods=['GET', 'POST'])
@require_login
def admin_perfil(username):
    # Solo Gaito puede acceder a esta ruta
    if not is_gaito_admin():
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('presupuestos'))
    
    perfiles = load_perfiles()
    perfil = get_lab_profile(username)
    
    if request.method == 'POST':
        # Actualizar campos de texto
        perfil['nombre_lab'] = request.form.get('nombre_lab', '').strip()
        perfil['subtitulo'] = request.form.get('subtitulo', '').strip()
        perfil['profesionales'] = request.form.get('profesionales', '').strip()
        perfil['direccion'] = request.form.get('direccion', '').strip()
        perfil['ciudad'] = request.form.get('ciudad', '').strip()
        perfil['telefono'] = request.form.get('telefono', '').strip()
        perfil['info_bancaria'] = request.form.get('info_bancaria', '').strip()
        perfil['firma_texto'] = request.form.get('firma_texto', '').strip()
        
        # Manejar subida de logo (Supabase Storage si está configurado; si no, disco local)
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename:
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
                filename = secure_filename(file.filename)
                if '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    extension = filename.rsplit('.', 1)[1].lower()
                    raw = file.read()
                    if raw:
                        if supabase_storage_configured():
                            url, err = upload_profile_image(
                                raw, username=username, kind='logo', extension=extension
                            )
                            if url:
                                perfil['logo_path'] = url
                                logger.info("Logo subido a Storage para %s", username)
                            else:
                                flash(f'No se pudo subir el logo al bucket: {err or "error desconocido"}', 'error')
                        else:
                            os.makedirs(LOGO_FOLDER, exist_ok=True)
                            logo_filename = f'logo_{username}.{extension}'
                            logo_path = os.path.join(LOGO_FOLDER, logo_filename)
                            with open(logo_path, 'wb') as out:
                                out.write(raw)
                            perfil['logo_path'] = logo_filename
                            logger.info(f"Logo guardado en disco para usuario {username}: {logo_filename}")

        # Manejar subida de imagen de firma
        if 'firma_imagen' in request.files:
            file = request.files['firma_imagen']
            if file and file.filename:
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
                filename = secure_filename(file.filename)
                if '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    extension = filename.rsplit('.', 1)[1].lower()
                    raw = file.read()
                    if raw:
                        if supabase_storage_configured():
                            url, err = upload_profile_image(
                                raw, username=username, kind='firma', extension=extension
                            )
                            if url:
                                perfil['firma_path'] = url
                                logger.info("Firma subida a Storage para %s", username)
                            else:
                                flash(f'No se pudo subir la firma al bucket: {err or "error desconocido"}', 'error')
                        else:
                            os.makedirs(LOGO_FOLDER, exist_ok=True)
                            firma_filename = f'firma_{username}.{extension}'
                            firma_path = os.path.join(LOGO_FOLDER, firma_filename)
                            with open(firma_path, 'wb') as out:
                                out.write(raw)
                            perfil['firma_path'] = firma_filename
                            logger.info(f"Imagen de firma guardada en disco para usuario {username}: {firma_filename}")
        
        # Guardar perfil
        perfiles[username] = perfil
        if save_perfiles(perfiles):
            flash(f'Perfil de {username} actualizado correctamente.', 'success')
            logger.info(f"Perfil actualizado para usuario {username}")
        else:
            flash('Error al guardar el perfil.', 'error')
        
        return redirect(url_for('admin_perfil', username=username))
    
    return render_template('admin_perfil.html', username=username, perfil=perfil, current_user=session.get('username'))

# Ruta para agregar obra social a la lista de no cobertura de anexo (solo para Gaito)
@app.route('/admin/anexo/agregar', methods=['POST'])
@require_login
def admin_anexo_agregar():
    # Solo Gaito puede acceder a esta ruta
    if not is_gaito_admin():
        return jsonify({'success': False, 'message': 'No tienes permiso para acceder a esta sección.'}), 403
    
    obra = request.form.get('obra', '').strip()
    if not obra:
        return jsonify({'success': False, 'message': 'Nombre de obra social requerido.'}), 400
    
    anexo_config = load_anexo_config()
    obras_sin_cobertura = anexo_config.get('obras_sin_cobertura', [])
    
    if obra in obras_sin_cobertura:
        return jsonify({'success': False, 'message': 'Esta obra social ya está en la lista.'}), 400
    
    obras_sin_cobertura.append(obra)
    anexo_config['obras_sin_cobertura'] = obras_sin_cobertura
    
    if save_anexo_config(anexo_config):
        logger.info(f"Obra social '{obra}' agregada a la lista de no cobertura de anexo por {session.get('username')}")
        return jsonify({'success': True, 'message': f'Obra social "{obra}" agregada correctamente.'})
    else:
        return jsonify({'success': False, 'message': 'Error al guardar la configuración.'}), 500

# Ruta para eliminar obra social de la lista de no cobertura de anexo (solo para Gaito)
@app.route('/admin/anexo/eliminar', methods=['POST'])
@require_login
def admin_anexo_eliminar():
    # Solo Gaito puede acceder a esta ruta
    if not is_gaito_admin():
        return jsonify({'success': False, 'message': 'No tienes permiso para acceder a esta sección.'}), 403
    
    obra = request.form.get('obra', '').strip()
    if not obra:
        return jsonify({'success': False, 'message': 'Nombre de obra social requerido.'}), 400
    
    anexo_config = load_anexo_config()
    obras_sin_cobertura = anexo_config.get('obras_sin_cobertura', [])
    
    if obra not in obras_sin_cobertura:
        return jsonify({'success': False, 'message': 'Esta obra social no está en la lista.'}), 400
    
    obras_sin_cobertura.remove(obra)
    anexo_config['obras_sin_cobertura'] = obras_sin_cobertura
    
    if save_anexo_config(anexo_config):
        logger.info(f"Obra social '{obra}' eliminada de la lista de no cobertura de anexo por {session.get('username')}")
        return jsonify({'success': True, 'message': f'Obra social "{obra}" eliminada correctamente.'})
    else:
        return jsonify({'success': False, 'message': 'Error al guardar la configuración.'}), 500

# Gestión de obras: vista principal (solo admin). Precios desde obras_entero.txt (misma fuente que Aranceles).
@app.route('/admin/obras', methods=['GET'])
@require_login
def admin_obras():
    if not is_gaito_admin():
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('presupuestos'))
    aplicar_modificaciones_programadas()
    obras_list, estado_data = load_obras_list_para_vista()
    anexo_config = load_anexo_config()
    obras_sin_cobertura = anexo_config.get('obras_sin_cobertura', [])
    for item in obras_list:
        item['no_cubre_anexo'] = item['nombre'] in obras_sin_cobertura
    obras_actuales_dict = {datos['nombre']: {'precio': datos.get('precio') or '', 'estado': datos.get('estado') or 'vigente'} for datos in obras_list}
    def _estado_label(estado):
        if estado == 'vigente': return 'Vigente'
        if estado == 'sin_convenio': return 'Sin convenio'
        if estado == 'suspendida': return 'Suspendida'
        return estado or 'Vigente'
    modificaciones_programadas_raw = load_modificaciones_programadas()
    modificaciones_programadas = []
    for p in modificaciones_programadas_raw:
        pp = dict(p)
        nombre_obra = p.get('nombre_obra') or ''
        actual = obras_actuales_dict.get(nombre_obra, {})
        pp['precio_actual'] = actual.get('precio') or ''
        pp['estado_actual'] = actual.get('estado') or 'vigente'
        pp['estado_actual_label'] = _estado_label(pp['estado_actual'])
        pp['estado_nuevo_label'] = _estado_label(p.get('estado') or 'vigente')
        pp['cambia_estado'] = (p.get('estado') or 'vigente') != (pp['estado_actual'])
        fecha = p.get('fecha_aplicar') or ''
        if len(fecha) >= 10:
            try:
                d = datetime.strptime(fecha[:10], '%Y-%m-%d')
                pp['fecha_display'] = d.strftime('%d/%m/%Y')
            except ValueError:
                pp['fecha_display'] = fecha
        else:
            pp['fecha_display'] = fecha
        modificaciones_programadas.append(pp)
    return render_template('admin_obras.html',
                         obras_list=obras_list,
                         obras_sin_cobertura_anexo=obras_sin_cobertura,
                         modificaciones_programadas=modificaciones_programadas,
                         current_user=session.get('username'))

# Gestión de obras: actualizar una obra (precio, estado) o programar para fecha futura — solo admin
@app.route('/admin/obras/actualizar', methods=['POST'])
@require_login
def admin_obras_actualizar():
    if not is_gaito_admin():
        return jsonify({'success': False, 'message': 'No tienes permiso.'}), 403
    nombre = (request.form.get('nombre') or request.form.get('nombre_obra') or '').strip()
    if not nombre:
        return jsonify({'success': False, 'message': 'Nombre de obra requerido.'}), 400
    precio = request.form.get('precio')
    estado = (request.form.get('estado') or 'vigente').strip().lower()
    if estado not in ('vigente', 'sin_convenio', 'suspendida'):
        estado = 'vigente'
    fecha_aplicar = request.form.get('fecha_aplicar', '').strip()
    no_cubre_anexo = request.form.get('no_cubre_anexo') in ('1', 'true', 'on', 'yes')
    estado_data = load_obras_estado()
    if nombre not in estado_data.get('obras', {}):
        return jsonify({'success': False, 'message': 'Obra no encontrada.'}), 400
    if fecha_aplicar:
        try:
            fecha = datetime.strptime(fecha_aplicar, '%Y-%m-%d').date()
            hoy = datetime.now().date()
            if fecha > hoy:
                lista = load_modificaciones_programadas()
                lista = [p for p in lista if p.get('nombre_obra') != nombre]
                lista.append({
                    'nombre_obra': nombre,
                    'fecha_aplicar': fecha_aplicar,
                    'precio': precio,
                    'estado': estado,
                    'no_cubre_anexo': no_cubre_anexo
                })
                if save_modificaciones_programadas(lista):
                    return jsonify({'success': True, 'message': f'Modificación programada para el {fecha_aplicar}.'})
                return jsonify({'success': False, 'message': 'Error al guardar la programación.'}), 500
        except ValueError:
            pass
    ok, err = save_obra_individual(nombre, precio, estado)
    if not ok:
        return jsonify({'success': False, 'message': err or 'Error al guardar.'}), 400
    anexo_config = load_anexo_config()
    obras_sin = anexo_config.get('obras_sin_cobertura', [])
    if no_cubre_anexo and nombre not in obras_sin:
        obras_sin.append(nombre)
        anexo_config['obras_sin_cobertura'] = obras_sin
        save_anexo_config(anexo_config)
    elif not no_cubre_anexo and nombre in obras_sin:
        obras_sin = [o for o in obras_sin if o != nombre]
        anexo_config['obras_sin_cobertura'] = obras_sin
        save_anexo_config(anexo_config)
    return jsonify({'success': True, 'message': 'Obra actualizada correctamente.'})

# Aplicar muchos cambios de obras en un solo paso (inmediatos + programados)
@app.route('/admin/obras/actualizar_lote', methods=['POST'])
@require_login
def admin_obras_actualizar_lote():
    if not is_gaito_admin():
        return jsonify({'success': False, 'message': 'No tienes permiso.'}), 403
    data = request.get_json(silent=True) or {}
    cambios = data.get('cambios', [])
    if not cambios or not isinstance(cambios, list):
        return jsonify({'success': False, 'message': 'Se requiere una lista de cambios.'}), 400
    estado_data = load_obras_estado()
    obras = estado_data.get('obras', {})
    anexo_config = load_anexo_config()
    obras_sin = list(anexo_config.get('obras_sin_cobertura', []))
    programadas = load_modificaciones_programadas()
    hoy = datetime.now().date()
    errors = []
    for c in cambios:
        nombre = (c.get('nombre_obra') or c.get('nombre') or '').strip()
        if not nombre or nombre not in obras:
            errors.append(f"Obra no encontrada: {nombre or '(vacío)'}")
            continue
        precio = c.get('precio')
        estado = (c.get('estado') or 'vigente').strip().lower()
        if estado not in ('vigente', 'sin_convenio', 'suspendida'):
            estado = 'vigente'
        no_cubre_anexo = c.get('no_cubre_anexo') in (True, '1', 'true', 'on', 'yes')
        fecha_aplicar = (c.get('fecha_aplicar') or '').strip()
        if fecha_aplicar:
            try:
                fecha = datetime.strptime(fecha_aplicar, '%Y-%m-%d').date()
                if fecha > hoy:
                    programadas = [p for p in programadas if p.get('nombre_obra') != nombre]
                    programadas.append({
                        'nombre_obra': nombre,
                        'fecha_aplicar': fecha_aplicar,
                        'precio': precio,
                        'estado': estado,
                        'no_cubre_anexo': no_cubre_anexo
                    })
                    continue
            except ValueError:
                pass
        # Aplicar inmediatamente en DB (fuente de verdad)
        ok, err = save_obra_individual(nombre, precio, estado)
        if not ok:
            errors.append(f"Error al guardar {nombre}: {err or 'desconocido'}")
            continue
        if no_cubre_anexo and nombre not in obras_sin:
            obras_sin.append(nombre)
        elif not no_cubre_anexo and nombre in obras_sin:
            obras_sin = [o for o in obras_sin if o != nombre]
    if errors:
        return jsonify({'success': False, 'message': '; '.join(errors[:5])}), 400
    try:
        anexo_config['obras_sin_cobertura'] = obras_sin
        save_anexo_config(anexo_config)
        save_modificaciones_programadas(programadas)
    except Exception as e:
        logger.error(f"Error al guardar lote de obras: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    return jsonify({'success': True, 'message': f'Se aplicaron {len(cambios)} cambio(s) correctamente.'})

# Eliminar una modificación programada sin aplicarla
@app.route('/admin/obras/programadas/eliminar', methods=['POST'])
@require_login
def admin_obras_programadas_eliminar():
    if not is_gaito_admin():
        return jsonify({'success': False, 'message': 'No tienes permiso.'}), 403
    nombre = (request.form.get('nombre') or request.form.get('nombre_obra') or '').strip()
    if not nombre:
        return jsonify({'success': False, 'message': 'Nombre de obra requerido.'}), 400
    lista = load_modificaciones_programadas()
    nueva = [p for p in lista if p.get('nombre_obra') != nombre]
    if len(nueva) == len(lista):
        return jsonify({'success': False, 'message': 'No hay programación para esta obra.'}), 404
    if save_modificaciones_programadas(nueva):
        return jsonify({'success': True, 'message': 'Programación cancelada.'})
    return jsonify({'success': False, 'message': 'Error al guardar.'}), 500

# Aranceles: cualquier usuario logueado puede ver (no es solo admin). Precios desde obras_entero.txt (misma fuente que Gestión de obras).
@app.route('/aranceles', methods=['GET'])
@require_login
def aranceles():
    aplicar_modificaciones_programadas()
    obras_list, estado_data = load_obras_list_para_vista()
    anexo_config = load_anexo_config()
    
    # Formatear fecha de actualización
    fecha_actualizacion = None
    if estado_data.get('fecha_actualizacion'):
        try:
            fecha_dt = datetime.fromisoformat(estado_data['fecha_actualizacion'])
            fecha_actualizacion = fecha_dt.strftime('%d/%m/%Y %H:%M:%S')
        except:
            fecha_actualizacion = estado_data.get('fecha_actualizacion')
    
    modificaciones_programadas = load_modificaciones_programadas()
    return render_template('admin_estado_obras.html', 
                         estado_data=estado_data,
                         obras_list=obras_list,
                         fecha_actualizacion=fecha_actualizacion,
                         modificaciones_programadas=modificaciones_programadas,
                         obras_sin_cobertura_anexo=anexo_config.get('obras_sin_cobertura', []),
                         current_user=session.get('username'))

@app.route('/aranceles/historial/<path:nombre>', methods=['GET'])
@require_login
def aranceles_historial(nombre):
    """Devuelve el historial de cambios de una obra social en JSON (público para logueados)."""
    try:
        tz_ar = ZoneInfo('America/Argentina/Buenos_Aires')
        registros = (
            ObraSocialHistorial.query
            .filter_by(obra_nombre=nombre)
            .order_by(ObraSocialHistorial.fecha.desc())
            .limit(100)
            .all()
        )
        data = []
        for r in registros:
            fecha_local = r.fecha.replace(tzinfo=None)
            data.append({
                'fecha': fecha_local.strftime('%d/%m/%Y %H:%M'),
                'precio_anterior': r.precio_anterior or '—',
                'precio_nuevo': r.precio_nuevo or '—',
                'estado_anterior': r.estado_anterior or '—',
                'estado_nuevo': r.estado_nuevo or '—',
                'solo_estado': r.precio_anterior == r.precio_nuevo,
            })
        return jsonify({'ok': True, 'obra': nombre, 'historial': data})
    except Exception as e:
        logger.error(f"Error al obtener historial de {nombre}: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# Archivo de instructivos por obra social
INSTRUCTIVOS_FILE = 'instructivos.json'

def load_instructivos():
    """Carga instructivos desde la DB."""
    try:
        return [
            {
                'nombre': i.nombre,
                'contenido': i.contenido or '',
                'contacto': i.contacto or '',
                'telefonos': i.telefonos or '',
                'notas_especiales': i.notas_especiales or '',
            }
            for i in Instructivo.query.order_by(Instructivo.nombre).all()
        ]
    except Exception as e:
        logger.error(f"Error al leer instructivos: {e}")
    return []


def save_instructivos(instructivos):
    """Persiste instructivos en la DB (upsert por nombre)."""
    try:
        for item in instructivos:
            nombre = (item.get('nombre') or '').strip()
            if not nombre:
                continue
            inst = Instructivo.query.filter_by(nombre=nombre).first()
            if not inst:
                inst = Instructivo(nombre=nombre)
                db.session.add(inst)
            inst.contenido = item.get('contenido', '')
            inst.contacto = item.get('contacto', '')
            inst.telefonos = item.get('telefonos', '')
            inst.notas_especiales = item.get('notas_especiales', '')
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar instructivos: {e}")
        return False

def load_instructivos_completos():
    """
    Devuelve la lista de instructivos garantizando una hoja por cada obra social del sistema
    (vigentes, sin convenio y suspendidas). Si falta una obra en instructivos.json, se agrega
    con contenido vacío y se guarda el archivo.
    """
    estado_data = load_obras_estado()
    obras_en_sistema = list((estado_data.get('obras') or {}).keys())
    instructivos = load_instructivos()
    # Índice por nombre normalizado para buscar y actualizar
    by_norm = {}
    for inv in instructivos:
        nombre = (inv.get('nombre') or '').strip()
        if nombre:
            by_norm[normalizar_nombre_obra(nombre)] = inv
    agregados = 0
    for nombre_obra in obras_en_sistema:
        if not (nombre_obra and nombre_obra.strip()):
            continue
        norm = normalizar_nombre_obra(nombre_obra)
        if norm not in by_norm:
            by_norm[norm] = {
                'nombre': nombre_obra.strip(),
                'contenido': '',
                'contacto': '',
                'telefonos': '',
                'notas_especiales': ''
            }
            agregados += 1
    # Lista final ordenada por nombre (usando el nombre de la obra en sistema para orden)
    resultado = []
    for nombre_obra in sorted(obras_en_sistema, key=lambda x: (x or '').lower()):
        norm = normalizar_nombre_obra(nombre_obra)
        if norm and norm in by_norm:
            resultado.append(by_norm[norm])
    if agregados > 0:
        save_instructivos(resultado)
        logger.info(f"Instructivos: se agregaron {agregados} hojas para obras nuevas en el sistema.")
    return resultado

# Ruta para instructivo de obras sociales (protegida). Siempre una hoja por cada obra del sistema.
@app.route('/instructivo', methods=['GET'])
@require_login
def instructivo():
    instructivos = load_instructivos_completos()
    return render_template('instructivo.html', 
                         instructivos=instructivos,
                         username=session.get('username'))

# Panel admin: gestión de instructivos por obra social (solo admin). Lista incluye todas las obras.
@app.route('/admin/instructivos', methods=['GET'])
@require_login
def admin_instructivos():
    if not is_gaito_admin():
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('instructivo'))
    instructivos = load_instructivos_completos()
    return render_template('admin_instructivos.html',
                         instructivos=instructivos,
                         current_user=session.get('username'))

@app.route('/admin/instructivos/actualizar', methods=['POST'])
@require_login
def admin_instructivos_actualizar():
    if not is_gaito_admin():
        return jsonify({'success': False, 'message': 'Sin permiso.'}), 403
    # Aceptar form (FormData) o JSON; request.json es None cuando se envía form
    data = request.json if request.is_json and request.json else {}
    nombre = (request.form.get('nombre') or data.get('nombre') or '').strip()
    if not nombre:
        return jsonify({'success': False, 'message': 'Falta el nombre de la obra social.'}), 400
    contenido = (request.form.get('contenido') or data.get('contenido') or '').strip()
    contacto = (request.form.get('contacto') or data.get('contacto') or '').strip()
    telefonos = (request.form.get('telefonos') or data.get('telefonos') or '').strip()
    notas_especiales = (request.form.get('notas_especiales') or data.get('notas_especiales') or '').strip()
    instructivos = load_instructivos_completos()
    encontrado = False
    for item in instructivos:
        if normalizar_nombre_obra(item.get('nombre')) == normalizar_nombre_obra(nombre):
            item['contenido'] = contenido
            item['contacto'] = contacto
            item['telefonos'] = telefonos
            item['notas_especiales'] = notas_especiales
            encontrado = True
            break
    if not encontrado:
        return jsonify({'success': False, 'message': f'Obra social "{nombre}" no encontrada.'}), 404
    if not save_instructivos(instructivos):
        return jsonify({'success': False, 'message': 'Error al guardar.'}), 500
    return jsonify({'success': True, 'message': 'Instructivo actualizado correctamente.'})

# Ruta para descargar PDF
@app.route('/descargar_pdf', methods=['POST'])
@require_login
def descargar_pdf():
    pdf_temp_files = []
    try:
        username = session.get('username')
        if not username:
            flash('Debes iniciar sesión para descargar PDFs.', 'error')
            return redirect(url_for('login'))
        
        # Obtener datos del formulario
        nombre_paciente = request.form.get('nombre_paciente', '').strip()
        nombre_obra_social = request.form.get('nombre_obra_social', '').strip()
        numero_afiliado = request.form.get('numero_afiliado', '').strip()
        fecha_presupuesto_str = request.form.get('fecha_presupuesto', '')
        estudios_json = request.form.get('estudios_json', '[]')
        iva_incluido = request.form.get('iva_incluido') == '1'
        
        # Procesar fecha (si viene del formulario, usarla; si no, usar fecha actual)
        if fecha_presupuesto_str:
            try:
                fecha_presupuesto = datetime.strptime(fecha_presupuesto_str, '%Y-%m-%d')
            except:
                fecha_presupuesto = datetime.now()
        else:
            fecha_presupuesto = datetime.now()
        
        try:
            estudios_data = json.loads(estudios_json)
        except json.JSONDecodeError:
            flash('Error al procesar los estudios.', 'error')
            return redirect(url_for('presupuestos'))
        
        # Obtener perfil del laboratorio
        perfil = get_lab_profile(username)

        # Rutas locales o temporales (URLs de Storage se bajan a tmp y se borran al final)
        resolved_logo, _tl = resolve_perfil_image(perfil.get('logo_path'), LOGO_FOLDER)
        if _tl:
            pdf_temp_files.append(_tl)
        resolved_firma, _tf = resolve_perfil_image(perfil.get('firma_path'), LOGO_FOLDER)
        if _tf:
            pdf_temp_files.append(_tf)

        # Función helper para texto con encoding seguro
        def safe_text(text):
            """Convierte texto a formato seguro para PDF (maneja tildes y caracteres especiales)"""
            if not text:
                return ''
            try:
                # Convertir a string si no lo es
                result = str(text)
                
                # Reemplazar caracteres problemáticos comunes ANTES de cualquier otra operación
                # IMPORTANTE: Hacer múltiples pasadas para asegurar que se reemplacen todos
                replacements = [
                    ('–', '-'),  # En-dash (U+2013) - PRIMERO
                    ('—', '-'),  # Em-dash (U+2014)
                    ('−', '-'),  # Minus sign (U+2212)
                    ('\u2013', '-'),  # En-dash como código Unicode
                    ('\u2014', '-'),  # Em-dash como código Unicode
                    ('\u2212', '-'),  # Minus sign como código Unicode
                    ('á', 'a'), ('é', 'e'), ('í', 'i'), ('ó', 'o'), ('ú', 'u'),
                    ('Á', 'A'), ('É', 'E'), ('Í', 'I'), ('Ó', 'O'), ('Ú', 'U'),
                    ('ñ', 'n'), ('Ñ', 'N'),
                    ('ü', 'u'), ('Ü', 'U'),
                    ('°', 'o'),  # Grado
                    ('€', 'EUR'),  # Euro
                    ('£', 'GBP'),  # Libra
                ]
                
                # Aplicar reemplazos múltiples veces para asegurar que se capturen todos
                for old, new in replacements:
                    result = result.replace(old, new)
                # Una pasada adicional específica para en-dash
                result = result.replace('\u2013', '-').replace('\u2014', '-')
                
                # Eliminar cualquier otro carácter no ASCII que pueda causar problemas
                result = result.encode('ascii', 'ignore').decode('ascii')
                return result
            except Exception as e:
                logger.warning(f"Error al procesar texto: {e}, texto original: {str(text)[:50]}")
                # Si falla, intentar solo con ASCII
                try:
                    return str(text).encode('ascii', 'ignore').decode('ascii')
                except:
                    return ''
        
        # Clase personalizada de PDF con header repetido
        class PDFConHeader(FPDF):
            def __init__(self, perfil, fecha_presupuesto, safe_text_func, resolved_logo_path=None):
                super().__init__()
                self.perfil = perfil
                self.fecha_presupuesto = fecha_presupuesto
                self.safe_text = safe_text_func
                self._resolved_logo_path = resolved_logo_path
                self.set_auto_page_break(auto=True, margin=15)
                self._header_rendering = False  # Bandera para evitar recursión
                self.y_linea_separadora = None  # Guardar posición Y de la línea separadora
            
            def header(self):
                if self._header_rendering:
                    return
                self._header_rendering = True
                
                try:
                    # A. LOGO (Fijo a la izquierda): ruta local, legado static/logos, o tmp desde URL
                    logo_path_use = self._resolved_logo_path
                    if logo_path_use and os.path.isfile(logo_path_use):
                        try:
                            self.image(logo_path_use, x=10, y=10, w=25)
                        except Exception as e:
                            logger.warning(f"No se pudo insertar logo del laboratorio: {e}")
                    
                    # B. TEXTO DEL LABORATORIO (Centrado y Espaciado)
                    # Título Principal
                    self.set_y(12)
                    self.set_x(0)  # OBLIGATORIO: Resetea X para centrar en la página
                    self.set_font('Helvetica', 'B', 14)
                    nombre_lab = self.safe_text(self.perfil.get('nombre_lab', 'Laboratorio'))
                    self.cell(0, 6, nombre_lab, align='C', ln=1)
                    
                    # Subtítulo (Bajamos 7mm)
                    self.set_y(19)
                    self.set_x(0)
                    self.set_font('Helvetica', 'I', 10)
                    subtitulo = self.safe_text(self.perfil.get('subtitulo', 'Analisis Clinicos'))
                    self.cell(0, 5, subtitulo, align='C', ln=1)
                    
                    # Profesionales (admite múltiples líneas con Enter)
                    self.set_y(25)
                    self.set_x(0)
                    self.set_font('Helvetica', '', 9)
                    profesionales_raw = self.perfil.get('profesionales', '')
                    profesionales_lines = []
                    if profesionales_raw:
                        # Preservar saltos de línea del formulario y limpiar cada línea para PDF.
                        for line in str(profesionales_raw).splitlines():
                            safe_line = self.safe_text(line).strip()
                            if safe_line:
                                profesionales_lines.append(safe_line)
                    if profesionales_lines:
                        for line in profesionales_lines:
                            self.set_x(0)
                            self.cell(0, 4, line, align='C', ln=1)

                    # Dirección (acomodar según la altura real de "profesionales")
                    self.set_y(max(30, self.get_y() + 1))
                    self.set_x(0)
                    direccion_text = self.safe_text(self.perfil.get('direccion', ''))
                    ciudad = self.safe_text(self.perfil.get('ciudad', ''))
                    
                    # Formatear dirección limpia
                    direccion_line = ""
                    if direccion_text:
                        direccion_limpia = direccion_text.split('-')[0].strip()
                        direccion_limpia = direccion_limpia.replace('  ', ' ').replace('/ ', '/').strip()
                        if ciudad:
                            direccion_line = f"{direccion_limpia}, {ciudad}"
                        else:
                            direccion_line = direccion_limpia
                        # Agregar CP si está en la dirección original
                        if '(9100)' in direccion_text or 'Cp (9100)' in direccion_text or 'CP (9100)' in direccion_text:
                            direccion_line = direccion_line.replace('Cp (9100)', '').replace('CP (9100)', '').replace('(9100)', '').strip()
                            if ciudad:
                                direccion_line = f"{direccion_limpia}, {ciudad} (CP 9100)"
                            else:
                                direccion_line = f"{direccion_limpia} (CP 9100)"
                    
                    # Formatear teléfono para incluir en la línea de dirección
                    telefono = self.perfil.get('telefono', '')
                    if telefono:
                        telefono_limpio = telefono.replace('/', ' / ').replace('  ', ' ').strip()
                        if '0280' in telefono_limpio:
                            partes_tel = telefono_limpio.split('/')
                            tel_formateado = []
                            for parte in partes_tel:
                                parte = parte.strip()
                                if '0280' in parte:
                                    parte = parte.replace('0280', '(0280)').replace('--', '-').replace(' ', '')
                                    if ') ' not in parte and ')' in parte:
                                        parte = parte.replace(')', ') ')
                                else:
                                    parte = parte.replace(' ', '-')
                                tel_formateado.append(parte)
                            telefono_limpio = ' / '.join(tel_formateado)
                        if direccion_line:
                            direccion_line = f"{direccion_line} - Tel: {telefono_limpio}"
                        else:
                            direccion_line = f"Tel: {telefono_limpio}"
                    
                    if direccion_line:
                        self.cell(0, 5, direccion_line, align='C', ln=1)
                    
                    # C. LÍNEA DIVISORIA (dinámica, evita cortar texto cuando hay más líneas)
                    line_y = max(38, self.get_y() + 3)
                    self.set_draw_color(0, 0, 0)
                    self.set_line_width(0.5)
                    self.line(10, line_y, 200, line_y)
                    self.set_line_width(0.2)
                    
                    # Guardar posición Y de la línea separadora para usar en el cuerpo
                    self.y_linea_separadora = line_y
                    
                    # D. FECHA (Debajo de la línea, a la derecha) - Se dibuja en el cuerpo, no en el header
                    # El header solo establece la línea separadora
                
                finally:
                    self._header_rendering = False
                    # Margen para que el cuerpo empiece limpio
                    self.set_y(max(50, (self.y_linea_separadora or 38) + 12))
            
        
        # Crear PDF con header automático
        pdf = PDFConHeader(perfil, fecha_presupuesto, safe_text, resolved_logo_path=resolved_logo)
        pdf.add_page()  # El header se dibujará automáticamente
        
        # Fecha - debajo de la línea separadora (solo en la primera página, no parte del header)
        # Fecha claramente DEBAJO de la línea divisoria, alineada a la derecha
        meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 
                 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
        fecha_str = f"{fecha_presupuesto.day} de {meses[fecha_presupuesto.month - 1]} {fecha_presupuesto.year}"
        ciudad = safe_text(perfil.get('ciudad', ''))
        fecha_formateada = f"{fecha_str}, {ciudad}"
        
        # Fecha debajo de la línea separadora (dinámico si el header ocupa más alto)
        line_y = pdf.y_linea_separadora or 38
        pdf.set_y(line_y + 2)
        pdf.set_x(0)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 5, fecha_formateada, align='R', ln=1)
        
        # Establecer posición Y después de la fecha
        pdf.set_y(max(50, line_y + 12))
        
        # Espacio adicional para separar claramente el cuerpo del header (mejor respiración visual)
        pdf.ln(10)
        
        # CUERPO (solo en la primera página)
        # Datos del cliente
        nombre_cliente = safe_text(nombre_paciente if nombre_paciente else 'Cliente')
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 8, f"SRES: {nombre_cliente}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        pdf.ln(2)
        # Obra Social
        nombre_obra = safe_text(nombre_obra_social if nombre_obra_social else 'Obra Social no especificada')
        pdf.cell(0, 8, f"Obra Social: {nombre_obra}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        # Número de Afiliado (solo si tiene valor)
        if numero_afiliado:
            pdf.ln(2)
            numero_afiliado_texto = safe_text(numero_afiliado)
            pdf.cell(0, 8, f"N° De Afiliado: {numero_afiliado_texto}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        pdf.ln(5)
        
        # Título del presupuesto - CENTRADO
        pdf.set_font('Helvetica', 'B', 16)
        pdf.cell(0, 10, "PRESUPUESTO", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(5)
        
        # Tabla de estudios - diseño mejorado
        # Anchos de columna optimizados
        w_codigo = 35
        w_analisis = 90
        w_nbu = 25
        w_valor = 40
        w_total_tabla = w_codigo + w_analisis + w_nbu + w_valor  # Ancho total de la tabla
        
        # Texto descriptivo - ALINEADO A LA IZQUIERDA
        pdf.set_font('Helvetica', '', 10)
        texto_descriptivo = "Me dirijo a Ud./s. en respuesta a lo solicitado, detallando a continuacion los valores finales de las practicas de laboratorio requeridas"
        # Usar multi_cell para texto largo que puede necesitar varias líneas, alineado a la izquierda
        pdf.multi_cell(0, 6, texto_descriptivo, align='L')
        pdf.ln(5)
        
        # Encabezados de tabla - con fondo gris (alineados a la izquierda)
        pdf.set_x(pdf.l_margin)  # Alinear a la izquierda desde el margen
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_fill_color(240, 240, 240)  # Gris claro para encabezados
        pdf.cell(w_codigo, 9, 'CODIGOS', border=1, align='C', fill=True)
        pdf.cell(w_analisis, 9, 'ANALISIS', border=1, align='C', fill=True)
        pdf.cell(w_nbu, 9, 'NBU', border=1, align='C', fill=True)
        pdf.cell(w_valor, 9, 'VALOR', border=1, align='C', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_fill_color(255, 255, 255)  # Restaurar color blanco
        
        # Filas de datos
        pdf.set_font('Helvetica', '', 10)
        total = 0
        for estudio in estudios_data:
            codigo = estudio.get('codigo', '')
            nombre = safe_text(estudio.get('nombre', ''))
            nbu = estudio.get('ub', '0')
            valor = float(estudio.get('valor', 0))
            
            total += valor
            
            # Formatear valores (formato argentino)
            try:
                nbu_float = float(nbu) if nbu else 0
                nbu_str = f"{nbu_float:.1f}".replace('.', ',')
            except:
                nbu_str = str(nbu).replace('.', ',')
            
            # Formatear valor en formato argentino
            valor_str = f"${valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
            
            # Filas de la tabla (alineadas a la izquierda)
            pdf.set_x(pdf.l_margin)  # Alinear cada fila desde el margen izquierdo
            nombre_truncado = nombre[:40] if len(nombre) > 40 else nombre
            try:
                pdf.cell(w_codigo, 8, codigo, border=1, align='C')
                pdf.cell(w_analisis, 8, nombre_truncado, border=1, align='L')
                pdf.cell(w_nbu, 8, nbu_str, border=1, align='C')
                pdf.cell(w_valor, 8, valor_str, border=1, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            except Exception as e:
                logger.error(f"Error al escribir fila de tabla - codigo: {codigo}, nombre: {nombre_truncado}, error: {e}")
                codigo_safe = safe_text(codigo)
                nombre_safe = safe_text(nombre_truncado)
                pdf.set_x(pdf.l_margin)  # Re-alinear después del error
                pdf.cell(w_codigo, 8, codigo_safe, border=1, align='C')
                pdf.cell(w_analisis, 8, nombre_safe, border=1, align='L')
                pdf.cell(w_nbu, 8, nbu_str, border=1, align='C')
                pdf.cell(w_valor, 8, valor_str, border=1, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # Total - fila destacada (alineada a la izquierda). Aplicar IVA 21% si corresponde
        if iva_incluido:
            total = total * 1.21
        pdf.set_x(pdf.l_margin)  # Alinear desde el margen izquierdo
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_fill_color(250, 250, 250)  # Gris muy claro para el total
        total_str = f"TOTAL: ${total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        pdf.cell(w_codigo + w_analisis + w_nbu, 9, '', border=0, fill=True)
        pdf.cell(w_valor, 9, total_str, border=1, align='R', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_fill_color(255, 255, 255)  # Restaurar color blanco
        if iva_incluido:
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(w_codigo + w_analisis + w_nbu + w_valor, 6, '(IVA Incluido)', align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)
        
        pdf.ln(15)  # Espacio después de la tabla (mejor respiración visual)
        
        # --- LÓGICA DE PIE DE PÁGINA INTELIGENTE ---
        info_bancaria = perfil.get('info_bancaria', '')
        firma_texto = safe_text(perfil.get('firma_texto', ''))
        firma_path = perfil.get('firma_path', '')
        
        # 1. Definimos la altura del bloque completo (Bancos + Firma + Ente + Márgenes)
        # 65 mm es una altura segura para que entre todo cómodo.
        altura_bloque_footer = 65
        
        # 2. Medimos cuánto espacio real queda en la hoja
        # 297 (Alto A4) - Y_actual - 10 (Margen inferior mínimo)
        espacio_disponible = 297 - pdf.get_y() - 10
        
        # 3. Decisión: ¿Entra el bloque entero?
        if espacio_disponible < altura_bloque_footer:
            # NO ENTRA: Agregamos página nueva.
            pdf.add_page()
            # Al añadir página, el header se imprime solo.
            # Bajamos el cursor (ej: 55) para no quedar pegados al header.
            pdf.set_y(55)
        else:
            # SÍ ENTRA: Solo damos un pequeño respiro (10mm) respecto a la tabla.
            pdf.set_y(pdf.get_y() + 10)
        
        # 4. IMPRESIÓN DEL BLOQUE (Desactivando salto automático)
        # IMPORTANTE: Desactivamos el salto automático para poder escribir el "Ente"
        # bien al fondo (-30) sin que FPDF salte de página por error.
        pdf.set_auto_page_break(auto=False)
        
        y_inicio = pdf.get_y()
        
        # --- A. BANCOS (Izquierda) ---
        if info_bancaria:
            pdf.set_xy(10, y_inicio)
            pdf.set_font('Helvetica', '', 9)
            # (Asegúrate de tener la variable texto_bancario lista)
            texto_bancario = safe_text(info_bancaria)
            pdf.multi_cell(100, 5, texto_bancario, align='L')
        
        # --- B. FIRMA (Derecha) ---
        # Volvemos a la misma altura Y para la columna derecha
        if firma_texto or firma_path:
            pdf.set_xy(110, y_inicio)
            pdf.set_font('Helvetica', '', 9)
            
            # Si hay imagen de firma, mostrarla primero (Storage URL -> tmp, o archivo local legado)
            if firma_path:
                firma_full_path = (
                    resolved_firma if (resolved_firma and os.path.isfile(resolved_firma)) else None
                )
                if firma_full_path:
                    try:
                        # Tamaño para la imagen de firma
                        firma_width_mm = 40
                        try:
                            from PIL import Image
                            img = Image.open(firma_full_path)
                            img_width, img_height = img.size
                            # Mantener proporción
                            firma_height_mm = (img_height / img_width) * firma_width_mm
                            # Limitar altura máxima a 20mm
                            if firma_height_mm > 20:
                                firma_height_mm = 20
                                firma_width_mm = (img_width / img_height) * 20
                            # Asegurar un tamaño mínimo razonable
                            if firma_height_mm < 10:
                                firma_height_mm = 10
                                firma_width_mm = (img_width / img_height) * 10
                        except:
                            firma_width_mm = 40
                            firma_height_mm = 15
                        
                        # Calcular posición X para alinear a la derecha (dentro del bloque de 110-200)
                        x_firma = 200 - firma_width_mm  # Alineado a la derecha del bloque
                        
                        # Insertar imagen de firma
                        pdf.image(firma_full_path, x=x_firma, y=y_inicio, w=firma_width_mm, h=firma_height_mm, keep_aspect_ratio=True)
                        
                        # Bajar un poco si hay imagen
                        y_despues_imagen = y_inicio + firma_height_mm + 5
                        pdf.set_xy(110, y_despues_imagen)
                        
                        # Dibujar línea de firma manual
                        espacio_firma_manual = 15
                        y_pos_linea = y_despues_imagen + espacio_firma_manual
                        pdf.line(110, y_pos_linea, 200, y_pos_linea)
                        
                        # Si hay texto de firma, mostrarlo debajo de la línea
                        if firma_texto:
                            pdf.set_xy(110, y_pos_linea + 3)
                            pdf.cell(90, 5, firma_texto, align='C', ln=1)
                    except Exception as e:
                        logger.warning(f"No se pudo insertar imagen de firma: {e}")
                        # Si falla la imagen, continuar con el texto normal
                        if firma_texto:
                            espacio_firma_manual = 15
                            y_pos_linea = y_inicio + espacio_firma_manual
                            pdf.line(110, y_pos_linea, 200, y_pos_linea)
                            pdf.set_xy(110, y_pos_linea + 3)
                            pdf.cell(90, 5, firma_texto, align='C', ln=1)
                elif firma_texto:
                    # Si la imagen no existe pero hay texto, mostrar solo el texto
                    espacio_firma_manual = 15
                    y_pos_linea = y_inicio + espacio_firma_manual
                    pdf.line(110, y_pos_linea, 200, y_pos_linea)
                    pdf.set_xy(110, y_pos_linea + 3)
                    pdf.cell(90, 5, firma_texto, align='C', ln=1)
            elif firma_texto:
                # Solo texto de firma, sin imagen
                espacio_firma_manual = 15
                y_pos_linea = y_inicio + espacio_firma_manual
                pdf.line(110, y_pos_linea, 200, y_pos_linea)
                pdf.set_xy(110, y_pos_linea + 3)
                pdf.cell(90, 5, firma_texto, align='C', ln=1)
        
        # --- C. ENTE REGULADOR (Diseño Horizontal Prolijo) ---
        
        # 1. Nos ubicamos bien abajo
        pdf.set_y(-30)
        
        # 2. Línea divisoria gris que cruza toda la hoja
        pdf.set_draw_color(200, 200, 200)
        pdf.set_line_width(0.1)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        
        # Bajamos un poco para empezar a escribir
        y_base = pdf.get_y() + 3
        
        # 3. COLUMNA IZQUIERDA: LOGO ABNECH
        ruta_logo_abnech = os.path.join(LOGO_FOLDER, ASOCIACION_BIOQUIMICA.get('logo_path', 'logo_asociacion_bioquimica.png'))
        
        if os.path.exists(ruta_logo_abnech):
            try:
                # Logo a la izquierda, tamaño razonable (aprox 20mm de ancho)
                pdf.image(ruta_logo_abnech, x=12, y=y_base, w=20)
                margen_texto = 35  # El texto empieza después del logo
            except Exception as e:
                logger.warning(f"No se pudo insertar logo de Asociación Bioquímica: {e}")
                margen_texto = 10  # Si no hay logo, empieza al margen
        else:
            margen_texto = 10  # Si no hay logo, empieza al margen
        
        # 4. COLUMNA DERECHA: TEXTO (Alineado verticalmente con el logo)
        pdf.set_xy(margen_texto, y_base + 2)  # Un poquito más abajo para centrar con el logo
        pdf.set_font('Helvetica', 'B', 8)  # Negrita para el título
        pdf.set_text_color(80, 80, 80)  # Gris oscuro
        pdf.cell(0, 4, 'Ente Regulador: Asociación Bioquímica del NE del Chubut', ln=1, align='L')
        
        pdf.set_x(margen_texto)
        pdf.set_font('Helvetica', '', 7)  # Normal para detalles
        pdf.cell(0, 4, 'Paraguay 37 - Trelew | Tel: 0280-4420440 | Email: abnechtrelew@gmail.com', ln=1, align='L')
        
        # Restaurar color de texto a negro
        pdf.set_text_color(0, 0, 0)
        
        # Reactivar seguridad del PDF para el futuro
        pdf.set_auto_page_break(auto=True, margin=15)
        
        # Generar PDF en memoria
        pdf_output = io.BytesIO()
        try:
            pdf.output(pdf_output)
            pdf_output.seek(0)
        except Exception as e:
            logger.error(f"Error al generar bytes del PDF: {e}", exc_info=True)
            raise
        
        # Nombre del archivo (sanitizar para evitar caracteres problemáticos)
        nombre_archivo_base = safe_text(nombre_paciente.replace(' ', '_') if nombre_paciente else 'cliente')
        nombre_archivo = f"presupuesto_{nombre_archivo_base}_{datetime.now().strftime('%Y%m%d')}.pdf"
        
        return send_file(
            pdf_output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=nombre_archivo
        )

    except Exception as e:
        logger.error(f"Error al generar PDF: {e}", exc_info=True)
        flash(f'Error al generar el PDF: {str(e)}. Por favor, intenta nuevamente.', 'error')
        return redirect(url_for('presupuestos'))
    finally:
        cleanup_temp_paths(pdf_temp_files)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Solo debug=True en desarrollo, no en producción
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
