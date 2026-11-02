"""Cross-Agent state, encrypted persistence, conflict and logout behavior."""

import json
import sqlite3
import uuid

import pytest
from cryptography.exceptions import InvalidTag

from app.services.desktop_automation.sandbox_host.browser_state import (
    MAX_BYTES,
    BrowserStateError,
    BrowserStates,
    cookie_key,
    flatten,
    local_key,
    merge,
)

SITE = "https://business.example"


def snapshot(value="session-A", local="token-A"):
    return {
        "cookies": []
        if value is None
        else [
            {
                "domain": "business.example",
                "path": "/",
                "name": "sid",
                "value": value,
                "secure": True,
                "httpOnly": True,
                "sameSite": "Lax",
                "expires": -1,
            }
        ],
        "origins": {SITE: {} if local is None else {"access_token": local}},
    }


def test_login_refresh_and_logout_propagate_without_resurrection():
    initial = snapshot()
    account, _ = merge({}, None, initial)
    base = dict(account)
    refreshed, _ = merge(account, base, snapshot("session-B", "token-B"))
    assert "session-B" in json.dumps(refreshed) and "token-B" in json.dumps(refreshed)
    chosen, conflicts = merge(refreshed, base, snapshot("stale-refresh", "stale-token"))
    assert chosen == refreshed and conflicts == 2
    logged_out, _ = merge(refreshed, refreshed, snapshot(None, None))
    assert all(v is None for v in logged_out.values())
    assert merge(logged_out, base, initial)[0] == logged_out
    assert merge(logged_out, None, initial)[0] == logged_out


def test_unobserved_origins_are_not_logout_and_disjoint_edits_merge():
    base = flatten(snapshot())
    current = dict(base)
    current[local_key(SITE, "another")] = "remote"
    desired, _ = merge(current, base, {"cookies": snapshot("changed")["cookies"], "origins": {}})
    assert desired[local_key(SITE, "access_token")] == "token-A"
    assert desired[local_key(SITE, "another")] == "remote"
    assert desired[cookie_key(snapshot("changed")["cookies"][0])]["value"] == "changed"


def test_account_tenant_isolation_encryption_and_pending_apply(tmp_path):
    db = sqlite3.connect(tmp_path / "private.sqlite")
    db.row_factory = sqlite3.Row
    vault = BrowserStates(db, tmp_path / "key")
    row = {"id": str(uuid.uuid4()), "tenant": str(uuid.uuid4()), "owner": str(uuid.uuid4())}
    peer = {**row, "id": str(uuid.uuid4())}
    desired = vault.prepare(row, snapshot())
    assert vault.state(peer)[0] == desired
    for field in ["owner", "tenant"]:
        assert vault.state({**row, field: str(uuid.uuid4())})[0] == {}
    raw = db.execute("SELECT payload FROM browser_accounts").fetchone()[0]
    assert b"session-A" not in raw and b"token-A" not in raw
    with pytest.raises(InvalidTag):
        vault.open(raw, "a-different-account")
    assert vault.prepare(row, snapshot("unconfirmed", "unconfirmed")) == desired
    vault.acknowledge(row, desired, 100)
    assert vault.view(row["id"])["status"] == "synced"
    changed = vault.prepare(row, snapshot("confirmed", "confirmed"))
    assert changed != desired
    reopened = BrowserStates(db, tmp_path / "key")
    assert reopened.state(row)[0] == changed and reopened.state(row)[2]
    assert (tmp_path / "key").stat().st_mode & 0o777 == 0o600
    db.close()


@pytest.mark.parametrize(
    "invalid",
    [
        {"cookies": [], "origins": {"https://evil.example/path": {}}},
        {"cookies": [], "origins": {SITE: {"x": 42}}},
        {"cookies": [{"domain": "../path", "name": "x", "value": "v", "path": "/"}], "origins": {}},
        {"cookies": [], "origins": {}, "account": "model-selected-owner"},
        {"cookies": [], "origins": {SITE: {"x": "中" * (MAX_BYTES // 3)}}},
    ],
)
def test_invalid_or_oversized_browser_data_cannot_enter_the_vault(invalid):
    with pytest.raises(BrowserStateError):
        flatten(invalid)


def test_complete_snapshot_byte_and_item_boundaries():
    from app.services.desktop_automation.sandbox_host.browser_state import MAX_ITEMS, bounded

    value = {"cookies": [], "origins": {SITE: {"x": ""}}}
    budget = MAX_BYTES - len(bounded(value))
    value["origins"][SITE]["x"] = "a" * (budget - 1)
    flatten(value)
    value["origins"][SITE]["x"] += "a"
    assert len(bounded(value)) == MAX_BYTES
    flatten(value)
    value["origins"][SITE]["x"] += "a"
    with pytest.raises(BrowserStateError, match="2 MiB"):
        flatten(value)
    for count in [MAX_ITEMS - 1, MAX_ITEMS]:
        assert len(flatten({"cookies": [], "origins": {SITE: {str(k): "v" for k in range(count)}}})) == count
    with pytest.raises(BrowserStateError, match="4096"):
        flatten({"cookies": [], "origins": {SITE: {str(k): "v" for k in range(MAX_ITEMS + 1)}}})


def test_expired_cookie_is_pruned_even_while_source_browser_is_offline(tmp_path):
    db = sqlite3.connect(tmp_path / "state.sqlite")
    db.row_factory = sqlite3.Row
    vault = BrowserStates(db, tmp_path / "key")
    row = {"id": str(uuid.uuid4()), "tenant": str(uuid.uuid4()), "owner": str(uuid.uuid4())}
    observed = snapshot()
    observed["cookies"][0]["expires"] = 1
    desired = vault.prepare(row, observed, "a" * 64)
    assert desired[cookie_key(observed["cookies"][0])] is None
    db.close()
