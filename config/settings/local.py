"""Local development settings. DJANGO_SETTINGS_MODULE=config.settings.local"""

import os

from .base import *  # noqa: F401,F403

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key")

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Defaults to Vite's default dev port - see design.md (add-react-frontend).
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DJANGO_CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
