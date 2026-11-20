"""Settings loaded from environment variables (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = _get("CLAUDE_EFFORT", "medium")

WHATSAPP_TOKEN = _get("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = _get("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = _get("WHATSAPP_APP_SECRET")
WHATSAPP_API_VERSION = _get("WHATSAPP_API_VERSION", "v21.0")

OWNER_WHATSAPP_NUMBER = _get("OWNER_WHATSAPP_NUMBER")
NOTIFY_WEBHOOK_URL = _get("NOTIFY_WEBHOOK_URL")

ERP_BACKEND = _get("ERP_BACKEND", "mock")
EGANIS_BASE_URL = _get("EGANIS_BASE_URL")
EGANIS_API_KEY = _get("EGANIS_API_KEY")

DB_PATH = ROOT / _get("DB_PATH", "data/bot.db")
TEST_PAGE_PASSWORD = _get("TEST_PAGE_PASSWORD", "change-me")

KNOWLEDGE_DIR = ROOT / "knowledge"
