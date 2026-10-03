# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Local Scan replaces "Adobe Scan, then Google Translate" with a fully offline app, and is growing into a scan
manager (folders, tags, search, "ask your documents"). You photograph letters on a phone, adjust the four
corners, and get three PDFs per document: **Original** (the cleaned scan with a searchable text layer),
**Translated** (same layout, text replaced by its translation, German to English by default) and **Side by
side**. They open in a new browser tab. Nothing leaves the machine. It runs on Windows 11 with an RTX 5080.

## Git

**Never run `git commit`, `git commit --amend` or `git push`.** At most, stage with `git add` and tell the
user it's ready; they always commit themselves. "Is this safe to commit?" is a request for a review, not
a commit.

## Writing

Prose, comments and commit messages use the plain hyphen. Never write em or en dashes (the `dashfix` skill).

## Commands

```powershell
.\run.bat                         # (double-clickable) build frontend if stale, serve everything on :8010 (prints LAN URL + QR)
.\run.bat -Dev                    # backend --reload on :8010 + Vite HMR on :5173 (phone: http://<lan-ip>:5173)
uv sync --extra paddle            # install deps incl. in-process PaddleOCR GPU
uv run pytest                     # backend tests
uv run pytest tests/test_ocr.py::test_paragraphs_lists_and_addresses   # single test
cd frontend; npx tsc -b           # frontend typecheck
cd frontend; npm run build        # production build into frontend/dist (served by FastAPI)
```

Python is 3.12 via uv (the system Python is 3.14 and is not used). Run Python through `uv run`, which also
puts `backend/` on the path for tests. The frontend has no test runner: check UI changes in the browser.

## Architecture

There is one FastAPI app (`backend/app`). It serves `/api/*` and, when it exists, the built React app from
`frontend/dist`. One background worker thread (`jobs.py`) processes documents one at a time, so OCR and
Ollama don't compete for the GPU.

The pipeline for each document (`jobs.process`):
1. **Scan** (`scan/`): corners are detected on upload (`detect.py`). `warp.py` does the perspective
   correction, recovering the real aspect ratio (Zhang & He whiteboard method, snapped to A4). The focal
   length estimated from the quad is used only within `PLAUSIBLE_FOCAL`; otherwise `TYPICAL_FOCAL` is
   assumed, because straight-on photos make the estimate blow up and squeeze the page. Then the filters
   apply. "Auto" = shadow removal by dividing by a large max-filter background, then a per-page white
   point measured from the paper.
2. **OCR** (`ocr/`): an `OcrEngine` protocol with a registry. `paddle_local` runs PaddleOCR in-process
   (the default); `paddle_http` calls a server (multipart, PaddleX or PaddleHub formats). Digital PDF
   imports use their own text layer (`pdf_text.py`) and skip OCR.
3. **Blocks** (`ocr/blocks.py`): lines are grouped into blocks. A block either *flows* (prose, reflowed)
   or keeps its lines (addresses, sidebars, tables, lists), in which case its text holds `\n` and each
   translated line is placed on its source line. The thresholds are tuned from a real letter; see the
   constants at the top of the file.
4. **Translate** (`translate/`): a `Translator` protocol with a registry; `OllamaTranslator` is the only
   engine. Blocks are sent as JSON `{id: text}` with a JSON-schema `format` that requires every id;
   missing ids are retried, and after that the block comes back as `None`: the render shows its source
   text, but it is not cached, so the next run tries it again. A block the model returns unchanged (a name,
   a number) is a real translation and is cached. The prompt is `SYSTEM_PROMPT` in `ollama.py`.
5. **Render** (`render/`): `inpaint.py` erases the OCR'd lines with the paper colour, using inpainting
   only on busy backgrounds. `pdf.py` builds the three PDFs with PyMuPDF. Font size comes from line
   *width* (Helvetica metrics), not box height, and is snapped per page. Text goes in its own box first,
   then grows into free space (`grow_boxes`, which avoids logos and stamps via `obstacle_mask`), and
   shrinks only as a last resort.

### AI naming

Naming is **manual only**. The user clicks "Suggest name with AI" in the Name group of the Options panel
(`NameOptions.tsx`) or the sparkle on a Library tile, and `POST /api/docs/<id>/suggest-name`
(`ai/naming.py`) returns `<letter date> <sender> - <subject in English>` as a suggestion to Use or dismiss.
Never rename documents automatically; the user removed auto-renaming on purpose. `name_source: "ai"` only
drives the sparkle marker.

- It reads **every page**. `jobs.document_pages_text` OCRs the pages not read yet, reuses cached OCR, and
  stores the result back unless the page was re-cropped meanwhile. While a job runs it uses the text read
  so far instead of competing with the worker.
