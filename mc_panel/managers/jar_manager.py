# mc_panel/managers/jar_manager.py
import os
import shutil
from werkzeug.utils import secure_filename # Für sichere Dateinamen

class JarManager:
    def __init__(self, jars_dir):
        self.jars_dir = jars_dir
        os.makedirs(self.jars_dir, exist_ok=True)

    def list_jars(self):
        """Gibt eine Liste der verfügbaren JAR-Dateien zurück."""
        try:
            return [f for f in os.listdir(self.jars_dir) if f.endswith('.jar') and os.path.isfile(os.path.join(self.jars_dir, f))]
        except OSError:
            return []

    def get_jar_path(self, jar_name):
        """Gibt den vollständigen Pfad zu einer JAR-Datei zurück, prüft auf Sicherheit."""
        # secure_filename entfernt problematische Zeichen und Pfadanteile
        safe_jar_name = secure_filename(jar_name)
        if not safe_jar_name.endswith('.jar'): # Sicherstellen, dass es immer noch eine .jar ist
            # Dies kann passieren, wenn der ursprüngliche Name sehr problematisch war
            return None
        
        # Verhindere, dass secure_filename einen leeren String zurückgibt, falls der Name nur aus ungültigen Zeichen bestand
        if not safe_jar_name:
            return None

        return os.path.join(self.jars_dir, safe_jar_name)


    def save_jar(self, file_storage):
        """
        Speichert eine hochgeladene JAR-Datei.
        :param file_storage: Das FileStorage-Objekt von Flask (request.files['jar_file'])
        :return: (True, Dateiname) bei Erfolg, (False, Fehlermeldung) bei Misserfolg
        """
        if not file_storage or not file_storage.filename:
            return False, 'Keine Datei ausgewählt.'
        
        # Dateinamen zuerst sichern
        filename = secure_filename(file_storage.filename)
        if not filename.endswith('.jar'): # Überprüfen, ob es nach secure_filename noch eine .jar ist
            return False, 'Ungültiger Dateityp oder Dateiname. Nur .jar Dateien sind erlaubt.'

        filepath = os.path.join(self.jars_dir, filename)
        
        # Zusätzlicher Check, ob der Pfad immer noch im JARS_DIR ist (paranoider Check)
        if os.path.commonprefix((os.path.realpath(filepath), os.path.realpath(self.jars_dir))) != os.path.realpath(self.jars_dir):
            return False, 'Ungültiger Speicherpfad für JAR-Datei.'

        try:
            file_storage.save(filepath)
            return True, filename
        except Exception as e:
            return False, f'Fehler beim Speichern der Datei: {e}'


    def delete_jar(self, jar_name):
        """
        Löscht eine JAR-Datei.
        :param jar_name: Name der zu löschenden JAR-Datei.
        :return: (True, Erfolgsmeldung) bei Erfolg, (False, Fehlermeldung) bei Misserfolg
        """
        # Wichtig: jar_name kann vom User kommen, daher validieren!
        safe_jar_name = secure_filename(jar_name)
        if not safe_jar_name or not safe_jar_name.endswith('.jar'):
            return False, "Ungültiger oder unsicherer JAR-Name."

        jar_path = os.path.join(self.jars_dir, safe_jar_name)
        
        # Paranoider Check, um sicherzustellen, dass wir nicht außerhalb des Jars-Verzeichnisses löschen
        if os.path.commonprefix((os.path.realpath(jar_path), os.path.realpath(self.jars_dir))) != os.path.realpath(self.jars_dir):
            return False, "Versuch, JAR-Datei außerhalb des erlaubten Verzeichnisses zu löschen."


        if os.path.exists(jar_path) and os.path.isfile(jar_path):
            try:
                os.remove(jar_path)
                return True, f"JAR-Datei '{safe_jar_name}' gelöscht."
            except Exception as e:
                return False, f"Fehler beim Löschen der JAR-Datei '{safe_jar_name}': {e}"
        else:
            return False, f"JAR-Datei '{safe_jar_name}' nicht gefunden oder ist kein File."