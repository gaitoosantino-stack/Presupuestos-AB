#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para hacer backup de la base de datos y archivos
"""

import os
import shutil
from datetime import datetime
import zipfile

def create_backup():
    """Crea un backup completo de la base de datos y archivos"""
    
    print("=" * 70)
    print("  💾 BACKUP DE BASE DE DATOS - LABORATORIO SCOZZINA")
    print("=" * 70)
    print()
    
    # Crear carpeta de backups si no existe
    backup_dir = "backups"
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        print(f"📁 Carpeta '{backup_dir}/' creada")
    
    # Timestamp para el nombre del backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"laboratorio_backup_{timestamp}"
    backup_path = os.path.join(backup_dir, backup_name)
    
    print(f"🔄 Creando backup: {backup_name}")
    print("-" * 70)
    
    # Crear archivo ZIP
    zip_filename = f"{backup_path}.zip"
    
    try:
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            
            # Backup de la base de datos
            if os.path.exists('turnos.db'):
                print("   ✓ Agregando turnos.db...")
                zipf.write('turnos.db')
                size = os.path.getsize('turnos.db')
                print(f"     Tamaño: {size/1024:.2f} KB")
            else:
                print("   ⚠️ turnos.db no encontrada")
            
            # Backup de archivos de receta
            if os.path.exists('uploads'):
                print("   ✓ Agregando uploads/...")
                count = 0
                total_size = 0
                for root, dirs, files in os.walk('uploads'):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zipf.write(file_path)
                        count += 1
                        total_size += os.path.getsize(file_path)
                print(f"     Archivos: {count}")
                print(f"     Tamaño: {total_size/1024/1024:.2f} MB")
            else:
                print("   ℹ️ uploads/ no existe (sin archivos)")
            
            # Backup de archivos de configuración
            config_files = [
                'obras_entero.txt',
                'CODIGO_ESTUDIO_UB.txt',
                'NOMBRES_PARA_CARRUSEL.txt',
                'requirements.txt',
                '.env.example'
            ]
            
            print("   ✓ Agregando archivos de configuración...")
            for config_file in config_files:
                if os.path.exists(config_file):
                    zipf.write(config_file)
                    print(f"     ✓ {config_file}")
        
        # Verificar el backup creado
        backup_size = os.path.getsize(zip_filename)
        
        print()
        print("=" * 70)
        print("✅ BACKUP COMPLETADO")
        print("=" * 70)
        print(f"📦 Archivo: {zip_filename}")
        print(f"💾 Tamaño: {backup_size/1024/1024:.2f} MB")
        print(f"📅 Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print()
        print("💡 IMPORTANTE:")
        print("   1. Guardá este archivo en un lugar seguro")
        print("   2. Considerá subirlo a Google Drive / Dropbox")
        print("   3. Mantené al menos 3 backups: actual, mensual, anual")
        print()
        print("📂 Para restaurar:")
        print(f"   1. Descomprimí {os.path.basename(zip_filename)}")
        print("   2. Reemplazá turnos.db y uploads/")
        print()
        
        return True
        
    except Exception as e:
        print()
        print(f"❌ Error al crear backup: {e}")
        return False

def list_backups():
    """Lista los backups existentes"""
    
    backup_dir = "backups"
    
    if not os.path.exists(backup_dir):
        print("📁 No hay backups creados aún")
        return
    
    backups = [f for f in os.listdir(backup_dir) if f.endswith('.zip')]
    
    if not backups:
        print("📁 No hay backups en la carpeta backups/")
        return
    
    print()
    print("📦 BACKUPS DISPONIBLES:")
    print("-" * 70)
    
    backups.sort(reverse=True)  # Más recientes primero
    
    for backup in backups:
        backup_path = os.path.join(backup_dir, backup)
        size = os.path.getsize(backup_path)
        mtime = os.path.getmtime(backup_path)
        date = datetime.fromtimestamp(mtime).strftime('%d/%m/%Y %H:%M')
        
        print(f"   {backup}")
        print(f"   Tamaño: {size/1024/1024:.2f} MB | Fecha: {date}")
        print()

if __name__ == '__main__':
    create_backup()
    list_backups()

