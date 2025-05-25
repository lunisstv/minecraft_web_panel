# server_manager.py
import os
import subprocess
import shlex
import signal as signal_module # Umbenannt
import re
import json
import logging
from config import (
    INSTANCES_BASE_PATH, SERVER_VERSIONS_BASE_PATH,
    DEFAULT_MIN_RAM, DEFAULT_MAX_RAM, DEFAULT_JAVA_ARGS, DEFAULT_SERVER_ARGS,
    DEFAULT_MINECRAFT_PORT
)
from mcrcon import MCRcon, MCRconException # Wird direkt hier verwendet

# Globale Variable für laufende Server (könnte auch Teil einer Manager-Klasse sein)
running_servers = {}
logger = logging.getLogger(__name__)


def get_instance_config_path(instance_name):
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name)
    return os.path.join(instance_dir, "panel_config.json")

def load_instance_config(instance_name):
    config_path = get_instance_config_path(instance_name)
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: logger.error(f"Fehler Laden Konfig '{instance_name}': {e}")
    return None

def save_instance_config(instance_name, config_data):
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name)
    os.makedirs(instance_dir, exist_ok=True)
    config_path = get_instance_config_path(instance_name)
    try:
        with open(config_path, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4)
        logger.info(f"Konfig für '{instance_name}' gespeichert.")
    except Exception as e: logger.error(f"Fehler Speichern Konfig '{instance_name}': {e}")


def get_available_server_jars():
    if not os.path.exists(SERVER_VERSIONS_BASE_PATH): return []
    try:
        return sorted([f for f in os.listdir(SERVER_VERSIONS_BASE_PATH)
                       if os.path.isfile(os.path.join(SERVER_VERSIONS_BASE_PATH, f)) and f.endswith('.jar')])
    except Exception as e: logger.error(f"Fehler Lesen JARs: {e}"); return []

def get_log_file_path(instance_name):
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name)
    return os.path.join(instance_dir, "logs", "latest.log")

