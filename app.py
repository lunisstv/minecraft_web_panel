# app.py
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, session, flash, Blueprint
import os
import time
import json
import shutil # Für delete_instance
import logging
from auth import auth_bp, login_required, User

# Importiere aus unseren Modulen
from config import SECRET_KEY, DEBUG, LOG_LEVEL, SERVER_VERSIONS_BASE_PATH, INSTANCES_BASE_PATH, DEFAULT_RCON_PORT, DEFAULT_MINECRAFT_PORT
from auth import login_view, logout_view, login_required # auth_bp für Routen, login_required für Schutz
import server_manager as sm # sm als Alias für server_manager
from mcrcon_patch import apply_mcrcon_patch

# Monkeypatch für mcrcon (muss vor der ersten MCRcon-Nutzung passieren)
# Wenn der Patch in server_manager.py wäre, müsste man sicherstellen,
# dass server_manager.py importiert wird, bevor MCRcon irgendwo anders genutzt wird.
# Es ist oft am sichersten, Patches so früh wie möglich in der Hauptanwendungsdatei anzuwenden.
apply_mcrcon_patch()


# Flask App Initialisierung
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.debug = DEBUG

# Logging Konfiguration für die App
logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
                    format='%(asctime)s %(levelname)s: %(name)s: %(message)s')
if not app.debug: # Werkzeug-Logger in Produktion weniger gesprächig machen
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.WARNING)

# Authentifizierungs-Blueprint erstellen und Routen hinzufügen
auth_bp = Blueprint('auth_bp', __name__, template_folder='templates')
auth_bp.add_url_rule('/login', view_func=login_view, methods=['GET', 'POST'], endpoint='login_route')
auth_bp.add_url_rule('/logout', view_func=logout_view, endpoint='logout_route')
app.register_blueprint(auth_bp) # Kein url_prefix, wenn /login und /logout direkt sein sollen

# Haupt-Blueprint für die Panel-Funktionen (optional, aber gut für Struktur)
main_bp = Blueprint('main_bp', __name__, template_folder='templates')

@main_bp.route('/')
@login_required
def index():
    server_jars = sm.get_available_server_jars()
    # Lese Instanz-Ordner direkt für die Anzeige
    instance_folders = [d for d in os.listdir(INSTANCES_BASE_PATH) if os.path.isdir(os.path.join(INSTANCES_BASE_PATH, d))] if os.path.exists(INSTANCES_BASE_PATH) else []
    
    return render_template('index.html',
                           server_jars=server_jars,
                           initial_instances=instance_folders, # Für die initiale Tabellenstruktur
                           default_instance_path=INSTANCES_BASE_PATH,
                           default_rcon_port=DEFAULT_RCON_PORT,
                           logged_in_user=session.get('logged_in_user'))

