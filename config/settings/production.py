"""Production settings. DJANGO_SETTINGS_MODULE=config.settings.production"""

import os

import dj_database_url

from .base import *  # noqa: F401,F403

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # required, no insecure fallback

DEBUG = False

ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

# Railway's Postgres plugin injects DATABASE_URL automatically once attached
# to this service - required, no sqlite fallback, so a misconfigured deploy
# fails loudly at boot rather than silently writing to a throwaway local
# file. Overrides base.py's sqlite DATABASES entirely (not merged).
DATABASES = {
    "default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=600)
}

# No default origins - the env var must be set explicitly to allow any
# cross-origin frontend, mirroring the ALLOWED_HOSTS pattern above. See
# design.md (add-react-frontend).
CORS_ALLOWED_ORIGINS = [
    origin for origin in os.environ.get("DJANGO_CORS_ALLOWED_ORIGINS", "").split(",") if origin
]

# Manifest-hashed, pre-compressed static files, served by WhiteNoiseMiddleware
# straight from the app process - no separate static host needed on Railway.
# Requires collectstatic to have already run (see Procfile's release phase);
# kept out of base.py because it raises on any file missing from the
# manifest, which breaks template-rendering tests that never run
# collectstatic first.
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
