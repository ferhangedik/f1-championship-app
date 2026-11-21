# app.py — Flask application factory.
#create_app() builds the application, connects the database and registers all blueprints (page groups). 
#Run: python app.py ---- # starts on http://127.0.0.1:8080

import os
from datetime import date

from flask import Flask
from dotenv import load_dotenv

import db
from helpers import current_user, is_admin, csrf_token, check_csrf


def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    app.config["SESSION_COOKIE_NAME"] = "hfg_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Bind the database teardown hook
    db.init_app(app)

    # Register blueprints
    from routes.standings import bp as standings_bp
    from routes.drivers import bp as drivers_bp
    app.register_blueprint(standings_bp)
    app.register_blueprint(drivers_bp)



    # Every POST request must carry the session's anti-CSRF token
    app.before_request(check_csrf)

    # Global variables injected into every template
    @app.context_processor
    def inject_globals():
        return {
            "current_user": current_user(),
            "is_admin": is_admin(),
            "current_year": date.today().year,
            "csrf_token": csrf_token,
        }

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("FLASK_PORT", "8080"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    # host=127.0.0.1, port=8080
    app.run(host="127.0.0.1", port=port, debug=debug)