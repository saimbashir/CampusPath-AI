# Release 0.9.0 — Real-time 3D characters

Front-end only. No API, database or migration changes.

## New 3D engine (app/static/cp3d.js)
- Characters are real 3D models rendered live on the GPU (WebGL 1, signed-distance-field ray
  marching). No libraries, no network calls, CSP-safe.
- Soft-vinyl look: wrap lighting, warm sub-surface tint, clear-coat specular, rim light,
  ambient occlusion, soft ground shadow, anti-aliased silhouettes.
- Arms and legs are blended into the body (smooth union) and posed with 2-bone IK, so limbs
  can never detach. Props are held in the hand and move with it.
- Real eyeballs with iris, pupil and catch-lights rotate to follow the 3D objects orbiting each
  character (or the mouse on desktop); natural random blinking; painted expressions
  (smile, grin, "o", frown, crying, talking, smirk), brows, blush and tears.
- Orbiting 3D objects (stars, gems, rings, cubes, hearts, check marks, glowing orbs) are drawn
  inside each character's own canvas, so they can never leave the box.
- One shared WebGL context renders every character and copies frames into each canvas
  (works with any number of characters per page). Off-screen characters pause; frame rate is
  capped (30 fps on phones) and resolution adapts automatically on slow devices.
- Falls back to a plain emoji if WebGL is unavailable or the context is lost.

## Cast (app/static/mascot.js)
Pip, Professor Mo, Sage, Inky, Coco, Kiwi, Atlas, Ruby, Blip, Peach, Nova, Drizzle, Puff,
Tango, Luma — 5 body shapes, 13 accessories, 18 props, 22 motions.
- Student and teacher screens have separate mappings; every student screen uses a different
  character, each doing that screen's job (reading for materials, writing for quizzes, typing
  for the lab, a mic for the viva, a compass for the learning path…).
- Results: ≥90% Nova back-flips with crown + trophy while Tango cheers · 70–89% cheer ·
  50–69% relieved shrug + thinking · <50% Drizzle cries under a rain cloud while Puff hugs ·
  pending → thinking.
- Busy → thinking, success → cheer, wrong answer → crying, error → shrug, viva mic on →
  listening, question playing → talking, tap → back-flip.
