import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("SOURCEWISE_DATA", "./data")).resolve()
MAX_TEXT = 200_000
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_MEDIA_BYTES = 100 * 1024 * 1024
MAX_VIDEO_SECONDS = 2 * 60 * 60
WORKERS = max(1, min(4, int(os.getenv("INGEST_WORKERS", "2"))))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in {"1", "true"}
TRUSTED_FETCH_PROXY = os.getenv("TRUSTED_FETCH_PROXY", "")
