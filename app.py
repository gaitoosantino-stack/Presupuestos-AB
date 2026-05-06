from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, send_file, jsonify
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
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

# Usar SECRET_KEY de variables de entorno, con fallback a una clave aleatoria
# En Render, configurá SECRET_KEY en el dashboard de variables de entorno
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24).hex()

# Configuración de sesión
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
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
db = SQLAlchemy(app)


class Usuario(db.Model):
    __tablename__ = 'usuario'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password = db.Column(db.Text, nullable=False)
    email = db.Column(db.String(120), default='')
    habilitado = db.Column(db.Boolean, default=True, nullable=False)
    perfil = db.relationship('Perfil', back_populates='usuario', uselist=False, cascade='all, delete-orphan')


class Perfil(db.Model):
    __tablename__ = 'perfil'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), db.ForeignKey('usuario.username', ondelete='CASCADE'), unique=True, nullable=False)
    nombre_lab = db.Column(db.String(200), default='Laboratorio')
    subtitulo = db.Column(db.String(200), default='Análisis Clínicos')
    profesionales = db.Column(db.String(300), default='Bioquímico: - MP: -')
    direccion = db.Column(db.String(200), default='')
    ciudad = db.Column(db.String(100), default='Trelew')
    telefono = db.Column(db.String(100), default='')
    logo_path = db.Column(db.String(200), default='')
    info_bancaria = db.Column(db.Text, default='')
    firma_texto = db.Column(db.String(200), default='')
    firma_path = db.Column(db.String(200), default='')
    usuario = db.relationship('Usuario', back_populates='perfil')


class ObraSocial(db.Model):
    """
    Obra social / convenio. PARTICULAR se trata como una obra más.
    cubre_anexo: True  → todos los estudios al NBU de esta obra.
                 False → estudios con es_anexo=True se cobran al NBU de PARTICULAR.
    """
    __tablename__ = 'obra_social'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False, index=True)
    precio = db.Column(db.String(50))
    estado = db.Column(db.String(20), default='vigente', nullable=False)
    cubre_anexo = db.Column(db.Boolean, default=True, nullable=False)
    ultima_actualizacion = db.Column(db.String(50))


class Estudio(db.Model):
    """
    Catálogo de estudios importado desde CODIGO_ESTUDIO_UB.txt / Anexo_Codigos.txt.
    es_anexo: True → práctica de anexo; se cobra a NBU PARTICULAR si la obra no cubre anexo.
    """
    __tablename__ = 'estudio'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False, index=True)
    nombre = db.Column(db.String(400), nullable=False)
    ub = db.Column(db.String(200), nullable=False)
    es_anexo = db.Column(db.Boolean, default=False, nullable=False)


class ObraSocialHistorial(db.Model):
    """
    Registro de cambios de precio/estado de obras sociales.
    Solo se inserta cuando el sync de OneDrive se confirma exitosamente.
    """
    __tablename__ = 'obra_social_historial'
    id = db.Column(db.Integer, primary_key=True)
    obra_nombre = db.Column(db.String(200), nullable=False, index=True)
    fecha = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    precio_anterior = db.Column(db.String(50))
    precio_nuevo = db.Column(db.String(50))
    estado_anterior = db.Column(db.String(20))
    estado_nuevo = db.Column(db.String(20))


class ModificacionProgramada(db.Model):
    __tablename__ = 'modificacion_programada'
    id = db.Column(db.Integer, primary_key=True)
    nombre_obra = db.Column(db.String(200), nullable=False, index=True)
    fecha_aplicar = db.Column(db.String(20), nullable=False)
    precio = db.Column(db.String(50))
    estado = db.Column(db.String(20))
    no_cubre_anexo = db.Column(db.Boolean, default=False)


class Instructivo(db.Model):
    __tablename__ = 'instructivo'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False, index=True)
    contenido = db.Column(db.Text, default='')
    contacto = db.Column(db.String(200), default='')
    telefonos = db.Column(db.String(200), default='')
    notas_especiales = db.Column(db.Text, default='')


with app.app_context():
    db.create_all()
    logger.info("Tablas DB verificadas/creadas.")


def strip_html(text):
    """Quita etiquetas HTML y normaliza espacios. Para mostrar texto plano en tablas/resúmenes."""
    if not text:
        return ''
    s = re.sub(r'<[^>]+>', '', str(text))
    return re.sub(r'\s+', ' ', s).strip()


app.jinja_env.filters['strip_html'] = strip_html


@app.errorhandler(400)
def bad_request_csrf(e):
    """Si el 400 viene del login (CSRF expirado), redirigir con mensaje amigable."""
    if request.method == 'POST' and request.path.rstrip('/') in ('', '/login'):
        flash('El formulario expiró. Volvé a intentar iniciar sesión.', 'error')
        return redirect(url_for('login'))
    if e.description:
        return e.description, 400
    return 'Bad Request', 400


# Archivo para almacenar usuarios habilitados
USERS_FILE = 'usuarios_habilitados.json'
# Archivo para almacenar perfiles de laboratorios
PERFILES_FILE = 'perfiles.json'
# Carpeta para logos
LOGO_FOLDER = 'static/logos'
# Configuración de Asociación Bioquímica (aparecerá en todos los PDFs)
ASOCIACION_BIOQUIMICA = {
    'logo_path': 'logo_asociacion_bioquimica.png',
    'nombre': 'Asociacion Bioquimica del Ne del Chubut',
    'direccion': 'Paraguay 37, U9100 Trelew, Chubut',
    'telefono': '02804420440'
}
# Archivo de obras sociales
OBRAS_FILE = 'obras_entero.txt'
# Archivo para almacenar estado completo de obras sociales (con estado vigente/cortada)
OBRAS_ESTADO_FILE = 'obras_estado.json'
# Archivo para almacenar configuración de anexo (obras sociales que no cubren anexo)
ANEXO_CONFIG_FILE = 'anexo_config.json'
# Archivo con códigos de anexo
ANEXO_CODIGOS_FILE = 'Anexo_Codigos.txt'
# Modificaciones programadas (fecha futura → aplicar cambio por obra)
MODIFICACIONES_PROGRAMADAS_FILE = 'modificaciones_programadas.json'
# URL del archivo Excel/CSV para sincronización de precios (configurar aquí o en variable de entorno)
# Puede ser Google Sheets (CSV) o OneDrive/Excel (.xlsx)
# Ejemplo OneDrive: https://onedrive.live.com/download?resid=RESID
GOOGLE_SHEET_URL = os.environ.get('GOOGLE_SHEET_URL', 'https://onedrive.live.com/:x:/g/personal/4296eb0072506afb/IQC4XG2_Nw4YRqWSeSwd8XlUAUeJtQY4DC0CVFNPlhmpoRU?rtime=I1jbPvmp3kg&redeem=aHR0cHM6Ly8xZHJ2Lm1zL3gvYy80Mjk2ZWIwMDcyNTA2YWZiL0lRQzRYRzJfTnc0WVJxV1NlU3dkOFhsVUFVZUp0UVk0REMwQ1ZGTlBsaG1wb1JVP2U9TFIyQVQ2')

