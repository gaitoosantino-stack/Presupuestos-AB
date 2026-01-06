from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, send_file, jsonify
from flask_wtf.csrf import CSRFProtect
import os
import json
import logging
from datetime import timedelta, datetime
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

# Habilitar protección CSRF
csrf = CSRFProtect(app)

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
# URL del archivo Excel/CSV para sincronización de precios (configurar aquí o en variable de entorno)
# Puede ser Google Sheets (CSV) o OneDrive/Excel (.xlsx)
# Ejemplo OneDrive: https://onedrive.live.com/download?resid=RESID
GOOGLE_SHEET_URL = os.environ.get('GOOGLE_SHEET_URL', 'https://onedrive.live.com/:x:/g/personal/4296EB0072506AFB/EcVnvhhOjqJMgDlQhEhMBbcBbFfE6VxrdwBR4ByfAvkIQw?resid=4296EB0072506AFB!s18be67c58e4e4ca280395084484c05b7&ithint=file%2Cxlsx&e=6RQ06elsx&migratedtospo=true&redeem=aHR0cHM6Ly8xZHJ2Lm1zL3gvYy80Mjk2ZWIwMDcyNTA2YWZiL0VjVm52aGhPanFKTWdEbFFoRWhNQmJjQmJGZkU2VnhyZHdCUjRCeWZBdmtJUXc_ZT02UlEwNmVsc3g')

