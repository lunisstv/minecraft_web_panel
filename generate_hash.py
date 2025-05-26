# generate_hash.py
import getpass
from werkzeug.security import generate_password_hash

def create_password_hash():
    """Fragt nach einem Passwort und gibt den Hash dafür aus."""
    password = getpass.getpass("Bitte gib das Passwort für den Admin-User ein: ")
    password_confirm = getpass.getpass("Bitte bestätige das Passwort: ")

    if password != password_confirm:
        print("Die Passwörter stimmen nicht überein.")
        return

    if not password:
        print("Passwort darf nicht leer sein.")
        return

    # Methode mit Salt, die Flask-Login und Werkzeug oft verwenden (pbkdf2:sha256 ist default)
    # generate_password_hash verwendet standardmäßig eine sichere Methode.
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)
    
    print("\n--- WICHTIG! ---")
    print("Bitte erstelle (falls nicht vorhanden) oder öffne die Datei 'instance/config.py'")
    print("und füge folgende Zeilen hinzu oder aktualisiere sie:")
    print("-------------------------------------------------------------")
    print(f"SECRET_KEY = 'DEIN_GANZ_LANGER_UND_ZUFÄLLIGER_SECRET_KEY_HIER_EINFÜGEN'")
    print(f"USERNAME = \"root\"  # Oder ein anderer Benutzername")
    print(f"PASSWORD_HASH = \"{hashed_password}\"")
    print("-------------------------------------------------------------")
    print("Stelle sicher, dass das Verzeichnis 'instance' existiert und die Datei 'config.py' darin liegt.")
    print("Die Datei 'instance/config.py' sollte NICHT versioniert werden (füge 'instance/' zu .gitignore hinzu).")

if __name__ == "__main__":
    create_password_hash()