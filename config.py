"""Central configuration for KisanVaani.

Loads environment variables from .env and exposes typed config values.
All secrets and environment-specific settings must be read through this module.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (kisanvaani/)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_env(name: str, default: str = "") -> str:
    """Return an environment variable value with an optional default."""
    return os.getenv(name, default).strip()


# --- Flask ---
FLASK_ENV = _get_env("FLASK_ENV", "development")
FLASK_DEBUG = _get_env("FLASK_DEBUG", "0") == "1"
FLASK_HOST = _get_env("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(_get_env("FLASK_PORT", "5000"))
APP_BASE_URL = _get_env("APP_BASE_URL", "http://localhost:5000")

# --- WhatsApp Cloud API ---
WHATSAPP_VERIFY_TOKEN = _get_env("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_ACCESS_TOKEN = _get_env("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _get_env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_API_VERSION = _get_env("WHATSAPP_API_VERSION", "v20.0")
WHATSAPP_API_BASE_URL = _get_env("WHATSAPP_API_BASE_URL", "https://graph.facebook.com")

# --- Speech-to-text ---
OPENAI_API_KEY = _get_env("OPENAI_API_KEY")
STT_PROVIDER = _get_env("STT_PROVIDER", "openai")
GOOGLE_APPLICATION_CREDENTIALS = _get_env("GOOGLE_APPLICATION_CREDENTIALS")

# --- Database ---
DATABASE_URL = _get_env("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'db' / 'kisanvaani.db').as_posix()}")

# --- Dashboard ---
DASHBOARD_PASSWORD = _get_env("DASHBOARD_PASSWORD", "change-me")

# --- Storage ---
def _resolve_path(value: str, default: str) -> Path:
    """Resolve storage path from env; absolute paths are used as-is."""
    raw = Path((value or default).strip())
    return raw if raw.is_absolute() else (BASE_DIR / raw)


MEDIA_DIR = _resolve_path(_get_env("MEDIA_DIR", "media"), "media")
PDF_DIR = _resolve_path(_get_env("PDF_DIR", "generated_pdfs"), "generated_pdfs")
