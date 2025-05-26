# mc_panel/managers/server_manager.py
import json
import os
import subprocess
import signal # Nicht direkt verwendet, aber oft nützlich für Prozessmanagement
import threading
import time
import shutil
from werkzeug.utils import secure_filename

try:
    import psutil # Für CPU/RAM-Auslastung
except ImportError:
    _psutil_available = False # Privates Modul-Level Flag
    psutil = None # Definiere psutil als None, damit Referenzen nicht fehlschlagen
    print("WARNUNG: psutil nicht gefunden. CPU/RAM-Auslastung wird nicht verfügbar sein.")
    print("Bitte installiere psutil: pip install psutil")
else:
    _psutil_available = True

class ServerManager:
    def __init__(self, config_file, instances_dir, jars_dir):
        self.config_file = config_file
        self.instances_dir = instances_dir
        self.jars_dir = jars_dir
        self.servers = self._load_servers_config()

        self.processes = {}
        self.threads = {}
        self.server_outputs = {}

        self._initialize_server_statuses()

    def _load_servers_config(self):
        if not os.path.exists(self.config_file):
            return {}
        try:
            with open(self.config_file, 'r') as f:
                content = f.read()
                if not content.strip():
                    return {}
                return json.loads(content)
        except json.JSONDecodeError:
            print(f"WARNUNG: {self.config_file} ist korrupt oder leer. Ein leeres Dictionary wird verwendet.")
            return {}
        except OSError as e:
            print(f"WARNUNG: Konnte Serverkonfiguration nicht laden: {e}")
            return {}

    def _save_servers_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.servers, f, indent=4)
        except OSError as e:
            print(f"FEHLER: Konnte Serverkonfiguration nicht speichern: {e}")

    def _initialize_server_statuses(self):
        changed = False
        server_names_to_remove = []
        for name, details in list(self.servers.items()):
            if not isinstance(details, dict):
                print(f"WARNUNG: Fehlerhafter Eintrag für Server '{name}' in Konfiguration gefunden und wird entfernt.")
                server_names_to_remove.append(name)
                changed = True
                continue

            if details.get('status') == 'running':
                details['status'] = 'stopped'
                changed = True

            details.setdefault('port', '25565')
            details.setdefault('ram_min', '1G')
            details.setdefault('ram_max', '2G')
            details.setdefault('jar', 'server.jar')
            details.setdefault('status', 'stopped')
            details.setdefault('path', self.get_server_path(name, validate_name_for_path=False))
            details.setdefault('eula_accepted_in_panel', False)
            details.setdefault('velocity_secret', '')
            details.setdefault('level_name', 'world')
            details.setdefault('gamemode', 'survival')
            details.setdefault('difficulty', 'easy')
            details.setdefault('max_players', 20)
            details.setdefault('online_mode', True)
            details.setdefault('custom_jvm_args', '')

        for name in server_names_to_remove:
            del self.servers[name]
        
        if changed:
            self._save_servers_config()

    def get_all_servers_with_resources(self):
        servers_view = {}
        current_config_snapshot = dict(self.servers)
        for name, details_template in current_config_snapshot.items():
            if not isinstance(details_template, dict): continue
            details = details_template.copy()
            process_obj = self.processes.get(name)
            if process_obj and process_obj.poll() is None:
                details['status'] = 'running'
                if _psutil_available and hasattr(process_obj, 'pid'):
                    try:
                        p = psutil.Process(process_obj.pid)
                        details['cpu_usage'] = p.cpu_percent(interval=0.1) 
                        mem_info = p.memory_info()
                        details['ram_usage_rss_mb'] = round(mem_info.rss / (1024 * 1024), 2)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        details['cpu_usage'] = 'N/A (Err)'
                        details['ram_usage_rss_mb'] = 'N/A (Err)'
                else:
                    details['cpu_usage'] = 'N/A (psutil)'
                    details['ram_usage_rss_mb'] = 'N/A (psutil)'
                if details_template.get('status') != 'running':
                    self.servers[name]['status'] = 'running'
                    self._save_servers_config()
            else:
                details['status'] = details_template.get('status', 'stopped')
                if details['status'] == 'running': 
                     details['status'] = 'stopped'
                     self.servers[name]['status'] = 'stopped'
                     self._save_servers_config()
                details['cpu_usage'] = 0
                details['ram_usage_rss_mb'] = 0
            servers_view[name] = details
        return servers_view
        
    def get_server_resource_usage(self, server_name):
        if not _psutil_available:
            return {'error': 'psutil_not_installed', 'cpu_usage': 'N/A', 'ram_usage_rss_mb': 'N/A', 'status': 'N/A'}
        process_obj = self.processes.get(server_name)
        # Hole den Status aus der Config als Fallback
        server_config_details = self.servers.get(server_name, {})
        current_status_from_config = server_config_details.get('status', 'stopped')

        if process_obj and process_obj.poll() is None and hasattr(process_obj, 'pid'):
            try:
                p = psutil.Process(process_obj.pid)
                p.cpu_percent(interval=None) 
                time.sleep(0.1) 
                cpu = p.cpu_percent(interval=None)
                mem_info = p.memory_info()
                ram_rss_mb = round(mem_info.rss / (1024 * 1024), 2)
                return {'cpu_usage': cpu, 'ram_usage_rss_mb': ram_rss_mb, 'status': 'running'}
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return {'error': 'process_disappeared_or_access_denied', 'cpu_usage': 'N/A', 'ram_usage_rss_mb': 'N/A', 'status': 'stopped'}
            except Exception as e:
                print(f"Fehler beim Abfragen der Ressourcen für {server_name}: {e}")
                return {'error': 'resource_query_error', 'cpu_usage': 'N/A', 'ram_usage_rss_mb': 'N/A', 'status': current_status_from_config}
        return {'cpu_usage': 0, 'ram_usage_rss_mb': 0, 'status': current_status_from_config}

    def get_server_details(self, server_name):
        all_servers = self.get_all_servers_with_resources()
        return all_servers.get(server_name)

    def get_server_path(self, server_name, validate_name_for_path=True):
        if validate_name_for_path:
            if not all(c.isalnum() or c in ['_', '-'] for c in server_name):
                raise ValueError("Ungültiger Servername für Pfad. Nur Buchstaben, Zahlen, '_' und '-' erlaubt.")
            safe_server_name = server_name
        else:
            safe_server_name = server_name
        return os.path.join(self.instances_dir, safe_server_name)

    def _read_output(self, process, server_name):
        if process.stdout:
            try:
                for line in iter(process.stdout.readline, ''):
                    line_stripped = line.strip()
                    if line_stripped: 
                        self.server_outputs.setdefault(server_name, []).append(line_stripped)
                        if len(self.server_outputs[server_name]) > 250: 
                            self.server_outputs[server_name].pop(0)
            except ValueError: 
                print(f"INFO: Stdout-Stream für Server {server_name} wurde geschlossen.")
            finally:
                if process.stdout and not process.stdout.closed:
                    process.stdout.close()
        process.wait() 
        if server_name in self.servers and isinstance(self.servers.get(server_name), dict):
            self.servers[server_name]['status'] = 'stopped'
            self._save_servers_config()
        if server_name in self.processes: del self.processes[server_name]
        if server_name in self.threads: del self.threads[server_name]

    def start_server(self, server_name):
        if server_name not in self.servers or not isinstance(self.servers.get(server_name), dict):
            return False, f"Server '{server_name}' nicht gefunden oder Konfiguration fehlerhaft."
        server_info = self.servers[server_name]
        try:
            server_dir = self.get_server_path(server_name)
        except ValueError as e:
             return False, str(e)
        jar_in_server_dir = os.path.join(server_dir, 'server.jar')
        if not os.path.exists(jar_in_server_dir):
            return False, f"server.jar nicht im Verzeichnis '{server_dir}' gefunden."
        if server_name in self.processes and self.processes[server_name].poll() is None:
            return False, f"Server '{server_name}' läuft bereits."

        ram_min = server_info.get('ram_min', '1G')
        ram_max = server_info.get('ram_max', '2G')
        velocity_secret = server_info.get('velocity_secret', '')
        custom_jvm_args_str = server_info.get('custom_jvm_args', '')
        custom_jvm_args_list = custom_jvm_args_str.split()

        command = ['java']
        # Velocity Secret und Custom Args kommen vor RAM und JAR
        if velocity_secret:
            command.append(f'-Dvelocity-forwarding-secret={velocity_secret}')
        command.extend(custom_jvm_args_list)
        command.extend([f'-Xms{ram_min}', f'-Xmx{ram_max}', '-jar', 'server.jar', 'nogui'])
        
        eula_path = os.path.join(server_dir, 'eula.txt')
        eula_ok = False
        if os.path.exists(eula_path):
            try:
                with open(eula_path, 'r') as f:
                    if any(line.strip().lower() == "eula=true" for line in f): eula_ok = True
            except IOError: pass
        if not eula_ok:
            if server_info.get("eula_accepted_in_panel", False):
                try:
                    with open(eula_path, 'w') as f: f.write("eula=true\n#Minecraft EULA accepted via WebPanel")
                    eula_ok = True
                except IOError as e: return False, f"Konnte eula.txt nicht schreiben: {e}"
            else: return False, f"EULA nicht akzeptiert für {server_name} (in Panel oder eula.txt)."
        if not eula_ok: return False, f"EULA Problem für {server_name} trotz Versuchen."

        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            print(f"Starte Server '{server_name}' mit Befehl: {' '.join(command)}")
            process = subprocess.Popen(
                command, cwd=server_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True,
                startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            self.processes[server_name] = process
            self.server_outputs[server_name] = []
            thread = threading.Thread(target=self._read_output, args=(process, server_name))
            thread.daemon = True
            thread.start()
            self.threads[server_name] = thread
            self.servers[server_name]['status'] = 'running'
            self._save_servers_config()
            return True, f"Server '{server_name}' gestartet."
        except Exception as e:
            if server_name in self.servers and isinstance(self.servers.get(server_name), dict):
                self.servers[server_name]['status'] = 'stopped'
                self._save_servers_config()
            if server_name in self.processes: del self.processes[server_name]
            return False, f"Fehler beim Starten von Server '{server_name}': {e}"

    def stop_server(self, server_name):
        if server_name not in self.processes or self.processes[server_name].poll() is not None:
            if server_name in self.servers and isinstance(self.servers.get(server_name), dict) and self.servers[server_name]['status'] == 'running':
                self.servers[server_name]['status'] = 'stopped'
                self._save_servers_config()
            return False, f"Server '{server_name}' läuft nicht oder wurde bereits gestoppt."
        process = self.processes[server_name]
        msg = ""
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.write("stop\n")
                process.stdin.flush()
            else: process.terminate()
            process.wait(timeout=30)
            msg = f"Server '{server_name}' gestoppt."
        except subprocess.TimeoutExpired:
            process.terminate() 
            try:
                process.wait(timeout=10)
                msg = f"Server '{server_name}' wurde terminiert (SIGTERM)."
            except subprocess.TimeoutExpired:
                process.kill(); process.wait() 
                msg = f"Server '{server_name}' musste hart beendet werden (SIGKILL)."
        except Exception as e: 
            if process.poll() is None: 
                try:
                    process.terminate(); process.wait(timeout=5)
                    msg = f"Server '{server_name}' terminiert nach Fehler."
                except: 
                    if process.poll() is None: process.kill(); process.wait()
                    msg = f"Server '{server_name}' hart beendet nach Fehler."
            else: msg = f"Server '{server_name}' war bereits gestoppt. Fehler: {e}"
        finally:
            if server_name in self.processes: del self.processes[server_name]
            if server_name in self.threads: del self.threads[server_name]
            self.server_outputs.pop(server_name, None) 
            if server_name in self.servers and isinstance(self.servers.get(server_name), dict):
                self.servers[server_name]['status'] = 'stopped'
                self._save_servers_config()
        return True, msg

    def get_console_output_with_resources(self, server_name):
        output = self.server_outputs.get(server_name, ["Server nicht aktiv oder keine aktuelle Ausgabe."])
        resources = self.get_server_resource_usage(server_name)
        return {'console': output, 'resources': resources}

    def send_command(self, server_name, command):
        if server_name not in self.processes or self.processes[server_name].poll() is not None:
            return False, "Server nicht gestartet oder bereits beendet."
        if not command: return False, "Kein Befehl erhalten."
        try:
            process = self.processes[server_name]
            if process.stdin and not process.stdin.closed:
                process.stdin.write(command + '\n'); process.stdin.flush()
                return True, "Befehl gesendet."
            else: return False, "Server-Konsole (stdin) ist nicht beschreibbar."
        except BrokenPipeError: return False, "Fehler: Verbindung zur Server-Konsole unterbrochen."
        except Exception as e: return False, f"Fehler beim Senden des Befehls: {e}"

    # ***** NEU DEFINIERTE METHODE *****
    def _generate_server_properties(self, server_dir, server_data):
        """ Generiert eine server.properties Datei mit den gegebenen Daten. """
        properties_path = os.path.join(server_dir, 'server.properties')
        
        # Standardwerte für server.properties, falls nicht in server_data
        props = {
            'server-port': server_data.get('port', '25565'),
            'level-name': server_data.get('level_name', 'world'),
            'gamemode': server_data.get('gamemode', 'survival'),
            'difficulty': server_data.get('difficulty', 'easy'),
            'max-players': server_data.get('max_players', 20),
            'online-mode': str(server_data.get('online_mode', True)).lower(), # Muss 'true' oder 'false' sein
            'enable-rcon': 'false', # Standardmäßig aus
            'motd': f"A Minecraft Server - {server_data.get('server_name', 'My Server')}",
            # Velocity/Proxy spezifische Einstellungen
            'network-compression-threshold': 256, # Guter Standardwert
        }

        # PaperMC spezifische Einstellungen für Velocity (falls Secret vorhanden ist)
        # Diese sollten nur geschrieben werden, wenn die JAR vermutlich Paper/Purpur etc. ist.
        # Für eine einfache Implementierung schreiben wir sie, wenn ein Secret da ist.
        # Besser wäre es, den Servertyp zu kennen.
        if server_data.get('velocity_secret'):
             props['player-identity-forwarding-type'] = "MODERN" # oder "LEGACY" oder "BUNGEECORD"
             props['player-identity-forwarding-secret'] = server_data.get('velocity_secret')
             # Für Paper/Purpur ist es oft 'settings.velocity-support.secret' und 'settings.velocity-support.online-mode'
             # in paper.yml / purpur.yml etc. Die server.properties für Velocity ist da anders.
             # Wir setzen hier die BungeeCord-Variante, die viele Forks unterstützen.
             props['prevent-proxy-connections'] = 'false' # Muss false sein für Bungee/Velocity
        else:
            # Wenn kein Proxy, kann man prevent-proxy-connections auf true setzen,
            # aber viele Server-JARs ignorieren das oder setzen es standardmäßig.
            # props['prevent-proxy-connections'] = 'true' # (Optional)
            pass


        # Erstelle den Inhalt der Datei
        content_lines = [
            "# Minecraft server properties",
            f"# Generated by WebPanel on {time.asctime()}"
        ]
        for key, value in props.items():
            content_lines.append(f"{key}={value}")

        try:
            with open(properties_path, 'w') as f:
                f.write("\n".join(content_lines) + "\n")
            return True, f"server.properties für '{server_data.get('server_name', 'Unbekannt')}' erstellt/aktualisiert."
        except IOError as e:
            return False, f"Fehler beim Schreiben der server.properties: {e}"
    # ***** ENDE NEU DEFINIERTE METHODE *****

    def create_server(self, server_data, selected_jar_filename):
        server_name = server_data.get('server_name')
        # Validierungen (gekürzt, da oben schon behandelt)
        if not all(c.isalnum() or c in ['_', '-'] for c in server_name):
             return False, "Servername darf nur Buchstaben, Zahlen, '_' und '-' enthalten."
        try:
            port_num = int(server_data.get('port'))
            if not (1024 <= port_num <= 65535): raise ValueError()
        except: return False, "Ungültiger Port."
        # Weitere Validierungen für RAM, max_players etc. sollten hier auch sein.

        try:
            server_dir = self.get_server_path(server_name)
        except ValueError as e: return False, str(e)

        if server_name in self.servers:
            return False, f"Ein Server mit dem Namen '{server_name}' existiert bereits."
        
        for s_info in self.servers.values():
            if isinstance(s_info, dict) and str(s_info.get('port')) == str(server_data.get('port')):
                return False, f"Port {server_data.get('port')} wird bereits verwendet."

        source_jar_path = os.path.join(self.jars_dir, os.path.basename(selected_jar_filename))
        if not os.path.exists(source_jar_path):
            return False, f"JAR-Datei '{os.path.basename(selected_jar_filename)}' nicht gefunden."

        try: os.makedirs(server_dir, exist_ok=True)
        except OSError as e: return False, f"Fehler beim Erstellen des Verzeichnisses '{server_dir}': {e}"

        destination_jar_path = os.path.join(server_dir, 'server.jar')
        try: shutil.copy(source_jar_path, destination_jar_path)
        except Exception as e:
            shutil.rmtree(server_dir, ignore_errors=True); return False, f"Fehler beim Kopieren der JAR: {e}"

        if server_data.get('eula_accepted_in_panel', False):
            try:
                with open(os.path.join(server_dir, 'eula.txt'), 'w') as f:
                    f.write("eula=true\n#Minecraft EULA accepted via WebPanel")
            except IOError as e:
                shutil.rmtree(server_dir, ignore_errors=True); return False, f"Konnte eula.txt nicht schreiben: {e}"
        else: # EULA nicht akzeptiert, trotzdem Server erstellen, aber mit Hinweis
            print(f"INFO: EULA für Server {server_name} nicht im Panel akzeptiert. Muss manuell in eula.txt erfolgen.")


        prop_success, prop_message = self._generate_server_properties(server_dir, server_data) # Aufruf hier
        if not prop_success:
            shutil.rmtree(server_dir, ignore_errors=True)
            return False, prop_message

        new_server_entry = {
            'port': server_data.get('port'),
            'ram_min': server_data.get('ram_min').upper(),
            'ram_max': server_data.get('ram_max').upper(),
            'jar': os.path.basename(selected_jar_filename),
            'status': 'stopped',
            'path': server_dir,
            'eula_accepted_in_panel': server_data.get('eula_accepted_in_panel', False),
            'velocity_secret': server_data.get('velocity_secret', ''),
            'level_name': server_data.get('level_name', 'world'),
            'gamemode': server_data.get('gamemode', 'survival'),
            'difficulty': server_data.get('difficulty', 'easy'),
            'max_players': int(server_data.get('max_players', 20)),
            'online_mode': server_data.get('online_mode', True),
            'custom_jvm_args': server_data.get('custom_jvm_args', '')
        }
        self.servers[server_name] = new_server_entry
        self._save_servers_config()
        eula_msg = " (EULA akzeptiert)" if new_server_entry['eula_accepted_in_panel'] else " (EULA muss manuell bestätigt werden)"
        return True, f"Server '{server_name}' erfolgreich erstellt. {prop_message}{eula_msg}"

    def delete_server(self, server_name):
        if server_name not in self.servers or not isinstance(self.servers.get(server_name), dict):
            return False, f"Server '{server_name}' nicht gefunden."
        if server_name in self.processes and self.processes[server_name].poll() is None:
            return False, f"Server '{server_name}' läuft noch. Bitte zuerst stoppen."
        try: server_dir_path = self.get_server_path(server_name) 
        except ValueError: return False, f"Ungültiger Servername '{server_name}'."
        if os.path.exists(server_dir_path):
            try: shutil.rmtree(server_dir_path) 
            except Exception as e: return False, f"Fehler beim Löschen Verzeichnis '{server_dir_path}': {e}"
        del self.servers[server_name]; self._save_servers_config()
        if server_name in self.processes: del self.processes[server_name]
        if server_name in self.threads: del self.threads[server_name]
        self.server_outputs.pop(server_name, None) 
        return True, f"Server '{server_name}' und Dateien gelöscht."