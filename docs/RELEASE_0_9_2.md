# CampusPath AI 0.9.2–0.9.5: performance and stability release

## 0.9.5 (pre-rendered 3D characters: nothing left that can freeze)

- Every character pose the app uses, plus each character's reactions (think, cheer, sad, oops,
  listen, talk, tap-flip), is pre-rendered with the project's own CP3D renderer into animated WebP
  images (`app/static/characters/`, 175 clips; `scripts/bake_characters.cjs` regenerates them).
- The site shows these by default: no WebGL, no shader compile, no GPU work, so reloading cannot
  freeze the browser. The characters are visible in about 0.3 s, and page timer lag measured 0 ms.
  Reactions and tap-to-flip still work by switching clips. Pointer-following eyes need live 3D.
- Live real-time 3D is opt-in: `?cp3d=live` (all 0.9.2–0.9.4 safeguards still apply).
- The emoji are only a last resort if an image file is missing.

## 0.9.4 (characters on every PC)

- Browsers that draw graphics in software (no hardware acceleration) now show the original 3D characters
  in a light profile instead of emoji: 15–20 fps, a lower pixel budget and lighter CSS effects,
  with one GPU frame in flight at most. Measured on a software GPU: longest pause 0.65 s once
  (original: 14 s), page responsive, Chrome CPU 66% (original: 114%).
- Slow graphics lower resolution and frame rate first; emoji are used only when frames are blank
  or the GPU stops responding (>3 s, three times), or after two starts in a row that froze.
- In local/demo mode (`DEMO_MODE=true`) static files always revalidate, so edited files can never
  stay cached. Production caches versioned files for a year.

## 0.9.3 hotfix (after testing on a real Windows PC)

- **Demo buttons said "Demo accounts are disabled".** This was a regression in 0.9.2: start-up ran
  `/api/health` and `/api/auth/me` together, and the normal 401 for signed-out visitors skipped saving
  the health result. Fixed in `app.js`. The 401 in the server log is normal; it means "not signed in".
- **Characters were blank on a Windows GPU.** 0.9.2 presented frames as ImageBitmaps, which some
  Windows GPU drivers return blank. Presentation is back to the 2D-canvas copy the original used on
  that PC, still with one atlas per frame and GPU backpressure.
- **Never blank, never stuck twice.** The emoji now stays until a frame is checked and confirmed to
  contain the character; blank frames switch every character to emoji. A per-device safety memory
  (`localStorage` key `cp3d-guard`) records a start that never confirmed a frame (because it froze
  or the tab was refreshed while stuck), or a start that was too slow or failed. That device then
  uses the emoji characters, so refreshing cannot freeze the browser again. It is retried after
  7 days or with `?cp3d=reset`.
- Shader: the orbiting-object loop and accessory calls are no longer duplicated by WebGL2 compilers
  (smaller programs for Chrome/Edge on Windows). 3D now starts at 75% resolution and 24 fps and
  ramps up only when the GPU keeps up.
- Still not testable here: real Windows GPUs. Run `CP3D.stats()` in the browser console to see
  which path a machine uses and why.


No design, colour, typography, character, screen, API, database or authentication behaviour
was changed. This release only changes how the existing 3D characters are compiled,
scheduled and drawn, plus caching, compression and SEO metadata.

## 1. Why the browser froze (root cause, measured)

The freeze came from the 3D character renderer (`app/static/cp3d.js`). It was reproduced in
Chrome 153 before any change was made. There were four compounding causes:

| # | Cause | Evidence (original build) |
|---|---|---|
| 1 | **Synchronous shader compile during first render.** The ray-marching shader has a 110-step loop that calls the whole scene function, and normals plus ambient occlusion call it 8 more times. WebGL1 requires constant loops, so drivers unroll and inline that code many times. Where `KHR_parallel_shader_compile` is unavailable (Firefox, and many Chrome/Edge GPU configurations), `getProgramParameter(LINK_STATUS)` blocked the page until compilation finished. On Windows, Chrome/Edge compile through Direct3D (FXC), which is notoriously slow with unrolled loops. | **One 13,973 ms main-thread task** on a cold landing page; LCP 15.3 s |
| 2 | **Synchronous GPU read-back on every frame.** Each character's frame was copied from the shared WebGL canvas into its own 2D canvas with `drawImage`. Chrome turns that into a ReadPixels stall that waits for the GPU, once per character, at up to 45 fps. | Chrome console: `GPU stall due to ReadPixels` |
| 3 | **No GPU backpressure.** New frames were queued whether or not the GPU had finished the previous one. Chrome and Edge run one GPU process for **all tabs and the browser UI**. A saturated GPU queue therefore makes the whole browser unresponsive, not just the tab, even with plenty of RAM and CPU. The existing "too slow" guard timed CPU work only, so it never triggered. | 102–114% Chrome CPU while the page sat idle |
| 4 | **Software WebGL not detected.** On machines where the GPU is blocklisted or unavailable, Chrome renders WebGL with SwiftShader/llvmpipe, ray-marching on every CPU core. | Renderer string `llvmpipe` in testing |

