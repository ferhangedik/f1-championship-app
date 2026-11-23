"""
serve.py — Entry point for preview / simple deployment (reloader disabled).
For development use `python app.py`; this script runs a single process.
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)