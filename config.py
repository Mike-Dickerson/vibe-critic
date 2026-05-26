import os
from pathlib import Path

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

PRECEPTS_PATH = Path(__file__).parent / "precepts.json"


INCLUDE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb",
    ".cs", ".cpp", ".c", ".h", ".php", ".swift", ".kt", ".rs",
    ".sh", ".bash",
}

EXCLUDE_DIRS = {
    # Package managers / build output
    "node_modules", "dist", "build", ".next", ".nuxt", "target", "vendor",
    # Python tooling
    "__pycache__", ".venv", "venv", "env", ".tox", "eggs", ".eggs",
    "site-packages", "dist-packages",
    # Caches
    ".git", ".cache", "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    # Vendored dependency dumps (pip packages copied wholesale into project)
    "lambda_grpc_fix",
}

MAX_FILE_SIZE_BYTES = 50_000
MAX_CONTENT_CHARS = 3_000
MAX_SAMPLE_FILES = 10

# Gemini free tier: 5 RPM — enforce minimum gap between requests
GEMINI_MIN_INTERVAL_SECS = 13  # 60s / 5 RPM + small buffer
