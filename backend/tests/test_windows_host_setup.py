"""Installer admission tests execute only against redirected files and fake commands."""

import runpy
import sqlite3
import subprocess
import uuid
from pathlib import Path

import pytest

INSTALLER = Path(__file__).parents[2] / "deploy/desktop-automation/setup-windows-host.py"


def install(tmp_path, monkeypatch, *, foreign=False, active=False, configured=False, restart_fails=False):
    root = tmp_path / "root/yaojin/agent-windows-sandbox-20261029"
    private = root / "private"
    private.mkdir(parents=True)
    ident = str(uuid.uuid4())
    with sqlite3.connect(private / "state.sqlite") as db:
        db.execute("CREATE TABLE desktops (id TEXT)")
        if not foreign:
            db.execute("INSERT INTO desktops VALUES (?)", (ident,))
    etc = tmp_path / "etc/libvirt"
    etc.mkdir(parents=True)
    config = etc / "qemu.conf"
    before = 'save_image_format = "zstd"\n' if configured else "# host-owned configuration\n"
    config.write_text(before)
    (tmp_path / "etc/systemd/system").mkdir(parents=True)
    calls = []
    original_path = Path

    def path(value, *parts):
        p = original_path(value, *parts)
        return tmp_path / str(p).lstrip("/") if p.is_absolute() else p

    def run(args, **kwargs):
        calls.append(args)
        stdout = ""
        if args[:5] == ["virsh", "-c", "qemu:///system", "list", "--all"]:
            stdout = ident + "\n" if "--uuid" in args else ""
        if "domstate" in args:
            stdout = "running\n" if active else "shut off\n"
        if "net-info" in args:
            stdout = "Active:         yes\n"
        if (
            restart_fails
            and args == ["systemctl", "restart", "virtqemud.service"]
            and sum(c == args for c in calls) == 1
        ):
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    with monkeypatch.context() as patch:
        patch.setattr("pathlib.Path", path)
        patch.setattr("subprocess.run", run)
        try:
            runpy.run_path(str(INSTALLER))
        except (RuntimeError, subprocess.CalledProcessError) as error:
            return config, before, calls, error
    return config, before, calls, None


def test_owned_stopped_host_can_enable_compression(tmp_path, monkeypatch):
    config, _, calls, error = install(tmp_path, monkeypatch)
    assert error is None
    assert 'save_image_format = "zstd"' in config.read_text()
    assert ["systemctl", "restart", "virtqemud.service"] in calls


@pytest.mark.parametrize("reason", ["foreign", "active"])
def test_initial_compression_rejects_unowned_or_active_domains(tmp_path, monkeypatch, reason):
    config, before, calls, error = install(tmp_path, monkeypatch, **{reason: True})
    assert isinstance(error, RuntimeError)
    assert config.read_text() == before
    assert ["systemctl", "restart", "virtqemud.service"] not in calls


def test_existing_setting_never_restarts_driver(tmp_path, monkeypatch):
    config, before, calls, error = install(tmp_path, monkeypatch, configured=True, active=True)
    assert error is None and config.read_text() == before
    assert ["systemctl", "restart", "virtqemud.service"] not in calls


def test_driver_restart_failure_restores_original_config(tmp_path, monkeypatch):
    config, before, calls, error = install(tmp_path, monkeypatch, restart_fails=True)
    assert isinstance(error, subprocess.CalledProcessError)
    assert config.read_text() == before
    assert calls.count(["systemctl", "restart", "virtqemud.service"]) == 2
