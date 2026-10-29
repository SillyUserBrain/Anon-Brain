# Building Anon Brain
Notes for running Anon Brain from the code, testing it, building the installer
and publishing updates. To just use the app, download it from the
[releases page](https://github.com/SillyUserBrain/Anon-Brain/releases/latest)
instead.

## Running from the code
You need **Python 3.12** and **FFmpeg** (`winget install ffmpeg`).

1. Double-click **Install.bat**. It sets everything up (a few minutes the
   first time) and puts an **Anon Brain** shortcut on your desktop.
2. That's it. Anon Brain is 100% free: its free voices run on your PC (they
   download once, about 120 MB, the first time you use one).
3. Optional: for ElevenLabs voices, click **Settings**, paste your API key and
   hit **Test & save key**.

After that, just use the desktop shortcut (or **Anon Brain.bat**).

## Checking everything still works
Double-click **run_tests.bat** (after Install.bat). In about a minute it makes
nine real test videos (posts, slide reveal, captions, threads, 24/60 fps movie
clips, a music folder, previews), clicks through every screen of the app in the background, and
checks the smaller pieces (links, schedules, settings, fonts...). It ends with
`33 passed, 0 failed` when all is well; anything else is listed by name. Run it
before building a new version. `run_tests.bat quick` skips the video renders.
It uses a throwaway data folder, so your settings and history aren't touched.

## Building the installer
1. Double-click **build_exe.bat** (after Install.bat). It gets FFmpeg (copies
   yours, or downloads it), builds the app, installs the free Inno Setup tool
   the first time, and makes **dist\Anon-Brain-Setup-1.0.0.exe**.
2. Send your friends that one file. It installs like a normal app (no admin
   needed): Start menu entry, optional desktop shortcut, and an uninstaller in
   Windows Settings → Apps. FFmpeg is built in.
3. Windows may say "Windows protected your PC" the first time because the app
   isn't signed: **More info → Run anyway**.

Before each new build, raise `VERSION` in `anonbrain/appinfo.py` so you can
tell builds apart (Settings → About shows it). Updating = run the new setup;
settings, history and voices are kept (they live in `%APPDATA%\AnonBrain`).

## Sending out updates
One-time: make a **public** GitHub repository and put its name in
`UPDATE_REPO` in `anonbrain/appinfo.py` (e.g. `"yourname/anon-brain"`), then
build. Every copy built after that checks for updates.

For each update:
1. Raise `VERSION` in `anonbrain/appinfo.py` (e.g. `1.0.1`) and run build_exe.bat.
2. On GitHub: **Releases → Draft a new release**, tag `v1.0.1`, write what's
   new (people see it in the app), and attach `dist\Anon-Brain-Setup-1.0.1.exe`.
   Publish.
3. Everyone's app shows **New update available** in the top-right corner.
   **Update now** downloads the setup, installs over the old version and
   reopens the app. Nothing to uninstall, and nothing is lost.

## When something breaks on someone's PC
They use Settings → About → **Copy error details** and send it to you. Logs are in `%APPDATA%\AnonBrain\logs`. Running
`"Anon Brain.exe" --selftest` checks every engine and writes `selftest.txt`
in that folder.

## Files
- `app.py`: starts the app; `anonbrain/appinfo.py`: version, logs, crash reports
- `anonbrain/updates.py` + `ui/updates_ui.py`: update checks and updating in place
- `anonbrain/ui/tour.py`: the first-run tour
- `build_exe.bat` + `anonbrain.spec` + `installer.iss`: the installer build
- `anonbrain/engine.py`: FFmpeg video building
- `anonbrain/library.py`: gameplay library / no-repeat footage
- `anonbrain/music.py`: music folder (random song, random part)
- `anonbrain/ocr.py`: reads text from screenshots (offline)
- `anonbrain/cleanup.py`: shorthand → spoken words
- `anonbrain/voice.py`: narration (line by line, with pauses)
- `anonbrain/free_tts.py`: free offline voices (Kokoro)
- `anonbrain/custom_voices.py`: your own voices (Piper, Kokoro files, mixes, servers)
- `anonbrain/reveal.py`: line timing, fade-in frames and the slide-down plan
- `anonbrain/links.py` + `cards.py`: Reddit / 4chan links drawn as post cards
- `anonbrain/presets.py`: saved looks; `anonbrain/ui/brand.py`: watermark and end card
- `anonbrain/pipeline.py`: ties it all together
- `anonbrain/automation.py` + `reddit_source.py`: Automate (picking, making, schedule)
- `anonbrain/posting/`: TikTok, YouTube and Instagram uploads; `oauth.py`: sign-ins
- `anonbrain/ui/`: the desktop app
- `make_video.py`: quick command-line test of the engine (no voice)
- `tests/` + `run_tests.bat`: the checks above
- `docs/images/`: the pictures in the README
