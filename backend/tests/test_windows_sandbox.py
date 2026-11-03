"""Account/Agent isolation, fenced leases and actual provider terminal state."""

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from test_desktop_automation import fixture as fixture  # noqa: PLC0414 -- Shared capability fixture.

from app.services.desktop_automation.driver import CuaDriver, DriverFailure
from app.services.desktop_automation.sandbox_host.manager import Manager, SandboxError
from app.services.desktop_automation.sandbox_host.provider import ProviderError
from app.services.desktop_automation.settings import Settings


class Provider:
    def __init__(self, root):
        self.root = root
        self.running = set()
        self.fail_save = False

    def state(self, ident):
        return "running" if ident in self.running else "shut off"

    def start(self, ident):
        self.running.add(ident)
        (self.root / ident).touch()

    def ready(self, *args):
        return "10.253.0.10"

    def save(self, ident):
        if self.fail_save:
            raise ProviderError("Save failed")
        self.running.remove(ident)
        return "saved"


@pytest.fixture
def manager(tmp_path):
    value = Manager(tmp_path / "state.sqlite", Provider(tmp_path), idle_seconds=10, lease_seconds=5)
    clock = [1000.0]
    value.clock = lambda: clock[0]
    yield value, clock
    value.db.close()


def scope():
    return {"tenant_id": str(uuid.uuid4()), "owner_id": str(uuid.uuid4()), "agent_id": str(uuid.uuid4())}


def test_identity_survives_manager_restart_and_never_merges_accounts(manager):
    m, _ = manager
    first = scope()
    a = m.create(first)
    b = m.create({**first, "agent_id": str(uuid.uuid4())})
    c = m.create({**first, "owner_id": str(uuid.uuid4())})
    d = m.create({**first, "tenant_id": str(uuid.uuid4())})
    assert len({a, b, c, d}) == 4
    assert m.create(first) == a
    assert len({m.row(x)["token"] for x in [a, b, c, d]}) == 4
    assert len(m.listing(first["tenant_id"], first["owner_id"])) == 2
    assert "password" not in json.dumps(m.listing(first["tenant_id"], first["owner_id"]))
    assert "token" not in m.view(m.row(a))
    with pytest.raises(SandboxError) as error:
        m.authorize(a, first["tenant_id"], str(uuid.uuid4()))
    assert error.value.status == 404
    path = m.provider.root / "state.sqlite"
    reopened = Manager(path, m.provider)
    assert reopened.create(first) == a
    reopened.db.close()


async def test_live_lease_blocks_save_other_task_and_expired_nonce_is_fenced(manager):
    m, clock = manager
    a = m.create(scope())
    m.lease(a, "run_first", "n" * 40)
    await m.ensure(a)
    with pytest.raises(SandboxError):
        await m.suspend(a)
    with pytest.raises(SandboxError):
        m.lease(a, "run_second", "z" * 40)
    assert a in m.provider.running
    clock[0] += 6
    with pytest.raises(SandboxError):
        m.lease(a, "run_first", "n" * 40)
    await m.sweep()
    with pytest.raises(SandboxError):
        m.lease(a, "run_first", "n" * 40)
    clock[0] += 11
    await m.sweep()
    assert a not in m.provider.running
    assert m.row(a)["state"] == "saved" and not m.row(a)["compute_held"]
    assert (m.provider.root / a).exists()
    await m.ensure(a)
    assert a in m.provider.running
    assert m.row(a)["id"] == a and m.row(a)["personalized"]


async def test_failure_does_not_claim_memory_release_and_capacity_is_bounded(manager):
    m, _ = manager
    a, b, c = [m.create(scope()) for _ in range(3)]
    await m.ensure(a)
    await m.ensure(b)
    with pytest.raises(SandboxError) as error:
        await m.ensure(c)
    assert error.value.status == 429 and c not in m.provider.running
    m.provider.fail_save = True
    with pytest.raises(SandboxError):
        await m.suspend(a)
    assert a in m.provider.running and m.row(a)["compute_held"] and m.row(a)["state"] == "error"
    with pytest.raises(SandboxError):
        await m.ensure(c)


def test_distinct_agents_can_lease_in_parallel_same_agent_cannot(manager):
    m, _ = manager
    s = scope()
    a = m.create(s)
    b = m.create({**s, "agent_id": str(uuid.uuid4())})
    m.lease(a, "run_a", "a" * 40)
    m.lease(b, "run_b", "b" * 40)
    with pytest.raises(SandboxError):
        m.lease(a, "run_other", "c" * 40)


