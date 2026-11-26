# Release 0.8.0 — Emoji3D characters, 3D page transitions, Android fixes

Front-end only. No API, database or migration changes.

## 3D emoji characters (app/static/mascot.js, mascot.css)
- 21 original 3D-shaded emoji characters: Sunny 😀, Prof. Grin 🧑‍🏫, Nerdy 🤓, Thinky 🤔, Starry 🤩,
  Teary 😭, Cool 😎, Winky 😉, Tex 🤠, Monty 🧐, Zib 👽, Echo 🎤, Chatty 😄, Quill ✍️, Zen 😌,
  Robo 🤖, Party 🥳, Angel 😇, Huggy 🤗, Dizzy 😵‍💫, Phew 😅.
- Jointed bodies: head/neck, shoulder → elbow → hand, hip → knee → shoe. Each joint is a nested SVG
  group rotating around its real pivot, so limbs never detach. Held props move with the hand.
- 24 continuous motions (wave, dance, think, read, write, type, present, cheer, champion back-flip,
  cry, shrug, listen, talk, walk, float, strut, hug, dizzy, point, guard ...).
- Every student/teacher/admin screen has its own character, motion and orbiting emojis.
- Score reactions on quiz, assigned-viva and practice-viva results:
  ≥90% champion + party + confetti · 70–89% cool strut · 50–69% relieved · <50% crying + rain cloud,
  with a hugging friend · no confirmed mark yet → thinking.
- Correct quiz answer → everyone cheers; wrong answer → brief sad reaction.
- Viva screens: the character listens while the microphone is on and talks while a question plays.
- Tap/click any character and it back-flips.
- Orbiting emojis are positioned every frame from the box size, so they cannot leave the box.
- Off-screen characters pause (battery); reduced-motion users get slow motion.

## 3D page transitions (motion.js, motion.css)
Cube, flip, door, depth-zoom, fold and swing; each page has its own, direction follows the menu.

## Responsive / Android
- Fixed horizontal overflow on the landing page (was 396px wide on a 360px phone).
- text-size-adjust (stops Android font boosting), 16px inputs (no zoom-on-focus), overflow clipping,
  safe-area padding, tighter small-phone spacing. Verified at 320, 360, 412 and 1366px.
- Asset URLs carry ?v=0.8.0 so phones do not keep the old cached CSS/JS.

# 0.8.1 — Baby-animal cast
- The app now uses 15 cute baby-animal characters: Bunny 🐰, Owlet 🦉, Panda 🐼, Kitten 🐱, Uni 🦄,
  Puppy 🐶, Foxy 🦊, Chick 🐥, Fawn 🦌, Hammy 🐹, Koala 🐨, Pengu 🐧, Teddy 🧸, Piggy 🐷, Lamb 🐑.
- Fur bodies with soft bellies, paws and paw pads, wiggling ears, a glowing unicorn horn.
- More depth: rounded (cylinder-shaded) limbs and torso; back ears, face and hats move at different
  depths as the character turns (parallax), on top of the 3D sway and pointer tilt.
- Results: 90%+ unicorn back-flip + piggy party · 70–89% fox thumbs-up + bunny cheer ·
  50–69% relieved chick + thinking hamster · <50% crying puppy hugged by Teddy · pending → kitten.
- Asset version bumped to ?v=0.8.1 so phones fetch the new files.
- The earlier face emojis are still in mascot.js (unused) and can be shown with CampusMascot.show(el, name).
