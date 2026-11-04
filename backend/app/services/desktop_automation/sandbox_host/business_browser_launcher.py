"""Desktop shortcut: open the private VM's owned persistent business browser."""

from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

secret = Path("C:/Clawith/private/token").read_text().strip()
request = Request(
    "http://127.0.0.1:8090/browser/open",
    data=b"{}",
    headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
)
with build_opener(ProxyHandler({})).open(request, timeout=160) as response:
    response.read(65536)