Secondary issues fixed: the page-wide MutationObserver re-ran the character decorator on every
card-tilt/transition class change; the speech-bubble timer kept running in hidden tabs; quiz and
viva countdown intervals could stack up when a session was repainted; IntersectionObserver
entries were never released for removed characters; and two start-up API calls ran in sequence.

## 2. What changed, file by file

| File | Change and reason |
|---|---|
| `app/static/cp3d.js` | **Renderer core.** (a) A cheap probe picks WebGL2 (WebGL1 fallback). Software renderers get the emoji characters instead of a CPU ray-marcher. (b) The shader compiles **after first paint, in idle time**, and in the background where the browser supports it. (c) WebGL2 variant: loops start at a uniform `ZERO`, so drivers cannot unroll and inline them. Normals use the equivalent 4-tap loop with the same maths. (d) Exact bounding-sphere early-outs for orbiting objects, props and hats skip work that cannot change the result. (e) All visible characters render into **one atlas per frame** and reach the page as **ImageBitmaps** (`bitmaprenderer`), with no read-back. A 2D-canvas fallback remains. (f) **At most one GPU frame in flight** (WebGL2 fence polling, never blocking). Quality and frame rate adapt to measured GPU latency; if the GPU stalls repeatedly, it falls back to emoji instead of freezing. (g) Per-frame pixel budget, DPR capped at 1.5 (was 2). ResizeObserver replaces per-frame layout reads. (h) The loop sleeps when no character is on screen or the tab is hidden. (i) GPU context loss is handled with restore, then fallback. `?cp3d=off/force` and `CP3D.stats()` added for support. Characters, motions, colours, props and the shader's look are unchanged. |
| `app/static/mascot.js` | Emoji placeholder inside each character box until its first 3D frame, so characters never appear blank or missing. Speech bubbles pause in hidden tabs and update the text node in place. The MutationObserver ignores irrelevant attribute/text mutations. |
| `app/static/mascot.css` | Placeholder positioning; the fallback emoji bob respects reduced motion. |
| `app/static/motion.js` / `motion.css` | `cp-lite` tier for low-power devices (≤2 cores, ≤2 GB, ≤4 cores with ≤4 GB, Save-Data) and software-GPU browsers. It drops the backdrop blurs, the blur in the zoom transition, and continuously repainting decorations. Layout and transitions are kept. Reduced motion was already respected and still is. |
| `app/static/app.js` | `/api/health` and `/api/auth/me` now load in parallel at start-up (one round trip). Failure handling is unchanged. |
| `app/static/workflows.js`, `universal.js` | Clear an existing quiz/viva countdown before starting another (interval leak). |
| `app/templates/index.html` | Asset versions → `0.9.2` (cache invalidation). Open Graph/Twitter tags, a server-filled SEO slot, and a `<noscript>` summary of the public page. |
| `app/performance.py` (new) | Year-long immutable caching for versioned static URLs, ETag revalidation for others. Text assets are pre-compressed **once** and served from memory. gzip for HTML/JSON, never for downloads or audio. Per-route title/description/canonical/Open Graph. `robots.txt`, `sitemap.xml`. |
| `app/main.py` | Uses the above. Private shells (`/app`, `/teacher/students`, `/student/{id}`) send `noindex` (header + meta). The HTML shell is `no-cache` so releases show immediately. |
| `.env.example` | Optional `PUBLIC_BASE_URL` for canonical links and the sitemap. |
| `.github/workflows/tests.yml` | Also syntax-checks `motion.js`, `cp3d.js`, `mascot.js`. |
| `tests/test_performance.py` (new) | Pytest for caching, compression, titles, canonical, noindex, robots and sitemap on the real FastAPI app. |
| `tests/perf/*` (new) | The profiling, responsive, long-session, regression and load-test harness used for this report. |

## 3. Before/after measurements

Environment: Linux, 2 CPU cores, Chrome 153 (headless) with a **software GPU (llvmpipe)**. This is
the worst case and the only GPU available in the test environment. Front-end tests used the real
HTML/CSS/JS with a mock JSON API (see section 7). Each figure is one run; expect variation of
about ±10%.

