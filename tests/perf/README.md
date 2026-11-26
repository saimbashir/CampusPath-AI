# Front-end performance and regression harness (optional)

Not needed to run CampusPath. These scripts drive a real Chrome/Edge through every screen and
measure loading, main-thread blocking, frame rate, CPU use, memory and layout overflow.

`mock_server.py` serves the real `app/templates` and `app/static` with a small mock JSON API.
That isolates front-end performance and works without a database. Sign-in state is a cookie (`mock=student|teacher|admin`).

```bash
npm install playwright              # once, in any folder on NODE_PATH
python tests/perf/mock_server.py . 8102 gzip &   # project root, port, gzip like production

# Use your own browser and GPU (most realistic):
CP_CHANNEL=chrome HEADED=1 node tests/perf/profile.cjs http://127.0.0.1:8102 mine
CP_CHANNEL=msedge HEADED=1 node tests/perf/profile.cjs http://127.0.0.1:8102 edge
# Worst case, a software GPU (what the 0.9.2 numbers in docs/RELEASE_0_9_2.md used):
CP_SOFTWARE_GL=1 node tests/perf/profile.cjs http://127.0.0.1:8102 sw "?cp3d=force"

node tests/perf/responsive.cjs http://127.0.0.1:8102 out     # 10 screens x 7 sizes, overflow check
node tests/perf/session.cjs    http://127.0.0.1:8102         # 120 navigations, hidden tab, 4 tabs, slow network
node tests/perf/regress.cjs    http://127.0.0.1:8102 snap.json   # text/controls of every screen, for diffing two builds
```

Static-file load test (single uvicorn worker, as in production):

```bash
MODE=after ROOT=$PWD python -m uvicorn --app-dir tests/perf asgi_static:app --port 8300 --workers 1 &
node tests/perf/load.cjs http://127.0.0.1:8300 200 15        # concurrency, seconds
```

`?cp3d=off` always shows the emoji characters. `?cp3d=force` renders 3D even on a software
GPU (testing only). `CP3D.stats()` in the browser console reports the renderer, compile time,
current quality, frame-rate cap and measured GPU latency.