async def test_gateway_shares_one_run_lease_and_unbound_actions_never_fall_back(tmp_path, monkeypatch):
    config = Settings(
        str(uuid.uuid4()),
        "http://old-shared-desktop",
        "private",
        "http://mcp",
        "sign",
        tmp_path,
        str(uuid.uuid4()),
        sandbox_url="http://private-host",
        sandbox_token="x" * 40,
    )
    driver = CuaDriver(config)
    with pytest.raises(DriverFailure, match="authenticated"):
        await driver.call("unbound", "click", {}, "write-1")
    gateway = driver.sandbox
    tenant, owner, agent, run = [uuid.uuid4() for _ in range(4)]
    for session in ["computer_a", "observe_a"]:
        gateway.bind(session, tenant, owner, agent, "run_" + run.hex)
    assert gateway.bindings["computer_a"]["nonce"] == gateway.bindings["observe_a"]["nonce"]
    with pytest.raises(DriverFailure):
        gateway.bind("computer_a", tenant, uuid.uuid4(), agent, "run_" + run.hex)
    calls = []

    async def request(path, payload, **kwargs):
        calls.append((path, payload))
        return {"ok": True}

    monkeypatch.setattr(gateway, "request", request)
    await gateway.release("observe_a", {})
    assert not calls and "computer_a" in gateway.bindings
    await gateway.release("computer_a", {})
    assert calls[0][0] == "/v1/release" and not gateway.bindings


async def test_private_host_api_enforces_token_owner_and_literal_route(manager):
    from app.services.desktop_automation.sandbox_host.application import app

    m, _ = manager
    app.state.manager = m
    app.state.token = "t" * 40
    first = scope()
    ident = m.create(first)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://host") as client:
        query = {"tenant": first["tenant_id"], "owner": first["owner_id"]}
        assert (await client.get("/v1/desktops", params=query)).status_code == 401
        headers = {"Authorization": "Bearer " + app.state.token}
        assert len((await client.get("/v1/desktops", params=query, headers=headers)).json()) == 1
        denied = await client.post(
            f"/v1/desktops/{ident}/save", json={**first, "owner_id": str(uuid.uuid4())}, headers=headers
        )
        assert denied.status_code == 404 and not m.provider.running


def test_only_explicit_preexisting_runs_retain_the_legacy_desktop(tmp_path):
    from app.services.desktop_automation.service import AutomationService

    tenant, owner, agent, legacy = [uuid.uuid4() for _ in range(4)]
    config = Settings(
        str(tenant),
        "http://old",
        "private",
        "http://mcp",
        "sign",
        tmp_path,
        str(uuid.uuid4()),
        sandbox_url="http://private-host",
        sandbox_token="x" * 40,
        legacy_run_ids=(str(legacy),),
    )
    service = AutomationService(config)
    user = SimpleNamespace(id=owner, tenant_id=tenant, is_active=True)
    actor = SimpleNamespace(id=legacy, origin_user_id=owner, agent_id=agent)
    service.bind_desktop("observe_legacy", user, actor=actor)
    assert "observe_legacy" in service.driver.legacy_sessions
    assert not service.driver.sandbox.bindings
    actor.id = uuid.uuid4()
    service.bind_desktop("observe_managed", user, actor=actor)
    assert "observe_managed" not in service.driver.legacy_sessions
    assert service.driver.sandbox.bindings["observe_managed"]["scope"]["owner_id"] == str(owner)


def test_provider_absence_requires_successful_domain_inventory(tmp_path, monkeypatch):
    from app.services.desktop_automation.sandbox_host.provider import Libvirt

    ident = str(uuid.uuid4())
    p = Libvirt(tmp_path, tmp_path / "template")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="provider unavailable"))
    monkeypatch.setattr(p, "command", lambda args: ident)
    with pytest.raises(ProviderError, match="unconfirmed"):
        p.state(ident)
    monkeypatch.setattr(p, "command", lambda args: "")
    assert p.state(ident) == "absent"

    def unavailable(args):
        raise ProviderError("inventory unavailable")

    monkeypatch.setattr(p, "command", unavailable)
    with pytest.raises(ProviderError, match="inventory unavailable"):
        p.state(ident)