@main_bp.route('/start_server', methods=['POST'])
@login_required
def start_server_route():
    data = request.form
    try:
        instance_name = data.get('instance_name', '').strip()
        rcon_port_str = data.get('rcon_port', '').strip()
        current_config = {
            'server_jar': data.get('server_jar'),
            'min_ram': data.get('min_ram', sm.DEFAULT_MIN_RAM),
            'max_ram': data.get('max_ram', sm.DEFAULT_MAX_RAM),
            'velocity_secret': data.get('velocity_secret', ''),
            'java_args': data.get('java_args', '').strip(),
            'server_args': data.get('server_args', sm.DEFAULT_SERVER_ARGS).strip(),
            'use_screen': 'use_screen' in data,
            'screen_name': data.get('screen_name', '').strip(),
            'rcon_port': int(rcon_port_str) if rcon_port_str.isdigit() else None,
            'rcon_password': data.get('rcon_password', '').strip()
        }
        if not current_config['java_args']: current_config['java_args'] = sm.DEFAULT_JAVA_ARGS
        if not current_config['server_args']: current_config['server_args'] = sm.DEFAULT_SERVER_ARGS
        if not instance_name or not current_config['server_jar']:
            return jsonify({'status': 'error', 'message': 'Instanzname und Server-JAR sind erforderlich.'}), 400
        if (current_config['rcon_password'] and not current_config['rcon_port']) or \
           (not current_config['rcon_password'] and current_config['rcon_port']):
            return jsonify({'status': 'error', 'message': 'Für RCON müssen Port und Passwort angegeben werden (oder beides leer lassen).'}),400
        if instance_name in sm.running_servers: # Zugriff auf running_servers in server_manager
             return jsonify({'status': 'warning', 'message': f"Instanz '{instance_name}' scheint bereits verwaltet zu werden."}), 400

        sm.save_instance_config(instance_name, current_config)
        start_type, message = sm.start_instance(instance_name, current_config)

        if start_type:
            app.logger.info(message)
            return jsonify({'status': 'success', 'message': message})
        else:
            return jsonify({'status': 'error', 'message': message}), 500
    except Exception as e:
        app.logger.error(f"Unerwarteter Fehler in /start_server für '{data.get('instance_name', 'N/A')}': {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f"Ein unerwarteter Fehler ist aufgetreten: {str(e)}"}), 500

@main_bp.route('/quick_start_server', methods=['POST'])
@login_required
def quick_start_server_route():
    data = request.form; instance_name = data.get('instance_name')
    if not instance_name: return jsonify({'status': 'error', 'message': 'Instanzname fehlt.'}), 400
    if instance_name in sm.running_servers: return jsonify({'status': 'warning', 'message': f"'{instance_name}' läuft bereits."}), 400
    
    config = sm.load_instance_config(instance_name)
    if not config: return jsonify({'status': 'error', 'message': f"Keine Konfig für '{instance_name}'."}), 404
    
    # Defaults anwenden, falls in gespeicherter Config nicht vorhanden
    config.setdefault('min_ram', sm.DEFAULT_MIN_RAM); config.setdefault('max_ram', sm.DEFAULT_MAX_RAM)
    config.setdefault('java_args', sm.DEFAULT_JAVA_ARGS)
    if not config['java_args'].strip(): config['java_args'] = sm.DEFAULT_JAVA_ARGS
    config.setdefault('server_args', sm.DEFAULT_SERVER_ARGS)
    if not config['server_args'].strip(): config['server_args'] = sm.DEFAULT_SERVER_ARGS
    config.setdefault('use_screen', True)
    if config['use_screen'] and not config.get('screen_name', '').strip():
        config['screen_name'] = f"mc_{instance_name.replace('.', '_').replace('-', '_')}"
    
    start_type, message = sm.start_instance(instance_name, config)
    if start_type: app.logger.info(f"Schnellstart '{instance_name}': {message}"); return jsonify({'status': 'success', 'message': message})
    else: return jsonify({'status': 'error', 'message': message}), 500

@main_bp.route('/stop_server', methods=['POST'])
@login_required
def stop_server_route_internal(): # Umbenannt, da stop_server_route in server_manager existiert
    data = request.form
    instance_name = data.get('instance_name')
    success, message = sm.stop_instance_managed(instance_name)
    status_code = 200 if success else 500
    if "bereits gestoppt" in message.lower() or "nicht gefunden" in message.lower() or "timeout" in message.lower():
        status_code = 200 # Oder 404/408, aber für Frontend ist Warning ok
        return jsonify({'status': 'warning', 'message': message}), status_code
    return jsonify({'status': 'success' if success else 'error', 'message': message}), status_code


@main_bp.route('/restart_server', methods=['POST'])
@login_required
def restart_server_route_internal():
    data = request.form; instance_name = data.get('instance_name')
    if not instance_name: return jsonify({'status': 'error', 'message': 'Instanzname fehlt.'}), 400

    config_to_restart_with = None
    was_running_managed = instance_name in sm.running_servers

    if was_running_managed:
        server_info_before_stop = sm.running_servers[instance_name].copy()
        config_to_restart_with = server_info_before_stop.get('config_snapshot')
        app.logger.info(f"Stopp für Neustart '{instance_name}'.")
        
        stopped_successfully, stop_message = sm.stop_instance_managed(instance_name)
        if not stopped_successfully and "bereits gestoppt" not in stop_message.lower(): # Wenn Stopp fehlschlägt (und nicht weil schon aus)
            app.logger.error(f"Fehler Stopp für Neustart '{instance_name}': {stop_message}")
            return jsonify({'status': 'error', 'message': f"Konnte Server nicht stoppen: {stop_message}"})

        max_wait=20; wait_int=1; waited=0; is_stopped_for_restart=False
        while waited < max_wait: # Warte und prüfe ob Prozess/Screen wirklich weg ist
            time.sleep(wait_int); waited += wait_int
            is_active_after_stop = False
            if server_info_before_stop['type'] == 'direct' and server_info_before_stop.get('pid'):
                is_active_after_stop = sm.is_pid_running(server_info_before_stop['pid'])
            elif server_info_before_stop['type'] == 'screen' and server_info_before_stop.get('screen_name'):
                is_active_after_stop = sm.is_screen_session_running(server_info_before_stop['screen_name'])
            if not is_active_after_stop:
                is_stopped_for_restart=True; app.logger.info(f"'{instance_name}' nach {waited}s für Neustart bestätigt gestoppt."); break
            else: app.logger.debug(f"Warte auf Stopp-Bestätigung '{instance_name}', {waited}s...")
        
        if not is_stopped_for_restart:
            app.logger.warning(f"'{instance_name}' nicht in {max_wait}s gestoppt.");
            return jsonify({'status': 'warning', 'message': f"'{instance_name}' konnte nicht rechtzeitig gestoppt werden."})
        
        # Sicherstellen, dass es aus running_servers entfernt wird
        if instance_name in sm.running_servers:
            if sm.running_servers[instance_name].get('log_handle'):
                try: sm.running_servers[instance_name]['log_handle'].close()
                except Exception: pass
            del sm.running_servers[instance_name]
    else:
        app.logger.info(f"'{instance_name}' nicht verwaltet. Überspringe Stopp für Neustart.")

    if not config_to_restart_with: config_to_restart_with = sm.load_instance_config(instance_name)
    if not config_to_restart_with:
        return jsonify({'status': 'error', 'message': f"Keine Konfig für Neustart von '{instance_name}'."}), 404
    
    # Defaults anwenden
    config_to_restart_with.setdefault('min_ram',sm.DEFAULT_MIN_RAM); config_to_restart_with.setdefault('max_ram',sm.DEFAULT_MAX_RAM) # ... etc.
    if not config_to_restart_with.get('java_args','').strip(): config_to_restart_with['java_args'] = sm.DEFAULT_JAVA_ARGS
    if not config_to_restart_with.get('server_args','').strip(): config_to_restart_with['server_args'] = sm.DEFAULT_SERVER_ARGS
    config_to_restart_with.setdefault('use_screen', True)
    if config_to_restart_with['use_screen'] and not config_to_restart_with.get('screen_name','').strip():
        config_to_restart_with['screen_name'] = f"mc_{instance_name.replace('.','_').replace('-','_')}"

    app.logger.info(f"Starte für Neustart '{instance_name}'.")
    start_type, message = sm.start_instance(instance_name, config_to_restart_with)
    if start_type: return jsonify({'status': 'success', 'message': f"Neustart: {message}"})
    else: return jsonify({'status': 'error', 'message': f"Fehler Neustart (Start): {message}"}), 500


@main_bp.route('/get_logs/<instance_name>')
@login_required
def get_logs_route(instance_name):
    log_file_path = sm.get_log_file_path(instance_name)
    if not os.path.exists(log_file_path): return jsonify({"logs": f"Logdatei nicht da: {log_file_path}", "error": True}), 404
    try:
        num_lines = int(request.args.get('lines', 200)); lines = []
        with open(log_file_path,'r',encoding='utf-8',errors='replace') as f: all_lines = f.readlines(); lines = all_lines[-num_lines:]
        return jsonify({"logs": "".join(lines)})
    except Exception as e: app.logger.error(f"Fehler Lesen Log {log_file_path}: {e}", exc_info=True); return jsonify({"logs": f"Fehler Lesen: {str(e)}", "error": True}), 500

@main_bp.route('/stream_logs/<instance_name>')
@login_required
def stream_logs_route(instance_name):
    log_file_path = sm.get_log_file_path(instance_name)
    def gen_logs():
        # (Logik aus server_manager.py hierher verschieben oder dort lassen und aufrufen)
        # Der Einfachheit halber hier dupliziert, besser wäre Auslagerung
        app.logger.info(f"Log-Stream '{instance_name}' ({log_file_path}).")
        if not os.path.exists(log_file_path): #... (Rest der gen_logs Logik)
            yield f"data: [WARN] Logdatei {os.path.basename(log_file_path)} nicht gefunden...\n\n"
            return
        inode=None; pos=0; init_sent=False
        while True:
            try:
                if not os.path.exists(log_file_path): yield "data: [WARN] Log-Datei temporär nicht da.\n\n"; inode=None;pos=0;init_sent=False; time.sleep(2); continue
                cur_inode=os.stat(log_file_path).st_ino; cur_size=os.path.getsize(log_file_path)
                if inode is not None and (cur_inode != inode or cur_size < pos): yield f"data: [INFO] Log-Rotation...\n\n"; pos=0; init_sent=False
                inode=cur_inode
                with open(log_file_path,'r',encoding='utf-8',errors='replace') as f:
                    if not init_sent: f.seek(max(0, cur_size-4096)); content=f.read(); pos=f.tell(); init_sent=True
                    else: f.seek(pos); content=f.read(); pos=f.tell()
                    if content:
                        for line in content.splitlines(keepends=False):
                            escaped_line = line.replace('\n', '\\n') # Newlines im Log-Inhalt escapen
                            yield f"data: {escaped_line}\n\n"
            except FileNotFoundError: # Sollte durch obigen Check abgedeckt sein, aber sicher ist sicher
                app.logger.warning(f"Log-Datei {log_file_path} während des Streamens (innerhalb try) nicht gefunden. Warte...")
                yield "data: [WARNUNG] Log-Datei temporär nicht gefunden (innerer Check). Warte...\n\n"
                last_known_inode = None; last_pos = 0; initial_chunk_sent = False
                time.sleep(2)
            except Exception as e:
                app.logger.error(f"Fehler im Log-Stream für {instance_name} ({log_file_path}): {e}", exc_info=True)
                yield f"data: [FEHLER] Interner Fehler im Log-Stream: {str(e)}\n\n"
                time.sleep(5) # Pause vor erneutem Versuch bei allgemeinen Fehlern
            time.sleep(0.2) # Kurze Pause zwischen den Leseversuchen
            
    return Response(gen_logs(), mimetype='text/event-stream')


@main_bp.route('/send_rcon_command/<instance_name>', methods=['POST'])
@login_required
def send_rcon_command_route(instance_name):
    command_to_send = request.form.get('command')
    response, error = sm.send_rcon_to_instance(instance_name, command_to_send)
    if error:
        app.logger.error(f"RCON Fehler für '{instance_name}', Befehl '{command_to_send}': {error}")
        return jsonify({'status': 'error', 'message': error}), 500
    
    app.logger.info(f"RCON '{command_to_send}' an '{instance_name}'. Antwort: {str(response)[:100]}...")
    return jsonify({'status': 'success', 'command': command_to_send, 'response': str(response)})

@main_bp.route('/delete_instance/<instance_name>', methods=['POST'])
@login_required
def delete_instance_route_internal(instance_name):
    app.logger.info(f"Löschanfrage für Instanz '{instance_name}'.")
    # 1. Server stoppen (falls verwaltet)
    if instance_name in sm.running_servers:
        app.logger.info(f"Stoppe '{instance_name}' vor dem Löschen.")
        stopped, msg = sm.stop_instance_managed(instance_name)
        if not stopped and "bereits gestoppt" not in msg.lower(): # Wenn Stopp fehlschlägt (und nicht weil schon aus)
            return jsonify({'status': 'error', 'message': f"Konnte Server nicht stoppen: {msg}"})
        time.sleep(5) # Wartezeit
        # Überprüfe erneut, ob der Prozess wirklich weg ist
        server_info = sm.running_servers.get(instance_name) # Hol es nochmal
        if server_info:
            is_still_active = False
            if server_info['type'] == 'direct' and server_info.get('pid'): is_still_active = sm.is_pid_running(server_info['pid'])
            elif server_info['type'] == 'screen' and server_info.get('screen_name'): is_still_active = sm.is_screen_session_running(server_info['screen_name'])
            if is_still_active: return jsonify({'status': 'warning', 'message': f"Server '{instance_name}' konnte nicht gestoppt werden. Manuell stoppen."})
            if instance_name in sm.running_servers: # Explizit entfernen, da stop_instance_managed es bei Fehler nicht immer tut
                if sm.running_servers[instance_name].get('log_handle'):
                    try: sm.running_servers[instance_name]['log_handle'].close()
                    except Exception: pass
                del sm.running_servers[instance_name]

    # 2. Verzeichnis löschen
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name)
    if os.path.exists(instance_dir) and os.path.isdir(instance_dir):
        try:
            shutil.rmtree(instance_dir)
            app.logger.info(f"Instanzverzeichnis '{instance_dir}' gelöscht.")
            if instance_name in sm.running_servers: del sm.running_servers[instance_name] # Sicherstellen
            return jsonify({'status': 'success', 'message': f"Instanz '{instance_name}' gelöscht."})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f"Fehler Löschen Dateien: {str(e)}"}), 500
    else:
        if instance_name in sm.running_servers: del sm.running_servers[instance_name]
        return jsonify({'status': 'warning', 'message': f"Verzeichnis für '{instance_name}' nicht gefunden."})


