"""Account-owned encrypted browser state and three-way, per-item synchronization."""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 4096
MAX_ORIGINS = 128


class BrowserStateError(RuntimeError):
    """Safe diagnostics only: never include browser values or provider bodies."""


def bounded(value) -> bytes:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > MAX_BYTES:
        raise BrowserStateError("Browser login state exceeds its 2 MiB synchronization limit")
    return data


def origin(value: str) -> bool:
    try:
        p = urlsplit(value)
        return (
            p.scheme in {"http", "https"}
            and bool(p.hostname)
            and p.netloc == p.hostname + (":" + str(p.port) if p.port else "")
            and not (p.path or p.query or p.fragment)
        )
    except (ValueError, TypeError):
        return False


def cookie_key(value: dict) -> str:
    return "c:" + json.dumps(
        [value["domain"], value["path"], value["name"], value.get("partitionKey")],
        sort_keys=True,
        separators=(",", ":"),
    )


def local_key(site: str, key: str) -> str:
    return "l:" + json.dumps([site, key], separators=(",", ":"))


def flatten(snapshot: dict) -> dict:
    bounded(snapshot)
    if not isinstance(snapshot, dict) or set(snapshot) != {"cookies", "origins"}:
        raise BrowserStateError("Invalid browser state envelope")
    cookies, origins = snapshot["cookies"], snapshot["origins"]
    if not isinstance(cookies, list) or not isinstance(origins, dict) or len(origins) > MAX_ORIGINS:
        raise BrowserStateError("Invalid browser state collection")
    values = {}
    allowed = {"name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires", "partitionKey"}
    for c in cookies:
        if not isinstance(c, dict) or set(c) - allowed:
            raise BrowserStateError("Invalid cookie fields")
        if any(not isinstance(c.get(k), str) for k in ["name", "value", "domain", "path"]):
            raise BrowserStateError("Invalid cookie identity")
        if not c["domain"] or not c["path"].startswith("/") or any(x in c["domain"] for x in "/:@\\\x00\r\n"):
            raise BrowserStateError("Invalid cookie scope")
        if any(k in c and not isinstance(c[k], bool) for k in ["secure", "httpOnly"]):
            raise BrowserStateError("Invalid cookie flags")
        if "sameSite" in c and (not isinstance(c["sameSite"], str) or c["sameSite"] not in {"Strict", "Lax", "None"}):
            raise BrowserStateError("Invalid cookie same-site mode")
        if "expires" in c and (isinstance(c["expires"], bool) or not isinstance(c["expires"], (float, int))):
            raise BrowserStateError("Invalid cookie expiration")
        partition = c.get("partitionKey")
        if partition is not None and (
            not isinstance(partition, dict)
            or set(partition) != {"topLevelSite", "hasCrossSiteAncestor"}
            or not origin(partition["topLevelSite"])
            or not isinstance(partition["hasCrossSiteAncestor"], bool)
        ):
            raise BrowserStateError("Invalid partitioned cookie scope")
        key = cookie_key(c)
        if key in values:
            raise BrowserStateError("Duplicate cookie identity")
        values[key] = c
    for site, items in origins.items():
        if not origin(site) or not isinstance(items, dict):
            raise BrowserStateError("Invalid local storage origin")
        for key, value in items.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise BrowserStateError("Invalid local storage item")
            values[local_key(site, key)] = value
    if len(values) > MAX_ITEMS:
        raise BrowserStateError("Browser state exceeds its 4096 item synchronization limit")
    return values


def merge(current: dict, base: dict | None, snapshot: dict) -> tuple[dict, int]:
    """Remote wins a concurrent conflict; stale peers cannot resurrect a deletion."""
    observed = flatten(snapshot)
    desired = dict(current)
    keys = set(observed)
    if base is not None:
        keys.update(k for k in base if k.startswith("c:") or json.loads(k[2:])[0] in snapshot["origins"])
    conflicts = 0
    for key in keys:
        value = observed.get(key)
        if base is None:
            if key not in desired:
                desired[key] = value
        elif value != base.get(key):
            if current.get(key) == base.get(key):
                desired[key] = value
            else:
                conflicts += 1
    if len(desired) > MAX_ITEMS:
        raise BrowserStateError("Account browser state exceeds its 4096 item limit")
    bounded(desired)
    return desired, conflicts