def test_initial_personalization_waits_for_a_new_interactive_logon(tmp_path, monkeypatch):
    from app.services.desktop_automation.sandbox_host.provider import Libvirt

    p = Libvirt(tmp_path, tmp_path / "template")
    commands = []
    responses = iter(
        [
            "oldboot",
            "",
            "oldboot\nHOST\\Clawith",
            "newboot\nHOST\\Clawith",
            "",
            "newboot\nHOST\\Clawith",
            "finalboot\nHOST\\Clawith",
            "",
        ]
    )

    def powershell(ident, source):
        commands.append(source)
        return next(responses)

    monkeypatch.setattr(p, "powershell", powershell)
    monkeypatch.setattr(p, "initialize_shell", lambda ident: None)
    monkeypatch.setattr(p, "upload_bridge", lambda ident: None)
    monkeypatch.setattr(p, "upload_browser", lambda ident: None)
    monkeypatch.setattr(p, "configure_browser", lambda ident: None)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    p.personalize(str(uuid.uuid4()), "private-token", "private-password")
    assert len(commands) == 8
    assert "shutdown.exe /r" in commands[1]
    assert "DefaultDomainName $env:COMPUTERNAME" in commands[1]
    assert not any("Set-LocalUser" in c for c in commands[2:])


async def test_recording_shortcut_keeps_the_selected_agent_and_rejects_foreign_desktop(fixture, monkeypatch):
    from fastapi import HTTPException
    from test_desktop_automation import USER

    from app.services.desktop_automation.sandbox import DesktopInventory

    service, _, sessions = fixture
    inventory = DesktopInventory(service)
    agent, desktop = uuid.uuid4(), uuid.uuid4()

    async def listing(db, user):
        return [{"id": str(desktop), "agent_id": str(agent), "agent_name": "采购专员"}]

    monkeypatch.setattr(inventory, "listing", listing)
    async with sessions() as db:
        value = await inventory.recording_workflow(db, USER, desktop)
        workflow = await service.workflow(db, USER, uuid.UUID(value["id"]))
        assert workflow.desktop_agent_id == agent
        with pytest.raises(HTTPException) as error:
            await inventory.recording_workflow(db, USER, uuid.uuid4())
        assert error.value.status_code == 404


async def test_first_boot_never_dispatches_input_until_a_fresh_observation(manager, monkeypatch):
    m, _ = manager
    observed = []
    client = httpx.AsyncClient

    def response(request):
        observed.append(json.loads(request.content)["params"]["arguments"]["action"])
        return httpx.Response(200, json={"result": {"content": []}})

    transport = httpx.MockTransport(response)
    monkeypatch.setattr(
        "app.services.desktop_automation.sandbox_host.manager.httpx.AsyncClient",
        lambda **kw: client(transport=transport, **kw),
    )
    first = scope()

    def body(action):
        return {"params": {"arguments": {"action": action}}}

    with pytest.raises(SandboxError) as preparing:
        await m.call(first, "record_first", "a" * 40, body("click"))
    assert preparing.value.status == 425 and observed == []
    await m.call(first, "record_first", "a" * 40, body("get_desktop_state"))
    await m.call(first, "record_first", "a" * 40, body("click"))
    assert observed == ["get_desktop_state", "click"]


@pytest.mark.parametrize("ended", [False, True])
async def test_computer_rechecks_run_after_desktop_preparation(fixture, monkeypatch, ended):
    from dataclasses import replace

    from fastapi import HTTPException
    from test_desktop_computer import DB, actor

    from app.services.desktop_automation.computer import Computer

    s, _, _ = fixture
    s.config = replace(s.config, sandbox_url="http://private-host")
    s.driver.runtime_contexts = {}
    value = actor()
    db = DB(value)
    calls = []

    async def refresh(row):
        row.lane_held = not ended

    async def call(*args):
        calls.append(args)
        return {"content": []}

    monkeypatch.setattr(db, "refresh", refresh, raising=False)
    monkeypatch.setattr(s, "bind_desktop", lambda *a, **k: None)
    monkeypatch.setattr(s.driver, "call", call, raising=False)
    computer = Computer(s)
    if ended:
        with pytest.raises(HTTPException) as error:
            await computer.call(db, value, {"action": "click", "params": {}})
        assert error.value.status_code == 403 and calls == []
    else:
        await computer.call(db, value, {"action": "click", "params": {}})
        assert len(calls) == 1
    await computer.close()


