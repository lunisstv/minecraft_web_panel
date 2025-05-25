# config.py
import os

# Flask Konfiguration
SECRET_KEY = os.urandom(32)  # Für Flask-Sessions, sollte geheim und zufällig sein
DEBUG = True # In Produktion auf False setzen!

# Pfade
SERVER_VERSIONS_BASE_PATH = os.environ.get("MC_SERVER_VERSIONS_PATH", "/opt/minecraft_versions")
INSTANCES_BASE_PATH = os.environ.get("MC_INSTANCES_PATH", "/srv/minecraft_servers")

# Standardwerte für Server
DEFAULT_MIN_RAM = "1G"
DEFAULT_MAX_RAM = "2G"
DEFAULT_JAVA_ARGS = (
    "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 "
    "-XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch "
    "-XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M "
    "-XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 "
    "-XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 "
    "-XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem "
    "-XX:MaxTenuringThreshold=1 -Dusing.aikars.flags=https://mcflags.emc.gs -Daikars.new.flags=true"
)
DEFAULT_SERVER_ARGS = "nogui"
DEFAULT_RCON_PORT = 25575
DEFAULT_MINECRAFT_PORT = 25565

# --- BENUTZERKONFIGURATION ---
# In einer realen Anwendung würden diese aus einer Datenbank oder einer sicheren Konfigurationsdatei kommen.
# Für dieses Beispiel: Speichere den Hash des Passworts.
# Um den Hash zu generieren (einmalig ausführen und hier eintragen):
# from werkzeug.security import generate_password_hash
# print(generate_password_hash("DeinSicheresPasswort"))
# Ersetze "DeinSicheresPasswort" mit dem gewünschten Passwort.
# Das Passwort "Potato" wird hier beispielhaft gehasht.
# print(generate_password_hash("Potato")) -> ergibt z.B. 'pbkdf2:sha256:600000$....'
# Trage den generierten Hash hier ein.
PANEL_USERS = {
    "root": "scrypt:32768:8:1$Q6UUZ17DfnIByHG9$50c59858def43718b73f10bb8e8d0927bf71f833051fe70898d3c5518af7c33e0393af8fc66f560b20385f5febbd62710a19a0d1d96cb9b4333f48d9083741b3" # Beispiel-Hash für "Potato"
    # Füge weitere Benutzer hinzu: "benutzername": "gehash_tes_passwort"
}

# Logging
LOG_LEVEL = "DEBUG" if DEBUG else "INFO"