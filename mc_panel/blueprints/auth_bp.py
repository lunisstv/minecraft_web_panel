# mc_panel/blueprints/auth_bp.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from werkzeug.security import check_password_hash, generate_password_hash # Import generate_password_hash für zukünftige User-Erstellung im Panel
from flask import render_template_string # Für die generate_hash_info_page

# Importiere globale Manager-Instanzen aus mc_panel/__init__.py
# from mc_panel import server_manager, jar_manager # Nicht direkt hier benötigt

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: # Bereits eingeloggt
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username_form = request.form.get('username')
        password_form = request.form.get('password')

        # Hole Konfiguration aus der App (gesetzt in instance/config.py)
        cfg_username = current_app.config.get('USERNAME')
        cfg_password_hash = current_app.config.get('PASSWORD_HASH')

        # Überprüfe, ob Konfiguration geladen wurde
        if not cfg_username or not cfg_password_hash or \
           cfg_username == "admin_default" or cfg_password_hash == "hash_me_in_instance_config":
            flash("Authentifizierung ist nicht korrekt konfiguriert. Bitte überprüfe instance/config.py.", "error")
            current_app.logger.error("Authentifizierung fehlgeschlagen: USERNAME oder PASSWORD_HASH nicht (korrekt) in instance/config.py gesetzt.")
            return render_template('login.html') # Fehler beim Laden der Config

        if username_form == cfg_username and check_password_hash(cfg_password_hash, password_form):
            session.clear() # Alte Session löschen
            session['user_id'] = username_form # Einfache Session, speichert nur den Usernamen
            session.permanent = True # Nutzt app.config['PERMANENT_SESSION_LIFETIME']
            
            next_url = request.args.get('next')
            flash('Erfolgreich angemeldet!', 'success')
            
            # Sicherheitscheck für next_url, um Open Redirect zu vermeiden (einfach)
            # Ideal: Überprüfen, ob next_url zur eigenen Domain gehört.
            if next_url and next_url.startswith('/'):
                 return redirect(next_url)
            return redirect(url_for('main.index'))
        else:
            flash('Ungültiger Benutzername oder Passwort.', 'error')
            # Beim Fehlschlag das Login-Formular erneut anzeigen
            return render_template('login.html') 
            
    # Für GET-Request das Login-Formular anzeigen
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Erfolgreich abgemeldet.', 'info')
    return redirect(url_for('auth.login'))

# Diese Route ist nur informativ, die eigentliche Generierung erfolgt über das CLI-Skript.
@auth_bp.route('/generate_hash_info')
def generate_hash_info_page():
    # Man könnte hier prüfen, ob DEBUG an ist, um diese Seite nur im Entwicklungsmodus anzuzeigen.
    # if not current_app.debug:
    #     return redirect(url_for('auth.login'))

    return render_template_string("""
    {% extends "base.html" %}
    {% block title %}Passwort Hash Info{% endblock %}
    {% block content %}
        <h2>Passwort Hash Generierung</h2>
        <p>Um einen neuen Passwort-Hash für den Admin-Benutzer zu generieren, 
           führe das Skript <code>generate_hash.py</code> im Hauptverzeichnis 
           deines Projekts in der Kommandozeile aus:</p>
        <pre>python generate_hash.py</pre>
        <p>Das Skript wird dich nach einem Passwort fragen und den entsprechenden Hash ausgeben.</p>
        <p>Öffne oder erstelle dann die Datei <code>instance/config.py</code> und füge die 
           ausgegebenen Zeilen für <code>SECRET_KEY</code>, <code>USERNAME</code> und <code>PASSWORD_HASH</code> ein 
           oder aktualisiere sie.</p>
        <p><strong>Beispiel für instance/config.py:</strong></p>
        <pre>
SECRET_KEY = 'ein_sehr_langer_zufälliger_string_hier_einfügen'
USERNAME = "admin"
PASSWORD_HASH = "pbkdf2:sha256:260000$salt$hashwert..." 
        </pre>
        <p><a href="{{ url_for('auth.login') }}" class="button">Zurück zum Login</a></p>
    {% endblock %}
    """, panel_config=current_app.config) # panel_config für base.html