| Scenario | Metric | Before | After, 3D forced on software GPU (`?cp3d=force`) | After, default behaviour |
|---|---|---|---|---|
| Landing, cold load | Longest main-thread task | **13,973 ms** | 1,099 ms | 87 ms |
| | Interactive content visible | 14,324 ms | 130 ms | 242 ms |
| | LCP | 15,260 ms | 1,440 ms | 1,132 ms |
| | Chrome CPU while idle on page | 114% | 107% | **26%** |
| Student dashboard | Longest task / LCP | 2,126 / 3,720 ms | 1,122 / 2,348 ms | 0 / 1,452 ms |
| Teacher dashboard | Longest task / LCP | 2,084 / 3,340 ms | 1,041 / 1,356 ms | 0 / 1,200 ms |
| 5 consecutive reloads | Time to content, each | 2.5–2.7 s | 1.2–1.4 s | 0.26–0.35 s |
| 4 tabs opened at once | Time to content | 8.1–11.9 s | 0.54–0.74 s | – |
| Slow network (150 ms RTT, 1.6 Mbps), cold cache | Hero visible / LCP / bytes | 4.5 s / 5.3 s / 283 KB | 1.1 s / 1.9 s / 91 KB | – |
| Shader compile | Time | ~14,000 ms (cold) | 21–45 ms | not compiled |
| Hidden tab | Frames rendered while hidden | n/a (loop kept scheduling) | 0, resumes on return | – |
| 120 rapid navigations | JS heap after GC | 2.4 → 2.8 MB | 2.4 → 2.9 MB, 3 live canvases | – |
| CLS (all screens) | | ≤ 0.011 | ≤ 0.012 | ≤ 0.012 |

The remaining ~1.1 s task in the forced column is the software rasteriser building its
pipeline on the first draw. In default mode that machine class gets the emoji characters.
On hardware GPUs this work happens in the GPU process; it has **not been measured** (section 7).

Static transfer: 288 KB → **90 KB** (gzip; versioned files are then cached for a year).

## 4. Browser and device testing actually performed

| Browser | Result |
|---|---|
| Chrome 153 (headless, Linux, software GPU) | All measurements above. 44 screen/state snapshots (guest, student, teacher, admin, every menu item, topic modal, theme toggle) are **identical before and after** in text, buttons, forms, inputs, character counts and headings. 0 page errors. |
| Responsive (Chrome device emulation) | 10 screens × 7 sizes (360×740, 390×844, 768×1024, 1024×700, 1366×800, 1920×1080, 844×390 landscape) = 70 combinations. No horizontal scrolling and no element outside the viewport, before or after. |
| Microsoft Edge, Firefox, Safari, real Android/iPhone, Windows, any hardware GPU | **Not tested.** No access in this environment. Edge shares Chrome's engine and code paths. Firefox and Safari use the WebGL1/2D-canvas fallbacks if a feature is missing. |

## 5. Server load test

FastAPI, SQLAlchemy and the database could not be installed in the test environment (no package
network access). The **static/HTML serving layer** ran under uvicorn with 1 worker (as in the
Dockerfile), with the load generator on the same 2-core machine, 15 s per level, 0 errors in every run:

| Concurrency | Before: req/s, p50/p95 ms | After: req/s, p50/p95 ms | Bandwidth |
|---|---|---|---|
| 50 | 926, 52/72 | **1,736**, 29/43 | 32 → 19 MB/s |
| 200 | 897, 213/290 | **1,696**, 131/162 | 31 → 18 MB/s |
| 500 | 825, 576/803 | **1,525**, 371/465 | 28 → 16 MB/s |

Server RSS at 500 connections: 68 MB → 42 MB. Every outbound provider call already had a
timeout (15–45 s); the PostgreSQL pool already uses `pool_pre_ping`/`pool_recycle`; SQLite uses
WAL and a busy timeout. These were reviewed and left unchanged. **API and database endpoints were not
load-tested.** The single worker is deliberate: the live-voice socket guard is in-memory.

## 6. SEO

Implemented and verified by automated checks (`tests/test_performance.py`, and raw-ASGI tests
run here): per-page titles and descriptions for `/`, `/login`, `/register`; absolute canonical
plus `og:url/title/description` (honours `X-Forwarded-Proto`, or `PUBLIC_BASE_URL`); `og:type`,
`og:site_name`, `twitter:card`; `robots.txt` allowing the three public pages and blocking `/api/`,
`/app`, `/teacher/`, `/student/`; `sitemap.xml` with only public pages; `noindex, nofollow`
on every private shell; a `<noscript>` summary so public content does not depend on JS or 3D.
Already correct and unchanged: `lang`, viewport, one `<h1>` per screen, decorative characters
`aria-hidden`, skip link. **Lighthouse was not available, so no Lighthouse scores are claimed.**
There is no `og:image`, because the project has no share image.

## 7. Limitations and unverified items

- Real hardware GPUs, Windows, Edge, Firefox, Safari and physical phones were not tested. Re-run
  `tests/perf/profile.cjs` with `CP_CHANNEL=chrome HEADED=1` (and `msedge`) on a Windows machine.
- Python tests (`pytest`), including the new `tests/test_performance.py`, could not be run here
  (dependencies not installable offline). `app/performance.py` was exercised with Starlette 1.7.0
  (the pinned version) through raw ASGI calls: 13 checks passed.
- Front-end profiling used a mock JSON API with demo-shaped data, not the real backend.
- Machines classed as software-GPU now see the existing emoji characters instead of 3D.
  `?cp3d=force` overrides that, for testing only.
- JS/CSS are compressed but not minified. Minifying would add a build tool, which this project avoids.
