# config.py
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Standard Flask Konfiguration (kann in instance/config.py überschrieben werden)
DEBUG = True
HOST = '0.0.0.0'
PORT = 5000
# UNBEDINGT ÄNDERN! Muss ein langer, zufälliger String sein.
# Du kannst z.B. "import secrets; secrets.token_hex(32)" in einer Python-Konsole nutzen.
SECRET_KEY = 'default_secret_key_please_change_in_instance_config_very_long_and_random' # Wichtig!
PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7 # 7 Tage

# Verzeichnisse und Dateien
SERVER_CONFIG_FILE = os.path.join(BASE_DIR, 'servers.json')
SERVER_INSTANCES_DIR = os.path.join(BASE_DIR, 'servers')
SERVER_JARS_DIR = os.path.join(BASE_DIR, 'server_jars')

# Standard-Benutzer (MUSS in instance/config.py überschrieben/ergänzt werden)
USERNAME = "admin_default" # Dieser Wert sollte nie verwendet werden
PASSWORD_HASH = "hash_me_in_instance_config" # Dieser Wert sollte nie verwendet werden

# Sicherstellen, dass die Verzeichnisse existieren (kann auch in create_app erfolgen)
os.makedirs(SERVER_INSTANCES_DIR, exist_ok=True)
os.makedirs(SERVER_JARS_DIR, exist_ok=True)