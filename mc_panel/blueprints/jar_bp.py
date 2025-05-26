# mc_panel/blueprints/jar_bp.py
from flask import Blueprint, request, redirect, url_for, flash, render_template, current_app
from mc_panel import jar_manager, login_required # Globale Instanz und Decorator

jar_bp = Blueprint('jar', __name__) # url_prefix='/jar' wird in __init__.py gesetzt

@jar_bp.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_jars_route():
    # Initialisiere available_jars mit einem Standardwert (leere Liste)
    available_jars = []

    if request.method == 'POST': # Dieser Block ist für den Upload
        if 'jar_file' not in request.files:
            flash('Keine Datei ausgewählt', 'error')
        else:
            file = request.files['jar_file']
            success, message = jar_manager.save_jar(file) # jar_manager.save_jar sichert den Dateinamen
            if success:
                flash(f'JAR-Datei "{message}" erfolgreich hochgeladen.', 'success')
            else:
                flash(message, 'error')
        return redirect(url_for('jar.manage_jars_route')) # Redirect nach POST zum erneuten Laden der Seite
            
    # Dieser Teil wird nur bei GET-Requests erreicht
    try:
        available_jars = jar_manager.list_jars()
    except Exception as e:
        current_app.logger.error(f"Fehler beim Auflisten der JARs in manage_jars_route: {e}")
        flash("Ein Fehler ist beim Laden der JAR-Dateien aufgetreten.", "error")
        # available_jars bleibt die initialisierte leere Liste im Fehlerfall
        
    return render_template('upload_jar.html', available_jars=available_jars)

@jar_bp.route('/delete/<path:jar_name>', methods=['POST']) # <path:jar_name> um Dateinamen mit Punkten zu erlauben
@login_required
def delete_jar_route(jar_name):
    # jar_name kommt hier direkt aus der URL. Der JarManager sollte ihn validieren/sichern.
    success, message = jar_manager.delete_jar(jar_name)
    if success:
        flash(message, "success")
    else:
        flash(message, "error") # oder "warning"
    return redirect(url_for('jar.manage_jars_route'))