# Deploy CampusPath AI on Railway (free) — step by step

Version 0.7.0 · checked November 2026

This guide puts CampusPath AI online at a public `https://….up.railway.app` address, using
only free plans. Plan about 45 minutes the first time.

## What you need (all free, no paid plan)

| What | Service | Free limit (Nov 2026) | Used for |
|---|---|---|---|
| Code storage | **GitHub** | unlimited private repos | Railway deploys from it |
| Hosting | **Railway** | 30-day trial with $5 credit, then the Free plan: $1 credit/month, 0.5 GB RAM, app sleeps when idle | Runs the Python app |
| Database | **Neon PostgreSQL** | **1 GB per project**, no expiry, sleeps after 5 min idle | Users, courses, uploaded books, marks |
| AI (required) | **Google AI Studio – Gemini** | free API key, daily request limit | Reads the teacher's material, writes questions, tutor answers, viva marking |
| Voice (optional) | **Groq – Whisper** | free API key, ~2,000 transcriptions/day | Turns a student's spoken viva answer into text |

> **Why Neon and not Railway's own database?** Railway's database would use up the same small
> $1/month credit as the app. Neon gives you a separate 1 GB PostgreSQL for free.
> (Backup choice with the same 1 GB size: **Aiven** free PostgreSQL. It also works by pasting its
> connection string into `DATABASE_URL`.)

> **Never** upload `.env`, API keys or passwords to GitHub. Keys go only into Railway → Variables.

---

## How many AI APIs do you need?

| # | API | Needed? | Variables |
|---|---|---|---|
| 1 | **Gemini** (Google AI Studio) | **Yes — the only required one.** Without it the app still works, but question generation, the AI tutor and AI viva marking are switched off. | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| 2 | **Groq Whisper** (speech-to-text) | Recommended for the spoken viva. Without it, students type answers or use the browser's own voice typing. | `SPEECH_BASE_URL`, `SPEECH_API_KEY`, `STT_MODEL` |
| — | Text-to-speech | Not needed: the browser reads questions aloud for free. | leave `TTS_MODEL` empty |
| — | Embeddings / Qdrant | Not needed: the built-in keyword search finds the right pages. | leave empty |

So: **1 API key is enough, 2 is the complete experience.** Both are free.

---

## Step 1 — Put the code on GitHub

1. Go to github.com → **New repository** → name it `campuspath-ai` → **Private** → Create.
2. On your computer, open a terminal in the `CampusPath-AI` folder (the one with `Dockerfile`):
   ```bash
   git init
   git add .
   git commit -m "CampusPath AI 0.7.0"
   git branch -M main
   git remote add origin https://github.com/YOUR-NAME/campuspath-ai.git
   git push -u origin main
   ```
   The `.gitignore` already keeps out `.env`, `.venv/`, `campuspath.db` and `backups/`.

## Step 2 — Create the free 1 GB database (Neon)

1. Sign up at **neon.tech** (Sign in with GitHub is fine) → **Create project**.
   Pick the region closest to Pakistan (for example AWS Singapore or Frankfurt).
2. Click **Connect**. **Turn "Connection pooling" OFF** (use the *direct* connection).
3. Copy the connection string. It looks like
   `postgresql://neondb_owner:xxxx@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
4. Keep it private. The app adds the PostgreSQL driver itself, so paste it exactly as shown.

## Step 3 — Get the Gemini key (required)

1. Go to **aistudio.google.com** → **Get API key** → **Create API key** → copy it.
2. In AI Studio's model list, copy the id of a current **Flash** model
   (for example `gemini-3-flash-preview`; use whatever Flash id AI Studio shows you today).
3. Note: on the free tier Google may use requests to improve its products, so do not upload
   private student data as course material.

## Step 4 — Get the Groq key (optional, for spoken viva)

1. Go to **console.groq.com** → **API Keys** → **Create API Key** → copy it.

## Step 5 — Deploy on Railway

1. Go to **railway.com** → **Login with GitHub**. New accounts start the free trial (no card needed).
2. **New Project → Deploy from GitHub repo** → choose `campuspath-ai`.
   Railway finds `Dockerfile` and `railway.json` automatically (build with Docker, health check
   `/api/health`, restart on failure).
3. Open the service → **Variables** → **Raw Editor**, paste this and fill in your values:

   ```env
   DATABASE_URL=postgresql://...your Neon string from Step 2...
   DEMO_MODE=false
   COOKIE_SECURE=true
   LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
   LLM_API_KEY=...your Gemini key...
   LLM_MODEL=...the Flash model id from AI Studio...
   LLM_EXCERPTS_PER_CALL=12
   LLM_QUESTIONS_PER_CALL=6
   MAX_UPLOAD_MIB=16
   BACKGROUND_UPLOAD_MIB=1.5
   ADMIN_EMAIL=you@example.com
   ADMIN_PASSWORD=choose-a-strong-password-12+
   # Optional: spoken viva (Groq)
   SPEECH_BASE_URL=https://api.groq.com/openai/v1
   SPEECH_API_KEY=...your Groq key...
   STT_MODEL=whisper-large-v3-turbo
   ```

   `DEMO_MODE=false` is important: in demo mode all AI generation is switched off.
   Do **not** set `PORT`; Railway sets it and the Dockerfile uses it.
4. Click **Deploy**. The first build takes 5–10 minutes. In **Deploy Logs** wait for
   `Uvicorn running on http://0.0.0.0:…`. On the first start the app creates all database tables
   in Neon by itself (`alembic upgrade head`).