@pytest.mark.parametrize("system_user", [False, True])
def test_initial_shell_requires_a_verified_non_system_receipt(tmp_path, monkeypatch, system_user):
    from app.services.desktop_automation.sandbox_host.provider import Libvirt

    p = Libvirt(tmp_path, tmp_path / "template")
    responses = iter(["launched", json.dumps({"ok": True, "is_system": system_user, "user": "HOST\\Clawith"})])
    monkeypatch.setattr(p, "powershell", lambda *a: next(responses))
    if system_user:
        with pytest.raises(ProviderError, match="registration failed"):
            p.initialize_shell(str(uuid.uuid4()))
    else:
        p.initialize_shell(str(uuid.uuid4()))


def test_readiness_uses_normal_capture_budget_and_keeps_one_session_across_timeout(tmp_path, monkeypatch):
    from app.services.desktop_automation.sandbox_host.provider import Libvirt

    p = Libvirt(tmp_path, tmp_path / "template")
    monkeypatch.setattr(p, "ip", lambda ident: "10.253.0.10")
    monkeypatch.setattr("time.sleep", lambda *a: None)
    sessions = []

    class DesktopHTTP:
        def __init__(self, **kwargs):
            assert kwargs["timeout"].read == 45

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return httpx.Response(200, json={"ready": True, "browser_sync_protocol": 2})

        def post(self, url, *, headers, json):
            args = json["params"]["arguments"]
            sessions.append(args["session_id"])
            if len(sessions) == 1:
                raise httpx.ReadTimeout("capture still preparing")
            content = [] if args["action"] == "release" else [{"type": "image", "data": "aW1hZ2U="}]
            return httpx.Response(200, json={"result": {"content": content}})

    monkeypatch.setattr("app.services.desktop_automation.sandbox_host.provider.httpx.Client", DesktopHTTP)
    assert p.ready(str(uuid.uuid4()), "private-token", "private-password", True) == "10.253.0.10"
    assert len(sessions) == 3 and len(set(sessions)) == 1


async def test_recovery_never_claims_an_unbound_managed_lease_was_released(fixture):
    from dataclasses import replace

    from test_desktop_automation import USER, workflow

    from app.services.desktop_automation.models import Playback

    s, engine, sessions = fixture
    s.config = replace(s.config, sandbox_url="http://private-host")
    async with sessions() as db:
        w = await workflow(s, db)
        run = Playback(
            id=uuid.uuid4(),
            tenant_id=USER.tenant_id,
            owner_id=USER.id,
            workflow_id=w.id,
            request_id="restart_recovery",
            fingerprint="a" * 64,
            status="running",
            script=w.draft,
            digest="a" * 64,
            input_summary={},
            result={},
        )
        db.add(run)
        await db.commit()
        ident = run.id
    await engine.recover()
    async with sessions() as db:
        value = await engine.get(db, USER, ident)
        assert value.status == "unknown" and not value.result["release_confirmed"]


def test_network_reservations_are_unique_stable_and_never_reuse_active_dhcp(tmp_path, monkeypatch):
    from xml.etree import ElementTree as ET

    from app.services.desktop_automation.sandbox_host.provider import Libvirt

    p = Libvirt(tmp_path, tmp_path / "template")
    hosts = []

    def command(args):
        if "net-dumpxml" in args:
            return (
                "<network><ip><dhcp>"
                + "".join(ET.tostring(h, encoding="unicode") for h in hosts)
                + "</dhcp></ip></network>"
            )
        if "net-dhcp-leases" in args:
            return "2026-10-30 12:00:00 52:54:00:00:00:01 ipv4 10.253.0.10/24 existing"
        if "net-update" in args:
            hosts.append(ET.fromstring(args[args.index("ip-dhcp-host") + 1]))
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(p, "command", command)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    first = p.network_address(a)
    second = p.network_address(b)
    assert first[0] != second[0] and first[1] == "10.253.0.11" and second[1] == "10.253.0.12"
    assert p.network_address(a) == first and len(hosts) == 2
    for i in range(13, 201):
        hosts.append(ET.Element("host", mac="52:54:00:00:00:01", ip=f"10.253.0.{i}", name="occupied_" + str(i)))
    with pytest.raises(ProviderError, match="capacity is full"):
        p.network_address(str(uuid.uuid4()))


