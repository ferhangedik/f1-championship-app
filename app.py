# app.py — Flask application factory.
#create_app() builds the application, connects the database and registers all blueprints (page groups). 
#Run: python app.py ---- # starts on http://127.0.0.1:8080

import os
from datetime import date

from flask import Flask, render_template
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
    from routes.races import bp as races_bp
    from routes.compare import bp as compare_bp
    from routes.analytics import bp as analytics_bp
    from routes.calendar import bp as calendar_bp
    from routes.home import bp as home_bp
    from routes.auth import bp as auth_bp
    app.register_blueprint(standings_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(races_bp)
    app.register_blueprint(compare_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)


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

    # Error pages (400 / 404 / 500)
    @app.errorhandler(400)
    def bad_request(e):
        return render_template("errors/400.html"), 400

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("FLASK_PORT", "8080"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    # host=127.0.0.1, port=8080
    app.run(host="127.0.0.1", port=port, debug=debug)