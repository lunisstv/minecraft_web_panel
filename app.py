from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session, flash
import subprocess
import os
import shlex
import signal
import time
import logging
import json
import shutil
from mcrcon import MCRcon, MCRconException
import socket
from functools import wraps # Für den Login-Decorator

# Logging-Konfiguration
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(name)s %(threadName)s : %(message)s')
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.INFO)

# --- BEGIN MONKEYPATCH für mcrcon (wie in der vorherigen korrigierten Version) ---
_original_signal_signal = signal.signal
_original_signal_alarm = signal.alarm
_original_MCRcon_init = MCRcon.__init__
_original_MCRcon_connect = MCRcon.connect
_original_MCRcon_command = MCRcon.command

def _patched_mcrcon_init(self, host, password, port=25575, timeout=5, tlsmode=0, tls_certfile=None, tls_keyfile=None, tls_ca_certs=None, family=socket.AF_UNSPEC):
    self.host = host; self.password = password; self.port = port
    self.timeout = timeout if timeout and timeout > 0 else 5
    self.tlsmode = tlsmode; self.tls_certfile = tls_certfile; self.tls_keyfile = tls_keyfile
    self.tls_ca_certs = tls_ca_certs; self.family = family; self.socket = None
    # signal.signal(signal.SIGALRM, self.__timeout_handler) WIRD WEGGELASSEN
    # logging.getLogger('app').debug(f"Patched MCRcon.__init__ for {self.host}:{self.port}. Signal handler registration skipped.") # Verwende app.logger

def _patched_mcrcon_connect(self):
    if self.socket: return
    # logging.getLogger('app').debug(f"Patched MCRcon.connect: Calling original connect for {self.host}:{self.port}")
    current_alarm = signal.alarm; signal.alarm = lambda t: logging.getLogger('app').debug(f"Patched MCRcon.connect: Skipped signal.alarm({t})")
    try:
        _original_MCRcon_connect(self)
        if self.socket:
            socket_timeout = self.timeout
            if socket_timeout is None or socket_timeout <= 0: socket_timeout = 5
            self.socket.settimeout(socket_timeout)
            # logging.getLogger('app').debug(f"Patched MCRcon.connect: Socket timeout set to {socket_timeout}s after original connect.")
    except Exception as e: raise
    finally: signal.alarm = current_alarm

def _patched_mcrcon_command(self, command_str):
    if not self.socket: _patched_mcrcon_connect(self)
    current_alarm = signal.alarm
    signal.alarm = lambda t: logging.getLogger('app').debug(f"Patched MCRcon.command: Skipped signal.alarm({t}) for command '{command_str}'")
    try:
        response = _original_MCRcon_command(self, command_str)
        return response
    except socket.timeout: raise MCRconException("RCON command timed out (socket timeout)")
    except Exception as e: raise
    finally: signal.alarm = current_alarm

MCRcon.__init__ = _patched_mcrcon_init
MCRcon.connect = _patched_mcrcon_connect
MCRcon.command = _patched_mcrcon_command
# --- END MONKEYPATCH ---

app = Flask(__name__)
app.secret_key = os.urandom(24) # Wichtig für Flask-Sessions

# --- Konfiguration (Benutzername und Passwort für Login) ---
# !!! NIEMALS SO IN PRODUKTION VERWENDEN !!!
PANEL_USERNAME = "root"
PANEL_PASSWORD = "Potato" # Einfach schrecklich, aber für das Beispiel...

SERVER_VERSIONS_BASE_PATH = os.environ.get("MC_SERVER_VERSIONS_PATH", "/opt/minecraft_versions")
INSTANCES_BASE_PATH = os.environ.get("MC_INSTANCES_PATH", "/srv/minecraft_servers")
os.makedirs(SERVER_VERSIONS_BASE_PATH, exist_ok=True)
os.makedirs(INSTANCES_BASE_PATH, exist_ok=True)
running_servers = {} # (Restliche globale Konfigurationen unverändert)
DEFAULT_MIN_RAM = "1G"; DEFAULT_MAX_RAM = "2G"
DEFAULT_JAVA_ARGS = ("-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 "
    "-XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch "
    "-XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M "
    "-XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 "
    "-XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 "
    "-XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem "
    "-XX:MaxTenuringThreshold=1 -Dusing.aikars.flags=https://mcflags.emc.gs -Daikars.new.flags=true")
