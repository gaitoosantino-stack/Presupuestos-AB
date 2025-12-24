from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, send_file
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
        'firma_texto': ''
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
        
        # Guardar perfil
        perfiles[username] = perfil
        if save_perfiles(perfiles):
            flash(f'Perfil de {username} actualizado correctamente.', 'success')
            logger.info(f"Perfil actualizado para usuario {username}")
        else:
            flash('Error al guardar el perfil.', 'error')
        
        return redirect(url_for('admin_perfil', username=username))
    
    return render_template('admin_perfil.html', username=username, perfil=perfil)

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
            
            def header(self):
                """Header que se repite en cada página"""
                y_start = 10
                x_logo = 10
                
                # Logo pequeño en la esquina superior izquierda
                if self.perfil.get('logo_path'):
                    logo_full_path = os.path.join(LOGO_FOLDER, self.perfil['logo_path'])
                    if os.path.exists(logo_full_path):
                        try:
                            # Logo pequeño: máximo 25mm de ancho
                            logo_width_mm = 25
                            try:
                                from PIL import Image
                                img = Image.open(logo_full_path)
                                img_width, img_height = img.size
                                # Mantener proporción
                                logo_height_mm = (img_height / img_width) * logo_width_mm
                                # Limitar altura máxima
                                if logo_height_mm > 25:
                                    logo_height_mm = 25
                                    logo_width_mm = (img_width / img_height) * 25
                            except:
                                logo_height_mm = 25
                            
                            # Insertar logo pequeño en esquina superior izquierda
                            self.image(logo_full_path, x=x_logo, y=y_start, w=logo_width_mm, h=logo_height_mm)
                        except Exception as e:
                            logger.warning(f"No se pudo insertar logo: {e}")
                
                # Bloque de texto institucional CENTRADO
                self.set_y(y_start + 2)
                self.set_x(0)
                
                # Título del laboratorio - CENTRADO
                self.set_font('Helvetica', 'B', 18)
                nombre_lab = self.safe_text(self.perfil.get('nombre_lab', 'Laboratorio'))
                try:
                    self.cell(0, 10, nombre_lab, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
                except Exception as e:
                    logger.error(f"Error al escribir nombre_lab: {nombre_lab}, error: {e}")
                    self.cell(0, 10, 'Laboratorio', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
                
                # Subtítulo - CENTRADO
                self.set_font('Helvetica', '', 13)
                subtitulo = self.safe_text(self.perfil.get('subtitulo', 'Analisis Clinicos'))
                self.cell(0, 7, subtitulo, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
                self.ln(2)
                
                # Profesionales - CENTRADO
                self.set_font('Helvetica', '', 10)
                profesionales_text = self.safe_text(self.perfil.get('profesionales', ''))
                if profesionales_text:
                    try:
                        self.cell(0, 6, profesionales_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
                    except Exception as e:
                        logger.error(f"Error al escribir profesionales: {profesionales_text[:50]}, error: {e}")
                        profesionales_text = profesionales_text.replace('–', '-').replace('—', '-')
                        profesionales_text = profesionales_text.encode('ascii', 'ignore').decode('ascii')
                        self.cell(0, 6, profesionales_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
                
                # Dirección - CENTRADO
                direccion_text = self.safe_text(self.perfil.get('direccion', ''))
                if direccion_text:
                    try:
                        self.cell(0, 6, direccion_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
                    except Exception as e:
                        logger.error(f"Error al escribir direccion: {direccion_text[:50]}, error: {e}")
                        direccion_text = direccion_text.replace('–', '-').replace('—', '-')
                        direccion_text = direccion_text.encode('ascii', 'ignore').decode('ascii')
                        self.cell(0, 6, direccion_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
                
                # Ciudad y teléfono - CENTRADO
                ciudad = self.safe_text(self.perfil.get('ciudad', ''))
                telefono = self.perfil.get('telefono', '')
                if ciudad or telefono:
                    info_line = ciudad
                    if telefono:
                        info_line += f" - Tel: {telefono}"
                    self.cell(0, 6, self.safe_text(info_line), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
                
                # Línea separadora
                self.ln(3)
                self.line(10, self.get_y(), 200, self.get_y())
                self.ln(3)
                
                # Fecha y ubicación - alineada a la derecha
                meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 
                         'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
                fecha_str = f"{self.fecha_presupuesto.day} de {meses[self.fecha_presupuesto.month - 1]} {self.fecha_presupuesto.year}"
                self.cell(0, 6, f"{fecha_str}, {ciudad}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
                
                self.ln(5)  # Espacio antes del cuerpo
        
        # Crear PDF con header automático
        pdf = PDFConHeader(perfil, fecha_presupuesto, safe_text)
        pdf.add_page()  # El header se dibujará automáticamente
        
        # CUERPO (solo en la primera página)
        # Datos del cliente
        pdf.set_font('Helvetica', 'B', 12)
        nombre_cliente = safe_text(nombre_paciente if nombre_paciente else 'Cliente')
        pdf.cell(0, 8, f"SRES: {nombre_cliente}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        pdf.ln(5)
        
        # Título del presupuesto - CENTRADO y sin "#"
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
        
        # Texto descriptivo - alineado con el ancho de la tabla
        pdf.set_font('Helvetica', '', 10)
        texto_descriptivo = "Me dirijo a Ud./s. en respuesta a lo solicitado, detallando a continuacion los valores finales de las practicas de laboratorio requeridas"
        # Calcular posición X para centrar la tabla (y el texto) en la página
        ancho_pagina = 210  # Ancho estándar A4 en mm
        margen_izq = (ancho_pagina - w_total_tabla) / 2
        pdf.set_x(margen_izq)
        # Usar multi_cell para texto largo que puede necesitar varias líneas
        pdf.multi_cell(w_total_tabla, 6, texto_descriptivo, align='C')
        pdf.ln(5)
        
        # Encabezados de tabla - con fondo gris (alineados con el texto descriptivo)
        pdf.set_x(margen_izq)  # Alinear con el texto descriptivo
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
            
            # Filas de la tabla (alineadas con el texto descriptivo)
            pdf.set_x(margen_izq)  # Alinear cada fila con el texto descriptivo
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
        
        # Total - fila destacada (alineada con el texto descriptivo)
        pdf.set_x(margen_izq)  # Alinear con el texto descriptivo
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_fill_color(250, 250, 250)  # Gris muy claro para el total
        total_str = f"TOTAL: ${total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        pdf.cell(w_codigo + w_analisis + w_nbu, 9, '', border=0, fill=True)
        pdf.cell(w_valor, 9, total_str, border=1, align='R', fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_fill_color(255, 255, 255)  # Restaurar color blanco
        
        pdf.ln(12)  # Espacio antes del pie de página
        
        # PIE DE PÁGINA - diseño mejorado
        info_bancaria = perfil.get('info_bancaria', '')
        if info_bancaria:
            pdf.set_font('Helvetica', '', 10)
            # Dividir en líneas
            for line in info_bancaria.split('\n'):
                if line.strip():
                    pdf.cell(0, 6, safe_text(line.strip()), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
            pdf.ln(8)
        
        # Firma - alineada a la derecha
        firma_texto = safe_text(perfil.get('firma_texto', ''))
        if firma_texto:
            pdf.set_font('Helvetica', '', 10)
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
