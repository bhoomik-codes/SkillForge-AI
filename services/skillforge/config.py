
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = os.getenv("APP_ENV") == "production"
ORIGIN = (os.getenv("APP_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL") or "http://localhost:5173").rstrip("/")
NEO4J_URI = os.getenv("NEO4J_URI") or "bolt://127.0.0.1:7687"
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME") or "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE") or "neo4j"
if PRODUCTION and not ORIGIN.startswith("https://"):
    raise RuntimeError("Production requires an HTTPS APP_ORIGIN or RENDER_EXTERNAL_URL.")
if PRODUCTION and (not NEO4J_URI.startswith(("neo4j+s://", "bolt+s://")) or not NEO4J_PASSWORD):
    raise RuntimeError("Production requires a TLS Neo4j URI and NEO4J_PASSWORD.")
GITHUB_TOKEN = os.getenv("GITHUB_API_TOKEN", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_CALLBACK = os.getenv("GITHUB_OAUTH_CALLBACK_URL", ORIGIN + "/api/auth/github/callback")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
JUDGE_URL = os.getenv("JUDGE_URL", "").rstrip("/")
JUDGE_TOKEN = os.getenv("JUDGE_TOKEN", "")
HISTORY_PAGE_LIMIT = int(os.getenv("HISTORY_PAGE_LIMIT", "20"))
if not 1 <= HISTORY_PAGE_LIMIT <= 50:
    raise RuntimeError("HISTORY_PAGE_LIMIT must be between 1 and 50.")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
COOKIE = "__Host-skillforge" if PRODUCTION else "skillforge"