DEFAULT_SERVER_ARGS = "nogui"; DEFAULT_RCON_PORT = 25575


# --- Decorator für Login-Prüfung ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in_user' not in session:
            flash('Bitte zuerst einloggen.', 'warning')
            return redirect(url_for('login_route', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# --- Hilfsfunktionen Konfig (unverändert) ---
def get_instance_config_path(instance_name): #...
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name)
    return os.path.join(instance_dir, "panel_config.json")
def load_instance_config(instance_name): #...
    config_path = get_instance_config_path(instance_name)
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f: return json.load(f)
        except json.JSONDecodeError as e: app.logger.error(f"JSONDecodeError '{instance_name}': {e}")
        except Exception as e: app.logger.error(f"Fehler Laden Konfig '{instance_name}': {e}")
    return None
def save_instance_config(instance_name, config_data): #...
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name)
    os.makedirs(instance_dir, exist_ok=True)
    config_path = get_instance_config_path(instance_name)
    try:
        with open(config_path, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4)
        app.logger.info(f"Konfig für '{instance_name}' gespeichert: {config_path}")
    except Exception as e: app.logger.error(f"Fehler Speichern Konfig '{instance_name}': {e}")

# --- Hilfsfunktionen Server (unverändert) ---
def get_available_server_jars(): #...
    if not os.path.exists(SERVER_VERSIONS_BASE_PATH): app.logger.warning(f"JAR-Verzeichnis nicht da: {SERVER_VERSIONS_BASE_PATH}"); return []
    try:
        return sorted([f for f in os.listdir(SERVER_VERSIONS_BASE_PATH) if os.path.isfile(os.path.join(SERVER_VERSIONS_BASE_PATH, f)) and f.endswith('.jar')])
    except Exception as e: app.logger.error(f"Fehler Lesen JARs '{SERVER_VERSIONS_BASE_PATH}': {e}"); return []
def get_log_file_path_for_instance(instance_name): #...
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name)
    return os.path.join(instance_dir, "logs", "latest.log")
