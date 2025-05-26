# run.py
from mc_panel import create_app

app = create_app()

if __name__ == '__main__':
    # Host und Port werden aus der config geladen (app.config['HOST'], app.config['PORT'])
    # Debug wird ebenfalls aus der config geladen (app.config['DEBUG'])
    app.run(host=app.config.get('HOST', '0.0.0.0'),
            port=app.config.get('PORT', 5000),
            debug=app.config.get('DEBUG', True))