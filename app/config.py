import os
from dotenv import load_dotenv
load_dotenv(override=True)
def _i(k, d):
    try: return int(os.getenv(k) or d)
    except ValueError: raise SystemExit(f"{k} must be an integer")
API_ID = _i("TG_API_ID", 0); API_HASH = os.getenv("TG_API_HASH", "")
HOST = os.getenv("HOST", "127.0.0.1"); PORT = _i("PORT", 8000)
OLLAMA_URL = os.getenv("OLLAMA_URL", "https://ollama.com"); OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b-cloud")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip().strip("\"'").strip()  # never sent to the browser
HISTORY_LIMIT = _i("HISTORY_LIMIT", 20)
DATA_FILE = os.getenv("DATA_FILE", "data/store.json"); LOG_FILE = os.getenv("LOG_FILE", "data/log.json"); SESSIONS_DIR = os.getenv("SESSIONS_DIR", "sessions")