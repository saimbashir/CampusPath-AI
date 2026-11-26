# CampusPath AI 0.7.0 — animated orange edition + Railway

## What changed

**Animated 3D characters on every screen** (`app/static/mascot.js`, `app/static/mascot.css`)
- Three original characters drawn in SVG: **Pathy** (orange robot guide, students/admin),
  **Prof. Hoot** (owl professor, teacher screens) and **Nova** (student with a backpack).
- Every page heading gets a character whose mood fits the screen: suggesting (💡 dashboard),
  thinking (💭 tutor), reading (📖 materials), writing (✏️ quiz, questions, assignments),
  listening (🎧🎤 viva), analysing (🔍📊 results, class intelligence), planning (🗓️⏰ study plan),
  exploring (🧭 learning path, knowledge map), coding (💻 algorithm lab), guarding (🛡️ admin, settings).
- Everything is always in motion: blinking, breathing/bobbing, head tilts, waving and pointing
  arms, swinging graduation tassel, glowing antenna, spinning floor rings, a 3D ring of emojis
  that passes behind the character, and rotating 3D cubes on the landing page.
- The characters react to the app: they **think** (thought bubble + "Thinking…") while any
  request is waiting for the server or the AI, **celebrate** (jump + emoji burst) when a success
  message appears, and look **puzzled** (head shake, ❓) on errors.
- They tilt in 3D towards the mouse; speech bubbles type out helpful tips for each screen.
- Also added to: the landing page (all three characters), sign-in/registration, empty states,
  loading states, the dashboard recommendation card and a small buddy in the sidebar.
- People who switch on "reduce motion" in their system still see gentle, slow movement.

**Orange theme**
- New warm orange palette for light and dark mode, gradient orange buttons, orange focus rings,
  sidebar, charts and progress bars (low scores now show in red so they stay distinct).
- Text contrast checked: white on button orange 5.2:1, body text above 7:1.

**General for every department**
- Landing page no longer shows computer-science examples; a new "Built for every department"
  strip lists subjects from science, medicine, law, business, engineering, arts and more.
- Tutor and copilot hints are subject-neutral; the algorithm lab is labelled "(computing)".
- **Faculty invitations can now be created in the browser** (Administration page, admin
  re-enters their password; code shown once; only its hash is stored; audited; rate-limited).
  Before, this needed a command line, which Railway's free plan does not give you.
  New endpoint: `POST /api/admin/keys`.

**Railway deployment**
- `railway.json` (Docker build, `/api/health` check with 300 s timeout, restart on failure).
- `DEPLOY_RAILWAY.md`: complete free deployment with Neon 1 GB PostgreSQL + Gemini (+ optional Groq).

## Verification done for this release
- JavaScript syntax checked; every screen type rendered in Chrome against a mock API at
  desktop and phone sizes, light and dark mode (landing, sign-in, student dashboard, tutor,
  teacher dashboard, materials with empty state, error page, admin).
- Not run here: the Python test suite and a live Railway/Neon/Gemini deployment (the build
  machine had no internet access to install the Python packages). Run
  `python run.py --check` and `python -m pytest -q` on your computer before deploying.

## Remaining work (honest list)
| Item | Needed for the demo? | Note |
|---|---|---|
| Create GitHub, Neon, Gemini (and Groq) accounts, set Railway variables | **Yes** | Follow DEPLOY_RAILWAY.md, ~45 min |
| One full live test after deploy: teacher uploads a PDF → generates questions → student quiz and viva | **Yes** | Proves the AI keys work |
| Prepare demo data (teacher, course, approved questions, a student with results) | Recommended | Empty screens look weaker in a presentation |
| Email delivery for password reset | No | Needs SMTP (e.g. a Gmail app password) in `SMTP_*` variables |
| Diagrams/handwriting understanding, scanned PDFs beyond 60 pages | No | Text PDFs, slides and Word files work fully |
| Background scheduler / push or email notifications | No | Notifications refresh when the user opens the app |
| Load testing for a whole university | No | Free plans are sized for a class demo, not hundreds of users at once |
