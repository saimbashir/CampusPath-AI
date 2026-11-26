# Release 0.6.0 — free hosted deployment and stronger material reading

## Deployment fixes
- **HTTPS proxy support.** Uvicorn starts with `--proxy-headers --forwarded-allow-ips='*'` and the
  origin checks (HTTP and voice WebSocket) accept the site's own host behind a hosting proxy.
  Previously every login/upload on Render-style hosts was rejected as cross-origin, and all
  visitors shared one rate-limit bucket (the proxy's IP).
- **PostgreSQL ready.** `psycopg[binary]` is included; `postgres://` / `postgresql://` URLs from
  Neon/Render/Supabase are converted automatically; connections use `pool_pre_ping` so a
  sleeping Neon database reconnects cleanly.
- **Docker** listens on the host's `$PORT`, includes free OCR tools (Tesseract, Poppler).
- **`render.yaml`** blueprint and **`DEPLOY_FREE.md`** step-by-step guide.
- **First accounts without a shell:** `ADMIN_EMAIL/ADMIN_PASSWORD` and optional
  `TEACHER_EMAIL/TEACHER_PASSWORD/TEACHER_NAME` create accounts once at startup.

## Reading teacher material
- Excerpts are split on paragraph and sentence boundaries (never mid-word); when a long
  paragraph is divided, one sentence overlaps so ideas crossing the boundary stay readable.
- Chapter detection now understands, for any subject: `Chapter/Unit/Section N`, `Lesson`,
  `Module`, `Lecture`, `Week`, `Part`, `Topic N`, numbered headings such as `4.2 Binary Trees`
  (table-of-contents lines are ignored), Word *Heading 1/2* styles and PDF bookmarks.
- Scanned PDF pages without a text layer are read with Tesseract OCR (labelled
  "OCR, verify"). Password-protected PDFs give a clear message.
- PowerPoint tables and speaker notes are indexed too.
- Files larger than `BACKGROUND_UPLOAD_MIB` (default 1.5 MiB) are indexed in a background
  thread; the Materials page shows *processing / failed* status, and unfinished jobs resume
  after a restart. Migration `0004_resource_status` adds the status columns.

## AI question generation
- Generation sends small groups of excerpts (`LLM_EXCERPTS_PER_CALL`, default 12) and asks for
  a few questions per call (`LLM_QUESTIONS_PER_CALL`, default 6), visiting the material in a
  spread-out order so a viva covers the whole book, not only the first pages.
- One invalid question no longer discards the whole batch: valid questions are kept and the
  app asks again until the requested count is reached (or explains how many passed).
- Quotation checks tolerate small wording drift (quote marks, spacing, a changed word) and
  store the teacher's exact source wording; invented quotations are still rejected.
- Support verification checks all questions of a round in one call (falls back to one call
  per question when a provider cannot follow the batch format).
- Requests retry with backoff on 429/5xx/timeouts, honour `Retry-After`, strip ```json fences,
  retry once with the validation error when JSON does not match the schema, and work with
  providers that do not support `response_format`.
- Curriculum extraction reads all uploaded material (up to 300 excerpts) in groups instead of
  only the first 30 excerpts; unknown prerequisite names are dropped instead of failing.
- Single-question generation sends the excerpts most related to the topic.

## Verification in this build
Python files compile, JavaScript passes `node --check`. Text/PDF/PPTX extraction, heading
detection, sentence chunking, scanned-PDF OCR, quote repair, generation rounds, Bloom quotas,
retry/JSON handling and fallback verification were exercised with controlled fake providers.
The full pytest suite and a real Render/Neon/Gemini deployment could not be run in the build
environment (packages could not be installed there). Run `python -m pytest -q` locally before
presenting.
