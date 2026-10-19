"""Local Scan in the Windows system tray: starts the server without a console window and gives it a tray menu.

Run with `run.bat -Tray` (or start it at login from the menu). Menu: open the app, copy the phone link, start with
Windows, open the log folder, restart, exit. Double-clicking the icon opens the app. Modelled on the cuppa shell
(shared/shell.rs), which does the same for the Rust remotes.
"""
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PORT = 8010
URL = f"http://localhost:{PORT}"
LOG_DIR = ROOT / "data" / "logs"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "LocalScan"
NO_WINDOW = subprocess.CREATE_NO_WINDOW
server: subprocess.Popen | None = None
lock = threading.Lock()


def message(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Local Scan", 0x40)


def lan_url() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outbound network interface
        return f"http://{s.getsockname()[0]}:{PORT}"
    except OSError:
        return ""
    finally:
        s.close()


def listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.3):
            return True
    except OSError:
        return False


def log_file():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return open(LOG_DIR / "server.log", "ab")


def build_frontend() -> None:
    """Same check run.bat makes: build when there is no build yet or a source is newer."""
    if subprocess.run(["uv", "run", "python", "scripts/needs_build.py"], cwd=ROOT, creationflags=NO_WINDOW).returncode == 0:
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", shell=True, creationflags=NO_WINDOW,
                       stdout=log_file(), stderr=subprocess.STDOUT)


def start_server() -> None:
    global server
    with lock:
        if server and server.poll() is None:
            return
        build_frontend()
        out = log_file()
        server = subprocess.Popen(
            ["uv", "run", "--extra", "paddle", "--directory", "backend", "uvicorn", "app.main:app",
             "--host", "0.0.0.0", "--port", str(PORT)],
            cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
        )


def stop_server() -> None:
    global server
    with lock:
        if server and server.poll() is None:
            # uv starts uvicorn as a child, so end the whole tree
            subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], creationflags=NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        server = None


def autostart_command() -> str:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{ROOT / "scripts" / "tray.py"}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_NAME)[0] == autostart_command()
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


def icon_image() -> Image.Image:
    """The app icon (public/icon.svg) redrawn: Catppuccin Latte blue tile with a page."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, 63, 63), radius=14, fill="#1e66f5")
    d.polygon([(20, 14), (38, 14), (46, 22), (46, 50), (20, 50)], fill="#eff1f5")
    d.polygon([(38, 14), (46, 22), (38, 22)], fill="#7287fd")
    for y, x2 in ((30, 41), (36, 41), (42, 35)):
        d.line((25, y, x2, y), fill="#1e66f5", width=3)
    return img


def status() -> str:
    if server and server.poll() is not None:
        return "stopped"
    return "running" if listening() else "starting"


def main() -> None:
    # One tray at a time: a second start just opens the app.
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "LocalScanTray")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        webbrowser.open(URL)
        return
    _ = mutex

    threading.Thread(target=start_server, daemon=True).start()

    def open_app(*_):
        webbrowser.open(URL)

    def copy_link(*_):
        url = lan_url()
        if not url:
            return message("No network address found. Connect this PC to a network.")
        subprocess.run(["clip"], input=url.encode(), creationflags=NO_WINDOW)

    def toggle_autostart(icon, item):
        try:
            set_autostart(not item.checked)
        except OSError as e:
            message(f"Could not change the setting: {e}")

    def restart(*_):
        stop_server()
        threading.Thread(target=start_server, daemon=True).start()

    def quit_app(icon, *_):
        stop_server()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Local Scan", open_app, default=True),
        pystray.MenuItem("Copy phone link", copy_link),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda item: autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open log folder", lambda *_: (LOG_DIR.mkdir(parents=True, exist_ok=True), os.startfile(LOG_DIR))),
        pystray.MenuItem("Restart", restart),
        pystray.MenuItem("Exit", quit_app),
    )
    icon = pystray.Icon("localscan", icon_image(), f"Local Scan: {status()}", menu)

    def keep_tooltip():
        while True:
            time.sleep(4)
            icon.title = f"Local Scan: {status()}"

    threading.Thread(target=keep_tooltip, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
