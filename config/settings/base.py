"""
Base Django settings shared by every environment.

Split into base/local/production per project convention (see
openspec/config.yaml). Never import this module directly - import
config.settings.local or config.settings.production instead.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    # Project apps, one per bounded context (see openspec/config.yaml).
    "core",
    "contracts",
    "pipeline",
    "razorpay_integration",
    "risk_scoring",
    "reporting",
    "evaluation",
    "report_ui",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database - SQLite only, deliberately. See design.md (add-django-foundation)
# for the rationale: zero-infrastructure setup for the buildathon demo.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# Django REST Framework - installed now (phase 1 exposes no endpoints yet),
# configured now so phase 3 doesn't need a settings change.

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}


# Project-specific settings, read once here so every app imports from
# django.conf.settings rather than reading os.environ directly.

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6")

# Stored but unused - no webhook endpoint exists in this codebase yet. See
# openspec/changes/switch-llm-provider-to-openai/proposal.md.
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

# Pipeline stage 2 (classification) confidence gates - see
# pipeline/clause-classification spec.
CLASSIFICATION_MIN_CONFIDENCE = float(os.environ.get("CLASSIFICATION_MIN_CONFIDENCE", "0.60"))
CLASSIFICATION_MIN_MARGIN = float(os.environ.get("CLASSIFICATION_MIN_MARGIN", "0.10"))

# Pipeline stage 3 (extraction) confidence gate - see
# pipeline/term-extraction spec.
EXTRACTION_MIN_CONFIDENCE = float(os.environ.get("EXTRACTION_MIN_CONFIDENCE", "0.65"))

# RazorpayX test-mode credentials (read-scope) - used from phase 2 onward by
# razorpay_integration.client.RazorpayConnector. See
# openspec/changes/add-razorpay-crosscheck/design.md.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

# Pipeline stage 4 (razorpay cross-check) tolerance configuration - see
# specs/razorpay-integration/payout-history-crosscheck/spec.md. Expressed as
# fractions of the contract-stated interval/amount (e.g. 0.2 = 20%).
CADENCE_MISMATCH_TOLERANCE_RATIO = float(
    os.environ.get("CADENCE_MISMATCH_TOLERANCE_RATIO", "0.2")
)
AMOUNT_MISMATCH_TOLERANCE_PCT = float(os.environ.get("AMOUNT_MISMATCH_TOLERANCE_PCT", "0.05"))

# Gates the pipeline.services.run_pipeline stage-4 call into
# razorpay_integration.services.detect_mismatches, so the app can be disabled
# without a code rollback. See design.md - Migration Plan.
ENABLE_STAGE_4 = os.environ.get("ENABLE_STAGE_4", "True").strip().lower() not in (
    "false",
    "0",
    "",
)

# CORS - lets the separate frontend project (a different origin/port) call
# this backend's JSON API in local development. See design.md
# (add-react-frontend) - "CORS_ALLOWED_ORIGINS read from a new
# DJANGO_CORS_ALLOWED_ORIGINS env var (comma-separated)". base.py provides
# no default origins - matches this file's existing ALLOWED_HOSTS pattern,
# where the environment-specific default (or lack of one) lives in
# local.py/production.py, not here.
CORS_ALLOWED_ORIGINS = [
    origin for origin in os.environ.get("DJANGO_CORS_ALLOWED_ORIGINS", "").split(",") if origin
]
