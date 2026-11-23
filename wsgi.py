"""
wsgi.py — Production WSGI entry point.

Run with Gunicorn (Linux VPS):
    gunicorn --bind 127.0.0.1:8080 wsgi:app

This module provides the `app` object that the production server imports.
"""

from app import create_app

app = create_app()