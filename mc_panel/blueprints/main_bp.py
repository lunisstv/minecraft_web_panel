# mc_panel/blueprints/main_bp.py
from flask import Blueprint, render_template, jsonify, redirect, url_for, flash, current_app
from mc_panel import server_manager, login_required # Importiere globale Instanz und Decorator

main_bp = Blueprint('main', __name__) # url_prefix ist standardmäßig '/'

@main_bp.route('/')
@login_required # Schütze diese Route
def index():
    # server_manager ist global in mc_panel/__init__.py verfügbar
    servers = server_manager.get_all_servers_with_resources()
    return render_template('index.html', servers=servers)

@main_bp.route('/server_console/<server_name>')
@login_required
def server_console(server_name):
    # server_name könnte manipuliert sein, get_server_details sollte damit umgehen können
    # oder hier validieren. ServerManager.get_server_details holt den aktuellen Status.
    server_info = server_manager.get_server_details(server_name)
    if not server_info:
        flash(f"Server '{server_name}' nicht gefunden oder Zugriff verweigert.", "error")
        return redirect(url_for('main.index'))
    return render_template('console.html', server_name=server_name, server_info=server_info)

@main_bp.route('/get_console_output/<server_name>')
@login_required
def get_console_output(server_name):
    # Auch hier: server_name validieren oder sicherstellen, dass Manager es tut.
    output = server_manager.get_console_output_with_resources(server_name)
    return jsonify(output)

# Eine einfache Route, um zu sehen, ob die App läuft (optional, ohne Login)
@main_bp.route('/health')
def health_check():
    return jsonify(status="ok", message="Panel is running"), 200