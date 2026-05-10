"""
Sistema de Semàfors Intel·ligent — Arduino UNO Q (App Lab)
==========================================================
Arquitectura: 1 MASTER + N SLAVES

El MPU (Qualcomm / Linux) corre aquest script Python.
El MCU (STM32 / Zephyr) rep ordres via el Bridge del App Lab.

Zones:
  - Zona 1: Cruce petit  → gestionada pel MASTER (càmera local)
  - Zona 2: Cruce gran   → gestionada pel SLAVE 1 (envia via HTTP)

Detecció de càmera:
  Brick: VideoObjectDetection
  on_detect_all rep: { "cotxe_esperant": 0.87, "pato_passant": 0.72, ... }
  Les classes del model (Edge Impulse) codifiquen tipus + estat.

Payload que cada SLAVE envia al MASTER:
  {
    "slave":    <int>,
    "zona":     <int>,
    "objectes": [{"tipus": str, "estat": str}, ...]
  }

Algoritme (per zona):
  - Pato esperant + sense cotxes → VERMELL immediat
  - Pato esperant + cotxes passant → esperar, tret que:
      a) Pato porta > 2 min esperant
      b) ≤ 2 cotxes passant i no hi ha risc
  - Pato passant → mantenir VERMELL fins que acabi
  - Màxim 60s en VERMELL
"""

import os
import time
import threading
import requests
import socket

from flask import Flask, request, jsonify, render_template

# ---------------------------------------------------------------------------
# Compatibilitat App Lab Runner
# ---------------------------------------------------------------------------
try:
    from arduino.app_utils import App
    USING_APP_RUNNER = True
except ImportError:
    USING_APP_RUNNER = False

# Brick de detecció de vídeo (disponible a l'App Lab)
try:
    from arduino.app_bricks.video_objectdetection import VideoObjectDetection
    BRICK_AVAILABLE = True
except ImportError:
    BRICK_AVAILABLE = False

# Bridge MPU → MCU per controlar els semàfors físics
try:
    from arduino import bridge
    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Rutas de templates i assets
# ---------------------------------------------------------------------------
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR   = os.path.join(PROJECT_ROOT, 'assets')

app = Flask(__name__,
            static_folder=ASSETS_DIR,
            static_url_path='',
            template_folder=ASSETS_DIR)

# ---------------------------------------------------------------------------
# Configuració (edita abans de desplegar cada placa)
# ---------------------------------------------------------------------------
ROLE       = "SLAVE"          # "MASTER" | "SLAVE"
SLAVE_ID   = 1                 # Ignorat si ROLE == "MASTER"
SLAVE_ZONA = 2                 # Zona que controla aquest SLAVE
MASTER_IP  = "10.160.177.35"   # IP del MASTER (usada pels SLAVES)
MASTER_PORT = 8080

# Configuració del Brick de càmera
CAM_CONFIDENCE = 0.4   # Threshold de confiança (40%)
CAM_DEBOUNCE   = 0.5   # Segons entre deteccions repetides de la mateixa classe

# Mode de testing: True = simula la càmera sense Brick real
# Seqüència: cotxes passant 10s → pato esperant → VERMELL → pato caminant → VERD
TESTING_SLAVE = False

# ---------------------------------------------------------------------------
# Utilitat de xarxa
# ---------------------------------------------------------------------------
def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ===========================================================================
# MAPA DE CLASSES DEL MODEL → OBJECTES DEL SISTEMA
# ===========================================================================
# El model d'Edge Impulse té classes compostes: "tipus_estat"
# El Brick retorna: { "cotxe_esperant": 0.87, "pato_passant": 0.72, ... }
#
CLASSE_A_OBJECTE: dict[str, tuple[str, str]] = {
    "cotxe_esperant": ("cotxe", "esperant"),
    "cotxe_passant":  ("cotxe", "passant"),
    "pato_esperant":  ("pato",  "esperant"),
    "pato_passant":   ("pato",  "passant"),
    "pato_caminant":  ("pato",  "caminant"),
}

def detections_to_objectes(detections: dict) -> list[dict]:
    """
    Converteix el dict del Brick { label: confidence, ... }
    a la llista d'objectes del sistema [{ tipus, estat }, ...].

    Nota: el Brick ja aplica el debounce i threshold configurats.
    Cada clau present en el dict és una detecció activa en aquest frame.
    """
    objectes = []
    for label, confidence in detections.items():
        if label in CLASSE_A_OBJECTE:
            tipus, estat = CLASSE_A_OBJECTE[label]
            objectes.append({"tipus": tipus, "estat": estat, "confidence": round(confidence, 2)})
        else:
            # Classe no reconeguda pel sistema (log informatiu)
            print(f"[CAM] Classe desconeguda ignorada: '{label}' ({confidence:.0%})")
    return objectes


