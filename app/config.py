import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
ROOT = Path(__file__).resolve().parent.parent


def _database_url():
    """Accept the connection strings that hosts such as Neon/Render/Supabase print.

    They usually start with postgres:// or postgresql:// (no driver). SQLAlchemy needs
    the psycopg (v3) driver named explicitly, so it is added here.
    """
    url = os.getenv('DATABASE_URL', '').strip() or 'sqlite:///' + str(ROOT / 'campuspath.db')
    for prefix in ('postgres://', 'postgresql://'):
        if url.startswith(prefix):
            return 'postgresql+psycopg://' + url[len(prefix):]
    return url


DATABASE_URL = _database_url()
DEMO_MODE = os.getenv('DEMO_MODE', 'true').lower() == 'true'
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
SESSION_HOURS = 8
MAX_UPLOAD = max(1,min(64,int(os.getenv('MAX_UPLOAD_MIB','8')))) * 1024 * 1024
MAX_PDF_PAGES=max(1,min(2000,int(os.getenv('MAX_PDF_PAGES','1200'))))
MAX_EXTRACTED_CHARS=max(10000,min(10_000_000,int(os.getenv('MAX_EXTRACTED_CHARS','5000000'))))
# Files larger than this are indexed in the background so the request does not time out
# on small free hosting plans. Smaller files are indexed immediately.
BACKGROUND_UPLOAD_BYTES=max(0,int(float(os.getenv('BACKGROUND_UPLOAD_MIB','1.5'))*1024*1024))
# OCR pages of scanned PDFs that contain no text (needs tesseract + pdftoppm on the host).
OCR_SCANNED_PDF=os.getenv('OCR_SCANNED_PDF','true').lower()=='true'
MAX_OCR_PAGES=max(0,min(500,int(os.getenv('MAX_OCR_PAGES','60'))))
# AI generation tuning for free-tier providers (small requests, a few retries).
LLM_EXCERPTS_PER_CALL=max(3,min(40,int(os.getenv('LLM_EXCERPTS_PER_CALL','12'))))
LLM_QUESTIONS_PER_CALL=max(1,min(15,int(os.getenv('LLM_QUESTIONS_PER_CALL','6'))))
LLM_TIMEOUT_SECONDS=max(10,min(300,int(os.getenv('LLM_TIMEOUT_SECONDS','90'))))
LLM_MAX_RETRIES=max(0,min(6,int(os.getenv('LLM_MAX_RETRIES','3'))))
