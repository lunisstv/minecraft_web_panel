# auth.py
from flask import session, flash, redirect, url_for, request, render_template # Blueprint hier entfernt
from werkzeug.security import check_password_hash
from functools import wraps
from config import PANEL_USERS

class User:
    def __init__(self, username, password_hash=None):
        self.username = username
        self.password_hash = password_hash

    @staticmethod
    def get(username):
        password_hash = PANEL_USERS.get(username)
        if password_hash:
            return User(username, password_hash)
        return None

    def check_password(self, password):
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in_user' not in session:
            flash('Bitte zuerst einloggen.', 'warning')
            return redirect(url_for('auth_bp.login_route', next=request.url_root.rstrip('/') + request.full_path))
        return f(*args, **kwargs)
    return decorated_function

# Blueprint für Authentifizierungsrouten
from flask import Blueprint, render_template

auth_bp = Blueprint('auth_bp', __name__, template_folder='templates')

def login_view(): # Umbenannt, um Kollision mit Blueprint-Namen zu vermeiden
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.get(username)
        if user and user.check_password(password):
            session['logged_in_user'] = user.username
            flash('Erfolgreich eingeloggt!', 'success')
            next_url = request.args.get('next')
            # Um den Redirect zu 'main_bp.index' zu ermöglichen, ohne app direkt zu importieren:
            # Wir leiten einfach zu '/' weiter, wenn next_url nicht da ist. Die '/' Route wird von main_bp bedient.
            return redirect(next_url or url_for('main_bp.index')) # Geht davon aus, dass main_bp.index auf '/' liegt
        else:
            flash('Falscher Benutzername oder Passwort.', 'error')
    return render_template('login.html')

@login_required # Der Decorator wird hier direkt angewendet
def logout_view(): # Umbenannt
    session.pop('logged_in_user', None)
    flash('Erfolgreich ausgeloggt.', 'info')
    return redirect(url_for('auth_bp.login_route')) # Dies ist okay