# ===========================================================================
# ESTAT GLOBAL DEL SISTEMA
# ===========================================================================
# Per zona: clau = zona_id (int)
# {
#   "objectes":            list[dict],   # deteccions actuals
#   "semafor":             "VERD" | "VERMELL",
#   "vermell_des_de":      float | None, # timestamp inici vermell
#   "pato_esperant_des_de":float | None, # timestamp 1er pato esperant
#   "actualitzat":         float,        # timestamp darrera actualització
# }
estat_zones: dict[int, dict] = {
    1: {
        "objectes": [],
        "semafor": "VERD",
        "vermell_des_de": None,
        "pato_esperant_des_de": None,
        "actualitzat": 0.0,
    },
    2: {
        "objectes": [],
        "semafor": "VERD",
        "vermell_des_de": None,
        "pato_esperant_des_de": None,
        "actualitzat": 0.0,
    },
}

estat_lock = threading.Lock()

# Historial d'esdeveniments per al dashboard
call_logs: list[dict] = []


# ===========================================================================
# ALGORITME DE SEMÀFORS
# ===========================================================================

MAX_VERMELL_SEG     = 60    # Màxim temps en vermell (1 min)
MAX_ESPERA_PATO_SEG = 120   # Màxim temps que pot esperar un pato (2 min)
MAX_COTXES_SAFE     = 2     # Cotxes passant considerats "tràfic acceptable"


def _compta(objectes: list[dict], tipus: str, estat: str | None = None) -> int:
    """Compta objectes d'un tipus i estat (estat=None = qualsevol)."""
    return sum(
        1 for o in objectes
        if o["tipus"] == tipus and (estat is None or o["estat"] == estat)
    )


def actualitzar_semafor(zona_id: int) -> None:
    """
    Aplica l'algoritme per a una zona i actualitza el semàfor.
    S'ha d'executar AMB estat_lock adquirit.
    Crida enviar_ordre_mcu si l'estat canvia.
    """
    z   = estat_zones[zona_id]
    ara = time.time()
    obj = z["objectes"]

    cotxes_passant = _compta(obj, "cotxe", "passant")
    patos_esperant = _compta(obj, "pato",  "esperant")
    patos_passant  = _compta(obj, "pato",  "passant")

    # Registra quan va arribar el primer pato esperant
    if patos_esperant > 0:
        if z["pato_esperant_des_de"] is None:
            z["pato_esperant_des_de"] = ara
    else:
        z["pato_esperant_des_de"] = None

    estat_anterior = z["semafor"]

    if z["semafor"] == "VERMELL":
        temps_vermell      = ara - z["vermell_des_de"]
        tot_net            = patos_esperant == 0 and patos_passant == 0
        timeout_vermell    = temps_vermell >= MAX_VERMELL_SEG

        if tot_net or timeout_vermell:
            z["semafor"]        = "VERD"
            z["vermell_des_de"] = None
            z["pato_esperant_des_de"] = None

    else:  # VERD
        posar_vermell = False

        if patos_esperant > 0:
            if cotxes_passant == 0:
                posar_vermell = True               # Sense cotxes: prioritat immediata
            else:
                temps_espera          = ara - z["pato_esperant_des_de"] \
                                        if z["pato_esperant_des_de"] else 0
                pato_ha_esperat_massa = temps_espera >= MAX_ESPERA_PATO_SEG
                trafic_acceptable     = cotxes_passant <= MAX_COTXES_SAFE

                if pato_ha_esperat_massa or trafic_acceptable:
                    posar_vermell = True

        if patos_passant > 0:
            posar_vermell = True                   # Pato ja passant: no interrompre

        if posar_vermell:
            z["semafor"] = "VERMELL"
            if z["vermell_des_de"] is None:
                z["vermell_des_de"] = ara

    if z["semafor"] != estat_anterior:
        print(f"[SEMAFOR Z{zona_id}] {estat_anterior} → {z['semafor']}")
        enviar_ordre_mcu(zona_id, z["semafor"])


