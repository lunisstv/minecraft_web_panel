# mc_panel/__init__.py
from flask import Flask, g, session, redirect, url_for, request, flash, current_app
from functools import wraps
import os

# Globale Manager-Instanzen (werden in create_app initialisiert)
jar_manager = None
server_manager = None

def login_required(f):
    """
    Stellt sicher, dass ein Benutzer angemeldet ist, bevor die Route aufgerufen wird.
    Leitet zur Login-Seite weiter, falls nicht angemeldet.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Bitte melde dich an, um diese Seite zu sehen.", "warning")
            # next=request.url speichert die ursprünglich angeforderte URL
            return redirect(url_for('auth.login', next=request.full_path))
        return f(*args, **kwargs)
    return decorated_function


def create_app():
    """
    Factory-Funktion für die Flask-Anwendung.
    """
    global jar_manager, server_manager

    app = Flask(__name__, instance_relative_config=True)

    # Lade Standardkonfiguration aus config.py im Hauptverzeichnis
    app.config.from_object('config')

    # Lade Instanzkonfiguration (überschreibt ggf. Standardwerte)
    # Diese Datei ist optional und wird nicht versioniert (sensible Daten)
    # Sie muss im 'instance' Ordner liegen.
    if os.path.exists(os.path.join(app.instance_path, 'config.py')):
        app.config.from_pyfile('config.py', silent=False) # False, um Fehler beim Laden anzuzeigen
    else:
        print("WARNUNG: instance/config.py nicht gefunden. Standardkonfiguration wird verwendet.")
        print("Bitte erstelle instance/config.py mit SECRET_KEY, USERNAME und PASSWORD_HASH.")


    # Stelle sicher, dass die notwendigen Verzeichnisse existieren
    os.makedirs(app.config['SERVER_INSTANCES_DIR'], exist_ok=True)
    os.makedirs(app.config['SERVER_JARS_DIR'], exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static'), exist_ok=True) # Für static Ordner

    # Importiere Manager erst hier, NACHDEM die Konfiguration geladen wurde,
    # da sie Pfade aus app.config verwenden könnten.
    from .managers.jar_manager import JarManager
    from .managers.server_manager import ServerManager

    # Initialisiere die Manager mit Pfaden aus der App-Konfiguration
    # Diese Instanzen werden dann von den Blueprints importiert
    jar_manager_instance = JarManager(app.config['SERVER_JARS_DIR'])
    server_manager_instance = ServerManager(
        config_file=app.config['SERVER_CONFIG_FILE'],
        instances_dir=app.config['SERVER_INSTANCES_DIR'],
        jars_dir=app.config['SERVER_JARS_DIR']
    )

    # Die globalen Variablen im Modul setzen
    globals()['jar_manager'] = jar_manager_instance
    globals()['server_manager'] = server_manager_instance

    # Blueprints registrieren
    from .blueprints.main_bp import main_bp
    from .blueprints.server_bp import server_bp
    from .blueprints.jar_bp import jar_bp
    from .blueprints.auth_bp import auth_bp

    app.register_blueprint(main_bp) # url_prefix standardmäßig '/'
    app.register_blueprint(server_bp, url_prefix='/server')
    app.register_blueprint(jar_bp, url_prefix='/jar')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    # Kontextprozessor, um panel_config (app.config) an alle Templates zu übergeben
    @app.context_processor
    def inject_panel_config():
        return dict(panel_config=current_app.config) # current_app.config ist sicherer hier

    return app