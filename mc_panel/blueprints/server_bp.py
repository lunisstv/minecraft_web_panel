# mc_panel/blueprints/server_bp.py
from flask import Blueprint, request, redirect, url_for, flash, render_template, current_app, jsonify
from mc_panel import server_manager, jar_manager, login_required # Globale Instanzen und Decorator

server_bp = Blueprint('server', __name__) # url_prefix='/server' wird in __init__.py gesetzt

@server_bp.route('/start/<server_name>', methods=['POST'])
@login_required
def start_server_route(server_name):
    success, message = server_manager.start_server(server_name)
    if success:
        flash(message, "success")
    else:
        flash(message, "error")
    return redirect(url_for('main.index'))

@server_bp.route('/stop/<server_name>', methods=['POST'])
@login_required
def stop_server_route(server_name):
    success, message = server_manager.stop_server(server_name)
    if success:
        flash(message, "success")
    else:
        flash(message, "warning") # Kann auch ein Fehler sein, je nach msg
    return redirect(url_for('main.index'))

@server_bp.route('/delete/<server_name>', methods=['POST'])
@login_required
def delete_server_route(server_name):
    success, message = server_manager.delete_server(server_name)
    if success:
        flash(message, "success")
    else:
        flash(message, "error")
    return redirect(url_for('main.index'))

@server_bp.route('/send_command/<server_name>', methods=['POST'])
@login_required
def send_command_route(server_name):
    command_text = request.form.get('command')
    success, message = server_manager.send_command(server_name, command_text)
    if success:
        return jsonify({'status': 'success', 'message': message})
    else:
        return jsonify({'status': 'error', 'message': message}), 400 # HTTP 400 für Client-Fehler


@server_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_server_route():
    available_jars = jar_manager.list_jars()
    form_data_on_error = {} # Für den Fall, dass das Formular mit Fehlern erneut angezeigt wird

    if request.method == 'POST':
        form_data_on_error = request.form # Alte Daten für erneute Anzeige speichern

        server_data = {
            'server_name': request.form.get('server_name', '').strip(),
            'port': request.form.get('port', '').strip(),
            'ram_min': request.form.get('ram_min', '').strip().upper(), # Konsistente Großschreibung
            'ram_max': request.form.get('ram_max', '').strip().upper(),
            'eula_accepted_in_panel': 'eula' in request.form
        }
        selected_jar = request.form.get('selected_jar')

        # --- Validierungen direkt in der Route für schnelles Feedback ---
        error_occured = False
        if not all([server_data['server_name'], server_data['port'], server_data['ram_min'], server_data['ram_max'], selected_jar]):
            flash("Alle Felder müssen ausgefüllt sein.", "error")
            error_occured = True
        
        # Servername Validierung
        if not error_occured and (not server_data['server_name'] or not all(c.isalnum() or c in ['_', '-'] for c in server_data['server_name'])):
            flash("Servername darf nur Buchstaben, Zahlen, '_' und '-' enthalten und nicht leer sein.", "error")
            error_occured = True

        # RAM Validierung (einfach)
        if not error_occured and not (
            server_data['ram_min'][:-1].isdigit() and server_data['ram_min'][-1] in ['M', 'G'] and
            server_data['ram_max'][:-1].isdigit() and server_data['ram_max'][-1] in ['M', 'G']
        ):
            flash("RAM Angaben müssen eine Zahl gefolgt von M oder G sein (z.B. 512M, 2G).", "error")
            error_occured = True
        
        # Port Validierung
        if not error_occured:
            try:
                port_num = int(server_data['port'])
                if not (1024 <= port_num <= 65535):
                    flash("Port muss eine Zahl zwischen 1024 und 65535 sein.", "error")
                    error_occured = True
            except ValueError:
                flash("Port muss eine gültige Zahl sein.", "error")
                error_occured = True

        if not error_occured and selected_jar not in available_jars:
            flash("Ausgewählte JAR-Datei ist nicht (mehr) verfügbar. Bitte Seite neu laden.", "error")
            error_occured = True
        
        if error_occured:
            return render_template('create_server.html', available_jars=available_jars, form_data=form_data_on_error)
        # --- Ende Validierungen in Route ---


        success, message = server_manager.create_server(server_data, selected_jar)
        
        if success:
            flash(message, "success")
            return redirect(url_for('main.index'))
        else:
            flash(message, "error")
            # Formular erneut mit den alten Daten anzeigen
            return render_template('create_server.html', available_jars=available_jars, form_data=form_data_on_error)

    # Für GET Request oder wenn keine POST-Daten (Initialaufruf)
    return render_template('create_server.html', available_jars=available_jars, form_data={})