5. **Settings → Networking → Generate Domain**. Your app is now at
   `https://campuspath-ai-production-xxxx.up.railway.app`.

## Step 6 — First use (any department, any teacher)

1. Open the address → **Sign in** with `ADMIN_EMAIL` / `ADMIN_PASSWORD`.
2. **Administration → Faculty invitations**: type your admin password → **Create faculty invitation**.
   Copy the code (shown once) and send it privately to a teacher. Repeat for each teacher, or set
   "Teachers who can use it" to e.g. 10 for a whole department.
3. The teacher opens **Create account**, chooses **Teacher**, pastes the code, and fills in their
   department. Then: **My courses → Create a course section** (any subject) → **Course materials →
   upload the book / slides** → **Question bank → generate questions** → approve them.
4. The teacher shares the course **enrollment code** (shown on the teacher Overview).
5. Students **Create account** as Student → **My courses → Join course** with that code.

## Step 7 — Clean up (security)

1. Back in Railway → **Variables**, delete `ADMIN_PASSWORD` (the account is already saved,
   password stored hashed). Railway redeploys automatically.

---

## Before you present to your teacher

* The Free plan **puts the app to sleep when nobody uses it**, and Neon sleeps after 5 minutes.
  Open the site **1–2 minutes before the demo** so both are awake (the first load can take 20–40 s).
* Prepare one teacher account, one course with a short PDF already uploaded, some approved
  questions, and one student account that already answered a quiz, so every screen has data.
* Show the characters: they think while the AI works, celebrate when something is saved, and look
  puzzled when something fails. Switch to dark mode with the moon button.

## How long will the free plan last?

* **Trial:** $5 for 30 days — plenty for building and presenting.
* **After the trial:** $1/month credit with the app sleeping when idle. A lightly used class
  project usually fits; heavy daily use by a whole class may not. If it runs out, either upgrade
  Railway to Hobby ($5/month) or use the included `render.yaml` to deploy the same code on
  Render's free plan (see `DEPLOY_FREE.md`). The Neon database stays the same in both cases.
* **Database:** 1 GB on Neon. Uploaded files are stored inside the database together with their
  extracted text, so roughly **40–60 average 10 MB PDFs** fit, plus all users and marks. Keep
  `MAX_UPLOAD_MIB=16` and delete old materials you no longer need.

## Troubleshooting

| Problem | Fix |
|---|---|
| Build OK but deploy fails health check | Open Deploy Logs. Usually `DATABASE_URL` is wrong or Neon pooling is on — use the direct string. |
| "Cross-origin requests are not allowed" | Open the app only through the Railway domain you generated. |
| Login works but you are logged out at once | `COOKIE_SECURE=true` needs `https://` — use the Railway domain, not `http://`. |
| "AI generation requires a configured provider" | Set `DEMO_MODE=false` and all three `LLM_…` variables, then redeploy. |
| Gemini error 429 | Free rate limit reached. Wait a minute; the app retries automatically. Lower `LLM_QUESTIONS_PER_CALL` to 4. |
| Gemini error 404 model not found | The model id changed. Copy the current Flash id from AI Studio into `LLM_MODEL`. |
| Large PDF stays "processing" | Normal for big books on 0.5 GB RAM; it continues in the background, even after a restart. Split very large books into chapters. |
| Out of memory / restarts | Lower `MAX_UPLOAD_MIB` to 8 and `MAX_OCR_PAGES` to 30. |
