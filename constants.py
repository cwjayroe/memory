"""Request/argument contracts for MCP tools and ingest commands."""
import os


DEFAULT_PROJECT_ID = os.environ.get("PROJECT_ID", "project-memory-default")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
MEMORY_ROOT = os.path.expanduser(os.environ.get("PROJECT_MEMORY_ROOT", "~/.project-memory"))
GET_ALL_LIMIT = int(os.environ.get("PROJECT_MEMORY_GET_ALL_LIMIT", "10000"))
DEFAULT_EXCERPT_CHARS = 420
MIN_EXCERPT_CHARS = 120
MAX_EXCERPT_CHARS = 4000
DEFAULT_RESPONSE_FORMAT = "text"
ALLOWED_RESPONSE_FORMATS = frozenset({"text", "json"})