@pytest.mark.parametrize("matching", [True, False])
def test_provider_network_target_requires_the_same_reserved_mac(tmp_path, monkeypatch, matching):
    from app.services.desktop_automation.sandbox_host.provider import Libvirt

    p = Libvirt(tmp_path, tmp_path / "template")
    ident = str(uuid.uuid4())
    monkeypatch.setattr(
        p,
        "virsh",
        lambda *a: '<domain><devices><interface><mac address="52:54:00:00:00:01"/></interface></devices></domain>',
    )
    mac = "52:54:00:00:00:01" if matching else "52:54:00:00:00:02"
    monkeypatch.setattr(
        p,
        "command",
        lambda *a: (
            f'<network><ip><dhcp><host name="{p.name(ident)}" mac="{mac}" ip="10.253.0.11"/></dhcp></ip></network>'
        ),
    )
    if matching:
        assert p.ip(ident) == "10.253.0.11"
    else:
        with pytest.raises(ProviderError, match="does not match"):
            p.ip(ident)


async def test_invalid_provider_terminal_result_keeps_capacity_reserved(manager, monkeypatch):
    m, _ = manager
    ident = m.create(scope())
    await m.ensure(ident)
    monkeypatch.setattr(m.provider, "save", lambda *args: "unconfirmed")
    with pytest.raises(SandboxError, match="terminal"):
        await m.suspend(ident)
    assert m.row(ident)["state"] == "error" and m.row(ident)["compute_held"] and ident in m.provider.running


async def test_inventory_actions_hide_foreign_desktops_before_forwarding(fixture):
    from fastapi import HTTPException
    from test_desktop_automation import USER

    from app.services.desktop_automation.sandbox import DesktopInventory

    service, _, _ = fixture
    desktop = uuid.uuid4()
    calls = []

    class Gateway:
        async def request(self, path, payload=None, **kwargs):
            calls.append(path)
            if path == "/v1/desktops":
                assert kwargs["query"]["owner"] == str(USER.id)
                return [{"id": str(desktop)}]
            return {"id": str(desktop), "state": "saved"}

    service.driver.sandbox = Gateway()
    inventory = DesktopInventory(service)
    for action in ["start", "save"]:
        with pytest.raises(HTTPException) as error:
            await inventory.action(USER, uuid.uuid4(), action)
        assert error.value.status_code == 404
    assert calls == ["/v1/desktops", "/v1/desktops"]
    assert (await inventory.action(USER, desktop, "save"))["state"] == "saved"
    assert calls[-1] == f"/v1/desktops/{desktop}/save"


def test_existing_host_database_upgrade_preserves_account_identity_and_guest_credentials(manager):
    m, _ = manager
    ident = m.create(scope())
    prior = dict(m.row(ident))
    m.db.execute("ALTER TABLE desktops DROP COLUMN browser_protocol")
    m.db.commit()
    reopened = Manager(m.provider.root / "state.sqlite", m.provider)
    try:
        row = reopened.row(ident)
        assert row["browser_protocol"] == 0
        assert (row["tenant"], row["owner"], row["agent"], row["password"], row["token"]) == tuple(
            prior[k] for k in ["tenant", "owner", "agent", "password", "token"]
        )
    finally:
        reopened.db.close()


async def test_old_ready_guest_upgrades_before_use_and_flushes_login_state_before_save(manager, monkeypatch):
    m, _ = manager
    ident = m.create(scope())
    await m.ensure(ident)
    m.db.execute("UPDATE desktops SET browser_protocol=0 WHERE id=?", (ident,))
    m.db.commit()
    events = []

    async def synchronize(value):
        assert value == ident and m.row(ident)["state"] == "ready"
        events.append("sync")

    def ready(*args):
        events.append("guest_ready")
        return "10.253.0.10"

    monkeypatch.setattr(m.provider, "ready", ready)
    m.browser_sync = SimpleNamespace(synchronize=synchronize)
    await m.ensure(ident)
    assert events == ["guest_ready", "sync"] and m.row(ident)["browser_protocol"] == 2
    await m.ensure(ident)
    assert events == ["guest_ready", "sync"]
    await m.suspend(ident)
    assert events == ["guest_ready", "sync", "sync"]
    assert m.row(ident)["state"] == "saved" and ident not in m.provider.running


def test_managed_browser_shortcuts_use_locale_independent_filenames(tmp_path, monkeypatch):
    from app.services.desktop_automation.sandbox_host.provider import Libvirt

    p = Libvirt(tmp_path, tmp_path / "template")
    commands = []
    monkeypatch.setattr(p, "powershell", lambda ident, source: commands.append(source))
    p.configure_browser(str(uuid.uuid4()))
    assert "@('Business Browser','Microsoft Edge')" in commands[0]
    assert "@('业务浏览器'" not in commands[0]