def parse_server_port(server_args_str, instance_dir):
    """Bestimmt den Server-Port basierend auf Argumenten und server.properties."""
    # 1. Aus Argumenten parsen
    match_args = re.search(r'(?:--port|-p)\s+(\d+)', server_args_str or "")
    if match_args:
        try: return int(match_args.group(1))
        except ValueError: pass

    # 2. Aus server.properties lesen
    props_path = os.path.join(instance_dir, "server.properties")
    if os.path.exists(props_path):
        try:
            with open(props_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('server-port='):
                        return int(line.split('=')[1].strip())
        except Exception:
            logger.warning(f"Konnte Port aus server.properties für {os.path.basename(instance_dir)} nicht lesen.")
    
    return DEFAULT_MINECRAFT_PORT # 3. Fallback

def start_instance(instance_name, config):
    instance_dir = os.path.join(INSTANCES_BASE_PATH, instance_name)
    os.makedirs(instance_dir, exist_ok=True)

    server_jar_name = config.get('server_jar')
    if not server_jar_name: return None, "Fehler: Server-JAR nicht spezifiziert."
    server_jar_path = os.path.join(SERVER_VERSIONS_BASE_PATH, server_jar_name)
    if not os.path.isfile(server_jar_path): return None, f"Fehler: Server-JAR '{server_jar_path}' nicht gefunden."

    eula_path = os.path.join(instance_dir, "eula.txt")
    try:
        if not os.path.exists(eula_path) or "eula=true" not in open(eula_path, encoding='utf-8').read():
            with open(eula_path, "w", encoding='utf-8') as f: f.write("eula=true\n")
    except Exception as e: logger.error(f"Fehler EULA '{instance_name}': {e}")

    server_props_path = os.path.join(instance_dir, "server.properties")
    props_content = {}
    if os.path.exists(server_props_path):
        try:
            with open(server_props_path, 'r', encoding='utf-8') as f_props:
                for line in f_props:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1); props_content[key.strip()] = value.strip()
        except Exception as e: logger.warning(f"Konnte server.properties für {instance_name} nicht lesen: {e}")

    final_server_port = parse_server_port(config.get('server_args', DEFAULT_SERVER_ARGS), instance_dir)
    props_content['server-port'] = str(final_server_port) # Stelle sicher, dass Port in Props ist

    rcon_enabled_by_panel = False
    if config.get('rcon_password') and config.get('rcon_port'):
        props_content['enable-rcon'] = 'true'
        props_content['rcon.port'] = str(config['rcon_port'])
        props_content['rcon.password'] = config['rcon_password']
        rcon_enabled_by_panel = True
    
    try:
        with open(server_props_path, 'w', encoding='utf-8') as f_props:
            for key, value in props_content.items(): f_props.write(f"{key}={value}\n")
        logger.info(f"server.properties für '{instance_name}' aktualisiert.")
    except Exception as e: logger.error(f"Fehler Schreiben server.properties '{instance_name}': {e}")

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
    except Exception as e: logger.error(f"Konnte Log '{log_file_path}' nicht initialisieren: {e}")
    
    message_suffix = f"Server loggt nach 'logs/latest.log'. Port: {final_server_port}."
    if rcon_enabled_by_panel: message_suffix += f" RCON auf Port {config.get('rcon_port')}."
    
    server_metadata = {
        'instance_dir': instance_dir, 'log_file_path': log_file_path, 'log_handle': None,
        'config_snapshot': config.copy(), 'server_port': final_server_port,
        'rcon_port': config.get('rcon_port') if config.get('rcon_password') else None,
        'rcon_password': config.get('rcon_password') if config.get('rcon_port') else None
    }
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
            log_handle = open(log_file_path, 'ab')
            process = subprocess.Popen(cmd_parts, cwd=instance_dir, stdout=log_handle, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
            server_metadata.update({'pid': process.pid, 'screen_name': None, 'type': 'direct', 'log_handle': log_handle})
            running_servers[instance_name] = server_metadata
            return "direct", f"'{instance_name}' startet direkt (PID: {process.pid}). {message_suffix}"
        except Exception as e:
            if 'log_handle' in locals() and log_handle: log_handle.close()
            logger.error(f"Fehler direkter Start '{instance_name}': {e}"); return None, f"Fehler direkter Start: {e}"

def stop_instance_managed(instance_name):
    """Stoppt eine verwaltete Instanz."""
    if instance_name not in running_servers:
        return False, f"Instanz '{instance_name}' nicht aktiv verwaltet."
    server_info = running_servers[instance_name]
    try:
        if server_info['type'] == 'screen' and server_info.get('screen_name'):
            subprocess.run(["screen", "-S", server_info['screen_name'], "-X", "stuff", "stop\r"], check=True, timeout=5)
            return True, f"Stop-Befehl an Screen '{server_info['screen_name']}' gesendet."
        elif server_info['type'] == 'direct' and server_info.get('pid'):
            os.killpg(server_info['pid'], signal_module.SIGINT)
            return True, f"Interrupt an Prozessgruppe von PID {server_info['pid']} gesendet."
        else:
            return False, "Unbekannter Servertyp oder fehlende Prozessinformationen."
    except subprocess.TimeoutExpired:
        return False, f"Timeout beim Stoppen von Screen '{server_info.get('screen_name')}'."
    except (subprocess.CalledProcessError, ProcessLookupError, PermissionError) as e:
        # Wenn schon gestoppt, ist das auch ein Erfolg im Kontext des Stoppens
        logger.warning(f"Fehler/Bereits gestoppt '{instance_name}': {e}")
        if instance_name in running_servers:
            if running_servers[instance_name].get('log_handle'):
                try: running_servers[instance_name]['log_handle'].close()
                except Exception: pass
            del running_servers[instance_name]
        return True, f"Server '{instance_name}' war bereits gestoppt oder Fehler: {e}"
    except Exception as e:
        logger.error(f"Allgemeiner Fehler beim Stoppen von '{instance_name}': {e}", exc_info=True)
        return False, f"Allgemeiner Fehler beim Stoppen: {e}"

def is_pid_running(pid):
    if pid is None: return False
    try: os.kill(pid, 0); return True
    except OSError: return False

def is_screen_session_running(screen_name):
    if not screen_name: return False
    try:
        result = subprocess.run(['screen', '-ls'], capture_output=True, text=True, check=False, timeout=3)
        if result.returncode == 0 and result.stdout:
            return f".{screen_name}\t(" in result.stdout or f"\t{screen_name}\t(" in result.stdout
        return False
    except: logger.debug(f"Fehler Prüfen Screen '{screen_name}'.", exc_info=False); return False

def send_rcon_to_instance(instance_name, command_to_send):
    config = None
    if instance_name in running_servers:
        config = running_servers[instance_name].get('config_snapshot', {})
    else:
        config = load_instance_config(instance_name)

    if not config:
        return None, f"Keine Konfig für Instanz '{instance_name}'."
    
    rcon_host = "127.0.0.1"
    rcon_port = config.get('rcon_port')
    rcon_password = config.get('rcon_password')

    if not command_to_send: return None, 'Kein Befehl.'
    if not rcon_port or not rcon_password:
        return None, 'RCON nicht (vollständig) konfiguriert.'
    try:
        with MCRcon(host=rcon_host, password=rcon_password, port=int(rcon_port), timeout=5) as mcr:
            response = mcr.command(command_to_send)
            return str(response), None # response, error
    except MCRconException as e:
        return None, f'RCON Fehler: {str(e)}'
    except Exception as e:
        return None, f'Allgemeiner RCON Fehler: {str(e)}'