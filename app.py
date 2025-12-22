from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
from flask_wtf.csrf import CSRFProtect
import os
import json
import logging
from datetime import timedelta
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

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

def require_login(f):
    """Decorador para proteger rutas que requieren login"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Debes iniciar sesión para acceder a esta página.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Inicializar archivo de usuarios al iniciar
init_users_file()

# Ruta para servir el favicon
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static', 'images'),
        'favicon.png',
        mimetype='image/png'
    )

# Ruta principal - Login
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    # Si ya está logueado, redirigir a presupuestos
    if session.get('logged_in'):
        return redirect(url_for('presupuestos'))
    
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

    # Leer obras sociales
    obras = {}
    try:
        with open('obras_entero.txt', 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    obra, precio = line.strip().split(':', 1)
                    # Convertir formato argentino: 1.740,88 -> 1740.88
                    precio = precio.replace('.', '').replace(',', '.')
                    obras[obra] = precio
        # Ordenar alfabéticamente
        obras = dict(sorted(obras.items()))
    except FileNotFoundError:
        logger.error("Archivo obras_entero.txt no encontrado")
        obras = {}
    except Exception as e:
        logger.error(f"Error al leer obras sociales: {e}")
        obras = {}

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

    return render_template('presupuestos.html', obras=obras, estudios=estudios, username=session.get('username'))

def is_gaito_admin():
    """Verifica si el usuario actual es Gaito (el único admin)"""
    return session.get('username') == 'Gaito'

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
            email = request.form.get('email', '').strip()
            
            if not username or not password:
                flash('Usuario y contraseña son obligatorios.', 'error')
                return redirect(url_for('admin_usuarios'))
            
            if username in users:
                flash('El usuario ya existe.', 'error')
                return redirect(url_for('admin_usuarios'))
            
            # Agregar nuevo usuario
            users[username] = {
                'password': generate_password_hash(password),
                'email': email,
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Solo debug=True en desarrollo, no en producción
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
