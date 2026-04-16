import sys
import os
import time
import psycopg2
import base64
from flask import Flask, render_template, redirect, url_for, Response, request
from psycopg2 import extras
from zk import ZK, const
from datetime import datetime

# --- CONFIGURACIÓN PARA EJECUTABLE (.EXE) ---
def resource_path(relative_path):
    """ Obtiene la ruta de los recursos para PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

app = Flask(__name__, template_folder=resource_path("templates"))

# --- CONFIGURACIÓN DE INFRAESTRUCTURA HRCV ---
DISPOSITIVOS = [
    {'nombre': 'G1 - Piso 1', 'ip': '192.168.43.199'},
    {'nombre': 'G1 - Piso 2', 'ip': '192.168.43.198'}
]
PUERTO_HUELLERO = 4370

# Datos de la DB Biosecurity en el servidor .244
DB_PARAMS = {
    "user": "postgress", 
    "password": "", 
    "host": "0.0.0.0", 
    "port": "5442", 
    "database": "biosecurity-boot"
}

# --- CLASE DE APOYO PARA PLANTILLAS DE HUELLA ---
class ZKTemplateFix:
    def __init__(self, uid, fid, data):
        self.uid, self.fid = uid, fid
        self.template = base64.b64decode(data) if isinstance(data, str) else bytes(data)
    def repack_only(self): return self.template
    def __iter__(self):
        yield self.uid; yield self.fid; yield self.template

# --- UTILIDADES DE BASE DE DATOS ---
def obtener_datos_db(query, params=None):
    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute(query, params)
        return cursor.fetchall()
    except Exception as e:
        print(f"❌ Error DB: {e}")
        return []
    finally:
        if conn: conn.close()

# --- RUTAS DE LA APLICACIÓN ---

@app.route('/')
def index():
    personal = obtener_datos_db("SELECT pin, name FROM pers_person ORDER BY name ASC")
    return render_template('index.html', personal=personal, dispositivos=DISPOSITIVOS)

@app.route('/sync/<ip>/<pin>/<nombre>')
def sync(ip, pin, nombre):
    pin_str = str(int(pin))
    huellas_db = obtener_datos_db("""
        SELECT b.template, b.template_no 
        FROM pers_biotemplate b 
        JOIN pers_person p ON p.id = b.person_id 
        WHERE p.pin = %s AND b.bio_type = 1
    """, (pin_str,))
    
    # Usamos TCP (force_udp=False) para mayor estabilidad en la sincronización
    zk = ZK(ip, port=PUERTO_HUELLERO, timeout=30, force_udp=False)
    conn = None
    try:
        print(f"--- Sincronizando {nombre} en {ip} ---")
        conn = zk.connect()
        conn.disable_device()
        conn.set_user(uid=int(pin_str), name=nombre[:24], privilege=const.USER_DEFAULT, user_id=pin_str)
        time.sleep(1)
        
        users_hw = conn.get_users()
        target = next((u for u in users_hw if str(u.user_id) == pin_str), None)
        
        if target and huellas_db:
            for h in huellas_db:
                h_fix = ZKTemplateFix(target.uid, int(h['template_no']), h['template'])
                conn.save_user_template(target, h_fix)
        
        conn.refresh_data()
        conn.enable_device()
    except Exception as e:
        print(f"❌ Error en Sincronización: {e}")
    finally:
        if conn: conn.disconnect()
    return redirect(url_for('index'))

@app.route('/descargar_asistencia')
def descargar_asistencia():
    pin_filtro = request.args.get('pin')
    ip_dispositivo = request.args.get('ip')
    
    # Timeout extendido para redes hospitalarias
    zk = ZK(ip_dispositivo, port=PUERTO_HUELLERO, timeout=90, force_udp=False)
    conn = None
    
    try:
        # Mapa de nombres desde PostgreSQL
        personal_db = obtener_datos_db("SELECT pin, name FROM pers_person")
        nombres_map = {str(p['pin']): p['name'] for p in personal_db}

        print(f"--- Conectando a {ip_dispositivo} ---")
        conn = zk.connect()
        conn.disable_device()
        
        # Descarga de registros
        logs = conn.get_attendance()
        
        # CSV Detallado (Todos los marcajes)
        csv_data = "sep=,\nPIN,Nombre,Fecha,Hora,Equipo\n"
        
        for log in logs:
            uid = str(log.user_id)
            if not pin_filtro or pin_filtro == "all" or uid == str(pin_filtro):
                nombre = nombres_map.get(uid, "No en BD")
                fecha = log.timestamp.strftime('%d/%m/%Y')
                hora = log.timestamp.strftime('%H:%M:%S')
                csv_data += f"{uid},{nombre},{fecha},{hora},{ip_dispositivo}\n"

        print(f"--- Reporte generado exitosamente ---")
        
        filename = f"asistencia_{ip_dispositivo}_{datetime.now().strftime('%H%M%S')}.csv"
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        print(f"❌ Error Reporte: {e}")
        return f"Error de conexión con el biométrico {ip_dispositivo}: {e}", 500
    finally:
        if conn:
            try:
                conn.enable_device()
                conn.disconnect()
            except: pass

if __name__ == '__main__':
    # host='0.0.0.0' para que sea visible en la red del Hospital
    # port=8080 para evitar conflictos con otros servicios web
    app.run(host='0.0.0.0', port=8080, debug=False)
