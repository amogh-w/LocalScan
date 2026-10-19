"""The helper-service controller: start a throwaway server, see it listen, read its log, stop it."""
import socket
import sys
import time

import pytest

from app import services


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(cond, secs=15):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "LOG_DIR", tmp_path)
    port = free_port()
    s = services.ProcessService("demo", "Demo", lambda: [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                                lambda: port, owners=("python",))
    yield s
    s.stop()


def test_start_stop_and_logs(svc):
    assert svc.status()["state"] == "stopped"
    svc.start()
    assert wait_for(lambda: svc.status()["state"] == "running")
    assert "starting" in svc.logs(50)
    svc.stop()
    assert wait_for(lambda: svc.status()["state"] == "stopped")


def test_start_twice_is_harmless(svc):
    svc.start()
    svc.start()
    assert wait_for(lambda: svc.status()["state"] == "running")


def test_refuses_to_stop_a_stranger(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "LOG_DIR", tmp_path)
    with socket.socket() as srv:  # this test process owns the port, and its name does not match the owner
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        s = services.ProcessService("x", "Other", lambda: ["x"], lambda: port, owners=("definitely-not-python",))
        with pytest.raises(services.ServiceError):
            s.stop()


def test_missing_program_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "LOG_DIR", tmp_path)
    s = services.ProcessService("x", "Nope", lambda: [str(tmp_path / "nope.exe")], free_port)
    with pytest.raises(services.ServiceError):
        s.start()
