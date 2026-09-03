"""Production settings. DJANGO_SETTINGS_MODULE=config.settings.production"""

import os

from .base import *  # noqa: F401,F403

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # required, no insecure fallback

DEBUG = False

ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

# No default origins - the env var must be set explicitly to allow any
# cross-origin frontend, mirroring the ALLOWED_HOSTS pattern above. See
# design.md (add-react-frontend).
CORS_ALLOWED_ORIGINS = [
    origin for origin in os.environ.get("DJANGO_CORS_ALLOWED_ORIGINS", "").split(",") if origin
]