def init_users_file():
    """Inicializa el archivo de usuarios si no existe"""
    if not os.path.exists(USERS_FILE):
        # Crear archivo con usuario Gaito como único admin
        default_users = {
            'Gaito': {
                'password': generate_password_hash('Simon@594*'),
                'email': '',
                'habilitado': True
            }
        }
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_users, f, indent=2, ensure_ascii=False)
        logger.info("Archivo de usuarios creado con usuario Gaito")
    else:
        # Verificar que Gaito exista, si no existe agregarlo
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users = json.load(f)
            if 'Gaito' not in users:
                users['Gaito'] = {
                    'password': generate_password_hash('Simon@594*'),
                    'email': '',
                    'habilitado': True
                }
                with open(USERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(users, f, indent=2, ensure_ascii=False)
                logger.info("Usuario Gaito agregado al archivo de usuarios")
        except Exception as e:
            logger.error(f"Error al verificar usuario Gaito: {e}")

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
                # Usuario sigue habilitado, redirigir normalmente
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
                if info_obra.get('estado') == 'cortada':
                    # Agregar obra cortada (con precio si existe, o None)
                    precio_cortada = info_obra.get('precio')
                    if precio_cortada:
                        # Convertir a formato numérico si es string
                        if isinstance(precio_cortada, str):
                            precio_cortada = precio_cortada.replace('.', '').replace(',', '.')
                        obras[nombre_obra] = str(precio_cortada)
                    else:
                        obras[nombre_obra] = None
                    obras_estado[nombre_obra] = 'cortada'
    except Exception as e:
        logger.error(f"Error al cargar obras cortadas: {e}")
    
    # Ordenar alfabéticamente
    obras = dict(sorted(obras.items()))

    # Leer estudios
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
        logger.error(f"Error al leer estudios: {e}")
        estudios = {}

    return render_template('presupuestos.html', obras=obras, obras_estado=obras_estado, estudios=estudios, username=session.get('username'))

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
                if vigente_str in ['suspendida', 'suspendid', 'cortada']:
                    estado = 'cortada'
            
            # Procesar precio (puede estar vacío para obras cortadas)
            precio_normalizado = None
            if not pd.isna(precio):
                precio_str = str(precio).strip()
                precio_normalizado = normalizar_precio_argentino(precio_str)
            
            # Guardar obra cortada (con o sin precio)
            if estado == 'cortada':
                obras_cortadas_dict[nombre] = {
                    'precio': precio_normalizado,
                    'estado': 'cortada'
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
                if vigente_str in ['suspendida', 'suspendid', 'cortada']:
                    estado = 'cortada'
            
            # Procesar precio (puede estar vacío para obras cortadas)
            precio_normalizado = None
            if not pd.isna(precio):
                precio_str = str(precio).strip()
                precio_normalizado = normalizar_precio_argentino(precio_str)
            
            # Guardar obra cortada (con o sin precio)
            if estado == 'cortada':
                obras_cortadas_dict[nombre] = {
                    'precio': precio_normalizado,
                    'estado': 'cortada'
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
            
            # Si la obra no existe actualmente o el precio cambió
            if precio_actual is None or comparar_precios(precio_actual, precio_nuevo):
                cambios_dict[nombre] = {
                    'precio_actual': precio_actual if precio_actual else 'Nueva obra',
                    'precio_nuevo': precio_nuevo,
                    'cambio': 'nuevo' if precio_actual is None else 'modificado',
                    'estado': 'vigente'
                }
        
        # Agregar obras cortadas SOLO si cambiaron de estado (de vigente a cortada)
        for nombre, datos_cortada in obras_cortadas_dict.items():
            # Verificar el estado actual de la obra
            obra_estado_actual = obras_estado_actual.get(nombre, {})
            estado_anterior = obra_estado_actual.get('estado', 'vigente')  # Si no existe, asumimos que estaba vigente
            
            # Solo incluir si cambió de vigente a cortada (no si ya estaba cortada)
            if estado_anterior == 'vigente':
                precio_actual = obras_actuales.get(nombre)
                if precio_actual is None:
                    # Intentar obtener desde obras_estado.json
                    precio_actual = obra_estado_actual.get('precio')
                
                cambios_dict[nombre] = {
                    'precio_actual': precio_actual if precio_actual else 'Nueva obra cortada',
                    'precio_nuevo': datos_cortada.get('precio') if datos_cortada.get('precio') else 'Cortada (sin precio)',
                    'cambio': 'cortada',
                    'estado': 'cortada'
                }
        
        # También detectar obras que están actualmente vigentes pero no están en el nuevo Excel (se cortaron)
        nombres_nuevos = set(obras_dict.keys()) | set(obras_cortadas_dict.keys())
        for nombre_actual, precio_actual in obras_actuales.items():
            if nombre_actual not in nombres_nuevos:
                # Verificar si realmente estaba vigente (no cortada)
                obra_estado_actual = obras_estado_actual.get(nombre_actual, {})
                estado_anterior = obra_estado_actual.get('estado', 'vigente')
                
                # Solo incluir si estaba vigente (no si ya estaba cortada)
                if estado_anterior == 'vigente':
                    cambios_dict[nombre_actual] = {
                        'precio_actual': precio_actual,
                        'precio_nuevo': 'Cortada (no está en el Excel)',
                        'cambio': 'cortada',
                        'estado': 'cortada'
                    }
        
        count = len(cambios_dict)
        cambios_ordenados = dict(sorted(cambios_dict.items()))
        
        total_obras_vigentes = len(obras_dict)
        total_obras_cortadas = len(obras_cortadas_dict)
        if count == 0:
            mensaje = f"No hay cambios. Todas las obras ({total_obras_vigentes}) ya tienen los precios actualizados."
        else:
            cambios_precio = sum(1 for c in cambios_dict.values() if c['cambio'] in ['nuevo', 'modificado'])
            cambios_cortadas = sum(1 for c in cambios_dict.values() if c['cambio'] == 'cortada')
            mensaje = f"Se encontraron {count} cambio(s): {cambios_precio} precio(s) modificado(s) y {cambios_cortadas} obra(s) cortada(s)."
        
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
                if vigente_str in ['suspendida', 'suspendid', 'cortada']:
                    estado = 'cortada'
            
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
                if vigente_str in ['suspendida', 'suspendid', 'cortada']:
                    estado = 'cortada'
            
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
            estado_data = {
                'fecha_actualizacion': datetime.now().isoformat(),
                'total_obras': len(obras_estado_ordenadas),
                'obras_vigentes': sum(1 for o in obras_estado_ordenadas.values() if o['estado'] == 'vigente'),
                'obras_cortadas': sum(1 for o in obras_estado_ordenadas.values() if o['estado'] == 'cortada'),
                'obras': obras_estado_ordenadas
            }
            
            with open(OBRAS_ESTADO_FILE, 'w', encoding='utf-8') as f:
                json.dump(estado_data, f, indent=2, ensure_ascii=False)
            
            count = len(obras_dict) if obras_dict else 0
            total_count = len(obras_estado_dict)
            cortadas_count = estado_data['obras_cortadas']
            logger.info(f"Sincronización completada: {count} obras activas, {total_count} total (incluyendo {cortadas_count} cortadas)")
            return True, f"Sincronización exitosa: {count} obras activas importadas ({total_count} total, {cortadas_count} cortadas).", count
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
    """Verifica si el usuario actual es Gaito (el único admin)"""
    return session.get('username') == 'Gaito'

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
                'obras_cortadas': 0,
                'obras': {}
            }
    except Exception as e:
        logger.error(f"Error al cargar estado de obras: {e}")
        return {
            'fecha_actualizacion': None,
            'total_obras': 0,
            'obras_vigentes': 0,
            'obras_cortadas': 0,
            'obras': {}
        }

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
                # No permitir deshabilitar a Gaito
                if username == 'Gaito':
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
                else:
                    del users[username]
                    if save_users(users):
                        flash(f'Usuario {username} eliminado.', 'success')
                    else:
                        flash('Error al guardar los cambios.', 'error')
        
        return redirect(url_for('admin_usuarios'))
    
    return render_template('admin_usuarios.html', users=users, current_user=session.get('username'))

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
    
    return render_template('admin_perfil.html', username=username, perfil=perfil)

# Ruta para ver estado de obras sociales (solo para Gaito)
@app.route('/admin/estado_obras', methods=['GET'])
@require_login
def admin_estado_obras():
    # Solo Gaito puede acceder a esta ruta
    if not is_gaito_admin():
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('presupuestos'))
    
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
                         fecha_actualizacion=fecha_actualizacion)

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
                # Evitar recursión infinita
                if self._header_rendering:
                    return
                self._header_rendering = True
                try:
                    """Header: 60% izquierda (Laboratorio), 40% derecha (Asociación)"""
                    y_start = 8
                    ancho_pagina = self.w
                    margen_lateral = 10
                    margen_derecho = 10
                    
                    # ========== CONFIGURACIÓN DE CAJAS ==========
                    # Bloque Izquierdo: 45% del ancho
                    ancho_izquierda = (ancho_pagina - margen_lateral - margen_derecho) * 0.45
                    # Espacio vacío (Centro): 10% del ancho
                    espacio_centro = (ancho_pagina - margen_lateral - margen_derecho) * 0.10
                    # Bloque Derecho: 45% del ancho
                    ancho_derecha = (ancho_pagina - margen_lateral - margen_derecho) * 0.45
                    
                    x_izquierda = margen_lateral
                    x_derecha = x_izquierda + ancho_izquierda + espacio_centro
                    
                    # Tamaños de logos específicos - Ajustados para que coincidan con la altura del texto
                    # Altura total del texto izquierdo: ~23mm, derecho: ~26mm
                    # Hacer los logos un poco más grandes que el texto
                    logo_lab_max_height = 28  # Aproximadamente la altura del texto + margen
                    logo_asoc_max_height = 28  # Aproximadamente la altura del texto + margen
                    margen_logo_texto = 4
                    
                    # Line height compacto
                    line_height = 1.2
                    espacio_lineas = 0.5
                    
                    # ========== CAJA IZQUIERDA: LABORATORIO (60% del ancho) ==========
                    # Alineación: Todo a la IZQUIERDA
                    x_lab = x_izquierda
                    y_lab = y_start
                    
                    # Logo del laboratorio (máximo 50px = 14mm)
                    logo_lab_width = logo_lab_max_height
                    logo_lab_height = 0
                    if self.perfil.get('logo_path'):
                        logo_full_path = os.path.join(LOGO_FOLDER, self.perfil['logo_path'])
                        if os.path.exists(logo_full_path):
                            try:
                                try:
                                    from PIL import Image
                                    img = Image.open(logo_full_path)
                                    img_width, img_height = img.size
                                    logo_height_mm = (img_height / img_width) * logo_lab_max_height
                                    if logo_height_mm > logo_lab_max_height:
                                        logo_height_mm = logo_lab_max_height
                                        logo_width_mm = (img_width / img_height) * logo_lab_max_height
                                    else:
                                        logo_width_mm = logo_lab_max_height
                                    logo_lab_width = logo_width_mm
                                except:
                                    logo_lab_width = logo_lab_max_height
                                    logo_height_mm = logo_lab_max_height
                                
                                self.image(logo_full_path, x=x_lab, y=y_lab, w=logo_lab_width, h=logo_height_mm)
                                logo_lab_height = logo_height_mm
                            except Exception as e:
                                logger.warning(f"No se pudo insertar logo del laboratorio: {e}")
                    
                    # Texto a la derecha del logo - CENTRADO VERTICALMENTE
                    x_texto_lab = x_lab + logo_lab_width + margen_logo_texto if logo_lab_height > 0 else x_lab
                    ancho_texto_lab = ancho_izquierda - (logo_lab_width + margen_logo_texto if logo_lab_height > 0 else 0)
                    # Validar que el ancho sea positivo
                    if ancho_texto_lab <= 0:
                        ancho_texto_lab = ancho_izquierda
                    
                    # Calcular altura total del texto para centrarlo verticalmente con el logo
                    # Fila 1: Título (10pt) - REDUCIDO
                    # Fila 2: Subtítulo (8pt) - REDUCIDO
                    # Fila 3: Profesionales (8pt)
                    # Fila 4: Dirección (8pt)
                    # Fila 5: Teléfonos (8pt)
                    altura_total_texto = (3.5 * line_height) + espacio_lineas + (3 * line_height) + espacio_lineas + (3 * line_height) + espacio_lineas + (3 * line_height) + espacio_lineas + (3 * line_height)
                    
                    # Centrar verticalmente: si hay logo, alinear el centro del texto con el centro del logo
                    # Validar que el cálculo no dé valores negativos
                    if logo_lab_height > 0:
                        offset_vertical = (logo_lab_height - altura_total_texto) / 2
                        y_inicio = max(y_lab, y_lab + offset_vertical)  # Asegurar que no sea negativo
                    else:
                        y_inicio = y_lab
                    
                    y_actual = y_inicio
                
                # Fila 1: "LABORATORIO SCOZZINA SAS" - Arial (Helvetica), Negrita, 10pt, Negro
                    self.set_font('Helvetica', 'B', 10)  # REDUCIDO de 12 a 10pt
                    nombre_lab = self.safe_text(self.perfil.get('nombre_lab', 'Laboratorio'))
                    self.set_xy(x_texto_lab, y_actual)
                    self.cell(ancho_texto_lab, 3.5 * line_height, nombre_lab, align='L')
                    y_actual += 3.5 * line_height + espacio_lineas
                
                # Fila 2: "Análisis Clínicos" - Arial, Cursiva, 8pt, Gris Oscuro
                    self.set_font('Helvetica', 'I', 8)  # REDUCIDO de 9 a 8pt
                    subtitulo = self.safe_text(self.perfil.get('subtitulo', 'Analisis Clinicos'))
                    self.set_xy(x_texto_lab, y_actual)
                    self.cell(ancho_texto_lab, 3 * line_height, subtitulo, align='L')
                    y_actual += 3 * line_height + espacio_lineas
                
                    # Fila 3: Profesionales - Arial, 8pt, Gris (información completa en dos líneas)
                    self.set_font('Helvetica', '', 8)
                    profesionales_text = self.safe_text(self.perfil.get('profesionales', ''))
                    if profesionales_text:
                        # Separar por " - " y mostrar cada profesional en una línea separada
                        # Ejemplo: "Bioquimico: Castillo Romina MP:0528 - Tec. Qca.: Schanz Carolina MP:100"
                        # Resultado: Línea 1: "Bioquimico: Castillo Romina MP:0528"
                        #           Línea 2: "Tec. Qca.: Schanz Carolina MP:100"
                        partes_profesionales = profesionales_text.split(' - ')
                        for parte in partes_profesionales:
                            parte = parte.strip()
                            if parte:
                                self.set_xy(x_texto_lab, y_actual)
                                self.cell(ancho_texto_lab, 3 * line_height, parte, align='L')
                                y_actual += 3 * line_height + espacio_lineas
                
                    # Fila 4: Dirección - Arial, 8pt, Gris (formato limpio, sin teléfono)
                    direccion_text = self.safe_text(self.perfil.get('direccion', ''))
                    ciudad = self.safe_text(self.perfil.get('ciudad', ''))
                    
                    # Formatear dirección limpia: "Pellegrini 631/605, Trelew (CP 9100)"
                    direccion_line = ""
                    if direccion_text:
                        # Limpiar dirección (remover duplicados, CP, etc.)
                        direccion_limpia = direccion_text.split('-')[0].strip()  # Tomar solo hasta el primer guión
                        # Remover espacios extra en la dirección
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
                    
                    if direccion_line:
                        self.set_xy(x_texto_lab, y_actual)
                        self.cell(ancho_texto_lab, 3 * line_height, direccion_line, align='L')
                        y_actual += 3 * line_height + espacio_lineas
                
                    # Fila 5: Teléfonos - Arial, 8pt, Gris (línea separada)
                    telefono = self.perfil.get('telefono', '')
                    if telefono:
                        # Formatear teléfono limpio: "(0280) 423-8264 / 15-4627531"
                        telefono_limpio = telefono.replace('/', ' / ').replace('  ', ' ').strip()
                        # Formatear con paréntesis y guiones
                        if '0280' in telefono_limpio:
                            partes_tel = telefono_limpio.split('/')
                            tel_formateado = []
                            for parte in partes_tel:
                                parte = parte.strip()
                                if '0280' in parte:
                                    # Formatear: (0280) 423-8264
                                    parte = parte.replace('0280', '(0280)').replace('--', '-').replace(' ', '')
                                    # Agregar guión después del código de área si no lo tiene
                                    if ') ' not in parte and ')' in parte:
                                        parte = parte.replace(')', ') ')
                                else:
                                    # Para números sin código de área (ej: 15-4627531)
                                    parte = parte.replace(' ', '-')
                                tel_formateado.append(parte)
                            telefono_limpio = ' / '.join(tel_formateado)
                        
                        telefono_line = f"Tel: {telefono_limpio}"
                        self.set_xy(x_texto_lab, y_actual)
                        self.cell(ancho_texto_lab, 3 * line_height, telefono_line, align='L')
                        y_actual += 3 * line_height
                
                    altura_izquierda = max(y_actual - y_inicio, logo_lab_height)
                
                # ========== CAJA DERECHA: ASOCIACIÓN BIOQUÍMICA (40% del ancho) ==========
                # Alineación: Todo a la DERECHA
                    y_asoc = y_start  # Mismo Y que caja izquierda
                
                # Logo ABNECh (máximo 40px = 11mm) a la derecha del texto
                    logo_asoc_width = logo_asoc_max_height
                    logo_asoc_height = 0
                    x_logo_asoc = 0
                    logo_asoc_path = os.path.join(LOGO_FOLDER, ASOCIACION_BIOQUIMICA['logo_path'])
                    if os.path.exists(logo_asoc_path):
                        try:
                            try:
                                from PIL import Image
                                img = Image.open(logo_asoc_path)
                                img_width, img_height = img.size
                                logo_height_mm = (img_height / img_width) * logo_asoc_max_height
                                if logo_height_mm > logo_asoc_max_height:
                                    logo_height_mm = logo_asoc_max_height
                                    logo_width_mm = (img_width / img_height) * logo_asoc_max_height
                                else:
                                    logo_width_mm = logo_asoc_max_height
                                logo_asoc_width = logo_width_mm
                            except:
                                logo_asoc_width = logo_asoc_max_height
                                logo_height_mm = logo_asoc_max_height
                            
                            # Logo alineado a la derecha de la caja
                            x_logo_asoc = x_derecha + ancho_derecha - logo_asoc_width
                            self.image(logo_asoc_path, x=x_logo_asoc, y=y_asoc, w=logo_asoc_width, h=logo_height_mm)
                            logo_asoc_height = logo_height_mm
                        except Exception as e:
                            logger.warning(f"No se pudo insertar logo de Asociación Bioquímica: {e}")
                
                # Texto a la izquierda del logo, alineado a la derecha - CENTRADO VERTICALMENTE
                    if logo_asoc_height > 0:
                        ancho_texto_asoc = x_logo_asoc - margen_logo_texto - x_derecha
                    else:
                        ancho_texto_asoc = ancho_derecha
                    # Validar que el ancho sea positivo
                    if ancho_texto_asoc <= 0:
                        ancho_texto_asoc = ancho_derecha
                    x_texto_asoc = x_derecha
                
                # Calcular altura total del texto para centrarlo verticalmente con el logo
                # Ajustar para que tenga la misma altura que el bloque izquierdo (6 líneas ahora)
                # Fila 1: Título parte 1 (10pt) - REDUCIDO y partido en dos
                # Fila 2: Título parte 2 (10pt)
                # Fila 3: Matrícula (8pt)
                # Fila 4: Dirección parte 1 (8pt)
                # Fila 5: Dirección parte 2 (8pt)
                # Fila 6: Teléfono (8pt)
                    altura_total_texto_asoc = (3.5 * line_height) + espacio_lineas + (3.5 * line_height) + espacio_lineas + (3 * line_height) + espacio_lineas + (3 * line_height) + espacio_lineas + (3 * line_height) + espacio_lineas + (3 * line_height)
                
                # Centrar verticalmente con el logo
                # Validar que el cálculo no dé valores negativos
                    if logo_asoc_height > 0:
                        offset_vertical_asoc = (logo_asoc_height - altura_total_texto_asoc) / 2
                        y_inicio_asoc = max(y_asoc, y_asoc + offset_vertical_asoc)  # Asegurar que no sea negativo
                    else:
                        y_inicio_asoc = y_asoc
                
                    y_actual_asoc = y_inicio_asoc
                
                # Fila 1: "ASOC. BIOQUÍMICA" - Arial, Negrita, 10pt (partido en dos líneas)
                    self.set_font('Helvetica', 'B', 10)  # REDUCIDO a 10pt
                # Partir el título siempre en: "ASOC. BIOQUÍMICA" y "DEL NE DEL CHUBUT"
                    titulo_parte1 = "ASOC. BIOQUÍMICA"
                    titulo_parte2 = "DEL NE DEL CHUBUT"
                
                    self.set_xy(x_texto_asoc, y_actual_asoc)
                    self.cell(ancho_texto_asoc, 3.5 * line_height, titulo_parte1, align='R')
                    y_actual_asoc += 3.5 * line_height + espacio_lineas
                
                # Fila 2: "DEL NE DEL CHUBUT" - Arial, Negrita, 10pt
                    self.set_xy(x_texto_asoc, y_actual_asoc)
                    self.cell(ancho_texto_asoc, 3.5 * line_height, titulo_parte2, align='R')
                    y_actual_asoc += 3.5 * line_height + espacio_lineas
                
                # Fila 3: Matrícula / Ente Regulador - Arial, 8pt
                    self.set_font('Helvetica', '', 8)
                    matricula_texto = "Ente Regulador"  # Texto genérico, puede personalizarse
                    self.set_xy(x_texto_asoc, y_actual_asoc)
                    self.cell(ancho_texto_asoc, 3 * line_height, matricula_texto, align='R')
                    y_actual_asoc += 3 * line_height + espacio_lineas
                
                # Fila 4: Dirección parte 1 - "Paraguay 37" - Arial, 8pt
                    if ASOCIACION_BIOQUIMICA.get('direccion'):
                        direccion_asoc = self.safe_text(ASOCIACION_BIOQUIMICA['direccion'])
                        # Separar dirección: "Paraguay 37" en una línea
                        if ',' in direccion_asoc:
                            partes = direccion_asoc.split(',')
                            direccion_parte1 = partes[0].strip()  # "Paraguay 37"
                            self.set_xy(x_texto_asoc, y_actual_asoc)
                            self.cell(ancho_texto_asoc, 3 * line_height, direccion_parte1, align='R')
                            y_actual_asoc += 3 * line_height + espacio_lineas
                            
                            # Fila 5: Dirección parte 2 - "Trelew - Chubut" - Arial, 8pt
                            if len(partes) > 1:
                                direccion_parte2 = partes[-1].strip()  # "U9100 Trelew, Chubut" o similar
                                # Limpiar y formatear: extraer Trelew y Chubut
                                direccion_parte2 = direccion_parte2.replace('U9100', '').replace('U 9100', '').replace('U9100', '').strip()
                                # Buscar Trelew y Chubut
                                if 'Trelew' in direccion_parte2:
                                    if 'Chubut' in direccion_parte2:
                                        direccion_parte2 = "Trelew - Chubut"
                                    else:
                                        direccion_parte2 = "Trelew - Chubut"
                                elif 'Chubut' in direccion_parte2:
                                    direccion_parte2 = f"Trelew - {direccion_parte2}"
                                else:
                                    # Si no encuentra, usar el texto limpio
                                    direccion_parte2 = direccion_parte2.replace(',', ' - ').strip()
                                self.set_xy(x_texto_asoc, y_actual_asoc)
                                self.cell(ancho_texto_asoc, 3 * line_height, direccion_parte2, align='R')
                                y_actual_asoc += 3 * line_height + espacio_lineas
                            else:
                                # Si solo hay una parte, agregar "Trelew - Chubut"
                                self.set_xy(x_texto_asoc, y_actual_asoc)
                                self.cell(ancho_texto_asoc, 3 * line_height, "Trelew - Chubut", align='R')
                                y_actual_asoc += 3 * line_height + espacio_lineas
                        else:
                            # Si no hay coma, intentar separar por espacios
                            if 'Paraguay' in direccion_asoc:
                                # Extraer "Paraguay 37"
                                palabras = direccion_asoc.split()
                                if len(palabras) >= 2:
                                    direccion_parte1 = f"{palabras[0]} {palabras[1]}"
                                    self.set_xy(x_texto_asoc, y_actual_asoc)
                                    self.cell(ancho_texto_asoc, 3 * line_height, direccion_parte1, align='R')
                                    y_actual_asoc += 3 * line_height + espacio_lineas
                                    # Segunda línea
                                    self.set_xy(x_texto_asoc, y_actual_asoc)
                                    self.cell(ancho_texto_asoc, 3 * line_height, "Trelew - Chubut", align='R')
                                    y_actual_asoc += 3 * line_height + espacio_lineas
                                else:
                                    self.set_xy(x_texto_asoc, y_actual_asoc)
                                    self.cell(ancho_texto_asoc, 3 * line_height, direccion_asoc, align='R')
                                    y_actual_asoc += 3 * line_height + espacio_lineas
                                    self.set_xy(x_texto_asoc, y_actual_asoc)
                                    self.cell(ancho_texto_asoc, 3 * line_height, "Trelew - Chubut", align='R')
                                    y_actual_asoc += 3 * line_height + espacio_lineas
                    else:
                        # Si no hay dirección, agregar líneas para mantener estructura
                        self.set_xy(x_texto_asoc, y_actual_asoc)
                        self.cell(ancho_texto_asoc, 3 * line_height, "Paraguay 37", align='R')
                        y_actual_asoc += 3 * line_height + espacio_lineas
                        self.set_xy(x_texto_asoc, y_actual_asoc)
                        self.cell(ancho_texto_asoc, 3 * line_height, "Trelew - Chubut", align='R')
                        y_actual_asoc += 3 * line_height + espacio_lineas
                    
                    # Fila 6: Teléfono - Arial, 8pt
                    if ASOCIACION_BIOQUIMICA.get('telefono'):
                        telefono_asoc = self.safe_text(ASOCIACION_BIOQUIMICA['telefono'])
                        # Formatear: "Tel: 0280-4420440"
                        telefono_formateado = telefono_asoc.replace(' ', '').replace('-', '-')
                        if '0280' in telefono_formateado and '-' not in telefono_formateado:
                            # Formatear: 02804420440 -> 0280-4420440
                            if len(telefono_formateado) == 11:
                                telefono_formateado = f"{telefono_formateado[:4]}-{telefono_formateado[4:]}"
                        telefono_line = f"Tel: {telefono_formateado}"
                        self.set_xy(x_texto_asoc, y_actual_asoc)
                        self.cell(ancho_texto_asoc, 3 * line_height, telefono_line, align='R')
                        y_actual_asoc += 3 * line_height + espacio_lineas
                    
                    # Fila 7: E-mail - Arial, 8pt
                    email_asoc = "E-mail: abnechtrelew@gmail.com"
                    self.set_xy(x_texto_asoc, y_actual_asoc)
                    self.cell(ancho_texto_asoc, 3 * line_height, email_asoc, align='R')
                    y_actual_asoc += 3 * line_height
                
                    altura_derecha = max(y_actual_asoc - y_inicio_asoc, logo_asoc_height)
                
                # Altura máxima del header
                    altura_maxima = max(altura_izquierda, altura_derecha)
                
                # ========== LÍNEA SEPARADORA ==========
                # Validar altura máxima para evitar valores problemáticos
                    altura_maxima = min(altura_maxima, 50)  # Limitar altura máxima a 50mm
                    y_linea = y_start + altura_maxima + 3
                # Validar que y_linea esté dentro de los límites de la página
                    if y_linea > self.h - 20:
                        y_linea = self.h - 20
                
                    self.set_line_width(0.5)
                    self.line(10, y_linea, 200, y_linea)
                    self.set_line_width(0.2)
                    
                    # Guardar posición Y de la línea separadora para usar en el cuerpo
                    self.y_linea_separadora = y_linea
                
                # NO dibujar la fecha aquí - se moverá al cuerpo del PDF
                # NO usar set_y() aquí - puede causar recursión infinita
                # FPDF manejará automáticamente la posición Y después del header
                finally:
                    self._header_rendering = False
            
        
        # Crear PDF con header automático
        pdf = PDFConHeader(perfil, fecha_presupuesto, safe_text)
        pdf.add_page()  # El header se dibujará automáticamente
        
        # Fecha - debajo de la línea separadora (solo en la primera página, no parte del header)
        # Usar la posición Y exacta de la línea separadora calculada en el header
        if pdf.y_linea_separadora is not None:
            meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 
                     'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
            fecha_str = f"{fecha_presupuesto.day} de {meses[fecha_presupuesto.month - 1]} {fecha_presupuesto.year}"
            ciudad = safe_text(perfil.get('ciudad', ''))
            pdf.set_font('Helvetica', '', 10)
            pdf.set_xy(0, pdf.y_linea_separadora + 2)
            pdf.cell(0, 4, f"{fecha_str}, {ciudad}", align='R')
            # Establecer posición Y después de la fecha
            pdf.set_y(pdf.y_linea_separadora + 6)
        else:
            # Fallback si no se calculó la línea (no debería pasar)
            pdf.set_y(26)
        
        # Espacio adicional para separar claramente el cuerpo del header
        pdf.ln(8)
        
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
                pdf.set_x(margen_izq)  # Re-alinear después del error
                pdf.cell(w_codigo, 8, codigo_safe, border=1, align='C')
                pdf.cell(w_analisis, 8, nombre_safe, border=1, align='L')
                pdf.cell(w_nbu, 8, nbu_str, border=1, align='C')
                pdf.cell(w_valor, 8, valor_str, border=1, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # Total - fila destacada (alineada a la izquierda)
        pdf.set_x(pdf.l_margin)  # Alinear desde el margen izquierdo
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_fill_color(250, 250, 250)  # Gris muy claro para el total
        total_str = f"TOTAL: ${total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        pdf.cell(w_codigo + w_analisis + w_nbu, 9, '', border=0, fill=True)
        pdf.cell(w_valor, 9, total_str, border=1, align='R', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_fill_color(255, 255, 255)  # Restaurar color blanco
        
        pdf.ln(12)  # Espacio después de la tabla
        
        # PIE DE PÁGINA - Información bancaria y Firma como bloque indivisible
        info_bancaria = perfil.get('info_bancaria', '')
        firma_texto = safe_text(perfil.get('firma_texto', ''))
        firma_path = perfil.get('firma_path', '')
        
        # Calcular altura total del bloque (info bancaria + firma)
        altura_info_bancaria = 0
        if info_bancaria:
            lineas_info = [line for line in info_bancaria.split('\n') if line.strip()]
            altura_info_bancaria = len(lineas_info) * 6  # 6mm por línea
        
        # Calcular altura de la firma (incluyendo espacio para firma manual)
        altura_firma = 0
        espacio_firma_manual = 15  # Espacio para firma manual con tinta
        if firma_path:
            try:
                firma_full_path = os.path.join(LOGO_FOLDER, firma_path)
                if os.path.exists(firma_full_path):
                    try:
                        from PIL import Image
                        img = Image.open(firma_full_path)
                        img_width, img_height = img.size
                        firma_width_mm = 40
                        firma_height_mm = (img_height / img_width) * firma_width_mm
                        if firma_height_mm > 20:
                            firma_height_mm = 20
                        altura_firma = firma_height_mm + espacio_firma_manual + 1 + 3  # imagen + espacio firma manual + línea + espacio
                        if firma_texto:
                            altura_firma += 6  # texto adicional
                    except:
                        altura_firma = 15 + espacio_firma_manual + 3  # altura por defecto + espacio firma manual
                        if firma_texto:
                            altura_firma += 6
            except:
                pass
        elif firma_texto:
            altura_firma = espacio_firma_manual + 5 + 6  # espacio firma manual + línea + texto
        
        # Altura total del bloque
        altura_bloque = max(altura_info_bancaria, altura_firma) + 10  # +10mm de margen
        
        # Verificar si hay espacio suficiente en la página actual
        espacio_disponible = pdf.h - pdf.get_y() - pdf.b_margin
        if espacio_disponible < altura_bloque:
            # No hay espacio suficiente, crear nueva página
            pdf.add_page()
            # Después de crear nueva página, posicionar debajo del header
            # El header tiene aproximadamente 26mm de altura (línea separadora)
            # Usar la posición Y de la línea separadora si está disponible, sino usar aproximación
            if pdf.y_linea_separadora is not None:
                altura_header_completo = pdf.y_linea_separadora + 2  # Línea + pequeño margen
            else:
                altura_header_completo = 26  # Aproximación
            # Aumentar margen para evitar que se superponga con el header
            pdf.set_y(altura_header_completo + 20)  # 20mm de margen después del header para evitar superposición
        
        # Guardar posición Y inicial del bloque
        y_bloque_inicio = pdf.get_y()
        
        # Dibujar información bancaria a la izquierda
        if info_bancaria:
            pdf.set_font('Helvetica', '', 10)
            x_info = pdf.l_margin
            y_info = y_bloque_inicio
            pdf.set_xy(x_info, y_info)
            for line in info_bancaria.split('\n'):
                if line.strip():
                    pdf.cell(0, 6, safe_text(line.strip()), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        
        # Dibujar firma a la derecha (mismo Y inicial que info bancaria)
        if firma_texto or firma_path:
            pdf.set_font('Helvetica', '', 10)
            margen_derecho = pdf.w - pdf.r_margin
            y_firma_inicio = y_bloque_inicio
            
            # Si hay imagen de firma, mostrarla primero
            if firma_path:
                firma_full_path = os.path.join(LOGO_FOLDER, firma_path)
                if os.path.exists(firma_full_path):
                    try:
                        # Tamaño para la imagen de firma (más pequeño y proporcional)
                        # Ancho máximo 50mm para que se vea mejor
                        firma_width_mm = 50
                        try:
                            from PIL import Image
                            img = Image.open(firma_full_path)
                            img_width, img_height = img.size
                            # Mantener proporción
                            firma_height_mm = (img_height / img_width) * firma_width_mm
                            # Limitar altura máxima a 25mm
                            if firma_height_mm > 25:
                                firma_height_mm = 25
                                firma_width_mm = (img_width / img_height) * 25
                            # Asegurar un tamaño mínimo razonable
                            if firma_height_mm < 10:
                                firma_height_mm = 10
                                firma_width_mm = (img_width / img_height) * 10
                        except:
                            firma_width_mm = 50
                            firma_height_mm = 20
                        
                        # Calcular posición X para alinear a la derecha
                        x_firma = margen_derecho - firma_width_mm
                        
                        # PRIMERO calcular dónde va la línea de firma
                        espacio_firma_manual = 15  # Espacio para firma manual
                        y_pos_linea = y_firma_inicio + espacio_firma_manual
                        
                        # LUEGO poner la imagen JUSTO ENCIMA de la línea
                        y_imagen_firma = y_pos_linea - firma_height_mm - 2  # 2mm de espacio entre imagen y línea
                        
                        # Insertar imagen de firma ENCIMA de la línea
                        pdf.image(firma_full_path, x=x_firma, y=y_imagen_firma, w=firma_width_mm, h=firma_height_mm, keep_aspect_ratio=True)
                        
                        # Dibujar la línea de firma
                        pdf.line(x_firma, y_pos_linea, margen_derecho, y_pos_linea)
                        
                        # Si hay texto de firma, mostrarlo debajo de la línea
                        if firma_texto:
                            pdf.set_xy(0, y_pos_linea + 3)
                            pdf.cell(0, 6, firma_texto, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
                    except Exception as e:
                        logger.warning(f"No se pudo insertar imagen de firma: {e}")
                        # Si falla la imagen, continuar con el texto normal
                        if firma_texto:
                            ancho_texto = pdf.get_string_width(firma_texto)
                            fin_linea = margen_derecho
                            inicio_linea = fin_linea - ancho_texto
                            # Espacio para firma manual
                            espacio_firma_manual = 15
                            pdf.line(inicio_linea, y_firma_inicio + espacio_firma_manual, fin_linea, y_firma_inicio + espacio_firma_manual)
                            pdf.set_xy(0, y_firma_inicio + espacio_firma_manual + 5)
                            pdf.cell(0, 6, firma_texto, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
                elif firma_texto:
                    # Si la imagen no existe pero hay texto, mostrar solo el texto
                    ancho_texto = pdf.get_string_width(firma_texto)
                    fin_linea = margen_derecho
                    inicio_linea = fin_linea - ancho_texto
                    # Espacio para firma manual
                    espacio_firma_manual = 15
                    pdf.line(inicio_linea, y_firma_inicio + espacio_firma_manual, fin_linea, y_firma_inicio + espacio_firma_manual)
                    pdf.set_xy(0, y_firma_inicio + espacio_firma_manual + 5)
                    pdf.cell(0, 6, firma_texto, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
            elif firma_texto:
                # Solo texto de firma, sin imagen
                ancho_texto = pdf.get_string_width(firma_texto)
                fin_linea = margen_derecho
                inicio_linea = fin_linea - ancho_texto
                # Espacio para firma manual
                espacio_firma_manual = 15
                pdf.line(inicio_linea, y_firma_inicio + espacio_firma_manual, fin_linea, y_firma_inicio + espacio_firma_manual)
                pdf.set_xy(0, y_firma_inicio + espacio_firma_manual + 5)
                pdf.cell(0, 6, firma_texto, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
        
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