def _seed_admin_users():
    """Asegura que los usuarios admin existan en la DB al arrancar."""
    admins = [
        ('Gaito', 'Simon@594*', ''),
        ('3', '3', ''),
        ('DanielABNECH', 'Paraguay37', ''),
    ]
    for username, pw, email in admins:
        if not Usuario.query.filter_by(username=username).first():
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
    """Devuelve dict {username: {password, email, habilitado}} desde la DB."""
    try:
        return {
            u.username: {
                'password': u.password,
                'email': u.email or '',
                'habilitado': u.habilitado,
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
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al guardar usuarios: {e}")
        return False


def load_perfiles():
    """Devuelve dict {username: {...campos perfil}} desde la DB."""
    try:
        return {
            p.username: {
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
            for p in Perfil.query.all()
        }
    except Exception as e:
        logger.error(f"Error al cargar perfiles: {e}")
        return {}


def save_perfiles(perfiles_dict):
    """Persiste perfiles en la DB (upsert por username)."""
    try:
        for username, data in perfiles_dict.items():
            p = Perfil.query.filter_by(username=username).first()
            if not p:
                p = Perfil(username=username)
                db.session.add(p)
            for k, v in data.items():
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
    try:
        p = Perfil.query.filter_by(username=username).first()
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
    return {
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

def estado_desde_vigente_celda(vigente_val):
    """
    Determina estado 'vigente', 'sin_convenio' o 'suspendida' según el valor de la celda Vigente del Excel.
    Acepta variantes: 'sin convenio', 'sinconvenio', 'cortada', con espacios o mayúsculas.
    """
    estado = 'vigente'
    if pd.isna(vigente_val):
        return estado
    vigente_str = str(vigente_val).strip().lower()
    # Normalizar espacios múltiples
    vigente_str = re.sub(r'\s+', ' ', vigente_str)
    if not vigente_str:
        return estado
    if 'sin convenio' in vigente_str or 'sinconvenio' in vigente_str or 'cortada' in vigente_str:
        return 'sin_convenio'
    if 'suspendida' in vigente_str or 'suspendid' in vigente_str:
        return 'suspendida'
    return estado

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

def preview_precios_google_sheet():
    """
    Obtiene un preview de los precios que se sincronizarían desde el Google Sheet/OneDrive.
    Compara con los precios actuales y solo muestra los que han cambiado.
    
    Retorna:
        tuple: (success: bool, message: str, cambios_dict: dict, count: int)
        cambios_dict contiene: {'nombre': {'precio_actual': str, 'precio_nuevo': str, 'cambio': str}}
    """
    if not GOOGLE_SHEET_URL:
        return False, "URL del archivo no configurada.", {}, 0
    
    try:
        logger.info(f"Obteniendo preview desde: {GOOGLE_SHEET_URL}")
        df = None
        
        # Convertir URL de OneDrive a formato de descarga si es necesario
        url = convert_onedrive_url(GOOGLE_SHEET_URL)
        logger.info(f"URL convertida para descarga: {url}")
        
        # Intentar múltiples métodos de descarga
        # Para URLs de OneDrive personal, probamos primero con requests ya que pandas puede fallar
        df = None
        error_str = ""
        
        # Método 1: Intentar con requests primero (más confiable para OneDrive personal)
        if ':x:/g/personal/' in url or 'onedrive.live.com' in url:
            logger.info("URL de OneDrive detectada, intentando descarga con requests primero...")
            file_content = download_file_with_requests(url)
            if file_content:
                try:
                    df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl', header=None)
                    logger.info("Archivo descargado y leído exitosamente con requests + pandas")
                except Exception as mem_e:
                    logger.warning(f"Error al leer archivo desde memoria: {mem_e}")
        
        # Método 2: Si requests falló, intentar leer directamente con pandas
        if df is None:
            try:
                df = pd.read_excel(url, engine='openpyxl', header=None)
                logger.info("Archivo leído exitosamente con pandas.read_excel")
            except Exception as e:
                error_str = str(e)
                logger.warning(f"No se pudo leer directamente con pandas: {e}")
                
                # Método 3: Intentar con formato alternativo de OneDrive
                if 'onedrive.live.com' in url:
                    # Intentar con download.aspx en lugar de download?
                    if '/download?' in url:
                        try:
                            alt_url = url.replace('/download?', '/download.aspx?')
                            logger.info(f"Intentando formato alternativo: {alt_url[:80]}...")
                            df = pd.read_excel(alt_url, engine='openpyxl', header=None)
                            logger.info("Archivo leído exitosamente con formato alternativo")
                        except Exception as alt_e:
                            logger.warning(f"Formato alternativo también falló: {alt_e}")
                    
                    # Intentar con la URL original sin conversión
                    if df is None and GOOGLE_SHEET_URL != url:
                        try:
                            logger.info(f"Intentando con URL original sin conversión: {GOOGLE_SHEET_URL[:80]}...")
                            file_content = download_file_with_requests(GOOGLE_SHEET_URL)
                            if file_content:
                                df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl', header=None)
                                logger.info("Archivo descargado con URL original y leído exitosamente")
                        except Exception as orig_e:
                            logger.warning(f"URL original también falló: {orig_e}")
                
                # Método 4: Intentar descargar con requests usando la URL convertida
                if df is None:
                    file_content = download_file_with_requests(url)
                    if file_content:
                        try:
                            df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl', header=None)
                            logger.info("Archivo descargado y leído exitosamente con requests + pandas (segundo intento)")
                        except Exception as mem_e:
                            logger.error(f"Error al leer archivo desde memoria: {mem_e}")
                            # Intentar formato alternativo con requests
                            if 'onedrive.live.com' in url and '/download?' in url:
                                alt_url = url.replace('/download?', '/download.aspx?')
                                file_content = download_file_with_requests(alt_url)
                                if file_content:
                                    df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl', header=None)
                                    logger.info("Archivo descargado con formato alternativo y leído exitosamente")
                
                # Si aún falla, verificar errores HTTP específicos
                if df is None:
                    if '404' in error_str or 'Not Found' in error_str:
                        return False, f"Error 404: El archivo no se encontró en la URL. Por favor, verifica que la URL de OneDrive/Google Sheets sea correcta y que el archivo esté compartido públicamente. URL actual: {GOOGLE_SHEET_URL[:80]}...", {}, 0
                    elif '403' in error_str or 'Forbidden' in error_str:
                        return False, f"Error 403: Acceso denegado. El archivo puede no estar compartido públicamente. Verifica los permisos del archivo en OneDrive/Google Sheets.", {}, 0
                    elif '401' in error_str or 'Unauthorized' in error_str:
                        return False, f"Error 401: No autorizado. El archivo puede requerir autenticación. Verifica que el archivo esté compartido públicamente.", {}, 0
                    else:
                        raise e
        
        if df is None:
            raise Exception("No se pudo leer el archivo con ningún método")
        
        # Cargar precios actuales al inicio para conservar precio cuando Excel trae 0/vacío en vigentes
        obras_actuales = load_current_obras()
        obras_dict = {}  # Obras vigentes con precio a importar
        obras_cortadas_dict = {}  # Obras cortadas para el preview
        
        # Procesar Bloque 1 (Columnas B, D=vigente, F=precio)
        for idx in range(2, len(df)):
            nombre = df.iloc[idx, 1] if len(df.columns) > 1 else None
            precio = df.iloc[idx, 5] if len(df.columns) > 5 else None
            vigente = df.iloc[idx, 3] if len(df.columns) > 3 else None
            
            # Validar nombre (es obligatorio)
            if pd.isna(nombre):
                continue
            
            nombre = normalizar_nombre_obra(nombre)
            if not nombre or nombre.lower() in ['obras sociales', 'obra social', 'nombre']:
                continue
            
            estado = estado_desde_vigente_celda(vigente)
            
            # Procesar precio (puede estar vacío para obras cortadas)
            precio_normalizado = None
            if not pd.isna(precio):
                precio_str = str(precio).strip()
                precio_normalizado = normalizar_precio_argentino(precio_str)
            
            # Guardar obra sin convenio/suspendida (con o sin precio)
            if estado in ['sin_convenio', 'suspendida']:
                obras_cortadas_dict[nombre] = {
                    'precio': precio_normalizado,
                    'estado': estado
                }
            
            # Solo vigentes: precio válido (>0) o conservar precio actual para no mostrar "modificado" a $0
            if estado == 'vigente':
                if precio_normalizado is not None and es_precio_real(precio_normalizado):
                    obras_dict[nombre] = precio_normalizado
                else:
                    # Excel trae 0 o vacío: conservar precio actual (evita "Modificado" a $0 en preview)
                    prev = obras_actuales.get(nombre)
                    if prev and es_precio_real(prev):
                        obras_dict[nombre] = prev
                    elif not pd.isna(precio):
                        logger.warning(f"Obra vigente {nombre} tiene precio inválido o cero: {precio}")
        
        # Procesar Bloque 2 (Columnas K, M=vigente, O=precio)
        for idx in range(2, len(df)):
            nombre = df.iloc[idx, 10] if len(df.columns) > 10 else None
            precio = df.iloc[idx, 14] if len(df.columns) > 14 else None
            vigente = df.iloc[idx, 12] if len(df.columns) > 12 else None
            
            # Validar nombre (es obligatorio)
            if pd.isna(nombre):
                continue
            
            nombre = normalizar_nombre_obra(nombre)
            if not nombre or nombre.lower() in ['obras sociales', 'obra social', 'nombre']:
                continue
            
            estado = estado_desde_vigente_celda(vigente)
            
            # Procesar precio (puede estar vacío para obras cortadas)
            precio_normalizado = None
            if not pd.isna(precio):
                precio_str = str(precio).strip()
                precio_normalizado = normalizar_precio_argentino(precio_str)
            
            # Guardar obra sin convenio/suspendida (con o sin precio)
            if estado in ['sin_convenio', 'suspendida']:
                obras_cortadas_dict[nombre] = {
                    'precio': precio_normalizado,
                    'estado': estado
                }
            
            # Solo vigentes: precio válido (>0) o conservar precio actual
            if estado == 'vigente':
                if precio_normalizado is not None and es_precio_real(precio_normalizado):
                    obras_dict[nombre] = precio_normalizado
                else:
                    prev = obras_actuales.get(nombre)
                    if prev and es_precio_real(prev):
                        obras_dict[nombre] = prev
                    elif not pd.isna(precio):
                        logger.warning(f"Obra vigente {nombre} tiene precio inválido o cero: {precio}")
        
        # Comparar con precios actuales y solo incluir cambios
        # Cargar estado actual completo para comparar cambios de estado (claves normalizadas para coincidir con nombre del Excel)
        estado_actual_data = load_obras_estado()
        obras_estado_actual = {normalizar_nombre_obra(k): v for k, v in (estado_actual_data.get('obras') or {}).items() if normalizar_nombre_obra(k)}
        
        cambios_dict = {}
        
        # Procesar obras vigentes con cambios de precio o estado
        for nombre, precio_nuevo in obras_dict.items():
            precio_actual = obras_actuales.get(nombre)
            obra_estado_actual = obras_estado_actual.get(nombre, {})
            estado_anterior = obra_estado_actual.get('estado')
            tiene_precio_real = es_precio_real(precio_actual)
            estado_cambio_a_vigente = estado_anterior in ['suspendida', 'sin_convenio']
            
            # Incluir cambios cuando:
            # - cambia de estado a vigente, o
            # - no tenía precio real, o
            # - cambia el precio
            if estado_cambio_a_vigente or (not tiene_precio_real) or comparar_precios(precio_actual, precio_nuevo):
                if estado_cambio_a_vigente:
                    precio_actual_display = 'Suspendida' if estado_anterior == 'suspendida' else 'Sin convenio'
                    cambio = 'a_vigente'
                elif not tiene_precio_real:
                    # Obra sin precio actual: puede ser nueva o pasar de suspendida/sin convenio a vigente
                    if estado_anterior == 'suspendida':
                        precio_actual_display = 'Suspendida'
                        cambio = 'a_vigente'
                    elif estado_anterior == 'sin_convenio':
                        precio_actual_display = 'Sin convenio'
                        cambio = 'a_vigente'
                    else:
                        precio_actual_display = None
                        cambio = 'nuevo'
                else:
                    precio_actual_display = precio_actual
                    cambio = 'modificado'
                cambios_dict[nombre] = {
                    'precio_actual': precio_actual_display,
                    'precio_nuevo': precio_nuevo,
                    'cambio': cambio,
                    'estado': 'vigente'
                }
        
        # Agregar obras sin convenio/suspendidas cuando cambian de estado o precio
        for nombre, datos_no_vigente in obras_cortadas_dict.items():
            # Verificar el estado actual de la obra
            obra_estado_actual = obras_estado_actual.get(nombre, {})
            estado_anterior = obra_estado_actual.get('estado', 'vigente')  # Si no existe, asumimos que estaba vigente
            estado_nuevo = datos_no_vigente.get('estado', 'sin_convenio')
            
            if estado_anterior == 'vigente':
                # Vigente → suspendida/sin convenio: incluir precio del Excel (o conservar actual si Excel vacío/0)
                precio_excel = datos_no_vigente.get('precio')
                precio_actual = obras_actuales.get(nombre) or obra_estado_actual.get('precio')
                # Si Excel no trae precio real, al importar se conserva el actual; mostrarlo en preview
                # Mostrar lo que trae OneDrive (incluido 0); solo usar precio_actual si la celda está vacía
                precio_nuevo_display = precio_excel if precio_excel is not None else precio_actual
                cambios_dict[nombre] = {
                    'precio_actual': precio_actual,
                    'precio_nuevo': precio_nuevo_display,
                    'cambio': estado_nuevo,
                    'estado': estado_nuevo
                }
            elif estado_anterior in ['suspendida', 'sin_convenio']:
                # Ya estaba no vigente: incluir si cambia estado (sin_convenio<->suspendida) o si cambia precio
                precio_excel = datos_no_vigente.get('precio')
                precio_actual = obra_estado_actual.get('precio')
                estado_cambio = estado_anterior != estado_nuevo
                precio_cambio = precio_excel is not None and es_precio_real(precio_excel) and comparar_precios(precio_actual, precio_excel)
                if estado_cambio or precio_cambio:
                    precio_nuevo_display = precio_excel if precio_excel is not None else precio_actual
                    cambios_dict[nombre] = {
                        'precio_actual': precio_actual,
                        'precio_nuevo': precio_nuevo_display,
                        'cambio': estado_nuevo if estado_cambio else 'modificado',
                        'estado': estado_nuevo
                    }
                # Si Excel no trae precio real, no mostrar como cambio (se conserva el actual)
        
        # También detectar obras que están en la base pero ya NO están en el Excel/OneDrive (borradas del archivo)
        nombres_nuevos = set(obras_dict.keys()) | set(obras_cortadas_dict.keys())
        for nombre_actual, precio_actual in obras_actuales.items():
            if nombre_actual not in nombres_nuevos:
                # No está en el archivo de OneDrive: es un borrado, no "sin convenio"
                obra_estado_actual = obras_estado_actual.get(nombre_actual, {})
                estado_anterior = obra_estado_actual.get('estado', 'vigente')
                # Incluir siempre que exista en nuestra base (vigente o no), para informar que fue borrada del archivo
                cambios_dict[nombre_actual] = {
                    'precio_actual': precio_actual if estado_anterior == 'vigente' else (estado_anterior == 'suspendida' and 'Suspendida' or 'Sin convenio'),
                    'precio_nuevo': 'No está en el archivo de OneDrive',
                    'cambio': 'borrado',
                    'estado': 'borrado'
                }
        
        count = len(cambios_dict)
        cambios_ordenados = dict(sorted(cambios_dict.items()))
        
        total_obras_vigentes = len(obras_dict)
        total_obras_no_vigentes = len(obras_cortadas_dict)
        # Obtener el total real de obras del estado actual (vigentes + no vigentes)
        total_obras_actual = estado_actual_data.get('total_obras', 0)
        if total_obras_actual == 0:
            # Si no hay total en el estado, calcularlo sumando vigentes y no vigentes actuales
            total_obras_actual = len(obras_estado_actual) if obras_estado_actual else (total_obras_vigentes + total_obras_no_vigentes)
        
        if count == 0:
            mensaje = f"No hay cambios. Todas las obras ({total_obras_actual}) ya tienen los precios actualizados."
        else:
            cambios_precio = sum(1 for c in cambios_dict.values() if c['cambio'] in ['nuevo', 'modificado', 'a_vigente'])
            cambios_sin_convenio = sum(1 for c in cambios_dict.values() if c['cambio'] == 'sin_convenio')
            cambios_suspendidas = sum(1 for c in cambios_dict.values() if c['cambio'] == 'suspendida')
            cambios_borrados = sum(1 for c in cambios_dict.values() if c['cambio'] == 'borrado')
            cambios_no_vigentes = cambios_sin_convenio + cambios_suspendidas
            partes = [f"{cambios_precio} precio(s) modificado(s)"]
            if cambios_no_vigentes:
                partes.append(f"{cambios_no_vigentes} no vigente(s) ({cambios_sin_convenio} sin convenio, {cambios_suspendidas} suspendidas)")
            if cambios_borrados:
                partes.append(f"{cambios_borrados} borrada(s) del archivo (ya no están en OneDrive)")
            mensaje = f"Se encontraron {count} cambio(s): " + ", ".join(partes) + "."
        
        return True, mensaje, cambios_ordenados, count
            
    except pd.errors.EmptyDataError:
        return False, "El archivo está vacío o no se pudo leer.", {}, 0
    except Exception as e:
        error_str = str(e)
        # Detectar errores HTTP específicos en el catch general
        if '404' in error_str or 'Not Found' in error_str:
            error_msg = f"Error 404: El archivo no se encontró en la URL. Por favor, verifica que la URL de OneDrive/Google Sheets sea correcta y que el archivo esté compartido públicamente. URL actual: {GOOGLE_SHEET_URL[:80]}..."
        elif '403' in error_str or 'Forbidden' in error_str:
            error_msg = f"Error 403: Acceso denegado. El archivo puede no estar compartido públicamente. Verifica los permisos del archivo en OneDrive/Google Sheets."
        elif '401' in error_str or 'Unauthorized' in error_str:
            error_msg = f"Error 401: No autorizado. El archivo puede requerir autenticación. Verifica que el archivo esté compartido públicamente."
        else:
            error_msg = f"Error al obtener preview: {error_str}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg, {}, 0

def convert_onedrive_url(url):
    """
    Convierte una URL de OneDrive a formato de descarga directa.
    Intenta múltiples formatos para maximizar la compatibilidad.
    
    Para URLs de OneDrive personal (:x:/g/personal/...), a veces la URL original
    funciona mejor que el formato de descarga directa.
    
    Formatos soportados:
    - https://onedrive.live.com/download?resid=RESID
    - https://onedrive.live.com/:x:/g/personal/...?resid=RESID
    - https://onedrive.live.com/download.aspx?resid=RESID
    - https://1drv.ms/x/s!RESID
    - URLs de Google Sheets (exportar como CSV/Excel)
    """
    if not url:
        return url
    
    # Google Sheets: convertir a formato de exportación CSV
    if 'docs.google.com/spreadsheets' in url:
        # Si ya es una URL de exportación, devolver tal cual
        if '/export?' in url:
            return url
        # Convertir URL de Google Sheets a formato de exportación CSV
        # Extraer el ID del documento
        import re
        sheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
        if sheet_id_match:
            sheet_id = sheet_id_match.group(1)
            # Intentar exportar como Excel primero
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx&id={sheet_id}"
        return url
    
    # OneDrive
    if 'onedrive.live.com' in url or '1drv.ms' in url:
        # Si ya tiene formato de descarga directa, devolver tal cual
        if '/download?' in url and 'resid=' in url:
            return url
        if '/download.aspx?' in url and 'resid=' in url:
            return url
        
        # Para URLs con formato :x:/g/personal/..., a veces la URL original funciona mejor
        # Intentamos primero con la URL original modificada para forzar descarga
        if ':x:/g/personal/' in url:
            # Intentar agregar parámetro download=1 si no existe
            if 'download=1' not in url:
                separator = '&' if '?' in url else '?'
                url_with_download = f"{url}{separator}download=1"
                logger.info(f"URL de OneDrive personal detectada, agregando download=1: {url_with_download[:80]}...")
                return url_with_download
            return url
        
        # Intentar extraer resid de la URL (puede estar en diferentes formatos)
        import urllib.parse
        import re
        
        # Buscar resid en los parámetros de la URL
        # Puede estar como: resid=RESID o resid=RESID!suffix
        resid_match = re.search(r'resid=([^&]+)', url)
        if resid_match:
            resid = urllib.parse.unquote(resid_match.group(1))
            # Limpiar el resid de espacios y caracteres extra
            resid = resid.strip()
            
            # Intentar múltiples formatos de descarga
            # Formato 1: download?resid= (formato clásico)
            format1 = f"https://onedrive.live.com/download?resid={resid}"
            # Formato 2: download.aspx?resid= (formato alternativo)
            format2 = f"https://onedrive.live.com/download.aspx?resid={resid}"
            
            logger.info(f"URL de OneDrive convertida (formato 1): {format1}")
            # Retornar el formato 1 primero (más común)
            return format1
        
        # Si es un enlace corto de OneDrive (1drv.ms), necesitaríamos expandirlo
        # Por ahora, devolvemos la URL original
        if '1drv.ms' in url:
            logger.warning(f"URL de OneDrive corta detectada (1drv.ms). Puede requerir expansión manual. URL: {url}")
        
        # Si no tiene resid pero es un enlace de OneDrive, intentar formato alternativo
        # Para archivos compartidos públicamente, a veces funciona el formato original
        logger.warning(f"No se pudo extraer resid de la URL de OneDrive. Intentando con URL original: {url[:80]}...")
        return url
    
    return url

def download_file_with_requests(url):
    """
    Descarga un archivo usando requests como alternativa cuando pandas falla.
    Retorna los bytes del archivo o None si falla.
    
    Para OneDrive, usa headers apropiados para simular un navegador.
    """
    try:
        import requests
        logger.info(f"Intentando descargar archivo con requests desde: {url[:80]}...")
        
        # Headers para simular un navegador (OneDrive a veces requiere esto)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,*/*',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        }
        
        # Para URLs de OneDrive personal, intentar primero sin modificar
        # Si la URL tiene parámetros, agregar download=1 si no existe
        if ':x:/g/personal/' in url and 'download=1' not in url:
            separator = '&' if '?' in url else '?'
            url_with_download = f"{url}{separator}download=1"
            logger.info(f"Intentando con download=1: {url_with_download[:80]}...")
            try:
                response = requests.get(url_with_download, headers=headers, timeout=30, allow_redirects=True)
                response.raise_for_status()
                # Verificar que el contenido sea realmente un archivo Excel
                content_type = response.headers.get('Content-Type', '').lower()
                if 'excel' in content_type or 'spreadsheet' in content_type or 'application/vnd' in content_type:
                    logger.info(f"Archivo descargado exitosamente (Content-Type: {content_type})")
                    return response.content
                elif len(response.content) > 1000:  # Si tiene contenido significativo, asumir que es válido
                    logger.info(f"Archivo descargado exitosamente (tamaño: {len(response.content)} bytes)")
                    return response.content
            except Exception as e1:
                logger.warning(f"Error con download=1, intentando URL original: {e1}")
        
        # Intentar con la URL original
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        response.raise_for_status()
        
        # Verificar que el contenido sea realmente un archivo Excel
        content_type = response.headers.get('Content-Type', '').lower()
        if 'excel' in content_type or 'spreadsheet' in content_type or 'application/vnd' in content_type:
            logger.info(f"Archivo descargado exitosamente (Content-Type: {content_type})")
            return response.content
        elif len(response.content) > 1000:  # Si tiene contenido significativo, asumir que es válido
            logger.info(f"Archivo descargado exitosamente (tamaño: {len(response.content)} bytes)")
            return response.content
        else:
            logger.warning(f"Respuesta recibida pero contenido sospechoso (Content-Type: {content_type}, tamaño: {len(response.content)} bytes)")
            # De todas formas, intentar devolverlo si tiene algún contenido
            if len(response.content) > 100:
                return response.content
            return None
            
    except ImportError:
        logger.warning("La biblioteca 'requests' no está instalada. Instálala con: pip install requests")
        return None
    except Exception as e:
        logger.error(f"Error al descargar archivo con requests: {e}")
        return None

def sync_precios_google_sheet():
    """
    Sincroniza los precios de obras sociales desde un Google Sheet/OneDrive Excel.
    
    Lee dos bloques de datos:
    - Bloque 1: Nombre en Columna B, Precio (UB) en Columna F
    - Bloque 2: Nombre en Columna K, Precio (UB) en Columna O
    
    Retorna:
        tuple: (success: bool, message: str, count: int)
    """
    if not GOOGLE_SHEET_URL:
        return False, "URL del archivo no configurada. Por favor, configura GOOGLE_SHEET_URL en app.py o en variables de entorno.", 0
    
    try:
        logger.info(f"Leyendo archivo desde: {GOOGLE_SHEET_URL}")
        df = None
        
        # Convertir URL de OneDrive a formato de descarga si es necesario
        url = convert_onedrive_url(GOOGLE_SHEET_URL)
        logger.info(f"URL convertida para descarga: {url}")
        
        # Intentar múltiples métodos de descarga
        # Método 1: Leer directamente con pandas (más rápido)
        try:
            df = pd.read_excel(url, engine='openpyxl', header=None)
            logger.info("Archivo leído exitosamente con pandas.read_excel")
        except Exception as e:
            error_str = str(e)
            logger.warning(f"No se pudo leer directamente con pandas: {e}")
            
            # Método 2: Intentar con formato alternativo de OneDrive
            if 'onedrive.live.com' in url and '/download?' in url:
                try:
                    # Intentar con download.aspx en lugar de download?
                    alt_url = url.replace('/download?', '/download.aspx?')
                    logger.info(f"Intentando formato alternativo: {alt_url[:80]}...")
                    df = pd.read_excel(alt_url, engine='openpyxl', header=None)
                    logger.info("Archivo leído exitosamente con formato alternativo")
                except Exception as alt_e:
                    logger.warning(f"Formato alternativo también falló: {alt_e}")
            
            # Método 3: Si pandas falla, intentar descargar con requests y leer desde memoria
            if df is None:
                file_content = download_file_with_requests(url)
                if file_content:
                    try:
                        df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl', header=None)
                        logger.info("Archivo descargado y leído exitosamente con requests + pandas")
                    except Exception as mem_e:
                        logger.error(f"Error al leer archivo desde memoria: {mem_e}")
                        # Intentar formato alternativo con requests
                        if 'onedrive.live.com' in url and '/download?' in url:
                            alt_url = url.replace('/download?', '/download.aspx?')
                            file_content = download_file_with_requests(alt_url)
                            if file_content:
                                df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl', header=None)
                                logger.info("Archivo descargado con formato alternativo y leído exitosamente")
            
            # Si aún falla, verificar errores HTTP específicos
            if df is None:
                if '404' in error_str or 'Not Found' in error_str:
                    return False, f"Error 404: El archivo no se encontró en la URL. Por favor, verifica que la URL de OneDrive/Google Sheets sea correcta y que el archivo esté compartido públicamente. URL actual: {GOOGLE_SHEET_URL[:80]}...", 0
                elif '403' in error_str or 'Forbidden' in error_str:
                    return False, f"Error 403: Acceso denegado. El archivo puede no estar compartido públicamente. Verifica los permisos del archivo en OneDrive/Google Sheets.", 0
                elif '401' in error_str or 'Unauthorized' in error_str:
                    return False, f"Error 401: No autorizado. El archivo puede requerir autenticación. Verifica que el archivo esté compartido públicamente.", 0
                else:
                    raise e
        
        if df is None:
            raise Exception("No se pudo leer el archivo con ningún método")
        
        obras_dict = {}  # Para obras_entero.txt (solo activas)
        obras_estado_dict = {}  # Para obras_estado.json (todas con estado)
        
        # Cargar estado previo para preservar precios de suspendidas/sin convenio cuando el Excel viene vacío
        estado_previo = load_obras_estado()
        obras_previas = estado_previo.get('obras', {})
        # Claves normalizadas (y por minúsculas para coincidir aunque el Excel cambie mayúsculas)
        obras_previas_norm = {}
        obras_previas_por_lower = {}
        for k, v in obras_previas.items():
            n = normalizar_nombre_obra(k)
            if n:
                obras_previas_norm[n] = v
                obras_previas_por_lower[n.lower()] = v
        obras_entero_previas = load_current_obras()  # claves normalizadas
        obras_entero_por_lower = {k.lower(): v for k, v in obras_entero_previas.items()}
        
        def _obtener_precio_previo(nombre):
            """Obtiene precio previo por nombre normalizado: exacto y luego por minúsculas (sin convenio)."""
            # Exacto
            p = obras_entero_previas.get(nombre)
            if p and es_precio_real(p):
                return p
            datos = obras_previas_norm.get(nombre)
            if isinstance(datos, dict) and datos.get('precio') and es_precio_real(datos.get('precio')):
                return datos.get('precio')
            # Por minúsculas (por si el Excel tiene otro uso de mayúsculas)
            p = obras_entero_por_lower.get(nombre.lower())
            if p and es_precio_real(p):
                return p
            datos = obras_previas_por_lower.get(nombre.lower())
            if isinstance(datos, dict) and datos.get('precio') and es_precio_real(datos.get('precio')):
                return datos.get('precio')
            return None
        
        def precio_final(nombre, estado, precio_normalizado, ya_en_dict=None):
            """Para suspendidas/sin convenio: si OneDrive trae valor (incluso 0), usarlo. Solo conservar previo si la celda está vacía."""
            # Si Excel trae un valor (incluido 0), ese es el que importamos
            if precio_normalizado is not None:
                return precio_normalizado
            # Solo si la celda está vacía: conservar precio previo
            if estado in ['suspendida', 'sin_convenio']:
                prev_precio = (ya_en_dict if ya_en_dict is not None and es_precio_real(ya_en_dict) else None
                               or _obtener_precio_previo(nombre))
                if prev_precio and es_precio_real(prev_precio):
                    return prev_precio
            return None
        
        # Bloque 1: Columna B (índice 1) = Nombre, Columna F (índice 5) = Precio
        # Bloque 2: Columna K (índice 10) = Nombre, Columna O (índice 14) = Precio
        # Los datos empiezan en la fila 3 (índice 2), después de los encabezados
        
        # Procesar Bloque 1 (Columnas B, D=vigente, F=precio)
        for idx in range(2, len(df)):  # Empezar desde fila 3 (índice 2)
            nombre = df.iloc[idx, 1] if len(df.columns) > 1 else None  # Columna B (índice 1)
            precio = df.iloc[idx, 5] if len(df.columns) > 5 else None  # Columna F (índice 5)
            vigente = df.iloc[idx, 3] if len(df.columns) > 3 else None  # Columna D (índice 3) = Vigente
            
            # Validar nombre (es obligatorio)
            if pd.isna(nombre):
                continue
            
            nombre = normalizar_nombre_obra(nombre)
            if not nombre or nombre.lower() in ['obras sociales', 'obra social', 'nombre']:
                continue
            
            estado = estado_desde_vigente_celda(vigente)
            
            # Procesar precio (puede estar vacío para obras cortadas; acepta número de Excel)
            precio_normalizado = None
            if pd.notna(precio) and precio != '':
                precio_normalizado = normalizar_precio_argentino(precio)
            
            # Para vigente con precio 0/vacío: conservar precio previo (no sobrescribir con 0)
            if estado == 'vigente' and (precio_normalizado is None or not es_precio_real(precio_normalizado)):
                prev_datos = obras_previas_norm.get(nombre) or {}
                precio_normalizado = ((prev_datos.get('precio') if isinstance(prev_datos, dict) else None) or
                                      obras_entero_previas.get(nombre) or precio_normalizado)
            # Para suspendidas/sin convenio: conservar precio previo si Excel viene vacío
            precio_a_guardar = precio_final(nombre, estado, precio_normalizado)
            
            # Guardar en obras_estado_dict (todas las obras con su estado, incluso sin precio)
            obras_estado_dict[nombre] = {
                'precio': precio_a_guardar,
                'estado': estado,
                'ultima_actualizacion': datetime.now().isoformat()
            }
            
            # obras_entero.txt: vigentes con precio; sin convenio/suspendida con precio conservado también (para que el valor se mantenga)
            if estado == 'vigente':
                if precio_normalizado is not None and es_precio_real(precio_normalizado):
                    obras_dict[nombre] = precio_normalizado
                else:
                    prev = (obras_previas_norm.get(nombre) or {}).get('precio') if isinstance(obras_previas_norm.get(nombre), dict) else None
                    prev = prev or obras_entero_previas.get(nombre)
                    if prev and es_precio_real(prev):
                        obras_dict[nombre] = prev
                    elif not pd.isna(precio):
                        logger.warning(f"Obra vigente {nombre} tiene precio inválido o cero: {precio}")
            elif estado in ['sin_convenio', 'suspendida']:
                # Solo agregar a obras_entero.txt si tienen precio > 0. Si OneDrive trae 0, no agregar (se muestra 0 desde JSON)
                if precio_a_guardar and es_precio_real(precio_a_guardar):
                    obras_dict[nombre] = precio_a_guardar
        
        # Procesar Bloque 2 (Columnas K, M=vigente, O=precio)
        for idx in range(2, len(df)):  # Empezar desde fila 3 (índice 2)
            nombre = df.iloc[idx, 10] if len(df.columns) > 10 else None  # Columna K (índice 10)
            precio = df.iloc[idx, 14] if len(df.columns) > 14 else None  # Columna O (índice 14)
            vigente = df.iloc[idx, 12] if len(df.columns) > 12 else None  # Columna M (índice 12) = Vigente
            
            # Validar nombre (es obligatorio)
            if pd.isna(nombre):
                continue
            
            nombre = normalizar_nombre_obra(nombre)
            if not nombre or nombre.lower() in ['obras sociales', 'obra social', 'nombre']:
                continue
            
            estado = estado_desde_vigente_celda(vigente)
            
            # Procesar precio (puede estar vacío para obras cortadas; acepta número de Excel)
            precio_normalizado = None
            if pd.notna(precio) and precio != '':
                precio_normalizado = normalizar_precio_argentino(precio)
            
            # Para vigente con precio 0/vacío: conservar precio previo
            if estado == 'vigente' and (precio_normalizado is None or not es_precio_real(precio_normalizado)):
                prev_datos = obras_previas_norm.get(nombre)
                prev_p = (prev_datos.get('precio') if isinstance(prev_datos, dict) else None) or obras_entero_previas.get(nombre)
                precio_normalizado = obras_estado_dict.get(nombre, {}).get('precio') or prev_p or precio_normalizado
            precio_existente = obras_estado_dict.get(nombre, {}).get('precio') if nombre in obras_estado_dict else None
            precio_a_guardar = precio_final(nombre, estado, precio_normalizado, ya_en_dict=precio_existente)
            
            # Guardar en obras_estado_dict (todas las obras con su estado, incluso sin precio)
            obras_estado_dict[nombre] = {
                'precio': precio_a_guardar,
                'estado': estado,
                'ultima_actualizacion': datetime.now().isoformat()
            }
            
            # obras_entero.txt: vigentes con precio; sin convenio/suspendida con precio conservado también
            if estado == 'vigente':
                if precio_normalizado is not None and es_precio_real(precio_normalizado):
                    obras_dict[nombre] = precio_normalizado
                else:
                    prev = precio_existente or (obras_previas_norm.get(nombre) or {}).get('precio') or obras_entero_previas.get(nombre)
                    if prev and es_precio_real(prev):
                        obras_dict[nombre] = prev
                    elif not pd.isna(precio):
                        logger.warning(f"Obra vigente {nombre} tiene precio inválido o cero: {precio}")
            elif estado in ['sin_convenio', 'suspendida']:
                if precio_a_guardar and es_precio_real(precio_a_guardar):
                    obras_dict[nombre] = precio_a_guardar
        
        # Persistir todas las obras en la DB (upsert por nombre) + historial
        if obras_estado_dict:
            ahora = datetime.now(ZoneInfo('America/Argentina/Buenos_Aires')).replace(tzinfo=None)
            for nombre, datos in obras_estado_dict.items():
                obra = ObraSocial.query.filter_by(nombre=nombre).first()
                precio_nuevo = datos.get('precio')
                estado_nuevo = datos.get('estado', 'vigente')

                # Capturar valores previos para historial
                precio_anterior = obra.precio if obra else None
                estado_anterior = obra.estado if obra else None

                if not obra:
                    obra = ObraSocial(nombre=nombre)
                    db.session.add(obra)

                obra.precio = precio_nuevo
                obra.estado = estado_nuevo
                obra.ultima_actualizacion = datos.get('ultima_actualizacion', ahora.isoformat())

                # Registrar historial solo si cambió precio o estado
                precio_cambio = comparar_precios(precio_anterior, precio_nuevo)
                estado_cambio = (estado_anterior or 'vigente') != (estado_nuevo or 'vigente')
                if precio_cambio or estado_cambio:
                    db.session.add(ObraSocialHistorial(
                        obra_nombre=nombre,
                        fecha=ahora,
                        precio_anterior=precio_anterior,
                        precio_nuevo=precio_nuevo,
                        estado_anterior=estado_anterior,
                        estado_nuevo=estado_nuevo,
                    ))

            try:
                db.session.commit()
            except Exception as db_err:
                db.session.rollback()
                logger.error(f"Error al guardar obras en DB durante sync: {db_err}")
                return False, f"Error al guardar en base de datos: {db_err}", 0

            count = len(obras_dict) if obras_dict else 0
            total_count = len(obras_estado_dict)
            sin_convenio_count = sum(1 for o in obras_estado_dict.values() if o['estado'] == 'sin_convenio')
            suspendidas_count = sum(1 for o in obras_estado_dict.values() if o['estado'] == 'suspendida')
            no_vigentes_count = sin_convenio_count + suspendidas_count
            logger.info(f"Sincronización completada: {count} obras activas, {total_count} total ({sin_convenio_count} sin convenio, {suspendidas_count} suspendidas)")
            return True, f"Sincronización exitosa: {count} obras activas importadas ({total_count} total, {no_vigentes_count} no vigentes).", count
        else:
            return False, "No se encontraron obras sociales válidas en el archivo.", 0
            
    except pd.errors.EmptyDataError:
        error_msg = "El archivo está vacío o no se pudo leer."
        logger.error(error_msg)
        return False, f"{error_msg}", 0
    except Exception as e:
        error_str = str(e)
        # Detectar errores HTTP específicos
        if '404' in error_str or 'Not Found' in error_str:
            error_msg = f"Error 404: El archivo no se encontró en la URL. Por favor, verifica que la URL de OneDrive/Google Sheets sea correcta y que el archivo esté compartido públicamente. URL actual: {GOOGLE_SHEET_URL[:80]}..."
        elif '403' in error_str or 'Forbidden' in error_str:
            error_msg = f"Error 403: Acceso denegado. El archivo puede no estar compartido públicamente. Verifica los permisos del archivo en OneDrive/Google Sheets."
        elif '401' in error_str or 'Unauthorized' in error_str:
            error_msg = f"Error 401: No autorizado. El archivo puede requerir autenticación. Verifica que el archivo esté compartido públicamente."
        else:
            error_msg = f"Error al sincronizar precios: {error_str}"
        logger.error(error_msg, exc_info=True)
        return False, f"{error_msg}", 0

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
            
            # Agregar nuevo usuario
            users[username] = {
                'password': generate_password_hash(password),
                'habilitado': True
            }
            
            if save_users(users):
                flash(f'Usuario {username} agregado y habilitado correctamente.', 'success')
                logger.info(f"Usuario {username} agregado por {session.get('username')}")
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
        
        # Manejar subida de logo
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename:
                # Validar extensión
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
                filename = secure_filename(file.filename)
                if '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    # Guardar con nombre único basado en username
                    extension = filename.rsplit('.', 1)[1].lower()
                    logo_filename = f'logo_{username}.{extension}'
                    logo_path = os.path.join(LOGO_FOLDER, logo_filename)
                    file.save(logo_path)
                    perfil['logo_path'] = logo_filename
                    logger.info(f"Logo guardado para usuario {username}: {logo_filename}")
        
        # Manejar subida de imagen de firma
        if 'firma_imagen' in request.files:
            file = request.files['firma_imagen']
            if file and file.filename:
                # Validar extensión
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
                filename = secure_filename(file.filename)
                if '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    # Guardar con nombre único basado en username
                    extension = filename.rsplit('.', 1)[1].lower()
                    firma_filename = f'firma_{username}.{extension}'
                    firma_path = os.path.join(LOGO_FOLDER, firma_filename)
                    file.save(firma_path)
                    perfil['firma_path'] = firma_filename
                    logger.info(f"Imagen de firma guardada para usuario {username}: {firma_filename}")
        
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
            def __init__(self, perfil, fecha_presupuesto, safe_text_func):
                super().__init__()
                self.perfil = perfil
                self.fecha_presupuesto = fecha_presupuesto
                self.safe_text = safe_text_func
                self.set_auto_page_break(auto=True, margin=15)
                self._header_rendering = False  # Bandera para evitar recursión
                self.y_linea_separadora = None  # Guardar posición Y de la línea separadora
            
            def header(self):
                if self._header_rendering:
                    return
                self._header_rendering = True
                
                try:
                    # A. LOGO (Fijo a la izquierda)
                    if self.perfil.get('logo_path'):
                        logo_full_path = os.path.join(LOGO_FOLDER, self.perfil['logo_path'])
                        if os.path.exists(logo_full_path):
                            try:
                                self.image(logo_full_path, x=10, y=10, w=25)
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
                    
                    # Profesionales (Bajamos 6mm)
                    self.set_y(25)
                    self.set_x(0)
                    self.set_font('Helvetica', '', 9)
                    profesionales_text = self.safe_text(self.perfil.get('profesionales', ''))
                    if profesionales_text:
                        self.cell(0, 5, profesionales_text, align='C', ln=1)
                    
                    # Dirección (Bajamos 5mm)
                    self.set_y(30)
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
                    
                    # C. LÍNEA DIVISORIA (Bajamos a 38mm para que NO corte el texto)
                    self.set_draw_color(0, 0, 0)
                    self.set_line_width(0.5)
                    self.line(10, 38, 200, 38)
                    self.set_line_width(0.2)
                    
                    # Guardar posición Y de la línea separadora para usar en el cuerpo
                    self.y_linea_separadora = 38
                    
                    # D. FECHA (Debajo de la línea, a la derecha) - Se dibuja en el cuerpo, no en el header
                    # El header solo establece la línea separadora
                
                finally:
                    self._header_rendering = False
                    # Margen para que el cuerpo empiece limpio
                    self.set_y(50)
            
        
        # Crear PDF con header automático
        pdf = PDFConHeader(perfil, fecha_presupuesto, safe_text)
        pdf.add_page()  # El header se dibujará automáticamente
        
        # Fecha - debajo de la línea separadora (solo en la primera página, no parte del header)
        # Fecha claramente DEBAJO de la línea divisoria, alineada a la derecha
        meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 
                 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
        fecha_str = f"{fecha_presupuesto.day} de {meses[fecha_presupuesto.month - 1]} {fecha_presupuesto.year}"
        ciudad = safe_text(perfil.get('ciudad', ''))
        fecha_formateada = f"{fecha_str}, {ciudad}"
        
        # Fecha en Y = 40 (debajo de la línea separadora en Y = 38)
        pdf.set_y(40)
        pdf.set_x(0)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 5, fecha_formateada, align='R', ln=1)
        
        # Establecer posición Y después de la fecha
        pdf.set_y(50)
        
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
            
            # Si hay imagen de firma, mostrarla primero
            if firma_path:
                firma_full_path = os.path.join(LOGO_FOLDER, firma_path)
                if os.path.exists(firma_full_path):
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Solo debug=True en desarrollo, no en producción
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
