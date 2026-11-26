# Deploy CampusPath AI for free (Render + Neon + Gemini)

This guide puts CampusPath AI online at a public `https://….onrender.com` address without
paying anything. It takes about 30–45 minutes the first time.

You need three free accounts:

| What | Service | Why |
|---|---|---|
| Code storage | GitHub (github.com) | Render deploys your code from GitHub |
| Database | Neon (neon.tech) | Keeps users, courses, uploads and marks permanently |
| AI | Google AI Studio (aistudio.google.com) | Reads the teacher's material and writes questions |
| Hosting | Render (render.com) | Runs the Python/FastAPI app |

> **Important:** never upload your `.env` file or any key to GitHub. Keys go only into
> Render's *Environment* settings.

---

## Step 1 — Put the code on GitHub

1. Create a new **private** repository on GitHub, for example `campuspath-ai`.
2. Upload the contents of the `CampusPath-AI` folder (the folder that contains `Dockerfile`,
   `app/`, `requirements.lock.txt`). Do **not** upload `.env`, `.venv/`, `campuspath.db` or `backups/`
   (the `.gitignore` file already excludes them if you use Git).

## Step 2 — Create the free database (Neon)

1. Sign up at neon.tech and create a project (pick the region closest to your users).
2. Open **Connect** / **Connection string** and copy the string. It looks like
   `postgresql://user:password@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`
3. Keep it private. You will paste it into Render in Step 4.
   (The app adds the PostgreSQL driver automatically — paste it exactly as shown.)

## Step 3 — Get a free AI key (Gemini)

1. Go to aistudio.google.com → **Get API key** → **Create API key**. Copy it.
2. In AI Studio, note the name of a current **Flash** model (for example the model id shown in
   the model picker). You will use it as `LLM_MODEL`.

Free AI plans limit requests per minute. CampusPath already sends small requests and retries
automatically when the limit is reached, so a 30-question viva can take a minute or two.

*Alternative:* Groq (console.groq.com) also has a free OpenAI-compatible API:
`LLM_BASE_URL=https://api.groq.com/openai/v1`. Its token limits are smaller, so keep
`LLM_EXCERPTS_PER_CALL=6` with Groq.

## Step 4 — Deploy on Render

1. Sign up at render.com with your GitHub account.
2. **New → Web Service** → choose your repository.
3. Render detects the `Dockerfile`. Choose **Instance type: Free**.
4. Open **Environment** and add these variables:

| Key | Value |
|---|---|
| `DATABASE_URL` | your Neon connection string (Step 2) |
| `DEMO_MODE` | `false` |
| `COOKIE_SECURE` | `true` |
| `LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `LLM_API_KEY` | your Gemini key (Step 3) |
| `LLM_MODEL` | your Gemini Flash model id |
| `MAX_UPLOAD_MIB` | `16` |
| `ADMIN_EMAIL` | your email |
| `ADMIN_PASSWORD` | a strong password, at least 12 characters |
| `TEACHER_EMAIL` | (optional) the teacher's email |
| `TEACHER_PASSWORD` | (optional) at least 12 characters |
| `TEACHER_NAME` | (optional) e.g. `Dr. Ayesha Khan` |

5. Set **Health Check Path** to `/api/health`.
6. Click **Create Web Service**. The first build takes 5–10 minutes. When the log shows
   `Uvicorn running`, open the `https://….onrender.com` address.

*Shortcut:* the repository contains `render.yaml`. In Render choose **New → Blueprint** and
select the repository; you will only need to fill in the secret values.

## Step 5 — First login and clean-up

1. Log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` (and the teacher with `TEACHER_EMAIL`).
2. Go back to Render → Environment and **delete** `ADMIN_PASSWORD` and `TEACHER_PASSWORD`.
   The accounts stay (passwords are stored hashed in the database); deleting the variables
   just removes the plain-text copy. Render redeploys automatically.
3. Students register themselves on the site and join a course with the teacher's
   enrollment code.

More teachers later: on your own computer, put the Neon `DATABASE_URL` in a local `.env`
and run `python scripts/manage.py invite --admin-email you@example.com` to print a one-time
faculty invite code.

## Step 6 — Check that it works

1. Teacher → create a course → **Materials** → upload a PDF/PowerPoint/Word file.
   Small files are ready at once; big books show *"Reading this document in the background"* —
   refresh after a minute.
2. **Material curriculum** → extract structure → approve.
3. **Create viva** or **Question bank → Generate batch** → review and approve the drafts.
4. Student → join with the enrollment code → practice, tutor, assigned viva.

---

## Free-plan limits to know

- **Render free sleeps** after 15 minutes without visitors; the next visit takes about a
  minute to wake up. Open the site a few minutes before a class demo.
- Render's own disk is wiped on restart — that is why the database is on Neon. Uploaded files
  are stored inside the Neon database, so they survive restarts.
- **Neon free** gives 1 GB per project. Text books are small; very large scanned PDFs use more
  space. Delete unused uploads if you approach the limit.
- **Free RAM is 512 MB.** Prefer uploading a big book chapter by chapter (one file per
  chapter) — it is faster and gives cleaner chapter labels.
- Scanned (image-only) PDF pages are read with free Tesseract OCR, up to 60 pages per file
  (`MAX_OCR_PAGES`). Check OCR text before using it for marks.
- Voice features: browser speech works without a key. Server speech-to-text needs a speech
  provider key (`SPEECH_*`), which is optional.

## If something goes wrong

| Problem | Fix |
|---|---|
| "Cross-origin requests are not allowed" | Make sure you deployed this version (Dockerfile starts uvicorn with `--proxy-headers`). |
| Login works but you are logged out immediately | `COOKIE_SECURE` must be `true` on https. |
| "Configure the language-model provider" | `DEMO_MODE` must be `false` and all three `LLM_*` variables set. |
| Question generation says "Only X of N questions passed" | Select more material, ask for fewer questions, or wait a minute (AI rate limit) and retry. |
| Build fails on `psycopg` | Use the included `requirements.lock.txt` (Render installs it from the Dockerfile). |
| Data disappeared after a restart | `DATABASE_URL` is not set, so the app used the temporary SQLite file. Add the Neon URL. |
