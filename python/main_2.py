import os
import time
import threading
import requests
import socket
from flask import Flask, request, jsonify, render_template

try:
    from arduino.app_bricks.video_objectdetection import VideoObjectDetection
except ImportError:
    print("Advertència: No s'ha pogut importar VideoObjectDetection.")

from arduino.app_utils import App

# Configuració de rutes per Flask
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR = os.path.join(PROJECT_ROOT, 'assets')

app = Flask(__name__, static_folder=ASSETS_DIR, template_folder=ASSETS_DIR)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# --- CONFIGURACIÓ (Canvia això a cada placa) ---
ROLE = "SLAVE"  # "MASTER" o "SLAVE"
SLAVE_ID = 1
MASTER_IP = "10.160.177.35"
MASTER_PORT = 8080

SLAVE_IP = "10.160.177.232"

# --- ESTAT GLOBAL (Només el Mestre) ---
# Ara guardem també la IP de l'esclau per al vídeo
slaves_connected = {} 

# --- INICIALITZACIÓ CÀMERA ---
print(f"[{ROLE}] Iniciant càmera...")
detection_stream = VideoObjectDetection(confidence=0.5, debounce_sec=0.0)

coches_local = 0
patos_local = 0

def procesar_detecciones(detections: dict):
    global coches_local, patos_local
    coches_local = len(detections.get("car", [])) + len(detections.get("coche", []))
    patos_local = len(detections.get("bird", [])) + len(detections.get("pato", []))

detection_stream.on_detect_all(procesar_detecciones)

# --- MESTRE: ENDPOINTS ---
@app.route('/')
def dashboard():
    return render_template('index.html', port=MASTER_PORT)

@app.route('/api/logs')
def get_logs():
    return jsonify({
        "slaves": slaves_connected,
        "master_ip": get_local_ip(),
        "port": MASTER_PORT
    })

@app.route('/api/camera-data', methods=['POST'])
def receive_camera_data():
    data = request.get_json()
    sid = data.get("slaveId")
    # Guardem la IP que ens envia l'esclau
    slaves_connected[sid] = {
        "ip": data.get("ip"),
        "cars": data.get("cars"),
        "patos": data.get("patos"),
        "time": time.strftime("%H:%M:%S")
    }
    return jsonify({"status": "ok"})

# --- BUCLE PRINCIPAL ---
def loop():
    if ROLE == "SLAVE":
        url = f"http://{MASTER_IP}:{MASTER_PORT}/api/camera-data"
        payload = {
            "slaveId": SLAVE_ID,
            "ip": SLAVE_IP, # enviem la nostra IP per al vídeo
            "cars": coches_local,
            "patos": patos_local
        }
        try:
            requests.post(url, json=payload, timeout=2)
        except:
            pass
        time.sleep(2)
    else:
        time.sleep(1)

def main():
    if ROLE == "MASTER":
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=MASTER_PORT, debug=False, use_reloader=False), daemon=True).start()
    App.run(user_loop=loop)

if __name__ == "__main__":
    main()



# Definicio del sistema

# Zones: El taulell esta dividit en 2 zones principals optimitzades per reduir els recursos i maximitzar el rang de visio
#    - Zona 1 (MASTER): Cruze petit
#    - Zona 2 (SLAVE) : Cruze gran
#
#
# Reconeixements: Cada camera detectara
#
#    - Patos: ( Pato | Esperant ); ( Pato | Passant ); 
#    - Cotxes: ( Cotxe | Passant ); ( Cotxe | Caminant ); ( Cotxe | Esperant ); 
#
#    Basicament es reconeix el objecte que es i el seu estat, sigui quin sigui 
#

#    El que hauria d'enviar cada SLAVE hauria de ser alguna cosa com ( el MASTER també ho ha de fer pero sense enviar-ho):
#    {
#        "slave": 1,
#        "zona":  2,
#        "objectes": [
#           { "tipus": "cotxe", "estat": "parat" }
#           { "tipus": "pato", "estat": "passant" }
#           { "tipus": "cotxe", "estat": "parat" }
#        ]
#    }
#    
#
#    El MASTER haura de tenir l'estat de tot el sistema i decidir en base a aixó
#
#
#
# Sistema: El sistema es un conjunt de semafors amb els seus estats i objectes amb els seus estats
#
#    Semafors:
#
#        Estats: { Vermell, Verd }
#    
#    Objectes: El que reconeixi la camera
#
#
#    Suposarem que si semafor està en vermell, el pato pot passar.
#
#    Hi ha un semafor per Zona.
#
#    El semafor 1 controla el tràfic de la zona 1
#
#    El semafor 2 controla el tràfic de la zona 2
#
#
# El sistema ha de ser suficientment inteligent per:
#
#    El semafor X ha de posar-se en vermell quan un pato vulgui passar a la Zona X, osigui, el seu estat sigui esperant.
#
#    
#    El semafor X ha de posar-se en verd un cop el pato hagi passat per la Zona X, osigui, el seu estat sigui caminant
#
#
#     Algoritme:
#
#        - Si no hi ha cap cotxe i hi ha un pato esperant, fer que passi el pato
#        - Si hi ha un pato esperant i hi ha cotxes passant, deixar que el trafic segueixi, exceptuant
#            - Si el pato ha esperat més de 2 min
#            - Si deixar passar el pato no agreujarà el trafic
#            - Si deixar passar el pato comporta un risc pel pato.
#
#        - Pot passar que hi hagi mes d'un pato passant, el semafor pot estar en vermell un maxim de 1 minut
#
#
#
#
#
#
#
#
#
#
#
#
#
#