- `naming.prompt_text` sends all pages with `--- Page N of M ---` markers. Up to `TEXT_BUDGET` characters
  nothing is cut; beyond it each page gets a fair share (page 1 counts double, as it has the letterhead,
  date and subject line). A plain truncation would silently drop later pages, so no page is ever dropped.
- Prompt examples steer small models strongly (an "Electricity ..." example made one invent electricity),
  so keep them neutral. On compound-heavy German letters qwen2.5:14b sometimes leaves the subject in
  German or mistranslates it. Stronger wording and a final reminder were compared on three synthetic
  letters and did not help, so that limit is the model, not the prompt (try another model in Settings).

### Sorting a batch into documents (`ai/sort.py`, `ai/pagesignals.py`)

Manual only: "Sort with AI" (split) and "Fix order" (reorder in place) in Options > Page, plus a dismissible
hint on documents with 3+ pages. `POST /api/docs/<id>/sort-pages?split=` only proposes;
`POST /api/docs/<id>/apply-sort` creates new documents (`storage.create_documents_from_pages`) holding
COPIES of the pages (new page ids, same blobs, OCR keys and crop; folder and tags inherited), so the original
scan stays as a backup and Undo is a bulk delete of the new documents. Reorder-only applies through the
existing `page_order` PATCH. Limit: `MAX_PAGES` = 40, text only.

- `pagesignals.py` extracts cheap facts per page with regexes: page markers (header/footer lines only),
  document-level vs account-level reference numbers, salutation/closing/subject, cut sentences, item numbers.
- The default engine is `ai/similarity.py`, with no model: TF-IDF keyword vectors (plus word pieces, so
  compounds match), then divide and conquer by average-linkage merging of the most similar groups until
  `MERGE_AT`. Hard rules steer it: a shared reference number pulls pages together; the same page number, a
  different page total, two letter openings or two different invoice numbers keep pages apart. A group is
  ordered by complete page markers, else opening page first, closing page last and the middle by
  `boundary_score`; with no cues the photo order is kept and the group is Low. Lone pages that resemble
  nothing go to the "Needs review" tray. The old model pipeline (describe, anchor, rate) is still in
  `sort.arrange(method="model")`; the tests cover it, but it is not used.
- `scripts/sort_benchmark.py` runs synthetic documents (never real letters) through the real model. It is
  slow, so do not run it in loops; unit tests use a fake model (`tests/test_sort.py`).

### Photo and PDF quality (`imaging.py`)

Settings > Photos & PDFs (`[images]` and `[export]` in `config.toml`, saved to `data/settings.json`; UI in
`components/ImageSettings.tsx`). Uploads have **no pixel limit by default**: a JPEG that needs no change
(upright, not resized, plain colour) is stored byte for byte (`documents._original_bytes`), and the phone
sends the file untouched (`prepareImage`); only a limit, an EXIF rotation or a non-JPEG forces a re-encode at
`resize_quality`. The cleaned page is `page_dpi` (300 = 3508 px) at `page_quality` 92; PDFs use a preset
(archive 300/92, standard 300/88, small 200/75) or custom values and never exceed the page resolution.
`jobs.clean_key` only includes the dpi/quality when they differ from the defaults, so default caches stay.
The Translated PDF subsets its fonts (`doc.subset_fonts()`): each `insert_htmlbox` embeds a whole font, which
made one real 3-page letter 5.4 MB (145 fonts) instead of 0.4 MB.

### Languages (`languages.py`)

Settings > Languages picks the scan language and the translation language (`[languages]` in `config.toml`; scan is a list, translate_to a single code,
saved to `data/settings.json`). The pair applies globally: the translation prompt and cache (languages are
in the key), the AI naming prompt (`{src}`, `{tgt}`), and the OCR model (`Language.ocr`, passed to PaddleOCR;
empty = the default models). To add a language, add one `Language(...)` to `LANGUAGES`; Settings lists it
automatically. Gaps: other prompts (sorting) and the PDF fonts assume Latin text, so a non-Latin language
needs a font in `render/` and a PaddleOCR model that is installed. The pair must differ (the API rejects
equal ones).

## Frontend

React + Vite + TypeScript (`frontend/src`) with hash routing: `#/`, `#/unfiled`, `#/folder/<id>`,
`#/tag/<id>` (Library), `#/doc/<id>` (document) and `#/settings`. `api.ts` holds all API calls and types.
Icons are Lucide (`lucide-react`). Each screen caps its width with `--page-max` (860px by default, 1440px
for the Library and the document screen).

