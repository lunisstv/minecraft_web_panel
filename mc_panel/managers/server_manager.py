# mc_panel/managers/server_manager.py
import json
import os
import subprocess
import signal
import threading
import time
import shutil
from werkzeug.utils import secure_filename

try:
    import psutil # Für CPU/RAM-Auslastung
except ImportError:
    psutil = None
    print("WARNUNG: psutil nicht gefunden. CPU/RAM-Auslastung wird nicht verfügbar sein.")
    print("Bitte installiere psutil: pip install psutil")

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
                if not content.strip(): # Handle empty or whitespace-only file
                    return {}
                return json.loads(content)
        except json.JSONDecodeError:
            print(f"WARNUNG: {self.config_file} ist korrupt oder leer. Ein leeres Dictionary wird verwendet.")
            # Optional: Backup-Mechanismus oder Fehler auslösen
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
        for name, details in list(self.servers.items()): # list() für sichere Iteration bei Modifikation
            if not isinstance(details, dict):
                print(f"WARNUNG: Fehlerhafter Eintrag für Server '{name}' in Konfiguration gefunden und wird entfernt.")
                server_names_to_remove.append(name)
                changed = True
                continue

            if details.get('status') == 'running':
                details['status'] = 'stopped'
                changed = True

            # Standardwerte für neue und bestehende Parameter
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
            details.setdefault('custom_jvm_args', '') # Für zusätzliche JVM Argumente

        for name in server_names_to_remove:
            del self.servers[name]
        
        if changed:
            self._save_servers_config()

    def get_all_servers_with_resources(self):
        """ Gibt alle Serverdetails inklusive aktueller Ressourcenverwendung zurück. """
        servers_view = {}
        # Iteriere über eine Kopie, falls _load_servers_config im Hintergrund was ändert
        # (sollte nicht, aber sicher ist sicher)
        current_config_snapshot = dict(self.servers)


        for name, details_template in current_config_snapshot.items():
            if not isinstance(details_template, dict): continue # Überspringe fehlerhafte Einträge

            details = details_template.copy() # Arbeite mit einer Kopie
            process_obj = self.processes.get(name)
            if process_obj and process_obj.poll() is None: # Prozess existiert und läuft
                details['status'] = 'running'
                if psutil and hasattr(process_obj, 'pid'):
                    try:
                        p = psutil.Process(process_obj.pid)
                        details['cpu_usage'] = p.cpu_percent(interval=0.1) # Kurzes Intervall für schnelle Abfrage
                        mem_info = p.memory_info()
                        details['ram_usage_rss_mb'] = round(mem_info.rss / (1024 * 1024), 2) # RSS in MB
                        # details['ram_usage_vms_mb'] = round(mem_info.vms / (1024 * 1024), 2) # VMS in MB
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        details['cpu_usage'] = 'N/A'
                        details['ram_usage_rss_mb'] = 'N/A'
                else:
                    details['cpu_usage'] = 'N/A (psutil)'
                    details['ram_usage_rss_mb'] = 'N/A (psutil)'
                
                if details_template.get('status') != 'running':
                    self.servers[name]['status'] = 'running'
                    self._save_servers_config() # Speichere Statusänderung
            else: # Prozess läuft nicht oder existiert nicht
                details['status'] = details_template.get('status', 'stopped')
                if details['status'] == 'running': # Korrigiere falls Prozess weg aber Status noch running
                    details['status'] = 'stopped'
                    self.servers[name]['status'] = 'stopped'
                    self._save_servers_config()
                details['cpu_usage'] = 0
                details['ram_usage_rss_mb'] = 0

            servers_view[name] = details
        return servers_view

    def get_server_resource_usage(self, server_name):
        """ Gibt CPU und RAM Nutzung für einen spezifischen Server zurück. """
        if not psutil:
            return {'error': 'psutil not installed', 'cpu_usage': 'N/A', 'ram_usage_rss_mb': 'N/A'}

        process_obj = self.processes.get(server_name)
        if process_obj and process_obj.poll() is None and hasattr(process_obj, 'pid'):
            try:
                p = psutil.Process(process_obj.pid)
                # Für eine einzelne Abfrage kann das Intervall für cpu_percent() None sein oder ein sehr kurzes.
                # Ein erstes None gibt oft 0 zurück, ein zweiter Aufruf kurz danach ist genauer.
                # Für periodische Updates ist ein kleines Intervall besser.
                p.cpu_percent(interval=None) # Erster Aufruf "initialisiert"
                time.sleep(0.1) # Kurze Pause für genauere Messung
                cpu = p.cpu_percent(interval=None)
                mem_info = p.memory_info()
                ram_rss_mb = round(mem_info.rss / (1024 * 1024), 2)
                return {'cpu_usage': cpu, 'ram_usage_rss_mb': ram_rss_mb, 'status': 'running'}
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return {'error': 'Process not found or access denied', 'cpu_usage': 'N/A', 'ram_usage_rss_mb': 'N/A', 'status': 'error'}
        return {'cpu_usage': 0, 'ram_usage_rss_mb': 0, 'status': 'stopped'}


    def get_server_details(self, server_name):
        # Gibt Details basierend auf dem aktuellen Laufzeitstatus zurück
        all_servers = self.get_all_servers_with_resources() # Holt jetzt auch Ressourcen
        return all_servers.get(server_name)

    def get_server_path(self, server_name, validate_name_for_path=True):
        if validate_name_for_path:
            # Erlaube nur alphanumerische Zeichen, Unterstrich und Bindestrich für Verzeichnisnamen
            # Dies ist eine stärkere Einschränkung als secure_filename für Dateinamen
            if not all(c.isalnum() or c in ['_', '-'] for c in server_name):
                raise ValueError("Ungültiger Servername für Pfad. Nur Buchstaben, Zahlen, '_' und '-' erlaubt.")
            # secure_filename ist hier nicht ideal, da es Zeichen ersetzen/entfernen kann,
            # was den Namen unkenntlich machen könnte. Besser ist eine strenge Validierung.
            safe_server_name = server_name
        else:
            safe_server_name = server_name # Für interne Aufrufe, wo der Name bereits validiert wurde

        return os.path.join(self.instances_dir, safe_server_name)


    def _read_output(self, process, server_name):
        if process.stdout:
            try:
                for line in iter(process.stdout.readline, ''):
                    line_stripped = line.strip()
                    if line_stripped: # Nur nicht-leere Zeilen hinzufügen
                        self.server_outputs.setdefault(server_name, []).append(line_stripped)
                        if len(self.server_outputs[server_name]) > 250: # Begrenzung der Ausgabezeilen
                            self.server_outputs[server_name].pop(0)
            except ValueError: # Kann auftreten, wenn Popen-Stream geschlossen wird, während readline liest
                print(f"INFO: Stdout-Stream für Server {server_name} wurde geschlossen (möglicherweise während des Stoppens).")
            finally:
                if process.stdout and not process.stdout.closed:
                    process.stdout.close()

        process.wait() # Warten bis Prozess beendet

        # Aktualisiere Status, wenn der Prozess von selbst endet
        # Stelle sicher, dass der Server noch in der Konfiguration ist
        if server_name in self.servers and isinstance(self.servers.get(server_name), dict):
            self.servers[server_name]['status'] = 'stopped'
            self._save_servers_config()
        
        if server_name in self.processes:
            del self.processes[server_name]
        if server_name in self.threads: # Thread sollte hier enden
            del self.threads[server_name]
        # print(f"Output thread for {server_name} finished, server marked as stopped.")


    def start_server(self, server_name):
        # self.servers = self._load_servers_config() # Lade neueste Konfig
        if server_name not in self.servers or not isinstance(self.servers.get(server_name), dict):
            return False, f"Server '{server_name}' nicht gefunden oder Konfiguration fehlerhaft."

        server_info = self.servers[server_name]
        try:
            server_dir = self.get_server_path(server_name) # Verwendet validierten Namen
        except ValueError as e:
             return False, str(e) # Ungültiger Servername

        jar_in_server_dir = os.path.join(server_dir, 'server.jar')

        if not os.path.exists(jar_in_server_dir):
            return False, f"server.jar nicht im Verzeichnis '{server_dir}' gefunden."

        if server_name in self.processes and self.processes[server_name].poll() is None:
            return False, f"Server '{server_name}' läuft bereits."

        ram_min = server_info.get('ram_min', '1G')
        ram_max = server_info.get('ram_max', '2G')
        velocity_secret = server_info.get('velocity_secret', '')
        custom_jvm_args_str = server_info.get('custom_jvm_args', '')
        custom_jvm_args_list = custom_jvm_args_str.split() # Trennt Argumente bei Leerzeichen

        command = ['java']
        if velocity_secret:
            command.append(f'-Dvelocity-forwarding-secret={velocity_secret}')
        
        # Füge benutzerdefinierte JVM Argumente hinzu
        command.extend(custom_jvm_args_list)

        command.extend([
            f'-Xms{ram_min}', f'-Xmx{ram_max}',
            '-jar', 'server.jar', 'nogui'
        ])
        # EULA-Check und Erstellung
        eula_path = os.path.join(server_dir, 'eula.txt')
        eula_ok = False
        if os.path.exists(eula_path):
            try:
                with open(eula_path, 'r') as f:
                    if any(line.strip().lower() == "eula=true" for line in f):
                        eula_ok = True
            except IOError:
                pass # Fehler beim Lesen, behandeln als ob nicht ok

        if not eula_ok:
            if server_info.get("eula_accepted_in_panel", False):
                try:
                    with open(eula_path, 'w') as f:
                        f.write("# EULA wurde durch das Webpanel akzeptiert.\n")
                        f.write(f"# {time.asctime()}\n")
                        f.write("eula=true\n")
                    print(f"eula.txt für '{server_name}' erstellt/aktualisiert und akzeptiert.")
                    eula_ok = True
                except IOError as e:
                     return False, f"Konnte eula.txt nicht schreiben für '{server_name}': {e}"
            else:
                return False, (
                    f"EULA für Server '{server_name}' ist in '{eula_path}' nicht auf 'eula=true' gesetzt "
                    f"und wurde beim Erstellen nicht im Panel akzeptiert. Bitte manuell anpassen oder Server neu erstellen und EULA akzeptieren."
                )
        
        if not eula_ok: # Endgültiger Check
             return False, f"EULA für Server '{server_name}' konnte nicht verifiziert oder akzeptiert werden."


        try:
            # Verhindert das Öffnen eines neuen Konsolenfensters unter Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE # Versteckt das Fenster

            print(f"Starte Server '{server_name}' mit Befehl: {' '.join(command)}") # Logging des Befehls
            process = subprocess.Popen(
                command,
                cwd=server_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # stderr auch auf stdout umleiten
                text=True,
                bufsize=1, # Line-buffered
                universal_newlines=True, # Stellt sicher, dass Newlines als \n behandelt werden
                startupinfo=startupinfo, # Für Windows
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0 # Sicherer
            )
            self.processes[server_name] = process
            self.server_outputs[server_name] = [] # Konsolenausgabe initialisieren/leeren

            thread = threading.Thread(target=self._read_output, args=(process, server_name))
            thread.daemon = True # Thread stirbt mit Hauptanwendung
            thread.start()
            self.threads[server_name] = thread

            self.servers[server_name]['status'] = 'running'
            self._save_servers_config()
            return True, f"Server '{server_name}' gestartet."
        except Exception as e:
            # Sicherstellen, dass Status korrekt ist, falls Start fehlschlägt
            if server_name in self.servers and isinstance(self.servers.get(server_name), dict):
                self.servers[server_name]['status'] = 'stopped'
                self._save_servers_config()
            if server_name in self.processes: # Aufräumen, falls Prozessobjekt erstellt, aber Popen fehlschlug
                del self.processes[server_name]
            return False, f"Fehler beim Starten von Server '{server_name}': {e}"


    def stop_server(self, server_name):
        # self.servers = self._load_servers_config() # Lade neueste Konfig
        if server_name not in self.processes or self.processes[server_name].poll() is not None:
            # Wenn Prozess nicht da, aber Status in Config "running", korrigieren.
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
            else: # Stdin nicht verfügbar, versuche direkt Terminate
                print(f"WARNUNG: Stdin für Server {server_name} nicht verfügbar. Versuche Terminate.")
                process.terminate()


            # Warte bis zu 30 Sekunden auf das Beenden durch "stop"
            process.wait(timeout=30)
            msg = f"Server '{server_name}' gestoppt."

        except subprocess.TimeoutExpired:
            print(f"Server '{server_name}' reagierte nicht auf 'stop'. Versuche Terminate/Kill.")
            process.terminate() # SIGTERM
            try:
                process.wait(timeout=10) # Warte kurz auf Terminierung
                msg = f"Server '{server_name}' wurde terminiert (SIGTERM)."
            except subprocess.TimeoutExpired:
                process.kill() # SIGKILL als letzte Instanz
                process.wait() # Sicherstellen, dass Prozess beendet ist
                msg = f"Server '{server_name}' musste hart beendet werden (SIGKILL)."
        except Exception as e: # z.B. BrokenPipeError wenn stdin schon zu
            print(f"Fehler beim Senden von 'stop' an Server '{server_name}': {e}. Versuche härtere Methoden.")
            if process.poll() is None: # Wenn Prozess noch läuft
                try:
                    process.terminate()
                    process.wait(timeout=5)
                    msg = f"Server '{server_name}' terminiert nach Fehler."
                except: # noqa
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    msg = f"Server '{server_name}' hart beendet nach Fehler."
            else: # Prozess ist schon beendet
                 msg = f"Server '{server_name}' war bereits gestoppt während des Stop-Vorgangs. Fehler: {e}"

        finally:
            # Aufräumen, auch wenn Fehler auftraten
            if server_name in self.processes:
                del self.processes[server_name]
            if server_name in self.threads:
                 # Thread sollte von selbst enden, da process.stdout geschlossen wird.
                 # Ein join() hier könnte blockieren, wenn der Thread nicht sauber beendet.
                 del self.threads[server_name]

            self.server_outputs.pop(server_name, None) # Konsole leeren oder Eintrag entfernen

            if server_name in self.servers and isinstance(self.servers.get(server_name), dict):
                self.servers[server_name]['status'] = 'stopped'
                self._save_servers_config()
        return True, msg


    def get_console_output_with_resources(self, server_name):
        """ Gibt Konsolenausgabe und Ressourceninformationen zurück. """
        output = self.server_outputs.get(server_name, ["Server nicht aktiv oder keine aktuelle Ausgabe."])
        resources = self.get_server_resource_usage(server_name)
        return {'console': output, 'resources': resources}


    def send_command(self, server_name, command):
        if server_name not in self.processes or self.processes[server_name].poll() is not None:
            return False, "Server nicht gestartet oder bereits beendet."
        if not command:
            return False, "Kein Befehl erhalten."
        try:
            process = self.processes[server_name]
            if process.stdin and not process.stdin.closed:
                process.stdin.write(command + '\n')
                process.stdin.flush()
                # Optional: Befehl zur Konsolenausgabe hinzufügen (clientseitig oft besser)
                # self.server_outputs.setdefault(server_name, []).append(f"> {command}")
                return True, "Befehl gesendet."
            else:
                return False, "Server-Konsole (stdin) ist nicht beschreibbar."
        except BrokenPipeError:
            return False, "Fehler: Verbindung zur Server-Konsole unterbrochen (BrokenPipe)."
        except Exception as e:
            return False, f"Fehler beim Senden des Befehls: {e}"


        def _generate_server_properties(self, server_dir, server_data):
            """ Generiert eine server.properties Datei mit den gegebenen Daten. """
            properties_path = os.path.join(server_dir, 'server.properties')
            content = "# Minecraft server properties generated by WebPanel\n"
            content += f"# {time.asctime()}\n"
            content += f"server-port={server_data.get('port')}\n"
            content += f"level-name={server_data.get('level_name', 'world')}\n"
            content += f"gamemode={server_data.get('gamemode', 'survival')}\n"
            content += f"difficulty={server_data.get('difficulty', 'easy')}\n"
            content += f"max-players={server_data.get('max_players', 20)}\n"
            content += f"online-mode={str(server_data.get('online_mode', True)).lower()}\n"
            # PaperMC spezifisch, falls Velocity Secret vorhanden ist.
            # Besser wäre, dies nur für Paper-Server zu setzen, aber es schadet meist nicht.
            if server_data.get('velocity_secret'):
                content += f"player-identity-forwarding-type=MODERN\n" # oder LEGACY, je nach Proxy
                content += f"player-identity-forwarding-secret={server_data.get('velocity_secret')}\n"
            
            # Weitere Standard- oder wichtige Properties, die man setzen könnte:
            content += "enable-rcon=false\n" # Standardmäßig aus Sicherheitsgründen deaktivieren
            content += "motd=A Minecraft Server managed by WebPanel\n"
            # ... füge hier weitere gewünschte Standard-Properties hinzu ...

            try:
                with open(properties_path, 'w') as f:
                    f.write(content)
                return True, f"server.properties für '{server_data.get('server_name')}' erstellt."
            except IOError as e:
                return False, f"Fehler beim Schreiben der server.properties: {e}"


    def create_server(self, server_data, selected_jar_filename):
        server_name = server_data.get('server_name')
        # ... (Validierungen für server_name, port, ram wie zuvor) ...
        if not all(c.isalnum() or c in ['_', '-'] for c in server_name): # Strenge Validierung
             return False, "Servername darf nur Buchstaben, Zahlen, '_' und '-' enthalten."
        # ... (Rest der Validierungen wie Port, RAM etc. aus vorheriger Version)

        try:
            server_dir = self.get_server_path(server_name) # Verwendet validierten Namen
        except ValueError as e:
            return False, str(e)

        # self.servers = self._load_servers_config() # Neueste Config laden
        if server_name in self.servers:
            return False, f"Ein Server mit dem Namen '{server_name}' existiert bereits."

        # Überprüfen, ob Port bereits verwendet wird
        for s_info in self.servers.values():
            if isinstance(s_info, dict) and str(s_info.get('port')) == str(server_data.get('port')):
                return False, f"Port {server_data.get('port')} wird bereits verwendet."

        # selected_jar_filename sollte bereits sicher sein (von JarManager.list_jars)
        # Dennoch os.path.basename als zusätzliche Sicherheitsebene
        source_jar_path = os.path.join(self.jars_dir, os.path.basename(selected_jar_filename))
        if not os.path.exists(source_jar_path):
            return False, f"Ausgewählte JAR-Datei '{os.path.basename(selected_jar_filename)}' nicht gefunden."

        # Serververzeichnis wurde oben bereits validiert und in server_dir gespeichert
        try:
            os.makedirs(server_dir, exist_ok=True)
        except OSError as e:
            return False, f"Fehler beim Erstellen des Serververzeichnisses '{server_dir}': {e}"

        destination_jar_path = os.path.join(server_dir, 'server.jar')
        try:
            shutil.copy(source_jar_path, destination_jar_path)
        except Exception as e:
            shutil.rmtree(server_dir, ignore_errors=True) # Aufräumen
            return False, f"Fehler beim Kopieren der JAR-Datei: {e}"

        # EULA-Datei erstellen, wenn im Formular akzeptiert
        if server_data.get('eula_accepted_in_panel', False):
            try:
                with open(os.path.join(server_dir, 'eula.txt'), 'w') as f:
                    f.write("# EULA wurde durch das Webpanel beim Erstellen akzeptiert.\n")
                    f.write(f"# {time.asctime()}\n")
                    f.write("eula=true\n")
            except IOError as e:
                shutil.rmtree(server_dir, ignore_errors=True) # Aufräumen
                return False, f"Konnte eula.txt nicht schreiben: {e}"


        prop_success, prop_message = self._generate_server_properties(server_dir, server_data)
        if not prop_success:
            shutil.rmtree(server_dir, ignore_errors=True)
            return False, prop_message # Gib die Fehlermeldung der Property-Generierung zurück


        # Daten für servers.json vorbereiten
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
        return True, f"Server '{server_name}' erfolgreich erstellt. {prop_message}"


    def delete_server(self, server_name):
        # self.servers = self._load_servers_config() # Neueste Config laden
        if server_name not in self.servers or not isinstance(self.servers.get(server_name), dict):
            return False, f"Server '{server_name}' nicht gefunden oder Konfiguration fehlerhaft."

        if server_name in self.processes and self.processes[server_name].poll() is None:
            return False, f"Server '{server_name}' läuft noch. Bitte zuerst stoppen."

        try:
            server_dir_path = self.get_server_path(server_name) # Verwendet validierten Namen
        except ValueError: # Sollte nicht passieren, wenn Server in Config ist
            return False, f"Ungültiger Servername '{server_name}' für Pfadoperation."


        if os.path.exists(server_dir_path):
            try:
                shutil.rmtree(server_dir_path) # Verzeichnis und Inhalt löschen
            except Exception as e:
                return False, f"Fehler beim Löschen des Serververzeichnisses '{server_dir_path}': {e}"

        del self.servers[server_name]
        self._save_servers_config()

        # Aus internen Laufzeit-Dictionaries entfernen, falls noch vorhanden
        if server_name in self.processes: del self.processes[server_name]
        if server_name in self.threads: del self.threads[server_name]
        self.server_outputs.pop(server_name, None) # Konsolenausgabe entfernen

        return True, f"Server '{server_name}' und seine Dateien wurden gelöscht."