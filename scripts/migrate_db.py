#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de migración de base de datos
Agrega los campos created_at y updated_at a la tabla turnos existente
También crea índices para mejorar rendimiento
"""

import sqlite3
import os
from datetime import datetime

def migrate_database():
    """Migra la base de datos a la nueva estructura"""
    
    db_path = 'turnos.db'
    
    if not os.path.exists(db_path):
        print("❌ No se encontró la base de datos turnos.db")
        print("💡 Si es una instalación nueva, no necesitás ejecutar este script.")
        return
    
    print("🔄 Iniciando migración de base de datos...")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Crear backup
        backup_name = f'turnos_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        import shutil
        shutil.copy(db_path, backup_name)
        print(f"✅ Backup creado: {backup_name}")
        
        # Verificar si los campos ya existen
        cursor.execute("PRAGMA table_info(turnos)")
        columns = [col[1] for col in cursor.fetchall()]
        
        needs_migration = False
        
        # Agregar campo created_at si no existe
        if 'created_at' not in columns:
            print("➕ Agregando campo created_at...")
            cursor.execute('''
                ALTER TABLE turnos 
                ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ''')
            needs_migration = True
        else:
            print("✓ Campo created_at ya existe")
        
        # Agregar campo updated_at si no existe
        if 'updated_at' not in columns:
            print("➕ Agregando campo updated_at...")
            cursor.execute('''
                ALTER TABLE turnos 
                ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ''')
            needs_migration = True
        else:
            print("✓ Campo updated_at ya existe")
        
        # Crear índices si no existen
        print("🔍 Creando índices para mejorar rendimiento...")
        
        try:
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_fecha_hora 
                ON turnos(fecha, hora)
            ''')
            print("✓ Índice idx_fecha_hora creado")
        except sqlite3.OperationalError:
            print("✓ Índice idx_fecha_hora ya existe")
        
        try:
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_email 
                ON turnos(email)
            ''')
            print("✓ Índice idx_email creado")
        except sqlite3.OperationalError:
            print("✓ Índice idx_email ya existe")
        
        try:
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_fecha 
                ON turnos(fecha)
            ''')
            print("✓ Índice idx_fecha creado")
        except sqlite3.OperationalError:
            print("✓ Índice idx_fecha ya existe")
        
        # Guardar cambios
        conn.commit()
        
        if needs_migration:
            print("\n✅ Migración completada exitosamente!")
            print(f"📁 Backup disponible en: {backup_name}")
        else:
            print("\n✅ La base de datos ya estaba actualizada")
            print(f"📁 Backup creado por seguridad: {backup_name}")
        
        # Mostrar estadísticas
        cursor.execute("SELECT COUNT(*) FROM turnos")
        total_turnos = cursor.fetchone()[0]
        print(f"📊 Total de turnos en la base de datos: {total_turnos}")
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"❌ Error de base de datos: {e}")
        print("💡 Restaurá el backup si es necesario")
        return False
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        return False
    
    return True

def verify_migration():
    """Verifica que la migración se haya realizado correctamente"""
    
    db_path = 'turnos.db'
    
    if not os.path.exists(db_path):
        print("❌ Base de datos no encontrada")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Verificar estructura
        cursor.execute("PRAGMA table_info(turnos)")
        columns = {col[1]: col[2] for col in cursor.fetchall()}
        
        print("\n🔍 Verificando estructura de la tabla turnos:")
        print("-" * 50)
        
        required_columns = {
            'id': 'INTEGER',
            'nombre': 'TEXT',
            'email': 'TEXT',
            'telefono': 'TEXT',
            'fecha': 'TEXT',
            'hora': 'TEXT',
            'tipo': 'TEXT',
            'receta': 'TEXT',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP'
        }
        
        all_ok = True
        for col_name, col_type in required_columns.items():
            if col_name in columns:
                print(f"✓ {col_name}: {columns[col_name]}")
            else:
                print(f"❌ {col_name}: FALTA")
                all_ok = False
        
        # Verificar índices
        cursor.execute("PRAGMA index_list(turnos)")
        indices = [idx[1] for idx in cursor.fetchall()]
        
        print("\n🔍 Verificando índices:")
        print("-" * 50)
        
        required_indices = ['idx_fecha_hora', 'idx_email', 'idx_fecha']
        for idx in required_indices:
            if idx in indices:
                print(f"✓ {idx}")
            else:
                print(f"❌ {idx}: FALTA")
                all_ok = False
        
        conn.close()
        
        if all_ok:
            print("\n✅ Todas las verificaciones pasaron correctamente")
        else:
            print("\n⚠️ Algunas verificaciones fallaron")
        
        return all_ok
        
    except Exception as e:
        print(f"❌ Error al verificar: {e}")
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("  🔄 MIGRACIÓN DE BASE DE DATOS - LABORATORIO SCOZZINA")
    print("=" * 60)
    print()
    
    # Ejecutar migración
    if migrate_database():
        print()
        # Verificar migración
        verify_migration()
    
    print()
    print("=" * 60)
    print("  Migración finalizada")
    print("=" * 60)

