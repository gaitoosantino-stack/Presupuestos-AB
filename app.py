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
# Log de accesos de Daniel (solo fecha y hora)
DANIEL_LOG_FILE = 'log_daniel.txt'
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
# URL del archivo Excel/CSV para sincronización de precios (configurar aquí o en variable de entorno)
# Puede ser Google Sheets (CSV) o OneDrive/Excel (.xlsx)
# Ejemplo OneDrive: https://onedrive.live.com/download?resid=RESID
GOOGLE_SHEET_URL = os.environ.get('GOOGLE_SHEET_URL', 'https://onedrive.live.com/:x:/g/personal/4296EB0072506AFB/EcVnvhhOjqJMgDlQhEhMBbcBbFfE6VxrdwBR4ByfAvkIQw?resid=4296EB0072506AFB!s18be67c58e4e4ca280395084484c05b7&ithint=file%2Cxlsx&e=6RQ06elsx&migratedtospo=true&redeem=aHR0cHM6Ly8xZHJ2Lm1zL3gvYy80Mjk2ZWIwMDcyNTA2YWZiL0VjVm52aGhPanFKTWdEbFFoRWhNQmJjQmJGZkU2VnhyZHdCUjRCeWZBdmtJUXc_ZT02UlEwNmVsc3g')

def init_users_file():
    """Inicializa el archivo de usuarios si no existe"""
    if not os.path.exists(USERS_FILE):
        # Crear archivo con usuarios administradores
        default_users = {
            'Gaito': {
                'password': generate_password_hash('Simon@594*'),
                'email': '',
                'habilitado': True
            },
            'DanielABNECH': {
                'password': generate_password_hash('Paraguay37'),
                'email': '',
                'habilitado': True
            }
        }
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_users, f, indent=2, ensure_ascii=False)
        logger.info("Archivo de usuarios creado con usuario Gaito")
    else:
        # Verificar que Gaito y usuario 3 existan, si no existen agregarlos
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users = json.load(f)
            modified = False
            if 'Gaito' not in users:
                users['Gaito'] = {
                    'password': generate_password_hash('Simon@594*'),
                    'email': '',
                    'habilitado': True
                }
                modified = True
                logger.info("Usuario Gaito agregado al archivo de usuarios")
            if '3' not in users:
                users['3'] = {
                    'password': generate_password_hash('3'),
                    'email': '',
                    'habilitado': True
                }
                modified = True
                logger.info("Usuario 3 agregado al archivo de usuarios")
            if 'DanielABNECH' not in users:
                users['DanielABNECH'] = {
                    'password': generate_password_hash('Paraguay37'),
                    'email': '',
                    'habilitado': True
                }
                modified = True
                logger.info("Usuario DanielABNECH agregado al archivo de usuarios")
            if modified:
                with open(USERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(users, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error al verificar usuarios admin: {e}")

def load_users():
    """Carga los usuarios desde el archivo JSON"""
    init_users_file()
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error al cargar usuarios: {e}")
        return {}

def save_users(users):
    """Guarda los usuarios en el archivo JSON"""
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error al guardar usuarios: {e}")
        return False

def init_perfiles_file():
    """Inicializa el archivo de perfiles si no existe"""
    if not os.path.exists(PERFILES_FILE):
        default_perfiles = {}
        with open(PERFILES_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_perfiles, f, indent=2, ensure_ascii=False)
        logger.info("Archivo de perfiles creado")

def load_perfiles():
    """Carga los perfiles desde el archivo JSON"""
    init_perfiles_file()
    try:
        with open(PERFILES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error al cargar perfiles: {e}")
        return {}

def save_perfiles(perfiles):
    """Guarda los perfiles en el archivo JSON"""
    try:
        with open(PERFILES_FILE, 'w', encoding='utf-8') as f:
            json.dump(perfiles, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error al guardar perfiles: {e}")
        return False

def get_lab_profile(username):
    """Obtiene el perfil del laboratorio para un usuario. Devuelve valores por defecto si no existe."""
    perfiles = load_perfiles()
    
    if username in perfiles:
        return perfiles[username]
    
    # Valores por defecto genéricos
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
        'firma_path': ''
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

# Inicializar archivos al iniciar
init_users_file()
init_perfiles_file()

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
                if username == 'DanielABNECH':
                    try:
                        with open(DANIEL_LOG_FILE, 'a', encoding='utf-8') as f:
                            ahora_argentina = datetime.now(ZoneInfo('America/Argentina/Buenos_Aires'))
                            f.write(ahora_argentina.strftime('%Y-%m-%d %H:%M:%S') + '\n')
                    except OSError:
                        pass
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

    # Leer obras sociales (vigentes y cortadas)
    obras = {}
    obras_estado = {}  # Para almacenar el estado de cada obra
    
    # Primero cargar obras vigentes desde obras_entero.txt
    try:
        with open('obras_entero.txt', 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    obra, precio = line.strip().split(':', 1)
                    # Convertir formato argentino: 1.740,88 -> 1740.88
                    precio = precio.replace('.', '').replace(',', '.')
                    obras[obra] = precio
                    obras_estado[obra] = 'vigente'
    except FileNotFoundError:
        logger.error("Archivo obras_entero.txt no encontrado")
    except Exception as e:
        logger.error(f"Error al leer obras sociales: {e}")
    
    # Luego cargar obras cortadas desde obras_estado.json
    try:
        estado_data = load_obras_estado()
        if estado_data and 'obras' in estado_data:
            for nombre_obra, info_obra in estado_data['obras'].items():
                estado_obra = info_obra.get('estado')
                if estado_obra in ['sin_convenio', 'suspendida']:
                    # Agregar obra sin convenio/suspendida (con precio si existe, o None)
                    precio_cortada = info_obra.get('precio')
                    if precio_cortada:
                        # Convertir a formato numérico si es string
                        if isinstance(precio_cortada, str):
                            precio_cortada = precio_cortada.replace('.', '').replace(',', '.')
                        obras[nombre_obra] = str(precio_cortada)
                    else:
                        obras[nombre_obra] = None
                    obras_estado[nombre_obra] = estado_obra
    except Exception as e:
        logger.error(f"Error al cargar obras cortadas: {e}")
    
    # Ordenar alfabéticamente
    obras = dict(sorted(obras.items()))

    # Leer estudios desde CODIGO_ESTUDIO_UB.txt (archivo principal)
    estudios = {}
    try:
        with open('CODIGO_ESTUDIO_UB.txt', 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    parts = line.strip().split(':', 2)
                    if len(parts) == 3:
                        codigo, estudio, ub = parts
                        estudios[codigo] = {'nombre': estudio, 'ub': ub.replace(',', '.')}
    except FileNotFoundError:
        logger.error("Archivo CODIGO_ESTUDIO_UB.txt no encontrado")
        estudios = {}
    except Exception as e:
        logger.error(f"Error al leer estudios desde CODIGO_ESTUDIO_UB.txt: {e}")
        estudios = {}
    
    # Leer estudios adicionales desde Anexo_Codigos.txt (solo los que no están ya en estudios)
    try:
        with open(ANEXO_CODIGOS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    parts = line.strip().split(':', 2)
                    if len(parts) == 3:
                        codigo, estudio, ub = parts
                        # Solo agregar si no existe ya (evitar duplicados)
                        if codigo not in estudios:
                            estudios[codigo] = {'nombre': estudio, 'ub': ub.replace(',', '.')}
    except FileNotFoundError:
        logger.warning(f"Archivo {ANEXO_CODIGOS_FILE} no encontrado, continuando sin estudios de anexo adicionales")
    except Exception as e:
        logger.error(f"Error al leer estudios desde {ANEXO_CODIGOS_FILE}: {e}")

    # Cargar configuración de anexo
    anexo_config = load_anexo_config()
    codigos_anexo = load_anexo_codigos()
    precio_particular = get_precio_particular()
    
    # Convertir set a lista para JSON serialization en el template
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
    """
    if not precio_str or precio_str == '' or precio_str.lower() == 'nan':
        return None
    
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

def load_current_obras():
    """Carga las obras sociales actuales desde obras_entero.txt"""
    obras = {}
    try:
        if os.path.exists(OBRAS_FILE):
            with open(OBRAS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if ':' in line:
                        obra, precio = line.strip().split(':', 1)
                        obras[obra] = precio
    except Exception as e:
        logger.error(f"Error al leer obras actuales: {e}")
    return obras

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
        
        obras_dict = {}  # Todas las obras del Excel (vigentes y cortadas)
        obras_cortadas_dict = {}  # Obras cortadas para el preview
        
        # Procesar Bloque 1 (Columnas B y F)
        for idx in range(2, len(df)):
            nombre = df.iloc[idx, 1] if len(df.columns) > 1 else None
            precio = df.iloc[idx, 5] if len(df.columns) > 5 else None
            vigente = df.iloc[idx, 3] if len(df.columns) > 3 else None
            
            # Validar nombre (es obligatorio)
            if pd.isna(nombre):
                continue
            
            nombre = str(nombre).strip()
            
            if not nombre or nombre == '' or nombre.lower() in ['obras sociales', 'obra social', 'nombre']:
                continue
            
            # Determinar estado
            estado = 'vigente'
            if not pd.isna(vigente):
                vigente_str = str(vigente).strip().lower()
                if vigente_str in ['sin convenio', 'sinconvenio', 'cortada']:
                    estado = 'sin_convenio'
                elif vigente_str in ['suspendida', 'suspendid']:
                    estado = 'suspendida'
            
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
            
            # Solo guardar en obras_dict si está vigente Y tiene precio válido
            if estado == 'vigente':
                if precio_normalizado is not None:
                    obras_dict[nombre] = precio_normalizado
                # Si está vigente pero no tiene precio válido, la saltamos (no debería pasar)
                elif not pd.isna(precio):
                    logger.warning(f"Obra vigente {nombre} tiene precio inválido: {precio}")
        
        # Procesar Bloque 2 (Columnas K y O)
        for idx in range(2, len(df)):
            nombre = df.iloc[idx, 10] if len(df.columns) > 10 else None
            precio = df.iloc[idx, 14] if len(df.columns) > 14 else None
            vigente = df.iloc[idx, 12] if len(df.columns) > 12 else None
            
            # Validar nombre (es obligatorio)
            if pd.isna(nombre):
                continue
            
            nombre = str(nombre).strip()
            
            if not nombre or nombre == '' or nombre.lower() in ['obras sociales', 'obra social', 'nombre']:
                continue
            
            # Determinar estado
            estado = 'vigente'
            if not pd.isna(vigente):
                vigente_str = str(vigente).strip().lower()
                if vigente_str in ['sin convenio', 'sinconvenio', 'cortada']:
                    estado = 'sin_convenio'
                elif vigente_str in ['suspendida', 'suspendid']:
                    estado = 'suspendida'
            
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
            
            # Solo guardar en obras_dict si está vigente Y tiene precio válido
            if estado == 'vigente':
                if precio_normalizado is not None:
                    obras_dict[nombre] = precio_normalizado
                # Si está vigente pero no tiene precio válido, la saltamos (no debería pasar)
                elif not pd.isna(precio):
                    logger.warning(f"Obra vigente {nombre} tiene precio inválido: {precio}")
        
        # Comparar con precios actuales y solo incluir cambios
        obras_actuales = load_current_obras()
        # Cargar estado actual completo para comparar cambios de estado
        estado_actual_data = load_obras_estado()
        obras_estado_actual = estado_actual_data.get('obras', {})
        
        cambios_dict = {}
        
        # Procesar obras vigentes con cambios de precio
        for nombre, precio_nuevo in obras_dict.items():
            precio_actual = obras_actuales.get(nombre)
            obra_estado_actual = obras_estado_actual.get(nombre, {})
            estado_anterior = obra_estado_actual.get('estado')
            tiene_precio_real = es_precio_real(precio_actual)
            
            # Si la obra no existe con precio real o el precio cambió
            if not tiene_precio_real or comparar_precios(precio_actual, precio_nuevo):
                if not tiene_precio_real:
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
        
        # Agregar obras sin convenio/suspendidas SOLO si cambiaron de estado (de vigente a no vigente)
        for nombre, datos_no_vigente in obras_cortadas_dict.items():
            # Verificar el estado actual de la obra
            obra_estado_actual = obras_estado_actual.get(nombre, {})
            estado_anterior = obra_estado_actual.get('estado', 'vigente')  # Si no existe, asumimos que estaba vigente
            
            # Solo incluir si cambió de vigente a no vigente (no si ya estaba no vigente)
            if estado_anterior == 'vigente':
                estado_nuevo = datos_no_vigente.get('estado', 'sin_convenio')
                # Vigente → suspendida/sin convenio: no mostrar precios (el precio no cambia, solo el estado)
                cambios_dict[nombre] = {
                    'precio_actual': None,
                    'precio_nuevo': None,
                    'cambio': estado_nuevo,
                    'estado': estado_nuevo
                }
        
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
        
        # Bloque 1: Columna B (índice 1) = Nombre, Columna F (índice 5) = Precio
        # Bloque 2: Columna K (índice 10) = Nombre, Columna O (índice 14) = Precio
        # Los datos empiezan en la fila 3 (índice 2), después de los encabezados
        
        # Procesar Bloque 1 (Columnas B y F)
        # Columna D (índice 3) = Vigente, Columna B (índice 1) = Nombre, Columna F (índice 5) = Precio
        for idx in range(2, len(df)):  # Empezar desde fila 3 (índice 2)
            nombre = df.iloc[idx, 1] if len(df.columns) > 1 else None  # Columna B (índice 1)
            precio = df.iloc[idx, 5] if len(df.columns) > 5 else None  # Columna F (índice 5)
            vigente = df.iloc[idx, 3] if len(df.columns) > 3 else None  # Columna D (índice 3) = Vigente
            
            # Validar nombre (es obligatorio)
            if pd.isna(nombre):
                continue
            
            nombre = str(nombre).strip()
            
            # Saltar si el nombre está vacío o parece ser un encabezado
            if not nombre or nombre == '' or nombre.lower() in ['obras sociales', 'obra social', 'nombre']:
                continue
            
            # Determinar estado
            estado = 'vigente'
            if not pd.isna(vigente):
                vigente_str = str(vigente).strip().lower()
                if vigente_str in ['sin convenio', 'sinconvenio', 'cortada']:
                    estado = 'sin_convenio'
                elif vigente_str in ['suspendida', 'suspendid']:
                    estado = 'suspendida'
            
            # Procesar precio (puede estar vacío para obras cortadas)
            precio_normalizado = None
            if not pd.isna(precio):
                precio_str = str(precio).strip()
                precio_normalizado = normalizar_precio_argentino(precio_str)
            
            # Guardar en obras_estado_dict (todas las obras con su estado, incluso sin precio)
            obras_estado_dict[nombre] = {
                'precio': precio_normalizado if precio_normalizado else None,
                'estado': estado,
                'ultima_actualizacion': datetime.now().isoformat()
            }
            
            # Solo guardar en obras_dict si está vigente Y tiene precio válido
            if estado == 'vigente':
                if precio_normalizado is not None:
                    obras_dict[nombre] = precio_normalizado
                elif not pd.isna(precio):
                    logger.warning(f"Obra vigente {nombre} tiene precio inválido: {precio}")
        
        # Procesar Bloque 2 (Columnas K y O)
        # Columna M (índice 12) = Vigente, Columna K (índice 10) = Nombre, Columna O (índice 14) = Precio
        for idx in range(2, len(df)):  # Empezar desde fila 3 (índice 2)
            nombre = df.iloc[idx, 10] if len(df.columns) > 10 else None  # Columna K (índice 10)
            precio = df.iloc[idx, 14] if len(df.columns) > 14 else None  # Columna O (índice 14)
            vigente = df.iloc[idx, 12] if len(df.columns) > 12 else None  # Columna M (índice 12) = Vigente
            
            # Validar nombre (es obligatorio)
            if pd.isna(nombre):
                continue
            
            nombre = str(nombre).strip()
            
            # Saltar si el nombre está vacío o parece ser un encabezado
            if not nombre or nombre == '' or nombre.lower() in ['obras sociales', 'obra social', 'nombre']:
                continue
            
            # Determinar estado
            estado = 'vigente'
            if not pd.isna(vigente):
                vigente_str = str(vigente).strip().lower()
                if vigente_str in ['sin convenio', 'sinconvenio', 'cortada']:
                    estado = 'sin_convenio'
                elif vigente_str in ['suspendida', 'suspendid']:
                    estado = 'suspendida'
            
            # Procesar precio (puede estar vacío para obras cortadas)
            precio_normalizado = None
            if not pd.isna(precio):
                precio_str = str(precio).strip()
                precio_normalizado = normalizar_precio_argentino(precio_str)
            
            # Guardar en obras_estado_dict (todas las obras con su estado, incluso sin precio)
            obras_estado_dict[nombre] = {
                'precio': precio_normalizado if precio_normalizado else None,
                'estado': estado,
                'ultima_actualizacion': datetime.now().isoformat()
            }
            
            # Solo guardar en obras_dict si está vigente Y tiene precio válido
            if estado == 'vigente':
                if precio_normalizado is not None:
                    obras_dict[nombre] = precio_normalizado
                elif not pd.isna(precio):
                    logger.warning(f"Obra vigente {nombre} tiene precio inválido: {precio}")
        
        # Escribir el archivo obras_entero.txt (solo obras activas)
        if obras_dict:
            # Ordenar alfabéticamente por nombre
            obras_ordenadas = dict(sorted(obras_dict.items()))
            
            # Escribir al archivo
            with open(OBRAS_FILE, 'w', encoding='utf-8') as f:
                for nombre, precio in obras_ordenadas.items():
                    f.write(f"{nombre}:{precio}\n")
        
        # Escribir el archivo obras_estado.json (todas las obras con estado)
        if obras_estado_dict:
            obras_estado_ordenadas = dict(sorted(obras_estado_dict.items()))
            
            # Agregar metadata
            obras_sin_convenio = sum(1 for o in obras_estado_ordenadas.values() if o['estado'] == 'sin_convenio')
            obras_suspendidas = sum(1 for o in obras_estado_ordenadas.values() if o['estado'] == 'suspendida')
            estado_data = {
                'fecha_actualizacion': datetime.now().isoformat(),
                'total_obras': len(obras_estado_ordenadas),
                'obras_vigentes': sum(1 for o in obras_estado_ordenadas.values() if o['estado'] == 'vigente'),
                'obras_sin_convenio': obras_sin_convenio,
                'obras_suspendidas': obras_suspendidas,
                'obras': obras_estado_ordenadas
            }
            
            with open(OBRAS_ESTADO_FILE, 'w', encoding='utf-8') as f:
                json.dump(estado_data, f, indent=2, ensure_ascii=False)
            
            count = len(obras_dict) if obras_dict else 0
            total_count = len(obras_estado_dict)
            sin_convenio_count = estado_data['obras_sin_convenio']
            suspendidas_count = estado_data['obras_suspendidas']
            no_vigentes_count = sin_convenio_count + suspendidas_count
            logger.info(f"Sincronización completada: {count} obras activas, {total_count} total (incluyendo {sin_convenio_count} sin convenio, {suspendidas_count} suspendidas)")
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
    """Carga el estado de obras sociales desde el archivo JSON"""
    try:
        if os.path.exists(OBRAS_ESTADO_FILE):
            with open(OBRAS_ESTADO_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {
                'fecha_actualizacion': None,
                'total_obras': 0,
                'obras_vigentes': 0,
                'obras_sin_convenio': 0,
                'obras_suspendidas': 0,
                'obras': {}
            }
    except Exception as e:
        logger.error(f"Error al cargar estado de obras: {e}")
        return {
            'fecha_actualizacion': None,
            'total_obras': 0,
            'obras_vigentes': 0,
            'obras_sin_convenio': 0,
            'obras_suspendidas': 0,
            'obras': {}
        }

def load_anexo_config():
    """Carga la configuración de anexo desde el archivo JSON"""
    try:
        if os.path.exists(ANEXO_CONFIG_FILE):
            with open(ANEXO_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {
                'obras_sin_cobertura': []  # Lista de nombres de obras sociales que no cubren anexo
            }
    except Exception as e:
        logger.error(f"Error al cargar configuración de anexo: {e}")
        return {
            'obras_sin_cobertura': []
        }

def save_anexo_config(config):
    """Guarda la configuración de anexo en el archivo JSON"""
    try:
        with open(ANEXO_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error al guardar configuración de anexo: {e}")
        return False

def load_anexo_codigos():
    """Carga los códigos de anexo desde el archivo Anexo_Codigos.txt"""
    codigos_anexo = set()
    try:
        if os.path.exists(ANEXO_CODIGOS_FILE):
            with open(ANEXO_CODIGOS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if ':' in line:
                        # Formato: codigo:nombre:UB
                        parts = line.strip().split(':', 1)
                        if len(parts) >= 1:
                            codigo = parts[0].strip()
                            if codigo:  # Ignorar líneas vacías
                                codigos_anexo.add(codigo)
        logger.info(f"Cargados {len(codigos_anexo)} códigos de anexo")
    except Exception as e:
        logger.error(f"Error al cargar códigos de anexo: {e}")
    return codigos_anexo

def get_precio_particular():
    """Obtiene el precio de Particular desde obras_estado.json o obras_entero.txt"""
    try:
        # Primero intentar desde obras_estado.json
        estado_data = load_obras_estado()
        if 'obras' in estado_data and 'PARTICULAR' in estado_data['obras']:
            precio_str = estado_data['obras']['PARTICULAR'].get('precio', '3000,00')
            # Convertir formato argentino a float
            precio = precio_str.replace('.', '').replace(',', '.')
            return float(precio)
    except Exception as e:
        logger.warning(f"Error al obtener precio de Particular desde obras_estado.json: {e}")
    
    # Si falla, intentar desde obras_entero.txt
    try:
        with open(OBRAS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('PARTICULAR:'):
                    precio_str = line.split(':', 1)[1].strip()
                    precio = precio_str.replace('.', '').replace(',', '.')
                    return float(precio)
    except Exception as e:
        logger.warning(f"Error al obtener precio de Particular desde obras_entero.txt: {e}")
    
    # Valor por defecto
    return 3000.0

# Ruta admin para gestionar usuarios (solo para Gaito)
@app.route('/admin/usuarios', methods=['GET', 'POST'])
@require_login
def admin_usuarios():
    # Solo Gaito puede acceder a esta ruta
    if not is_gaito_admin():
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('presupuestos'))
    
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
    
    # Log Daniel (solo para ver desde el panel, temporal)
    daniel_log_lines = []
    if os.path.isfile(DANIEL_LOG_FILE):
        try:
            with open(DANIEL_LOG_FILE, 'r', encoding='utf-8') as f:
                daniel_log_lines = f.read().strip().split('\n')[-50:]  # últimas 50
        except OSError:
            pass
    
    return render_template('admin_usuarios.html', 
                         users=users, 
                         current_user=session.get('username'),
                         obras_sin_cobertura_anexo=anexo_config.get('obras_sin_cobertura', []),
                         todas_las_obras=todas_las_obras,
                         precio_particular=precio_particular,
                         daniel_log_lines=daniel_log_lines)

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
    
    return redirect(url_for('admin_usuarios'))

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

# Aranceles: cualquier usuario logueado puede ver (no es solo admin)
@app.route('/aranceles', methods=['GET'])
@require_login
def aranceles():
    estado_data = load_obras_estado()
    
    # Formatear fecha de actualización
    fecha_actualizacion = None
    if estado_data.get('fecha_actualizacion'):
        try:
            fecha_dt = datetime.fromisoformat(estado_data['fecha_actualizacion'])
            fecha_actualizacion = fecha_dt.strftime('%d/%m/%Y %H:%M:%S')
        except:
            fecha_actualizacion = estado_data.get('fecha_actualizacion')
    
    # Convertir obras a lista ordenada para el template
    obras_list = []
    for nombre, datos in sorted(estado_data.get('obras', {}).items()):
        obras_list.append({
            'nombre': nombre,
            'precio': datos.get('precio', 'N/A'),
            'estado': datos.get('estado', 'vigente'),
            'ultima_actualizacion': datos.get('ultima_actualizacion', '')
        })
    
    return render_template('admin_estado_obras.html', 
                         estado_data=estado_data,
                         obras_list=obras_list,
                         fecha_actualizacion=fecha_actualizacion,
                         current_user=session.get('username'))

# Ruta para instructivo de obras sociales (protegida)
@app.route('/instructivo', methods=['GET'])
@require_login
def instructivo():
    instructivos_file = 'instructivos.json'
    instructivos = []
    
    try:
        if os.path.exists(instructivos_file):
            with open(instructivos_file, 'r', encoding='utf-8') as f:
                instructivos = json.load(f)
        else:
            logger.warning(f"Archivo {instructivos_file} no encontrado")
    except Exception as e:
        logger.error(f"Error al leer instructivos: {e}")
        instructivos = []
    
    return render_template('instructivo.html', 
                         instructivos=instructivos,
                         username=session.get('username'))

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
        pdf.cell(w_nbu, 9, 'NBU=', border=1, align='C', fill=True)
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
