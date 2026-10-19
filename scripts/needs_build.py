"""Exit code 0 when the frontend must be built (no build yet, or a source file is newer), else 1 (called by run.bat)."""
import sys
from pathlib import Path

frontend = Path(__file__).resolve().parents[1] / "frontend"
dist = frontend / "dist" / "index.html"
if not dist.exists():
    sys.exit(0)
newest = max(
    (f.stat().st_mtime for root in (frontend / "src", frontend / "ui", frontend / "public", frontend / "index.html")
     for f in ([root] if root.is_file() else root.rglob("*") if root.exists() else []) if f.is_file()),
    default=0,
)
sys.exit(0 if newest > dist.stat().st_mtime else 1)