- **Library** (`pages/Library.tsx`): a sidebar (`components/Sidebar.tsx`: folder tree and tags, a drawer
  below 800px) next to a grid of tiles (`DocCard`). A tile shows the cached preview of the first page, the
  title (2 lines), pages and date, a folder chip, tags and, on hover, a select box (a bulk bar appears
  when anything is selected). The sparkle and pencil buttons sit over the thumbnail. The footer is the
  three PDF buttons when the document is done, otherwise one next step ("Review & translate", "Add pages",
  "Open to retry"). The status badge shows only while queued, processing or failed.
- **Document** (`pages/DocPage.tsx`): three panels, Pages (thumbnail grid and adding), Page (crop editor
  or preview, with a pager) and Options (Name, Organize, Color, Crop, Page, Translate). From 1000px wide
  all three show; below that they are tabs with a bottom bar. The editor sizes itself from its panel with
  container query units (`cqw`/`cqh`), not from the window height.
- **PDF buttons**: `PdfLinks` in `components/common.tsx` is the only place PDFs are offered: Original,
  Translated, Side by side. Each opens inline in a new tab (`/files/<kind>?inline=true`, `target="_blank"`
  with `rel="noopener"`); the browser's viewer does save and print. There are no download buttons and the
  labels never name a language. The stored kinds are `scan`, `translated` and `side_by_side`; the file
  names a viewer proposes come from `jobs.OUTPUTS`.

**Theming is Catppuccin only.** `src/catppuccin.css` is the official palette (v1.8.0) as `--ctp-*`
variables, one class per flavor. `styles.css` maps the app's tokens onto Catppuccin roles: `--bg` base,
`--card` mantle, `--raised` surface0/1, `--text`/`--label`/`--muted` text/subtext1/subtext0, `--danger`
red, `--ok` green, `--warn` yellow, and `--accent` the user's chosen accent. Use those tokens or
`var(--ctp-*)`; never write raw hex or rgba in styles. The one exception is the QR code background, kept
at Latte base so it stays scannable. `src/theme.ts` applies the flavor class, `--accent` and the text size (`font-size` on `<html>`; sizes are in rem so everything scales) to `<html>`
and stores the choice per device in localStorage. The inline script in `index.html` applies it before
first paint, so keep the two in sync. The picker is `components/AppearancePicker.tsx`, shown in Settings.

## Data and caching

- **SQLite** at `data/localscan.db` (WAL), opened by `storage.init()` at startup. The schema lives in
  `backend/app/db/migrations/NNN_*.sql`, applied in order with `schema_version`; add a new file, never
  edit an applied one.
- **Files** live in the content-addressed blob store `data/blobs/<2 hex>/<sha256>.<ext>`
  (`db/blobs.py`), referenced from `pages.original_blob`, `pages.clean_blob`, `outputs.blob` and
  `previews.blob`. `storage.collect_garbage()` deletes unreferenced blobs, keeping anything younger than
  10 minutes, since an upload stores its blob a moment before its page row.
- `storage.py` keeps the old dict API (`load_doc`, `editing`, `list_docs`, `save_doc`, ...). A page refers
  to its photo by sha in `original` and its cleaned image in `clean`.
- **Caches:**
  - Each page's cleaned image and OCR are keyed by `jobs.clean_key` (SCAN_VERSION, original sha,
    corners, rotation, filter).
  - Translations go in the global `translation_cache` table, per paragraph (block), keyed by engine,
    model, prompt hash, languages and text. They are shared by every document, and `jobs.process` sends
    only paragraphs not seen before, so adding or re-cropping a page never re-translates the others.
    Never cache a failed block (`tests/test_translation_cache.py` guards this).
  - Rendered photos and previews go in the `previews` table (`api/documents._cached_jpeg`).
  - Changing filter or render code does **not** invalidate cached cleaned images: bump `SCAN_VERSION`.
- **Folders and tags** (`library.py`, `api/library.py`, migration `002`):
  - Folders form a tree through `parent_id`. Deleting a folder moves its documents and subfolders up to
    its parent; it never deletes documents. Moving a folder into its own subtree is rejected.
  - Tags are unique ignoring case (`COLLATE NOCASE`); creating an existing name returns that tag.
    Colours are Catppuccin accent names (`TAG_COLORS`).
  - `documents.folder_id` is written by `save_doc`, so `storage.editing()` round-trips keep it.
  - Tags are only changed through `library.set_tags` / `add_tag` / `remove_tag`.
  - The Library loads all documents and filters by view in the browser. Drag-and-drop carries document
    ids in the `application/x-localscan-docs` data type; the tile's link and image are
    `draggable={false}` so a drag starts on the tile, not on the image.
