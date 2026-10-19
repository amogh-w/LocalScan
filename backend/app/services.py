"""Start, stop and watch the helper services (Ollama, PaddleOCR) from the Settings page.

Nothing here runs by itself: a service starts only when the user clicks Start. Ollama and the separate PaddleOCR
server (engine "paddle_http") are programs on this PC that we launch hidden, with their output in data/logs/<id>.log.
With the in-process engine ("paddle_local") the "service" is the loaded models: Start loads them onto the GPU now
(otherwise they load on the first page), Stop frees the GPU memory.
"""
import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import psutil

from .config import settings
from .ocr import paddle_local

LOG_DIR = settings.data_dir / "logs"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ServiceError(Exception):
    """A user-facing reason a service could not be started or stopped."""


class Service(Protocol):
    id: str
    name: str

    def status(self) -> dict: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def logs(self, lines: int) -> str: ...


def _tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 64 * 1024))  # the last 64 KB is plenty for a few hundred lines
        text = f.read().decode("utf-8", "replace")
    return "\n".join(text.splitlines()[-lines:])


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _listener(port: int) -> psutil.Process | None:
    """The process that listens on `port`, if any."""
    for c in psutil.net_connections(kind="tcp"):
        if c.status == psutil.CONN_LISTEN and c.laddr.port == port and c.pid:
            try:
                return psutil.Process(c.pid)
            except psutil.Error:
                return None
    return None


def _kill_tree(p: psutil.Process) -> None:
    try:
        procs = [*p.children(recursive=True), p]
    except psutil.NoSuchProcess:
        return  # already gone, for example killed with its parent
    for x in procs:
        try:
            x.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(procs, timeout=5)


class ProcessService:
    """A program that listens on a port. `command` is called when starting, so config changes apply at once."""

    def __init__(self, id: str, name: str, command: Callable[[], list[str]], port: Callable[[], int],
                 cwd: Callable[[], str | None] = lambda: None, owners: tuple[str, ...] = ()) -> None:
        self.id, self.name = id, name
        self._command, self._port, self._cwd, self._owners = command, port, cwd, owners
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def log_path(self) -> Path:
        return LOG_DIR / f"{self.id}.log"

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> dict:
        port = self._port()
        if _listening(port):
            ours = self._alive()
            return {"state": "running", "detail": f"port {port}" + ("" if ours else " (started outside Local Scan)")}
        if self._alive():
            return {"state": "starting", "detail": f"waiting for port {port}"}
        if self._proc is not None and self._proc.returncode:
            return {"state": "stopped", "detail": f"exited with code {self._proc.returncode}, see the logs"}
        return {"state": "stopped", "detail": ""}

    def start(self) -> None:
        with self._lock:
            if _listening(self._port()) or self._alive():
                return
            command = self._command()
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            out = self.log_path.open("ab")
            out.write(f"\n--- starting {' '.join(command)}\n".encode())
            out.flush()
            try:
                self._proc = subprocess.Popen(command, cwd=self._cwd(), stdin=subprocess.DEVNULL, stdout=out,
                                              stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            except OSError as e:
                raise ServiceError(f"Could not start {self.name}: {e}") from e

    def stop(self) -> None:
        with self._lock:
            port = self._port()
            targets: list[psutil.Process] = []
            if self._alive():
                try:
                    targets.append(psutil.Process(self._proc.pid))  # type: ignore[union-attr]
                except psutil.NoSuchProcess:
                    pass  # it just exited
            owner = _listener(port)
            if owner and all(owner.pid != t.pid for t in targets):
                ours = {c.pid for t in targets for c in t.children(recursive=True)}
                if owner.pid in ours or owner.name().lower().startswith(self._owners or ("\0",)):
                    targets.append(owner)
                else:
                    raise ServiceError(f"Port {port} is used by {owner.name()}, which is not {self.name}. Not stopping it.")
            for t in targets:
                _kill_tree(t)
            self._proc = None

    def logs(self, lines: int) -> str:
        return _tail(self.log_path, lines)


class LocalPaddle:
    """PaddleOCR inside this process: running means the models are on the GPU."""

    id, name = "paddle", "PaddleOCR (in this app)"

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._error = ""

    def _cfg(self) -> tuple[str, str]:
        c = settings.section("ocr", "paddle_local")
        return c.get("lang", ""), c.get("device", "gpu")

    def status(self) -> dict:
        if self._thread and self._thread.is_alive():
            return {"state": "starting", "detail": "loading the models"}
        if paddle_local.loaded(*self._cfg()):
            return {"state": "running", "detail": f"models loaded on {self._cfg()[1]}"}
        return {"state": "stopped", "detail": self._error or "models load on the first page, or when you click Start"}

    def start(self) -> None:
        if (self._thread and self._thread.is_alive()) or paddle_local.loaded(*self._cfg()):
            return
        self._error = ""

        def load() -> None:
            try:
                paddle_local.preload(*self._cfg())
            except Exception as e:  # noqa: BLE001 - shown in the UI
                self._error = f"loading failed: {e}"

        self._thread = threading.Thread(target=load, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        paddle_local.unload()  # waits for a page that is being read
        self._error = ""

    def logs(self, lines: int) -> str:
        # The models log into the app's own log, which exists only when it runs from the tray (run.bat).
        return _tail(LOG_DIR / "server.log", lines)


def _local_url(url: str, what: str) -> int:
    u = urlparse(url)
    if (u.hostname or "") not in LOCAL_HOSTS:
        raise ServiceError(f"{what} is set to {url}, which is not on this PC, so Local Scan cannot start it.")
    return u.port or 80


def _ollama_command() -> list[str]:
    exe = shutil.which(settings.section("services", "ollama").get("command", "ollama"))
    if not exe:
        guess = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        exe = str(guess) if guess.exists() else None
    if not exe:
        raise ServiceError("Ollama is not installed (or not on PATH). Set services.ollama.command in config.toml.")
    _local_url(settings.section("translator", "ollama")["url"], "The Ollama URL")
    return [exe, "serve"]


def _ollama_port() -> int:
    u = urlparse(settings.section("translator", "ollama")["url"])
    return u.port or 11434


def _paddle_http_command() -> list[str]:
    cfg = settings.section("services", "paddle_server")
    python = Path(cfg.get("python", "")).expanduser()
    if not python.is_file():
        raise ServiceError("Set services.paddle_server.python and cwd in config.toml to start the PaddleOCR server.")
    port = _local_url(settings.section("ocr", "paddle_http")["url"], "The PaddleOCR URL")
    return [str(python), "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", str(port)]


def _paddle_http_cwd() -> str | None:
    cwd = settings.section("services", "paddle_server").get("cwd")
    return str(Path(cwd).expanduser()) if cwd else None


def _paddle_http_port() -> int:
    return urlparse(settings.section("ocr", "paddle_http")["url"]).port or 8000


_ollama = ProcessService("ollama", "Ollama", _ollama_command, _ollama_port, owners=("ollama",))
_paddle_http = ProcessService("paddle", "PaddleOCR server", _paddle_http_command, _paddle_http_port,
                              _paddle_http_cwd, owners=("python",))
_paddle_local = LocalPaddle()


def paddle() -> Service:
    """The PaddleOCR service for the engine chosen in Settings."""
    return _paddle_http if settings.values["ocr"]["engine"] == "paddle_http" else _paddle_local


def listing() -> list[Service]:
    return [_ollama, paddle()]


def get(id: str) -> Service | None:
    return next((s for s in listing() if s.id == id), None)