def enviar_ordre_mcu(zona_id: int, estat: str) -> None:
    """Envia l'estat del semàfor al MCU via Bridge del App Lab."""
    clau = f"semafor_{zona_id}"
    if BRIDGE_AVAILABLE:
        try:
            bridge.put(clau, estat)
        except Exception as e:
            print(f"[BRIDGE] Error {clau}={estat}: {e}")
    else:
        print(f"[BRIDGE-SIM] {clau} = {estat}")


# ===========================================================================
# CÀMERA — Brick VideoObjectDetection
# ===========================================================================

def _crear_detector() -> "VideoObjectDetection | None":
    """Inicialitza el Brick de detecció. Retorna None si no disponible."""
    if not BRICK_AVAILABLE:
        print("[CAM] Brick VideoObjectDetection no disponible (entorn local).")
        return None
    detector = VideoObjectDetection(
        camera=None,                # Càmera per defecte (USB)
        confidence=CAM_CONFIDENCE,
        debounce_sec=CAM_DEBOUNCE,
        camera_preview=False,
    )
    return detector


# --- Callback per al MASTER (actualitza Zona 1 directament) ---
def _callback_master(detections: dict) -> None:
    """
    Callback on_detect_all per al MASTER.
    detections = { "cotxe_esperant": 0.87, "pato_passant": 0.72, ... }
    """
    objectes = detections_to_objectes(detections)

    with estat_lock:
        estat_zones[1]["objectes"]    = objectes
        estat_zones[1]["actualitzat"] = time.time()
        actualitzar_semafor(1)

    resum = _resum_objectes(objectes)
    print(f"[CAM MASTER] Zona 1: {resum or 'cap objecte'}")


# --- Callback per al SLAVE (acumula deteccions per enviar-les al MASTER) ---
_slave_deteccions_actuals: list[dict] = []
_slave_lock = threading.Lock()

def _callback_slave(detections: dict) -> None:
    """
    Callback on_detect_all per al SLAVE.
    Emmagatzema les deteccions actuals perquè loop() les enviï.
    """
    global _slave_deteccions_actuals
    objectes = detections_to_objectes(detections)

    with _slave_lock:
        _slave_deteccions_actuals = objectes

    resum = _resum_objectes(objectes)
    print(f"[CAM SLAVE {SLAVE_ID}] Zona {SLAVE_ZONA}: {resum or 'cap objecte'}")


def _resum_objectes(objectes: list[dict]) -> str:
    return ", ".join(f"{o['tipus']} ({o['estat']})" for o in objectes)


# ===========================================================================
# ENDPOINTS FLASK (MASTER)
# ===========================================================================

@app.route('/', methods=['GET'])
def dashboard():
    return render_template('index.html', port=MASTER_PORT)


@app.route('/api/logs', methods=['GET'])
def get_logs():
    with estat_lock:
        zones_snapshot = {
            str(zid): {
                "semafor":  z["semafor"],
                "objectes": z["objectes"],
            }
            for zid, z in estat_zones.items()
        }
    return jsonify({
        "logs":  list(reversed(call_logs)),
        "zones": zones_snapshot,
        "port":  MASTER_PORT,
    })


@app.route('/api/camera-data', methods=['POST'])
def receive_camera_data():
    """
    Endpoint per als SLAVES.
    Payload: { "slave": int, "zona": int, "objectes": [{tipus, estat}] }
    """
    if not request.is_json:
        return jsonify({"status": "error", "message": "Payload must be JSON"}), 400

    data     = request.get_json()
    slave_id = data.get("slave")
    zona_id  = data.get("zona")
    objectes = data.get("objectes", [])

    if slave_id is None or zona_id is None:
        return jsonify({"status": "error", "message": "Camps 'slave' i 'zona' obligatoris"}), 400

    if zona_id not in estat_zones:
        return jsonify({"status": "error", "message": f"Zona {zona_id} desconeguda"}), 400

    timestamp = time.strftime("%H:%M:%S")

    with estat_lock:
        estat_zones[zona_id]["objectes"]    = objectes
        estat_zones[zona_id]["actualitzat"] = time.time()
        actualitzar_semafor(zona_id)
        semafor_actual = estat_zones[zona_id]["semafor"]

    resum = _resum_objectes(objectes) or "cap objecte"

    call_logs.append({
        "slave":    slave_id,
        "zona":     zona_id,
        "objectes": objectes,
        "resum":    resum,
        "semafor":  semafor_actual,
        "time":     timestamp,
    })
    if len(call_logs) > 50:
        call_logs.pop(0)

    print(f"[MASTER ← SLAVE {slave_id}] Zona {zona_id}: {resum} | Semafor: {semafor_actual}")
    return jsonify({"status": "ok", "semafor": semafor_actual})