- **Trash** (migration `003`): deleting a document sets `documents.deleted_at` (`storage.trash_doc`); the
  pages and files stay. `list_docs` hides trashed documents unless `trashed=True`; folder and tag counts
  skip them. `#/trash` lists them with Restore, Delete forever and Empty trash, and `storage.init` purges
  anything trashed more than `TRASH_DAYS` (30) ago. Bulk actions: `delete` = to the trash, `restore`,
  `purge` = for good (only from the trash). Deleted pages (single delete, or removing sorted pages from the
  source) are kept too: `storage.trash_pages` stores them as a trashed document, which Restore turns
  into a separate document. Folders and tags are organisation, not content, and are deleted directly.
- **Moving pages** (`storage.move_pages` / `return_pages`, `POST /api/docs/<id>/move-pages` and `return-pages`):
  the right-click menu on a thumbnail (`ContextMenu.tsx`, picked pages via Ctrl/Cmd/Shift-click) moves the
  pages out of the document into a new one in a chosen folder. It is a real move (`UPDATE pages SET doc_id`,
  the one place a page changes document; `save_doc` never does), so ids, OCR and previews travel with the
  page. Undo puts the pages back at their old positions. The sort feature still COPIES pages instead.
- **Legacy data:** an old `data/docs/*/doc.json` tree is imported once on startup (`db/legacy.py`),
  then renamed to `data/docs.migrated-<timestamp>`.
- `data/` is gitignored and holds the user's real letters.

## Rules that are easy to get wrong

- **Every document mutation must go through `storage.editing(doc_id)`**, which loads, changes and saves
  in one `BEGIN IMMEDIATE` transaction (re-entrant per thread). Separate load/save calls caused a
  lost-update race that silently reset a user's crop. The worker writes only its own fields
  (`jobs._save`). On the client, `DocPage` sends page saves in order through one queue, and Translate
  waits for that queue.
- **In recursive React components, spread inherited props before the explicit ones.** The folder tree
  once rendered `<FolderRow folder={f} {...props} />` while `props` carried the parent's `folder`, so every
  child row rendered its parent again and recursed forever: nesting one folder froze the tab. Test
  nested data in the browser, since nothing else will catch it.
- **Paddle must be the CUDA 12.9 build** (`paddle-cu129` index in `pyproject.toml`). The cu126 build
  runs on the RTX 5080 (Blackwell, sm_120) but returns garbage text. The Windows wheel doesn't declare
  its CUDA DLLs, so the `paddle` extra pins `nvidia-*-cu12` wheels explicitly, and `tool.uv.environments`
  limits resolution to Windows.
- **Port 8010**, not 8000: `~/Projects/Paddle/start_server.bat` (the user's separate OCR server) kills
  whatever listens on 8000.
- Bump `jobs.SCAN_VERSION` whenever the dewarp or filter code changes, or old documents keep their stale
  images.
- On Windows the dev servers' file watchers sometimes miss changes: Vite has served stale modules, and
  `uvicorn --reload` has kept old backend code (it served old PDF names after an edit). If a change
  doesn't show up, touch the file or restart the backend before debugging further.
- OCR models load lazily on the first page (about a minute of GPU warm-up), and every backend reload
  unloads them. `/api/health` is slow the first time for the same reason.
- `paddlex` depends on `opencv-contrib-python`, so that is the cv2 package here as well; never add
  `opencv-python(-headless)` alongside it.
- **Tests use synthetic letters only** ("Max Mustermann", "Musterstadt"). Never copy names, addresses,
  amounts or reference numbers from the user's real documents into tests or fixtures.
- External services: Ollama on `localhost:11434`. The model is picked in Settings; empty means the
  first installed model by name.

## Planned, not built yet

Decisions already made for the scan-manager roadmap (the plan itself lives outside the repo):

- **Full-text search:** an FTS5 table with `tokenize="trigram"`, so a fragment like *forderung* finds
  *Rückforderung* (German compounds). It covers the name, German text, English text and tags, ranks with
  bm25 and returns snippets. Keep it in sync after OCR or translation, rename, tag change and delete.
  `GET /api/search?q=&folder=&tag=`.
- **AI tags and folder:** suggested only when the user clicks (like AI naming), preferring existing
  tags, applied only by the user. Never automatic.
- **Ask your documents (RAG):** Ollama embeddings (model chosen later, candidates bge-m3 or
  qwen3-embedding), chunks of about 800 characters, brute-force cosine with numpy fused with FTS by
  reciprocal rank, and a streamed `/api/ask` answer that cites document and page.
- **Known gaps:** `GET /api/docs` returns every page's OCR `lines`, and the Library polls it every 3
  seconds; strip `lines` and `pdf_lines` from list responses before the archive gets large. Folders
  can only be nested by creating a subfolder, not by dragging.