@main_bp.route('/server_status', methods=['GET'])
@login_required
def server_status_route_internal():
    statuses = {}
    all_instance_folders = [d for d in os.listdir(INSTANCES_BASE_PATH) if os.path.isdir(os.path.join(INSTANCES_BASE_PATH, d))] if os.path.exists(INSTANCES_BASE_PATH) else []
    
    stale = []
    for name, info in list(sm.running_servers.items()): # Benutze running_servers aus server_manager
        active = False
        if info['type'] == 'direct' and info.get('pid'): active = sm.is_pid_running(info['pid'])
        elif info['type'] == 'screen' and info.get('screen_name'): active = sm.is_screen_session_running(info['screen_name'])
        if not active: stale.append(name)
    for name in stale:
        if name in sm.running_servers:
            if sm.running_servers[name].get('log_handle'):
                try: sm.running_servers[name]['log_handle'].close()
                except Exception: pass
            del sm.running_servers[name]

    for name in all_instance_folders:
        status_txt = "Gestoppt"; log_p = sm.get_log_file_path(name); log_ex = os.path.exists(log_p)
        managed_run = False; has_cfg = os.path.exists(sm.get_instance_config_path(name)); rcon_ok = False
        current_server_port = DEFAULT_MINECRAFT_PORT

        instance_config = sm.load_instance_config(name) if has_cfg else {}
        
        if name in sm.running_servers:
            info = sm.running_servers[name]; cfg_snap = info.get('config_snapshot', {})
            if info['type'] == 'direct': status_txt = f"Läuft (Direkt, PID: {info['pid']})"
            elif info['type'] == 'screen': status_txt = f"Läuft (Screen: {info['screen_name']})"
            managed_run = True
            if cfg_snap.get('rcon_port') and cfg_snap.get('rcon_password'): rcon_ok = True
            current_server_port = info.get('server_port', DEFAULT_MINECRAFT_PORT)
        elif has_cfg and instance_config:
            if instance_config.get('rcon_port') and instance_config.get('rcon_password'): rcon_ok = True
            current_server_port = sm.parse_server_port(instance_config.get('server_args', ""), os.path.join(INSTANCES_BASE_PATH, name))
            
        statuses[name] = {
            "status_text": status_txt, "log_exists": log_ex,
            "is_running_managed": managed_run, "has_config": has_cfg,
            "rcon_available": rcon_ok, "server_port": current_server_port
        }
    return jsonify(statuses)

app.register_blueprint(main_bp) # Standard-URL-Prefix ist '/'


if __name__ == '__main__':
    # ... (Start-Logmeldungen)
    app.logger.info(f"Starte Minecraft Server Panel mit Loglevel {LOG_LEVEL}...")
    app.run(host='0.0.0.0', port=5000) # debug=DEBUG wird von app.debug gesteuert