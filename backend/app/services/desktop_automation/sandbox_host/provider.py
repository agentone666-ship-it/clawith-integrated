"""Bounded libvirt adapter. Only manager-created UUID domains are mutable."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import pwd
import subprocess
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from .windows_bootstrap import AUTOLOGON_SECRET, CONSOLE_LAUNCHER, CONTROLLER_STARTUP, FIRST_LOGON


class ProviderError(RuntimeError):
    pass


class Libvirt:
    def __init__(self, root: Path, template: Path):
        self.root, self.template = root, template

    def command(self, args: list[str], timeout: int = 30) -> str:
        try:
            result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ProviderError("Windows lifecycle operation timed out; state needs reconciliation") from exc
        if result.returncode:
            # virsh guest-exec can contain credentials; never return its argv/output.
            detail = "" if "qemu-agent-command" in args else result.stderr[-700:]
            raise ProviderError("Windows provider operation failed: " + args[0] + " " + detail)
        return result.stdout.strip()

    @staticmethod
    def name(ident: str) -> str:
        return "clawith-ws-" + uuid.UUID(ident).hex

    def virsh(self, ident: str, operation: str, *args: str, timeout: int = 30) -> str:
        return self.command(["virsh", "-c", "qemu:///system", operation, self.name(ident), *args], timeout)

    def state(self, ident: str) -> str:
        result = subprocess.run(
            ["virsh", "-c", "qemu:///system", "domstate", self.name(ident)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode:
            # Error wording differs across libvirt builds/locales. A successful
            # domain inventory is the authority for absence, never stderr text.
            domains = self.command(["virsh", "-c", "qemu:///system", "list", "--all", "--uuid"])
            if str(uuid.UUID(ident)) not in domains.splitlines():
                return "absent"
            raise ProviderError("Windows provider state is unavailable; compute release is unconfirmed")
        return result.stdout.strip()

    def network_address(self, ident: str) -> tuple[str, str]:
        # The network reservation is the address authority. Fixed DHCP mappings
        # plus host-enforced MAC/IP filters prevent guest-side ARP poisoning.
        with (self.root / "network.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            network = ET.fromstring(self.command(["virsh", "-c", "qemu:///system", "net-dumpxml", "clawith-sandbox"]))
            hosts = network.findall("./ip/dhcp/host")
            name = self.name(ident)
            for host in hosts:
                if host.attrib.get("name") == name:
                    return host.attrib["mac"], str(ipaddress.IPv4Address(host.attrib["ip"]))
            occupied = {host.attrib["ip"] for host in hosts}
            leases = self.command(["virsh", "-c", "qemu:///system", "net-dhcp-leases", "clawith-sandbox"])
            for line in leases.splitlines():
                fields = line.split()
                if "ipv4" in fields:
                    occupied.add(fields[fields.index("ipv4") + 1].split("/")[0])
            address = next((f"10.253.0.{i}" for i in range(10, 201) if f"10.253.0.{i}" not in occupied), None)
            if address is None:
                raise ProviderError("Persistent desktop network address capacity is full")
            used_macs = {host.attrib["mac"] for host in hosts}
            for counter in range(256):
                suffix = hashlib.sha256((str(uuid.UUID(ident)) + ":" + str(counter)).encode()).hexdigest()[:8]
                mac = "52:54:" + ":".join(suffix[i : i + 2] for i in range(0, 8, 2))
                if mac not in used_macs:
                    break
            else:
                raise ProviderError("Persistent desktop network identity capacity is full")
            host = ET.Element("host", mac=mac, name=name, ip=address)
            self.command(
                [
                    "virsh",
                    "-c",
                    "qemu:///system",
                    "net-update",
                    "clawith-sandbox",
                    "add-last",
                    "ip-dhcp-host",
                    ET.tostring(host, encoding="unicode"),
                    "--live",
                    "--config",
                ]
            )
            return mac, address

    def provision(self, ident: str) -> None:
        folder = self.root / "instances" / uuid.UUID(ident).hex
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        account = pwd.getpwnam("qemu")
        os.chown(folder, account.pw_uid, account.pw_gid)
        disk = folder / "system.qcow2"
        if not disk.exists():
            self.command(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", str(self.template), str(disk)])
            disk.chmod(0o600)
        if self.state(ident) != "absent":
            return
        # Stable CPU/device layout is pinned for save/restore. Each domain gets
        # independent writable disk, NVRAM and TPM state; base is immutable.
        domain = ET.Element("domain", type="kvm")
        ET.SubElement(domain, "name").text = self.name(ident)
        ET.SubElement(domain, "uuid").text = ident
        ET.SubElement(domain, "memory", unit="MiB").text = "4096"
        ET.SubElement(domain, "vcpu").text = "2"
        osnode = ET.SubElement(domain, "os")
        ET.SubElement(osnode, "type", arch="x86_64", machine="pc-q35-rhel9.6.0").text = "hvm"
        ET.SubElement(osnode, "loader", readonly="yes", type="pflash").text = os.environ.get(
            "WINDOWS_OVMF_CODE", "/usr/share/edk2/ovmf/OVMF_CODE.fd"
        )
        ET.SubElement(
            osnode, "nvram", template=os.environ.get("WINDOWS_OVMF_VARS", "/usr/share/edk2/ovmf/OVMF_VARS.fd")
        ).text = str(folder / "nvram.fd")
        ET.SubElement(osnode, "boot", dev="hd")
        features = ET.SubElement(domain, "features")
        ET.SubElement(features, "acpi")
        ET.SubElement(features, "apic")
        hyperv = ET.SubElement(features, "hyperv", mode="custom")
        for name in ["relaxed", "vapic", "vpindex", "synic", "stimer"]:
            ET.SubElement(hyperv, name, state="on")
        ET.SubElement(domain, "cpu", mode="host-model", check="partial")
        clock = ET.SubElement(domain, "clock", offset="utc")
        ET.SubElement(clock, "timer", name="hypervclock", present="yes")
        ET.SubElement(domain, "on_poweroff").text = "destroy"
        ET.SubElement(domain, "on_reboot").text = "restart"
        devices = ET.SubElement(domain, "devices")
        ET.SubElement(devices, "emulator").text = "/usr/libexec/qemu-kvm"
        controller = ET.SubElement(devices, "controller", type="scsi", model="virtio-scsi")
        ET.SubElement(controller, "driver", queues="2")
        d = ET.SubElement(devices, "disk", type="file", device="disk")
        ET.SubElement(d, "driver", name="qemu", type="qcow2", cache="none", discard="unmap")
        ET.SubElement(d, "source", file=str(disk))
        ET.SubElement(d, "target", dev="sda", bus="scsi")
        mac, address = self.network_address(ident)
        interface = ET.SubElement(devices, "interface", type="network")
        ET.SubElement(interface, "mac", address=mac)
        ET.SubElement(interface, "source", network="clawith-sandbox")
        filtering = ET.SubElement(interface, "filterref", filter="clean-traffic")
        ET.SubElement(filtering, "parameter", name="IP", value=address)
        ET.SubElement(interface, "model", type="virtio")
        ET.SubElement(interface, "port", isolated="yes")
        channel = ET.SubElement(devices, "channel", type="unix")
        ET.SubElement(channel, "target", type="virtio", name="org.qemu.guest_agent.0")
        ET.SubElement(devices, "input", type="tablet", bus="usb")
        ET.SubElement(devices, "controller", type="usb", model="qemu-xhci")
        ET.SubElement(devices, "graphics", type="vnc", autoport="yes", listen="127.0.0.1")
        video = ET.SubElement(devices, "video")
        ET.SubElement(video, "model", type="virtio", heads="1", primary="yes")
        tpm = ET.SubElement(devices, "tpm", model="tpm-crb")
        ET.SubElement(tpm, "backend", type="emulator", version="2.0")
        xml = folder / "domain.xml"
        xml.write_text(ET.tostring(domain, encoding="unicode"))
        self.command(["virsh", "-c", "qemu:///system", "define", str(xml)])

    def start(self, ident: str) -> None:
        self.provision(ident)
        if self.state(ident) == "shut off":
            # Cold compressed snapshots can take minutes on a contended host.
            # Keep the desktop in restoring state while libvirt finishes.
            self.virsh(ident, "start", timeout=600)
        elif self.state(ident) != "running":
            raise ProviderError("Windows has an unexpected provider state; operator reconciliation required")

    def save(self, ident: str) -> str:
        if self.state(ident) == "absent":
            return "stopped"  # Successful inventory proves no owned VM is running.
        if self.state(ident) == "running":
            self.virsh(ident, "managedsave", "--running", timeout=120)
        if self.state(ident) != "shut off":
            raise ProviderError("Windows memory release is unconfirmed")
        saved = self.command(["virsh", "-c", "qemu:///system", "list", "--all", "--with-managed-save", "--uuid"])
        return "saved" if str(uuid.UUID(ident)) in saved.splitlines() else "stopped"

    def ip(self, ident: str) -> str:
        xml = ET.fromstring(self.virsh(ident, "dumpxml"))
        element = xml.find("./devices/interface/mac")
        if element is None:
            raise ProviderError("Windows network interface is missing")
        mac = element.attrib["address"]
        network = ET.fromstring(self.command(["virsh", "-c", "qemu:///system", "net-dumpxml", "clawith-sandbox"]))
        for host in network.findall("./ip/dhcp/host"):
            if host.attrib.get("name") == self.name(ident):
                if host.attrib.get("mac") != mac:
                    raise ProviderError("Windows network identity does not match its private reservation")
                return str(ipaddress.IPv4Address(host.attrib["ip"]))
        raise ProviderError("Windows private network reservation is missing")

    def powershell(self, ident: str, source: str) -> str:
        encoded = base64.b64encode(source.encode("utf-16-le")).decode()
        result = json.loads(
            self.virsh(
                ident,
                "qemu-agent-command",
                json.dumps(
                    {
                        "execute": "guest-exec",
                        "arguments": {
                            "path": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                            "arg": ["-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            "capture-output": True,
                        },
                    }
                ),
            )
        )
        pid = result["return"]["pid"]
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            status = json.loads(
                self.virsh(
                    ident,
                    "qemu-agent-command",
                    json.dumps(
                        {
                            "execute": "guest-exec-status",
                            "arguments": {"pid": pid},
                        }
                    ),
                )
            )["return"]
            if status.get("exited"):
                if status.get("exitcode") != 0:
                    raise ProviderError("Windows guest setup failed")
                return base64.b64decode(status.get("out-data", "")).decode("utf-8-sig", errors="replace")
            time.sleep(0.5)
        raise ProviderError("Windows guest setup timed out")

    def upload_bridge(self, ident: str) -> None:
        # Bound every Windows command line below 32 KiB. Only the pinned provider
        # asset is written; this path never accepts model code or a caller path.
        source = Path(__file__).with_name("windows_bridge.py.in").read_bytes()
        for offset in range(0, len(source), 3072):
            chunk = base64.b64encode(source[offset : offset + 3072]).decode()
            mode = "Create" if offset == 0 else "Append"
            self.powershell(
                ident,
                f"""$ErrorActionPreference='Stop'
