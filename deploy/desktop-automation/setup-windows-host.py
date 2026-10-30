"""Install the private lifecycle service after preparing an immutable Windows template.

Run on the designated Linux KVM host. Does not touch pre-existing Windows VMs.
Dependencies: libvirt-daemon-kvm, libvirt-client, libvirt-daemon-config-nwfilter,
libvirt-daemon-driver-nwfilter, qemu-kvm, edk2-ovmf, swtpm, zstd,
python3.11. Place the sandbox_host package under ROOT/service first.
"""

from pathlib import Path
import os
import secrets
import subprocess
import sqlite3
import re

ROOT = Path("/root/yaojin/agent-windows-sandbox-20261029")
MEDIA = Path("/var/lib/libvirt/images/clawith-sandboxes")
PRIVATE = ROOT / "private"
PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(PRIVATE, 0o700)
for path in [MEDIA, MEDIA / "instances", MEDIA / "template"]:
    path.mkdir(parents=True, exist_ok=True, mode=0o711)
token = PRIVATE / "gateway-token"
if not token.exists():
    token.write_text(secrets.token_urlsafe(48))
    token.chmod(0o600)
network = ROOT / "network.xml"
network.write_text("""<network><name>clawith-sandbox</name>
<forward mode="nat"/><bridge name="virbr-cws" stp="on" delay="0"/>
<ip address="10.253.0.1" netmask="255.255.255.0"><dhcp>
<range start="10.253.0.10" end="10.253.0.200"/></dhcp></ip></network>""")


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


run(
    [
        "systemctl",
        "start",
        "virtqemud.socket",
        "virtnetworkd.socket",
        "virtlogd.socket",
        "virtlockd.socket",
        "virtnwfilterd.socket",
    ]
)
# Compression is a host-level libvirt setting: never change another owner's
# domains or restart the driver while one of our desktops is active.
run(["zstd", "--version"])
qemu_config = Path("/etc/libvirt/qemu.conf")
config = qemu_config.read_text()
if not re.search(r'^\s*save_image_format\s*=\s*"zstd"', config, re.M):
    physical = set(
        run(["virsh", "-c", "qemu:///system", "list", "--all", "--uuid"]).stdout.split()
    )
    owned = set()
    if (PRIVATE / "state.sqlite").exists():
        with sqlite3.connect(PRIVATE / "state.sqlite") as db:
            owned = {row[0] for row in db.execute("SELECT id FROM desktops")}
    if physical - owned:
        raise RuntimeError(
            "Foreign libvirt domains exist; use a dedicated owned host before changing compression"
        )
    for ident in physical:
        if (
            run(["virsh", "-c", "qemu:///system", "domstate", ident]).stdout.strip()
            != "shut off"
        ):
            raise RuntimeError(
                "Save owned desktops before applying the initial compression setting"
            )
    backup = PRIVATE / "qemu-before-zstd.conf"
    if not backup.exists():
        backup.write_text(config)
        backup.chmod(0o600)
    changed = re.sub(
        r"^\s*save_image_format\s*=.*$",
        'save_image_format = "zstd"',
        config,
        flags=re.M,
    )
    if not re.search(r"^save_image_format\s*=", changed, re.M):
        changed += '\nsave_image_format = "zstd"\n'
    qemu_config.write_text(changed)
    try:
        run(["systemctl", "restart", "virtqemud.service"])
        run(["virsh", "-c", "qemu:///system", "list", "--all"])
    except subprocess.CalledProcessError:
        qemu_config.write_text(config)
        run(["systemctl", "restart", "virtqemud.service"])
        raise
existing = subprocess.run(
    ["virsh", "-c", "qemu:///system", "net-info", "clawith-sandbox"],
    capture_output=True,
    check=False,
)
if existing.returncode:
    run(["virsh", "-c", "qemu:///system", "net-define", str(network)])
info = run(["virsh", "-c", "qemu:///system", "net-info", "clawith-sandbox"]).stdout
if "Active:         yes" not in info:
    run(["virsh", "-c", "qemu:///system", "net-start", "clawith-sandbox"])
run(["virsh", "-c", "qemu:///system", "net-autostart", "clawith-sandbox"])
# Preserve Docker's existing rules. Guest ports are isolated in each domain XML;
# these additional rules prevent guests reaching host management and one another.
firewall = ROOT / "firewall.nft"
firewall.write_text("""table inet clawith_windows_sandbox {
 chain input { type filter hook input priority -10; policy accept;
  iifname "virbr-cws" ct state established,related accept
  iifname "virbr-cws" udp dport { 53, 67 } accept
  iifname "virbr-cws" tcp dport 53 accept
  iifname "virbr-cws" drop
 }
 chain forward { type filter hook forward priority -10; policy accept;
  iifname "virbr-cws" oifname "virbr-cws" drop
  iifname "virbr-cws" oifname "docker0" drop
  iifname "virbr-cws" oifname "br-*" drop
 }
}""")
subprocess.run(
    ["nft", "delete", "table", "inet", "clawith_windows_sandbox"],
    capture_output=True,
    check=False,
)
run(["nft", "-f", str(firewall)])
env = PRIVATE / "host.env"
if not env.exists():
    env.write_text(
        f"WINDOWS_SANDBOX_ROOT={MEDIA}\nWINDOWS_SANDBOX_STATE={PRIVATE}\nWINDOWS_SANDBOX_TOKEN_FILE={token}\nWINDOWS_SANDBOX_IDLE_SECONDS=600\nWINDOWS_SANDBOX_MAX_RUNNING=2\n"
    )
env.chmod(0o600)
unit = Path("/etc/systemd/system/clawith-windows-sandbox.service")
unit.write_text(f"""[Unit]
Description=Clawith private Windows sandbox lifecycle
After=network-online.target virtqemud.socket virtnetworkd.socket virtnwfilterd.socket
Requires=virtqemud.socket virtnetworkd.socket virtnwfilterd.socket
[Service]
WorkingDirectory={ROOT}/service
EnvironmentFile={env}
ExecStartPre=-/usr/sbin/nft delete table inet clawith_windows_sandbox
ExecStartPre=/usr/sbin/nft -f {firewall}
ExecStart={ROOT}/venv/bin/python -m uvicorn sandbox_host.application:app --host 192.168.0.1 --port 18131 --no-access-log
Restart=on-failure
RestartSec=3
UMask=0077
MemoryMax=512M
CPUQuota=100%
[Install]
WantedBy=multi-user.target
""")
run(["systemctl", "daemon-reload"])
print(
    "Host configuration prepared. Start service only after the clean template is sealed."
)
