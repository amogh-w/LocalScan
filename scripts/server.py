"""Start, stop and restart the Local Scan server on port 8010. The one place that knows how; run.bat and the tray use it.

    python scripts/server.py            restart: stop what listens on 8010, build the frontend if stale, start hidden
    python scripts/server.py --console  the same, but the server runs in this window
    python scripts/server.py --stop     stop it

Fast on purpose: it runs the venv's Python directly (no `uv run`, which re-checks the whole venv on every start), builds
the frontend only when a source is newer than the build, and loads no OCR models (they load on the first page, or from
Settings > Services). Install or update packages with `uv sync`, which run.bat does only when pyproject.toml or uv.lock
changed.
"""
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PORT = 8010
LOG_DIR = ROOT / "data" / "logs"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
COMMAND = [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"),
           "--host", "0.0.0.0", "--port", str(PORT)]


def listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.3):
            return True
    except OSError:
        return False


def needs_build() -> bool:
    """No build yet, or a frontend source is newer than it."""
    dist = FRONTEND / "dist" / "index.html"
    if not dist.exists():
        return True
    built = dist.stat().st_mtime
    for root in (FRONTEND / "src", FRONTEND / "ui", FRONTEND / "public"):
        if any(f.stat().st_mtime > built for f in root.rglob("*") if f.is_file()):
            return True
    return (FRONTEND / "index.html").stat().st_mtime > built


def build_frontend(out=None) -> None:
    if needs_build():
        if not (FRONTEND / "node_modules").exists():
            subprocess.run("npm install", cwd=FRONTEND, shell=True, stdout=out, stderr=subprocess.STDOUT, check=True)
        subprocess.run("npm run build", cwd=FRONTEND, shell=True, stdout=out, stderr=subprocess.STDOUT, check=True)


def stop() -> None:
    """End whatever serves port 8010, but only if it is a Python (our uvicorn), never a stranger on the port."""
    for c in psutil.net_connections(kind="tcp"):
        if c.status == psutil.CONN_LISTEN and c.laddr.port == PORT and c.pid:
            try:
                p = psutil.Process(c.pid)
                if not p.name().lower().startswith(("python", "uvicorn")):
                    raise SystemExit(f"Port {PORT} is used by {p.name()}, not Local Scan. Not stopping it.")
                procs = [*p.children(recursive=True), p]
                for x in procs:
                    x.kill()
                psutil.wait_procs(procs, timeout=5)
            except psutil.NoSuchProcess:
                pass
    end = time.time() + 5
    while listening() and time.time() < end:
        time.sleep(0.1)


def log_file():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return open(LOG_DIR / "server.log", "ab")


def start_hidden() -> subprocess.Popen:
    """Start the server without a window, its output in data/logs/server.log. Returns at once."""
    out = log_file()
    build_frontend(out)
    return subprocess.Popen(COMMAND, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                            creationflags=NO_WINDOW)


def wait_until_up(timeout: float = 60) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if listening():
            return True
        time.sleep(0.2)
    return False


def main() -> None:
    args = sys.argv[1:]
    stop()
    if "--stop" in args:
        return
    if "--console" in args:
        build_frontend()
        raise SystemExit(subprocess.call(COMMAND, cwd=ROOT))
    t = time.time()
    start_hidden()
    if wait_until_up():
        print(f"Local Scan is up on http://localhost:{PORT} ({time.time() - t:.1f} s)")
    else:
        raise SystemExit(f"The server did not come up. See {LOG_DIR / 'server.log'}")


if __name__ == "__main__":
    main()
