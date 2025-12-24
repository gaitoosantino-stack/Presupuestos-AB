#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para verificar el tamaño de la base de datos y archivos
"""

import os
import sqlite3
from datetime import datetime

def format_size(bytes):
    """Formatea bytes a formato legible"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.2f} TB"

def get_directory_size(path):
    """Calcula el tamaño total de un directorio"""
    total = 0
    count = 0
    if os.path.exists(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
                    count += 1
    return total, count

def check_database():
    """Verifica información de la base de datos"""
    
    print("=" * 70)
    print("  📊 ANÁLISIS DE ESPACIO - LABORATORIO SCOZZINA")
    print("=" * 70)
    print()
    
    # Base de datos
    print("🗄️  BASE DE DATOS (turnos.db)")
    print("-" * 70)
    
    if os.path.exists('turnos.db'):
        db_size = os.path.getsize('turnos.db')
        print(f"   Tamaño: {format_size(db_size)}")
        
        # Contar registros
        try:
            conn = sqlite3.connect('turnos.db')
            cursor = conn.cursor()
            
            # Total de turnos
            cursor.execute("SELECT COUNT(*) FROM turnos")
            total_turnos = cursor.fetchone()[0]
            print(f"   Turnos registrados: {total_turnos:,}")
            
            if total_turnos > 0:
                # Tamaño promedio por turno
                avg_size = db_size / total_turnos if total_turnos > 0 else 0
                print(f"   Tamaño promedio/turno: {format_size(avg_size)}")
                
                # Turnos con receta
                cursor.execute("SELECT COUNT(*) FROM turnos WHERE receta IS NOT NULL")
                con_receta = cursor.fetchone()[0]
                print(f"   Turnos con receta: {con_receta:,} ({con_receta/total_turnos*100:.1f}%)")
                
                # Primer y último turno
                cursor.execute("SELECT MIN(fecha), MAX(fecha) FROM turnos")
                min_fecha, max_fecha = cursor.fetchone()
                print(f"   Rango de fechas: {min_fecha} → {max_fecha}")
                
                # Turnos por mes (últimos 6 meses)
                cursor.execute("""
                    SELECT strftime('%Y-%m', fecha) as mes, COUNT(*) 
                    FROM turnos 
                    GROUP BY mes 
                    ORDER BY mes DESC 
                    LIMIT 6
                """)
                turnos_mensuales = cursor.fetchall()
                
                if turnos_mensuales:
                    print(f"\n   📅 Últimos 6 meses:")
                    for mes, cantidad in turnos_mensuales:
                        print(f"      {mes}: {cantidad:,} turnos")
            
            conn.close()
            
        except Exception as e:
            print(f"   ⚠️ Error al leer BD: {e}")
    else:
        print("   ❌ No se encontró turnos.db")
    
    print()
    
    # Archivos de receta
    print("📄 ARCHIVOS DE RECETA (uploads/)")
    print("-" * 70)
    
    if os.path.exists('uploads'):
        uploads_size, uploads_count = get_directory_size('uploads')
        print(f"   Tamaño total: {format_size(uploads_size)}")
        print(f"   Cantidad de archivos: {uploads_count:,}")
        
        if uploads_count > 0:
            avg_file_size = uploads_size / uploads_count
            print(f"   Tamaño promedio/archivo: {format_size(avg_file_size)}")
    else:
        print("   📁 Carpeta uploads/ no existe (se creará al subir archivos)")
    
    print()
    
    # Total
    print("💾 RESUMEN TOTAL")
    print("-" * 70)
    
    total_size = 0
    if os.path.exists('turnos.db'):
        total_size += os.path.getsize('turnos.db')
    if os.path.exists('uploads'):
        total_size += get_directory_size('uploads')[0]
    
    print(f"   Espacio total usado: {format_size(total_size)}")
    
    # Proyecciones
    if os.path.exists('turnos.db') and total_turnos > 0:
        print()
        print("📈 PROYECCIONES")
        print("-" * 70)
        
        # Calcular turnos por día promedio
        if min_fecha and max_fecha:
            try:
                fecha_inicio = datetime.strptime(min_fecha, '%Y-%m-%d')
                fecha_fin = datetime.strptime(max_fecha, '%Y-%m-%d')
                dias = (fecha_fin - fecha_inicio).days + 1
                
                if dias > 0:
                    turnos_por_dia = total_turnos / dias
                    print(f"   Promedio actual: {turnos_por_dia:.1f} turnos/día")
                    
                    # Proyecciones
                    size_per_turno = total_size / total_turnos
                    
                    print(f"\n   Si continúa a este ritmo:")
                    print(f"      En 1 mes:  ~{format_size(size_per_turno * turnos_por_dia * 30)}")
                    print(f"      En 6 meses: ~{format_size(size_per_turno * turnos_por_dia * 180)}")
                    print(f"      En 1 año:   ~{format_size(size_per_turno * turnos_por_dia * 365)}")
            except:
                pass
    
    print()
    
    # Recomendaciones
    print("💡 RECOMENDACIONES")
    print("-" * 70)
    
    if total_size < 100 * 1024 * 1024:  # < 100 MB
        print("   ✅ Espacio usado: BAJO")
        print("   👍 No necesitas hacer nada especial por ahora")
        print("   📝 Continuá con backups mensuales regulares")
    
    elif total_size < 500 * 1024 * 1024:  # < 500 MB
        print("   ⚠️ Espacio usado: MODERADO")
        print("   💡 Considerá archivar recetas de hace +6 meses")
        print("   📦 Hacé un backup completo pronto")
    
    else:  # > 500 MB
        print("   🔴 Espacio usado: ALTO")
        print("   ⚠️ Recomendación: Archivar datos antiguos YA")
        print("   📦 Backup completo urgente")
        print("   🗄️ Mover recetas antiguas a almacenamiento externo")
    
    print()
    print("=" * 70)
    print()

if __name__ == '__main__':
    check_database()