def run_flask_server():
    print(f"[MASTER] Iniciant servidor Flask al port {MASTER_PORT}...")
    app.run(host='0.0.0.0', port=MASTER_PORT, debug=False, use_reloader=False)


# ===========================================================================
# SLAVE: enviament periòdic al MASTER
# ===========================================================================

def send_camera_data() -> None:
    """Envia les deteccions actuals al MASTER via HTTP POST."""
    with _slave_lock:
        objectes = list(_slave_deteccions_actuals)

    url     = f"http://{MASTER_IP}:{MASTER_PORT}/api/camera-data"
    payload = {"slave": SLAVE_ID, "zona": SLAVE_ZONA, "objectes": objectes}
    try:
        r = requests.post(url, json=payload, timeout=2)
        print(f"[SLAVE {SLAVE_ID}] {len(objectes)} objectes enviats → HTTP {r.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[SLAVE {SLAVE_ID}] Error connectant al Master ({url}): {e}")


# ===========================================================================
# MODE TESTING — Simulació de càmera sense Brick real
# ===========================================================================

def _sim_inject(zona: int, detections: dict) -> None:
    """
    Injecta deteccions simulades seguint el mateix camí que la càmera real:
      - Zona pròpia del SLAVE (SLAVE_ZONA): via _callback_slave → loop() envia HTTP
      - Zona 1 en rol MASTER:               via _callback_master → estat directe
      - Zones creuades:                     via HTTP POST al Master
    """
    if ROLE == "SLAVE" and zona == SLAVE_ZONA:
        _callback_slave(detections)

    elif ROLE == "MASTER" and zona == 1:
        _callback_master(detections)

    else:
        # Zona que no és la pròpia: enviem via HTTP igual que un SLAVE real
        objectes = detections_to_objectes(detections)
        url      = f"http://{MASTER_IP}:{MASTER_PORT}/api/camera-data"
        payload  = {"slave": 0, "zona": zona, "objectes": objectes}  # slave=0 = simulat
        try:
            requests.post(url, json=payload, timeout=2)
        except Exception as e:
            print(f"[TEST] Error enviant zona {zona} al Master: {e}")


def _sim_zona(zona: int) -> None:
    """
    Simula la seqüència completa per a UNA zona:
      1. Cotxes passant      (10s — 2 ticks × 5s)
      2. Pato esperant       ( 5s — 1 tick)
      3. Cotxes aturats      ( 5s — 1 tick)  → semàfor VERMELL
      4. Pato caminant       (10s — 2 ticks × 5s)
      5. Zona neta           ( 5s — 1 tick)
    Total per zona: ~35s
    """
    print(f"\n[TEST] ── Zona {zona} ──────────────────────────────────")

    # 1. Cotxes passant (10s)
    print(f"[TEST] Z{zona} ▸ cotxes passant (10s)")
    for _ in range(2):
        _sim_inject(zona, {"cotxe_passant": 0.99})
        time.sleep(5)

    # 2. Pato apareix + cotxes segueixen passant (5s)
    print(f"[TEST] Z{zona} ▸ pato esperant + cotxes passant (5s)")
    _sim_inject(zona, {"cotxe_passant": 0.99, "pato_esperant": 0.99})
    time.sleep(5)

    # 3. Cotxes s'aturen + pato segueix esperant → VERMELL (5s)
    print(f"[TEST] Z{zona} ▸ cotxes aturats + pato esperant → VERMELL (5s)")
    _sim_inject(zona, {"cotxe_esperant": 0.99, "pato_esperant": 0.99})
    time.sleep(5)

    # 4. Pato caminant + cotxes aturats (10s)
    print(f"[TEST] Z{zona} ▸ pato caminant + cotxes aturats (10s)")
    for _ in range(2):
        _sim_inject(zona, {"cotxe_esperant": 0.99, "pato_caminant": 0.99})
        time.sleep(5)

    # 5. Zona neta (5s)
    print(f"[TEST] Z{zona} ▸ zona neta (5s)")
    _sim_inject(zona, {})
    time.sleep(5)