$f=[IO.File]::Open('C:\\Clawith\\bridge.py',[IO.FileMode]::{mode},[IO.FileAccess]::Write)
try {{$b=[Convert]::FromBase64String('{chunk}');$f.Write($b,0,$b.Length)}} finally {{$f.Dispose()}}
""",
            )

    def personalize(self, ident: str, token: str, password: str) -> None:
        # Values are generated server-side using URL-safe ASCII, never user code.
        previous = self.powershell(
            ident,
            "$ErrorActionPreference='Stop';if ((Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Setup\\State').ImageState -ne 'IMAGE_STATE_COMPLETE') {throw 'Waiting for Windows first-boot setup'};(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')",
        ).strip()
        self.upload_bridge(ident)
        secret_code = base64.b64encode(AUTOLOGON_SECRET.encode()).decode()
        startup_code = base64.b64encode(CONTROLLER_STARTUP.encode()).decode()
        self.powershell(
            ident,
            f"""$ErrorActionPreference='Stop'
if ((Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Setup\\State').ImageState -ne 'IMAGE_STATE_COMPLETE') {{ throw 'Waiting for Windows first-boot setup' }}
Set-LocalUser -Name 'Clawith' -Password (ConvertTo-SecureString '{password}' -AsPlainText -Force) -PasswordNeverExpires $true
$p='HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon'
Set-ItemProperty $p AutoAdminLogon '1';Set-ItemProperty $p DefaultUserName 'Clawith'
Set-ItemProperty $p DefaultDomainName $env:COMPUTERNAME;Remove-ItemProperty $p AutoLogonCount -ErrorAction SilentlyContinue
Add-Type -TypeDefinition ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{secret_code}')))
[ClawithAutoLogon]::Set('{password}')
Remove-ItemProperty $p DefaultPassword -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName 'Clawith-CUA-Interactive' -ErrorAction SilentlyContinue
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
[IO.File]::WriteAllText('C:\\Clawith\\private\\token','{token}')
$account="$env:COMPUTERNAME\\Clawith"
[IO.File]::WriteAllBytes('C:\\Clawith\\start-control.ps1',[Convert]::FromBase64String('{startup_code}'))
Remove-Item C:\\Users\\Public\\Desktop\\Shared*.lnk,C:\\Users\\Clawith\\Desktop\\Shared*.lnk -ErrorAction SilentlyContinue
$action=New-ScheduledTaskAction -Execute 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' -Argument '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\\Clawith\\start-control.ps1' -WorkingDirectory 'C:\\Clawith'
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $account
$principal=New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'Clawith-CUA-Interactive' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
# The initial password change precedes all personal data. Re-logon once so
# DPAPI starts under the instance password, then never reset it on restore.
shutdown.exe /r /t 3 /f | Out-Null
""",
        )

        # A successful QGA command only schedules reboot; wait for a different
        # boot and an actual interactive logon before admitting personal actions.
        until = time.monotonic() + 100
        while time.monotonic() < until:
            try:
                current = (
                    self.powershell(
                        ident,
                        "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o');"
                        "(Get-CimInstance Win32_ComputerSystem).UserName",
                    )
                    .strip()
                    .splitlines()
                )
                if len(current) == 2 and current[0] != previous and current[1].endswith("\\Clawith"):
                    self.initialize_shell(ident)
                    # Apply user-scoped registration by rebooting. Killing SiHost
                    # can log off the console and terminate the control bridge.
                    self.powershell(ident, "shutdown.exe /r /t 3 /f | Out-Null")
                    self.wait_logon(ident, current[0])
                    self.powershell(ident, "Start-ScheduledTask -TaskName 'Clawith-CUA-Interactive'")
                    return
            except ProviderError:
                pass  # The guest agent disconnects while this initial reboot runs.
            time.sleep(2)
        raise ProviderError("Windows initial personalized logon did not complete")

    def wait_logon(self, ident: str, previous: str) -> None:
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            try:
                lines = (
                    self.powershell(
                        ident,
                        "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o');(Get-CimInstance Win32_ComputerSystem).UserName",
                    )
                    .strip()
                    .splitlines()
                )
                if len(lines) == 2 and lines[0] != previous and lines[1].endswith("\\Clawith"):
                    return
            except ProviderError:
                pass  # The guest agent reconnects after the one-time restart.
            time.sleep(2)
        raise ProviderError("Windows initial shell restart did not complete")

    def initialize_shell(self, ident: str) -> None:
        # Microsoft documents explicit user-session registration for image-derived
        # XAML components. This runs once before the desktop admits personal data.
        helper = base64.b64encode(CONSOLE_LAUNCHER.encode()).decode()
        script = base64.b64encode(FIRST_LOGON.encode("utf-16-le")).decode()
        self.powershell(
            ident,
            f"""$ErrorActionPreference='Stop'
[IO.File]::WriteAllBytes('C:\\Clawith\\console-launch.py',[Convert]::FromBase64String('{helper}'))
[IO.File]::WriteAllText('C:\\Clawith\\first-logon.ps1',[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{script}')))
Remove-Item 'C:\\Clawith\\private\\first-logon-ready.json' -ErrorAction SilentlyContinue
& C:\\Clawith\\Python\\python.exe C:\\Clawith\\console-launch.py 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\\Clawith\\first-logon.ps1'
if ($LASTEXITCODE -ne 0) {{throw 'Interactive shell initialization did not launch'}}
""",
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            receipt = self.powershell(
                ident,
                "if (Test-Path 'C:\\Clawith\\private\\first-logon-ready.json') {[IO.File]::ReadAllText('C:\\Clawith\\private\\first-logon-ready.json')};exit 0",
            )
            if receipt.strip():
                value = json.loads(receipt)
                if value.get("ok") and not value.get("is_system") and value.get("user", "").endswith("\\Clawith"):
                    return
                raise ProviderError("Windows initial desktop component registration failed")
            time.sleep(2)
        raise ProviderError("Windows initial desktop component registration timed out")

    def ready(self, ident: str, token: str, password: str, personalized: bool) -> str:
        deadline = time.monotonic() + (180 if personalized else 600)
        configured = personalized
        session = "ready_" + uuid.uuid4().hex
        while time.monotonic() < deadline:
            try:
                if not configured:
                    self.personalize(ident, token, password)
                    configured = True
                ip = self.ip(ident)
                with httpx.Client(trust_env=False, timeout=httpx.Timeout(45, connect=2)) as client:
                    response = client.get("http://" + ip + ":8090/health", timeout=2)
                    if response.status_code == 200 and response.json().get("ready"):
                        # Prove an interactive screenshot exists before admitting inputs.
                        body = {
                            "jsonrpc": "2.0",
                            "id": "ready",
                            "method": "tools/call",
                            "params": {
                                "name": "computer",
                                "arguments": {"action": "get_desktop_state", "params": {}, "session_id": session},
                            },
                        }
                        response = client.post(
                            "http://" + ip + ":8090/mcp", headers={"Authorization": "Bearer " + token}, json=body
                        )
                        result = response.json().get("result", {})
                        if (
                            response.status_code == 200
                            and not result.get("isError")
                            and any(x.get("type") == "image" for x in result.get("content", []))
                        ):
                            body["params"]["arguments"]["action"] = "release"
                            released = client.post(
                                "http://" + ip + ":8090/mcp", headers={"Authorization": "Bearer " + token}, json=body
                            )
                            if not released.json().get("result", {}).get("isError"):
                                return ip

            except (ProviderError, httpx.HTTPError, ValueError, KeyError):
                # No business input has been sent. Guest/network startup may lag.
                pass
            time.sleep(2)
        raise ProviderError("Windows interactive desktop did not become ready within its initialization bound")