class BrowserStates:
    """Private host vault; secrets never cross the capability/Runtime boundary."""

    def __init__(self, db, key_path: Path):
        self.db = db
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_bytes(32))
                f.flush()
                os.fsync(f.fileno())
        key_path.chmod(0o600)
        self.cipher = AESGCM(key_path.read_bytes())
        db.executescript("""
          CREATE TABLE IF NOT EXISTS browser_accounts (
            tenant TEXT NOT NULL, owner TEXT NOT NULL, payload BLOB NOT NULL,
            PRIMARY KEY(tenant,owner));
          CREATE TABLE IF NOT EXISTS browser_peers (
            desktop TEXT PRIMARY KEY, payload BLOB, pending INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'waiting', synced REAL, conflicts INTEGER NOT NULL DEFAULT 0, epoch TEXT NOT NULL DEFAULT '');
        """)

    def seal(self, value, aad: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self.cipher.encrypt(nonce, bounded(value), aad.encode())

    def open(self, blob: bytes, aad: str):
        return json.loads(self.cipher.decrypt(blob[:12], blob[12:], aad.encode()))

    def state(self, row):
        account = self.db.execute(
            "SELECT payload FROM browser_accounts WHERE tenant=? AND owner=?", (row["tenant"], row["owner"])
        ).fetchone()
        peer = self.db.execute("SELECT * FROM browser_peers WHERE desktop=?", (row["id"],)).fetchone()
        aad = row["tenant"] + ":" + row["owner"]
        current = self.open(account[0], aad) if account else {}
        base = self.open(peer["payload"], aad + ":" + row["id"]) if peer and peer["payload"] else None
        return current, base, bool(peer and peer["pending"])

    def prepare(self, row, snapshot, epoch=""):
        current, base, pending = self.state(row)
        peer = self.db.execute("SELECT epoch FROM browser_peers WHERE desktop=?", (row["id"],)).fetchone()
        if epoch and (not peer or peer[0] != epoch):
            # A browser restart discards session cookies; absence on first contact is
            # not a user logout. Canonical tombstones still block stale resurrection.
            base = None
        # An unacknowledged apply must reconcile before this peer can publish again.
        desired, conflicts = (current, 0) if pending else merge(current, base, snapshot)
        # Expiration is authoritative even when every source browser is asleep.
        now = time.time()
        desired = {
            k: None if k.startswith("c:") and v is not None and 0 < v.get("expires", -1) <= now else v
            for k, v in desired.items()
        }
        aad = row["tenant"] + ":" + row["owner"]
        with self.db:
            if (
                desired != current
                or not self.db.execute(
                    "SELECT 1 FROM browser_accounts WHERE tenant=? AND owner=?", (row["tenant"], row["owner"])
                ).fetchone()
            ):
                self.db.execute(
                    "INSERT INTO browser_accounts VALUES(?,?,?) ON CONFLICT(tenant,owner) DO UPDATE SET payload=excluded.payload",
                    (row["tenant"], row["owner"], self.seal(desired, aad)),
                )
            self.db.execute(
                "INSERT INTO browser_peers(desktop,pending,status,conflicts,epoch) VALUES(?,1,'syncing',?,?) "
                "ON CONFLICT(desktop) DO UPDATE SET pending=1,status='syncing',conflicts=excluded.conflicts,epoch=excluded.epoch",
                (row["id"], conflicts, epoch),
            )
        return desired

    def acknowledge(self, row, desired, stamp):
        aad = row["tenant"] + ":" + row["owner"] + ":" + row["id"]
        _, previous, _ = self.state(row)
        with self.db:
            if previous != desired:
                self.db.execute(
                    "UPDATE browser_peers SET payload=? WHERE desktop=?", (self.seal(desired, aad), row["id"])
                )
            self.db.execute(
                "UPDATE browser_peers SET pending=0,status='synced',synced=? WHERE desktop=?", (stamp, row["id"])
            )

    def status(self, ident, status):
        with self.db:
            self.db.execute(
                "INSERT INTO browser_peers(desktop,status) VALUES(?,?) ON CONFLICT(desktop) DO UPDATE SET status=excluded.status",
                (ident, status),
            )

    def view(self, ident):
        peer = self.db.execute("SELECT status,synced,conflicts FROM browser_peers WHERE desktop=?", (ident,)).fetchone()
        return dict(peer) if peer else {"status": "waiting", "synced": None, "conflicts": 0}