def _run_simulation() -> None:
    """
    Thread de simulació (TESTING_SLAVE=True).
    Bucle infinit: primer Z1, després Z2, entre cicles 20s d'alternança.
    """
    time.sleep(5)  # Esperar Flask

    cicle = 1
    while True:
        print(f"\n[TEST] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"[TEST]  CICLE #{cicle}")
        print(f"[TEST] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Primer Zona 1, després Zona 2
        _sim_zona(1)
        _sim_zona(2)

        # Alternança de 20s sense patos (semàfors es turnen sols)
        print(f"\n[TEST] Z1 i Z2 netes — alternança automàtica 20s")
        time.sleep(20)

        print(f"[TEST] ─── Cicle #{cicle} completat ───")
        cicle += 1


# ===========================================================================
# BUCLE PRINCIPAL (user_loop per a App.run)
# ===========================================================================

def loop() -> None:
    """Executat repetidament pel framework. Re-avalua l'algoritme per timeouts."""
    if ROLE == "MASTER":
        # Re-evaluar periòdicament per gestionar timeouts (2-min pato, 1-min vermell)
        with estat_lock:
            for zona_id in estat_zones:
                actualitzar_semafor(zona_id)
        time.sleep(1)

    elif ROLE == "SLAVE":
        # El Brick actualitza _slave_deteccions_actuals via callback.
        # Aquí simplement enviem l'estat actual al Master cada 2s.
        send_camera_data()
        time.sleep(2)


# ===========================================================================
# ARRENCADA
# ===========================================================================

def main() -> None:
    print(f"\n{'=' * 60}")
    print(f"  Sistema de Semàfors Intel·ligent — Arduino UNO Q")
    print(f"  Rol: {ROLE} | App Lab: {USING_APP_RUNNER} | "
          f"Brick: {BRICK_AVAILABLE} | Bridge: {BRIDGE_AVAILABLE}")
    print(f"{'=' * 60}\n")

    # No inicialitzar el Brick si estem en mode testing
    detector = None if TESTING_SLAVE else _crear_detector()

    if ROLE == "MASTER":
        real_ip = get_local_ip()
        print(f"[MASTER] 🌐 IP:         {real_ip}")
        print(f"[MASTER] 🚀 Dashboard:  http://{real_ip}:{MASTER_PORT}/")
        print(f"[MASTER] 📡 API:        http://{real_ip}:{MASTER_PORT}/api/camera-data\n")

        # Flask en thread separat (daemon)
        threading.Thread(target=run_flask_server, daemon=True).start()

        if detector:
            # El MASTER observa la Zona 1 amb la seva pròpia càmera
            detector.on_detect_all(_callback_master)
            detector.start()
            print("[MASTER] 📷 Càmera (Zona 1) iniciada via Brick VideoObjectDetection.")
        else:
            print("[MASTER] ⚠️  Sense Brick — Zona 1 s'actualitzarà via /api/camera-data.")

    elif ROLE == "SLAVE":
        print(f"[SLAVE {SLAVE_ID}] Zona assignada: {SLAVE_ZONA}")
        print(f"[SLAVE {SLAVE_ID}] Enviant dades a: http://{MASTER_IP}:{MASTER_PORT}\n")

        if TESTING_SLAVE:
            print(f"[SLAVE {SLAVE_ID}] 🧪 Mode testing actiu — càmera simulada.")
        elif detector:
            # El SLAVE observa la seva zona i acumula les deteccions
            detector.on_detect_all(_callback_slave)
            detector.start()
            print(f"[SLAVE {SLAVE_ID}] 📷 Càmera (Zona {SLAVE_ZONA}) iniciada via Brick.")
        else:
            print(f"[SLAVE {SLAVE_ID}] ⚠️  Sense Brick — les deteccions seran buides.")

    # Arrancar thread de simulació si TESTING_SLAVE=True (per a qualsevol rol)
    if TESTING_SLAVE:
        threading.Thread(target=_run_simulation, daemon=True).start()

    # App.run() manté els threads del Brick actius i crida loop() periòdicament.
    # En entorn local (sense App Lab) simulem el comportament manualment.
    if USING_APP_RUNNER:
        App.run(user_loop=loop)
    else:
        print("[INFO] Mode local — prem Ctrl+C per aturar.\n")
        try:
            while True:
                loop()
        except KeyboardInterrupt:
            if detector:
                detector.stop()
            print("\n[INFO] Sistema aturat per l'usuari.")


if __name__ == "__main__":
    main()