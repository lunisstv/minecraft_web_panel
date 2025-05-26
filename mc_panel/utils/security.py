# mc_panel/utils/security.py
from werkzeug.security import generate_password_hash, check_password_hash

# Diese Datei ist momentan ein Platzhalter für zukünftige,
# wiederverwendbare Sicherheitsfunktionen.

# Beispiel:
# def create_user_password_hash(password):
#     return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

# def verify_user_password(stored_password_hash, provided_password):
#     return check_password_hash(stored_password_hash, provided_password)

# Man könnte auch CSRF-Token-Generierung hier unterbringen,
# falls man nicht Flask-WTF oder Flask-SeaSurf verwendet.