# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Local Scan replaces "Adobe Scan, then Google Translate" with a fully offline app. You photograph German
letters on a phone, adjust the four corners, and get three PDFs: an English one that keeps the original
layout, a clean German scan with a searchable text layer, and a side-by-side version. Nothing leaves the
machine. It runs on Windows 11 with an RTX 5080.

## Git

**Never run `git commit`, `git commit --amend` or `git push`.** At most, stage with `git add` and tell the
user it's ready; they always commit themselves. "Is this safe to commit?" is a request for a review, not
a commit.

## Commands

```powershell
.\run.ps1                         # build frontend if stale, serve everything on :8010 (prints LAN URL + QR)
.\run.ps1 -Dev                    # backend --reload on :8010 + Vite HMR on :5173 (phone: http://<lan-ip>:5173)
uv sync --extra paddle            # install deps incl. in-process PaddleOCR GPU
uv run pytest                     # backend tests
uv run pytest tests/test_ocr.py::test_paragraphs_lists_and_addresses   # single test
cd frontend; npx tsc -b           # frontend typecheck
cd frontend; npm run build        # production build into frontend/dist (served by FastAPI)
```

Python is 3.12 via uv (the system Python is 3.14 and is not used). Run Python through `uv run`, which also
puts `backend/` on the path for tests.

## Architecture

There is one FastAPI app (`backend/app`). It serves `/api/*` and, when it exists, the built React app from
`frontend/dist`. One background worker thread (`jobs.py`) processes documents one at a time, so OCR and
Ollama don't compete for the GPU.

The pipeline for each document (`jobs.process`):
1. **Scan** (`scan/`): corners are detected on upload (`detect.py`). `warp.py` does the perspective
   correction, recovering the real aspect ratio (Zhang & He whiteboard method, snapped to A4). The
   focal length estimated from the quad is used only within `PLAUSIBLE_FOCAL`; otherwise
   `TYPICAL_FOCAL` is assumed, because straight-on photos make the estimate blow up and squeeze the
   page. After that,
   applies the filters. "Auto" = shadow removal by dividing by a large max-filter background, then a
   per-page white point measured from the paper.
2. **OCR** (`ocr/`): an `OcrEngine` protocol with a registry. `paddle_local` runs PaddleOCR in-process
   (the default); `paddle_http` calls a server (multipart, PaddleX or PaddleHub formats). Digital PDF
   imports use their own text layer (`pdf_text.py`) and skip OCR.
3. **Blocks** (`ocr/blocks.py`): lines are grouped into blocks. A block either *flows* (prose, reflowed)
   or keeps its lines (addresses, sidebars, tables, lists), in which case its text holds `\n` and each
   translated line is placed on its source line. The thresholds are tuned from a real letter; see the
   constants at the top of the file.
4. **Translate** (`translate/`): a `Translator` protocol with a registry; `OllamaTranslator` is the only
   engine. Blocks are sent as JSON `{id: text}` with a JSON-schema `format` that requires every id;
   missing ids are retried, and after that the source text is kept. The prompt is `SYSTEM_PROMPT` in
   `ollama.py`.
5. **Render** (`render/`): `inpaint.py` erases the OCR'd lines with the paper colour, using inpainting
   only on busy backgrounds. `pdf.py` builds the three PDFs with PyMuPDF. Font size comes from line
   *width* (Helvetica metrics), not box height, and is snapped per page. Text goes in its own box first,
   then grows into free space (`grow_boxes`, which avoids logos and stamps via `obstacle_mask`), and
   shrinks only as a last resort.

The frontend (`frontend/src`) is React + Vite + TypeScript with hash routing (`#/`, `#/doc/<id>`,
`#/settings`). `components/CornerEditor.tsx` is the 4-corner editor with a loupe. `api.ts` holds all
API calls and types.

**Theming is Catppuccin only.** `src/catppuccin.css` is the official palette (v1.8.0) as `--ctp-*`
variables, one class per flavor. `styles.css` maps the app's tokens onto Catppuccin roles: `--bg` base,
`--card` mantle, `--raised` surface0/1, `--text`/`--label`/`--muted` text/subtext1/subtext0, `--danger`
red, `--ok` green, `--warn` yellow, and `--accent` the user's chosen accent. Use those tokens or
`var(--ctp-*)`; never write raw hex or rgba in styles. The one exception is the QR code background, kept
at Latte base so it stays scannable. `src/theme.ts` applies the flavor class and `--accent` to `<html>`
and stores the choice per device in localStorage. The inline script in `index.html` applies it before
first paint, so keep the two in sync. The picker is `components/AppearancePicker.tsx`, shown in Settings.

## Data and caching

- `data/docs/<id>/doc.json` is the manifest, with page images in `pages/` and outputs `scan.pdf`,
  `translated.pdf` and `side_by_side.pdf`. `data/` is gitignored and holds the user's real letters.
- `config.toml` holds the defaults. Changes made on the Settings page go to `data/settings.json` and are
  merged over the defaults (`config.Settings`).
- Caches: each page's cleaned image and OCR are keyed by `clean_key` (file + corners + rotation +
  filter). Translations go in `doc["tcache"]`, keyed by engine, model, a hash of `SYSTEM_PROMPT` and
  the text. Editing the prompt therefore invalidates translations, but changing the filter or render
  code does **not** invalidate cached clean images; use a new document (or delete `*.clean.jpg`) when
  testing those.

## Rules that are easy to get wrong

- **Every document mutation must go through `storage.editing(doc_id)`**, which does load, change and
  save under one lock. Separate load/save calls caused a lost-update race that silently reset a user's
  crop. The worker writes only its own fields (`jobs._save`). On the client, `DocPage` sends page saves
  in order through one queue, and Translate waits for that queue.
- **Paddle must be the CUDA 12.9 build** (`paddle-cu129` index in `pyproject.toml`). The cu126 build
  runs on the RTX 5080 (Blackwell, sm_120) but returns garbage text. The Windows wheel doesn't declare
  its CUDA DLLs, so the `paddle` extra pins `nvidia-*-cu12` wheels explicitly, and `tool.uv.environments`
  limits resolution to Windows.
- **Port 8010**, not 8000: `~/Projects/Paddle/start_server.bat` (the user's separate OCR server) kills
  whatever listens on 8000.
- Cached cleaned pages are keyed by `jobs.SCAN_VERSION` too: bump it whenever the dewarp or filter
  code changes, or old documents keep their stale images.
- On Windows the dev servers' file watchers sometimes miss changes: Vite has served stale modules, and
  `uvicorn --reload` has kept old backend code. If a change doesn't show up, touch the file or restart
  the backend before debugging further.
- OCR models load lazily on the first page (about a minute of GPU warm-up), and every backend reload
  unloads them.
- `paddlex` depends on `opencv-contrib-python`, so that is the cv2 package here as well; never add
  `opencv-python(-headless)` alongside it.
- **Tests use synthetic letters only** ("Max Mustermann", "Musterstadt"). Never copy names, addresses,
  amounts or reference numbers from the user's real documents into tests or fixtures.
- External services: Ollama on `localhost:11434`. The model is picked in Settings; empty means the
  first installed model.
