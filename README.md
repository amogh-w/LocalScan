# Local Scan

Local Scan is a local replacement for "Adobe Scan, then Google Translate". Photograph German letters on
your phone, fix the crop by dragging the four corners, and get three PDFs back, all without anything
leaving your PC:

- **Original PDF**: the cleaned scan, with a searchable text layer
- **Translated PDF**: same layout, logos, stamps and signatures, with the text replaced by its translation
- **Side by side**: original and translation next to each other

Each opens in a new browser tab.

OCR runs on the GPU with PaddleOCR (in-process by default) and translation on your local Ollama.

## Run

```powershell
.\run.ps1
```

Open `http://localhost:8010` on the PC, or scan the QR code it prints with your phone (same Wi-Fi).
Needs `uv`, Node and a running Ollama. The first run installs everything, including PaddleOCR GPU
(`uv sync --extra paddle`). The first page after a start takes about a minute while the OCR models warm up
on the GPU; after that a page takes well under a second.

Open **Settings** (⚙) to pick the Ollama model and the OCR engine. The status section shows whether both respond.

Port 8010 is used because `Projects/Paddle/start_server.bat` takes 8000 and kills anything else on it.

### GPU note (RTX 50xx)

Paddle must be the **CUDA 12.9** build (`paddle-cu129` index in `pyproject.toml`). The cu126 build loads on a
Blackwell card but returns garbage text. Paddle's Windows wheel doesn't declare its CUDA DLL packages, so the
`paddle` extra lists the `nvidia-*-cu12` wheels explicitly.

## Configuration

`config.toml` holds the defaults. Changes made on the Settings page are stored in `data/settings.json`.

OCR engines:
- `paddle_local` (default): PaddleOCR inside this app on the GPU, using the models in `~/.paddlex`
- `paddle_http`: an OCR server. `ocr.paddle_http.request` selects the format: `multipart` (the
  `Projects/Paddle` server), `paddlex` (PaddleX serving) or `paddlehub` (PaddleHub serving)

## Workflow

1. **New scan**, then **Take photo** for each page (or **Choose photos** for several at once, or **Import PDF**
   for an existing scan or a digital PDF).
2. Corners are detected automatically. Drag them, or the edge bars, to adjust; a magnifier shows the detail.
   Rotate, reorder and pick a filter (Auto / Original / Gray / B&W) per page. **Preview** shows the result.
3. **Translate**: when it finishes, download the PDFs.

Changing a page and translating again only reruns OCR for changed pages, and translations are cached.

## Layout

```
backend/app/
  scan/       corner detection, perspective correction (with real aspect ratio recovery), filters
  ocr/        OcrEngine protocol, PaddleOCR HTTP client, line -> paragraph grouping, PDF text layer import
  translate/  Translator protocol, Ollama implementation
  render/     text erasing and the three PDFs (PyMuPDF)
  api/        FastAPI routes
  jobs.py     background worker
frontend/src/ React UI (corner editor in components/CornerEditor.tsx)
data/         documents (gitignored)
```

Adding another OCR or translation engine means one class implementing the protocol in `ocr/base.py` or
`translate/base.py`, plus a line in that package's `registry.py`.

## Develop

```powershell
uv run pytest               # backend tests
.\run.ps1 -Dev              # backend reload + Vite on :5173
```