def _start_server_process(instance_name, config): #... (RCON-Teil bleibt)
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name); os.makedirs(instance_dir, exist_ok=True)
    server_jar_name = config.get('server_jar')
    if not server_jar_name: return None, "Fehler: Server-JAR nicht spezifiziert."
    server_jar_path = os.path.join(SERVER_VERSIONS_BASE_PATH, server_jar_name)
    if not os.path.isfile(server_jar_path): return None, f"Fehler: Server-JAR '{server_jar_path}' nicht gefunden."
    eula_path = os.path.join(instance_dir, "eula.txt")
    try:
        if not os.path.exists(eula_path) or "eula=true" not in open(eula_path, encoding='utf-8').read():
            with open(eula_path, "w", encoding='utf-8') as f: f.write("eula=true\n")
            app.logger.info(f"EULA für '{instance_name}' akzeptiert.")
    except Exception as e: app.logger.error(f"Fehler EULA '{instance_name}': {e}")
    server_props_path = os.path.join(instance_dir, "server.properties"); rcon_enabled_by_panel = False
    if config.get('rcon_password') and config.get('rcon_port'):
        try:
            props_content = {}
            if os.path.exists(server_props_path):
                with open(server_props_path, 'r', encoding='utf-8') as f_props:
                    for line in f_props:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line: key, value = line.split('=', 1); props_content[key.strip()] = value.strip()
            props_content['enable-rcon']='true'; props_content['rcon.port']=str(config['rcon_port']); props_content['rcon.password']=config['rcon_password']
            with open(server_props_path, 'w', encoding='utf-8') as f_props:
                for key, value in props_content.items(): f_props.write(f"{key}={value}\n")
            app.logger.info(f"RCON in server.properties für '{instance_name}' gesetzt."); rcon_enabled_by_panel = True
        except Exception as e: app.logger.error(f"Fehler Schreiben RCON server.properties '{instance_name}': {e}")
    cmd_parts = ["java", f"-Xms{config.get('min_ram', DEFAULT_MIN_RAM)}", f"-Xmx{config.get('max_ram', DEFAULT_MAX_RAM)}"]
    java_args_to_use = config.get('java_args', DEFAULT_JAVA_ARGS)
    if java_args_to_use and java_args_to_use.strip(): cmd_parts.extend(shlex.split(java_args_to_use))
    if config.get('velocity_secret'): cmd_parts.append(f"-Dvelocity-forwarding-secret={config['velocity_secret']}")
    cmd_parts.extend(["-jar", server_jar_path])
    server_args_to_use = config.get('server_args', DEFAULT_SERVER_ARGS)
    if server_args_to_use and server_args_to_use.strip(): cmd_parts.extend(shlex.split(server_args_to_use))
    log_dir = os.path.join(instance_dir, "logs"); os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "latest.log")
    try:
        with open(log_file_path, 'w', encoding='utf-8') as lf: lf.write(f"--- Log {instance_name} @ {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    except Exception as e: app.logger.error(f"Konnte Log '{log_file_path}' nicht initialisieren: {e}")
    message_suffix = f"Server loggt nach 'logs/latest.log'."; log_handle_for_direct_start = None
    if rcon_enabled_by_panel: message_suffix += f" RCON auf Port {config.get('rcon_port')}."
    server_metadata = {'instance_dir': instance_dir, 'log_file_path': log_file_path, 'log_handle': None, 'config_snapshot': config.copy(),
        'rcon_port': config.get('rcon_port') if config.get('rcon_password') else None,
        'rcon_password': config.get('rcon_password') if config.get('rcon_port') else None}
    if config.get('use_screen', True):
        screen_name = config.get('screen_name', '').strip() or f"mc_{instance_name.replace('.', '_').replace('-', '_')}"
        if subprocess.call("command -v screen > /dev/null", shell=True, executable='/bin/bash') != 0: return None, "'screen' nicht gefunden."
        screen_cmd = ["screen", "-L", "-Logfile", log_file_path, "-S", screen_name, "-dmS"]; screen_cmd.extend(cmd_parts)
        subprocess.Popen(screen_cmd, cwd=instance_dir)
        server_metadata.update({'pid': None, 'screen_name': screen_name, 'type': 'screen'})
        running_servers[instance_name] = server_metadata
        return "screen", f"'{instance_name}' startet in Screen '{screen_name}'. {message_suffix}"
    else:
        try:
            log_handle_for_direct_start = open(log_file_path, 'ab')
            process = subprocess.Popen(cmd_parts, cwd=instance_dir, stdout=log_handle_for_direct_start, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
            server_metadata.update({'pid': process.pid, 'screen_name': None, 'type': 'direct', 'log_handle': log_handle_for_direct_start})
            running_servers[instance_name] = server_metadata
            return "direct", f"'{instance_name}' startet direkt (PID: {process.pid}). {message_suffix}"
        except Exception as e:
            if log_handle_for_direct_start: log_handle_for_direct_start.close()
            app.logger.error(f"Fehler direkter Start '{instance_name}': {e}"); return None, f"Fehler direkter Start: {e}"


# --- Login Routen ---
@app.route('/login', methods=['GET', 'POST'])
def login_route():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # !!! EXTREM UNSICHERE AUTHENTIFIZIERUNG - NUR FÜR BEISPIEL !!!
        if username == PANEL_USERNAME and password == PANEL_PASSWORD:
            session['logged_in_user'] = username
            flash('Erfolgreich eingeloggt!', 'success')
            next_url = request.args.get('next')
            return redirect(next_url or url_for('index'))
        else:
            flash('Falscher Benutzername oder Passwort.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout_route():
    session.pop('logged_in_user', None)
    flash('Erfolgreich ausgeloggt.', 'info')
    return redirect(url_for('login_route'))

# --- Geschützte Hauptroute ---
@app.route('/')
@login_required
def index():
    server_jars = get_available_server_jars()
    instance_folders = [d for d in os.listdir(INSTANCES_BASE_PATH) if os.path.isdir(os.path.join(INSTANCES_BASE_PATH, d))] if os.path.exists(INSTANCES_BASE_PATH) else []
    return render_template('index.html',
                           server_jars=server_jars,
                           initial_instances=instance_folders,
                           default_instance_path=INSTANCES_BASE_PATH,
                           default_rcon_port=DEFAULT_RCON_PORT,
                           logged_in_user=session.get('logged_in_user')) # Für Anzeige im Header

# --- Geschützte API-Routen ---
@app.route('/start_server', methods=['POST'])
@login_required
def start_server_from_form(): #... (wie vorher)
    data = request.form
    try:
        instance_name = data.get('instance_name', '').strip(); rcon_port_str = data.get('rcon_port', '').strip()
        current_config = {'server_jar': data.get('server_jar'), 'min_ram': data.get('min_ram', DEFAULT_MIN_RAM), 'max_ram': data.get('max_ram', DEFAULT_MAX_RAM),
            'velocity_secret': data.get('velocity_secret', ''), 'java_args': data.get('java_args', '').strip(),
            'server_args': data.get('server_args', DEFAULT_SERVER_ARGS).strip(), 'use_screen': 'use_screen' in data,
            'screen_name': data.get('screen_name', '').strip(), 'rcon_port': int(rcon_port_str) if rcon_port_str.isdigit() else None,
            'rcon_password': data.get('rcon_password', '').strip()}
        if not current_config['java_args']: current_config['java_args'] = DEFAULT_JAVA_ARGS
        if not current_config['server_args']: current_config['server_args'] = DEFAULT_SERVER_ARGS
        if not instance_name or not current_config['server_jar']: return jsonify({'status': 'error', 'message': 'Instanzname und JAR sind Pflicht.'}), 400
        if (current_config['rcon_password'] and not current_config['rcon_port']) or \
           (not current_config['rcon_password'] and current_config['rcon_port']):
            return jsonify({'status': 'error', 'message': 'Für RCON Port und Passwort angeben (oder beides leer).'}),400
        if instance_name in running_servers: return jsonify({'status': 'warning', 'message': f"'{instance_name}' scheint verwaltet zu werden."}), 400
        save_instance_config(instance_name, current_config)
        start_type, message = _start_server_process(instance_name, current_config)
        if start_type: app.logger.info(message); return jsonify({'status': 'success', 'message': message})
        else: return jsonify({'status': 'error', 'message': message}), 500
    except Exception as e: app.logger.error(f"Fehler /start_server '{data.get('instance_name', 'N/A')}': {e}", exc_info=True); return jsonify({'status': 'error', 'message': f"Unerwarteter Fehler: {str(e)}"}), 500

@app.route('/quick_start_server', methods=['POST'])
@login_required
def quick_start_server(): #... (wie vorher)
    data = request.form; instance_name = data.get('instance_name')
    if not instance_name: return jsonify({'status': 'error', 'message': 'Instanzname fehlt.'}), 400
    if instance_name in running_servers: return jsonify({'status': 'warning', 'message': f"'{instance_name}' läuft bereits."}), 400
    config = load_instance_config(instance_name)
    if not config: return jsonify({'status': 'error', 'message': f"Keine Konfig für '{instance_name}'."}), 404
    config.setdefault('min_ram', DEFAULT_MIN_RAM); config.setdefault('max_ram', DEFAULT_MAX_RAM); config.setdefault('java_args', DEFAULT_JAVA_ARGS)
    if not config['java_args'].strip(): config['java_args'] = DEFAULT_JAVA_ARGS
    config.setdefault('server_args', DEFAULT_SERVER_ARGS)
    if not config['server_args'].strip(): config['server_args'] = DEFAULT_SERVER_ARGS
    config.setdefault('use_screen', True)
    if config['use_screen'] and not config.get('screen_name', '').strip(): config['screen_name'] = f"mc_{instance_name.replace('.', '_').replace('-', '_')}"
    start_type, message = _start_server_process(instance_name, config)
    if start_type: app.logger.info(f"Schnellstart '{instance_name}': {message}"); return jsonify({'status': 'success', 'message': message})
    else: return jsonify({'status': 'error', 'message': message}), 500

@app.route('/stop_server', methods=['POST'])
@login_required
def stop_server_route(): #... (wie vorher)
    data = request.form; instance_name = data.get('instance_name')
    if not instance_name or instance_name not in running_servers: return jsonify({'status': 'error', 'message': f"'{instance_name}' nicht gefunden/verwaltet."}), 404
    server_info = running_servers[instance_name]; message = ""
    try:
        if server_info['type'] == 'screen' and server_info.get('screen_name'):
            subprocess.run(["screen", "-S", server_info['screen_name'], "-X", "stuff", "stop\r"], check=True, timeout=5)
            message = f"Stop-Befehl an Screen '{server_info['screen_name']}'."
        elif server_info['type'] == 'direct' and server_info.get('pid'):
            os.killpg(server_info['pid'], signal.SIGINT)
            message = f"Interrupt an Prozessgruppe von PID {server_info['pid']}."
        else: return jsonify({'status': 'error', 'message': 'Unbekannter Typ/Fehlende Infos.'}), 500
        app.logger.info(f"Stopp '{instance_name}': {message}"); return jsonify({'status': 'success', 'message': message})
    except subprocess.TimeoutExpired: message = f"Timeout Stop Screen '{server_info.get('screen_name')}'"; app.logger.warning(message); return jsonify({'status': 'warning', 'message': message}), 500
    except (subprocess.CalledProcessError, ProcessLookupError, PermissionError) as e:
        message = f"Fehler Stop '{instance_name}': {str(e)}. Evtl. schon gestoppt."; app.logger.warning(message)
        if instance_name in running_servers:
            if running_servers[instance_name].get('log_handle'):
                try: running_servers[instance_name]['log_handle'].close()
                except Exception: pass
            del running_servers[instance_name]
        return jsonify({'status': 'warning', 'message': message}), 500
    except Exception as e: app.logger.error(f"Allg. Fehler Stop '{instance_name}': {e}", exc_info=True); return jsonify({'status': 'error', 'message': f"Allg. Fehler: {str(e)}"}), 500

@app.route('/restart_server', methods=['POST'])
@login_required
def restart_server_route(): #... (wie vorher)
    data = request.form; instance_name = data.get('instance_name')
    if not instance_name: return jsonify({'status': 'error', 'message': 'Instanzname fehlt.'}), 400
    config_to_restart_with = None; was_running_managed = instance_name in running_servers
    if was_running_managed:
        server_info_before_stop = running_servers[instance_name].copy(); config_to_restart_with = server_info_before_stop.get('config_snapshot')
        app.logger.info(f"Stopp für Neustart '{instance_name}'.");
        class MockForm: get = lambda self, key, default=None: instance_name if key == 'instance_name' else default
        original_request_form = request.form; request.form = MockForm()
        stop_response = stop_server_route(); request.form = original_request_form
        stop_data = json.loads(stop_response.get_data(as_text=True))
        if stop_data.get('status') not in ['success', 'warning']: app.logger.error(f"Fehler Stopp für Neustart '{instance_name}': {stop_data.get('message')}"); return jsonify({'status': 'error', 'message': f"Konnte nicht stoppen: {stop_data.get('message')}"})
        max_wait=20; wait_int=1; waited=0; stopped_ok=False
        while waited < max_wait:
            time.sleep(wait_int); waited += wait_int; active_after_stop = False
            if server_info_before_stop['type'] == 'direct' and server_info_before_stop.get('pid'): active_after_stop = is_pid_running(server_info_before_stop['pid'])
            elif server_info_before_stop['type'] == 'screen' and server_info_before_stop.get('screen_name'): active_after_stop = is_screen_session_running(server_info_before_stop['screen_name'])
            if not active_after_stop: stopped_ok=True; app.logger.info(f"'{instance_name}' nach {waited}s für Neustart gestoppt."); break
            else: app.logger.debug(f"Warte auf Stopp '{instance_name}', {waited}s...")
        if not stopped_ok: app.logger.warning(f"'{instance_name}' nicht in {max_wait}s gestoppt."); return jsonify({'status': 'warning', 'message': f"'{instance_name}' nicht rechtzeitig gestoppt."})
        if instance_name in running_servers:
            if running_servers[instance_name].get('log_handle'):
                try: running_servers[instance_name]['log_handle'].close()
                except Exception: pass
            del running_servers[instance_name]
    else: app.logger.info(f"'{instance_name}' nicht verwaltet. Überspringe Stopp für Neustart.")
    if not config_to_restart_with: config_to_restart_with = load_instance_config(instance_name)
    if not config_to_restart_with: app.logger.warning(f"Keine Konfig Neustart '{instance_name}'."); return jsonify({'status': 'error', 'message': f"Keine Konfig für '{instance_name}'."}), 404
    config_to_restart_with.setdefault('min_ram',DEFAULT_MIN_RAM); config_to_restart_with.setdefault('max_ram',DEFAULT_MAX_RAM); config_to_restart_with.setdefault('java_args',DEFAULT_JAVA_ARGS)
    if not config_to_restart_with['java_args'].strip(): config_to_restart_with['java_args'] = DEFAULT_JAVA_ARGS
    config_to_restart_with.setdefault('server_args',DEFAULT_SERVER_ARGS)
    if not config_to_restart_with['server_args'].strip(): config_to_restart_with['server_args'] = DEFAULT_SERVER_ARGS
    config_to_restart_with.setdefault('use_screen', True)
    if config_to_restart_with['use_screen'] and not config_to_restart_with.get('screen_name','').strip(): config_to_restart_with['screen_name'] = f"mc_{instance_name.replace('.','_').replace('-','_')}"
    app.logger.info(f"Starte für Neustart '{instance_name}'."); start_type, message = _start_server_process(instance_name, config_to_restart_with)
    if start_type: app.logger.info(f"Neustart '{instance_name}': {message}"); return jsonify({'status': 'success', 'message': f"Neustart: {message}"})
    else: return jsonify({'status': 'error', 'message': f"Fehler Neustart (Start): {message}"}), 500

@app.route('/get_logs/<instance_name>')
@login_required
def get_logs(instance_name): #... (wie vorher)
    log_file_path = get_log_file_path_for_instance(instance_name)
    if not os.path.exists(log_file_path): return jsonify({"logs": f"Logdatei nicht da: {log_file_path}", "error": True}), 404
    try:
        num_lines = int(request.args.get('lines', 200)); lines = []
        with open(log_file_path,'r',encoding='utf-8',errors='replace') as f: all_lines = f.readlines(); lines = all_lines[-num_lines:]
        return jsonify({"logs": "".join(lines)})
    except Exception as e: app.logger.error(f"Fehler Lesen Log {log_file_path}: {e}", exc_info=True); return jsonify({"logs": f"Fehler Lesen: {str(e)}", "error": True}), 500

@app.route('/stream_logs/<instance_name>')
@login_required
def stream_logs(instance_name): #... (wie vorher, mit korrigiertem `escaped_line` in `gen_logs`)
    log_file_path = get_log_file_path_for_instance(instance_name)
    def gen_logs():
        app.logger.info(f"Log-Stream '{instance_name}' ({log_file_path}).")
        if not os.path.exists(log_file_path):
            app.logger.warning(f"Log {log_file_path} nicht da."); yield f"data: [WARN] Log {os.path.basename(log_file_path)} erwartet...\n\n"
            for _ in range(5):
                if os.path.exists(log_file_path): break
                time.sleep(1)
            if not os.path.exists(log_file_path): yield f"data: [FEHLER] Log nicht gefunden.\n\n"; app.logger.error(f"Log {log_file_path} nach Warten nicht da."); return
        inode=None; pos=0; init_sent=False
        while True:
            try:
                if not os.path.exists(log_file_path): app.logger.warning(f"Log {log_file_path} weg."); yield "data: [WARN] Log temporär nicht da.\n\n"; inode=None;pos=0;init_sent=False; time.sleep(2); continue
                cur_inode=os.stat(log_file_path).st_ino; cur_size=os.path.getsize(log_file_path)
                if inode is not None and (cur_inode != inode or cur_size < pos): app.logger.info(f"Log-Rotation {log_file_path}."); yield f"data: [INFO] Log-Rotation...\n\n"; pos=0; init_sent=False
                inode=cur_inode
                with open(log_file_path,'r',encoding='utf-8',errors='replace') as f:
                    if not init_sent: f.seek(max(0, cur_size-4096)); content=f.read(); pos=f.tell(); init_sent=True
                    else: f.seek(pos); content=f.read(); pos=f.tell()
                    if content:
                        for line in content.splitlines(keepends=False):
                            escaped_line = line.replace('\n', '\\n')
                            yield f"data: {escaped_line}\n\n"
            except FileNotFoundError: app.logger.warning(f"Log {log_file_path} (inner) nicht da."); yield "data: [WARN] Log (inner) nicht da.\n\n"; inode=None;pos=0;init_sent=False; time.sleep(2)
            except Exception as e: app.logger.error(f"Fehler Log-Stream '{instance_name}': {e}", exc_info=True); yield f"data: [FEHLER] Interner Log-Stream Fehler: {str(e)}\n\n"; time.sleep(5)
            time.sleep(0.2)
    return Response(gen_logs(), mimetype='text/event-stream')


@app.route('/send_rcon_command/<instance_name>', methods=['POST'])
@login_required
def send_rcon_command(instance_name): # (wie vorher, mit MCRconException)
    config = None
    if instance_name in running_servers:
        config = running_servers[instance_name].get('config_snapshot', {})
    else:
        config = load_instance_config(instance_name)
    if not config: return jsonify({'status': 'error', 'message': f"Keine Konfig für Instanz '{instance_name}'."}), 404
    rcon_host = "127.0.0.1"; rcon_port = config.get('rcon_port'); rcon_password = config.get('rcon_password')
    command_to_send = request.form.get('command')
    if not command_to_send: return jsonify({'status': 'error', 'message': 'Kein Befehl.'}), 400
    if not rcon_port or not rcon_password: return jsonify({'status': 'error', 'message': 'RCON nicht (vollständig) konfiguriert.'}), 400
    try:
        app.logger.debug(f"RCON Verbindung zu {rcon_host}:{rcon_port} für {instance_name}")
        with MCRcon(host=rcon_host, password=rcon_password, port=int(rcon_port), timeout=5) as mcr: # Nutzt gepatchte MCRcon
            app.logger.debug(f"RCON verbunden. Sende: {command_to_send}")
            response = mcr.command(command_to_send) 
            app.logger.info(f"RCON '{command_to_send}' an '{instance_name}'. Antwort: {str(response)[:100]}...")
            return jsonify({'status': 'success', 'command': command_to_send, 'response': str(response)})
    except MCRconException as e: 
        app.logger.error(f"MCRconException '{instance_name}' Cmd '{command_to_send}': {e}", exc_info=False)
        return jsonify({'status': 'error', 'message': f'RCON Fehler: {str(e)}'}), 500
    except Exception as e:
        app.logger.error(f"Allg. RCON Fehler '{instance_name}' Cmd '{command_to_send}': {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Allgemeiner RCON Fehler: {str(e)}'}), 500

@app.route('/delete_instance/<instance_name>', methods=['POST'])
@login_required
def delete_instance_route(instance_name): #... (wie vorher)
    app.logger.info(f"Löschanfrage für Instanz '{instance_name}' erhalten.")
    if instance_name in running_servers:
        app.logger.info(f"Instanz '{instance_name}' läuft, versuche zu stoppen vor dem Löschen.")
        class MockForm: get = lambda self, key, default=None: instance_name if key == 'instance_name' else default
        original_request_form = request.form; request.form = MockForm()
        stop_response = stop_server_route(); request.form = original_request_form
        try:
            stop_data = json.loads(stop_response.get_data(as_text=True))
            if stop_data.get('status') not in ['success', 'warning']:
                app.logger.error(f"Konnte Server '{instance_name}' nicht für Löschung stoppen: {stop_data.get('message')}")
                return jsonify({'status': 'error', 'message': f"Konnte Server nicht stoppen: {stop_data.get('message')}"})
            app.logger.info(f"Warte nach Stopp-Befehl für '{instance_name}'..."); time.sleep(5)
            server_info_before_delete = running_servers.get(instance_name)
            if server_info_before_delete:
                is_still_active = False
                if server_info_before_delete['type'] == 'direct' and server_info_before_delete.get('pid'): is_still_active = is_pid_running(server_info_before_delete['pid'])
                elif server_info_before_delete['type'] == 'screen' and server_info_before_delete.get('screen_name'): is_still_active = is_screen_session_running(server_info_before_delete['screen_name'])
                if is_still_active:
                    app.logger.warning(f"Server '{instance_name}' läuft noch. Löschung abgebrochen.")
                    return jsonify({'status': 'warning', 'message': f"Server '{instance_name}' konnte nicht gestoppt werden. Manuell stoppen."})
                else:
                    if instance_name in running_servers:
                        if running_servers[instance_name].get('log_handle'):
                            try: running_servers[instance_name]['log_handle'].close()
                            except Exception: pass
                        del running_servers[instance_name]
        except Exception as e_stop: app.logger.error(f"Fehler Stopp-Logik beim Löschen von '{instance_name}': {e_stop}", exc_info=True)
    else: app.logger.info(f"Instanz '{instance_name}' nicht in running_servers. Überspringe Stopp.")
    instance_dir_to_delete = os.path.join(INSTANCES_BASE_PATH, instance_name)
    if os.path.exists(instance_dir_to_delete) and os.path.isdir(instance_dir_to_delete):
        try:
            shutil.rmtree(instance_dir_to_delete)
            app.logger.info(f"Instanzverzeichnis '{instance_dir_to_delete}' gelöscht.")
            if instance_name in running_servers: del running_servers[instance_name]
            return jsonify({'status': 'success', 'message': f"Instanz '{instance_name}' und alle Dateien wurden gelöscht."})
        except Exception as e:
            app.logger.error(f"Fehler beim Löschen des Verzeichnisses '{instance_dir_to_delete}': {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': f"Fehler beim Löschen der Serverdateien: {str(e)}"}), 500
    else:
        app.logger.warning(f"Instanzverzeichnis '{instance_dir_to_delete}' nicht gefunden. Markiere als gelöscht.")
        if instance_name in running_servers: del running_servers[instance_name]
        return jsonify({'status': 'warning', 'message': f"Instanzverzeichnis für '{instance_name}' nicht gefunden, aber als gelöscht markiert."})


@app.route('/server_status', methods=['GET'])
@login_required
def server_status_route(): #... (rcon_available Check bleibt)
    statuses = {}
    all_instance_folders = [d for d in os.listdir(INSTANCES_BASE_PATH) if os.path.isdir(os.path.join(INSTANCES_BASE_PATH, d))] if os.path.exists(INSTANCES_BASE_PATH) else []
    stale = []
    for name, info in list(running_servers.items()):
        active = False
        if info['type'] == 'direct' and info.get('pid'): active = is_pid_running(info['pid'])
        elif info['type'] == 'screen' and info.get('screen_name'): active = is_screen_session_running(info['screen_name'])
        if not active: stale.append(name)
    for name in stale:
        if name in running_servers:
            app.logger.info(f"'{name}' nicht mehr aktiv, entferne aus running_servers.")
            if running_servers[name].get('log_handle'):
                try: running_servers[name]['log_handle'].close()
                except Exception as e: app.logger.debug(f"Fehler Schließen Log-Handle {name}: {e}")
            del running_servers[name]
    for name in all_instance_folders:
        status_txt = "Gestoppt"; log_p = get_log_file_path_for_instance(name); log_ex = os.path.exists(log_p)
        managed_run = False; has_cfg = os.path.exists(get_instance_config_path(name)); rcon_ok = False
        if name in running_servers:
            info = running_servers[name]; cfg_snap = info.get('config_snapshot', {})
            if info['type'] == 'direct': status_txt = f"Läuft (Direkt, PID: {info['pid']})"
            elif info['type'] == 'screen': status_txt = f"Läuft (Screen: {info['screen_name']})"
            managed_run = True
            if cfg_snap.get('rcon_port') and cfg_snap.get('rcon_password'): rcon_ok = True
        elif has_cfg:
            cfg = load_instance_config(name)
            if cfg and cfg.get('rcon_port') and cfg.get('rcon_password'): rcon_ok = True
        statuses[name] = {"status_text": status_txt, "log_exists": log_ex, "is_running_managed": managed_run, "has_config": has_cfg, "rcon_available": rcon_ok}
    return jsonify(statuses)

# --- Hilfsfunktionen Status (unverändert) ---
def is_pid_running(pid): #...
    if pid is None: return False
    try: os.kill(pid, 0); return True
    except OSError: return False
def is_screen_session_running(screen_name): #...
    if not screen_name: return False
    try:
        result = subprocess.run(['screen', '-ls'], capture_output=True, text=True, check=False, timeout=3)
        if result.returncode == 0 and result.stdout:
            return f".{screen_name}\t(" in result.stdout or f"\t{screen_name}\t(" in result.stdout
        return False
    except: app.logger.debug(f"Fehler Prüfen Screen '{screen_name}'.", exc_info=False); return False


if __name__ == '__main__':
    app.logger.info(f"Starte Minecraft Server Panel...")
    app.logger.info(f"Server Versionen werden aus '{SERVER_VERSIONS_BASE_PATH}' geladen.")
    app.logger.info(f"Instanzen werden in '{INSTANCES_BASE_PATH}' verwaltet.")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)