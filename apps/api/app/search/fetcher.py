"""SafeFetcher: SSRF-guarded HTTP GET for untrusted URLs (docs/33 §7)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_PORTS = {80, 443, 8080, 8443}
MAX_BYTES = 2 * 1024 * 1024
UA = "NovaAI-Bot/1.0 (+https://nova.ai/bot)"
METADATA = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}


class BlockedURL(Exception):
    pass


@dataclass
class Fetched:
    url: str
    content_type: str
    text: str


def _ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip in METADATA:
        return False
    cgnat = ipaddress.ip_network("100.64.0.0/10")
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 4 and ip in cgnat)
    )


async def resolve_public(host: str, port: int) -> str:
    """Resolve host; reject if ANY address is non-public. Returns one validated IP."""
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        if not _ip_allowed(literal):
            raise BlockedURL("address not allowed")
        return str(literal)
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise BlockedURL("unresolvable host") from e
    addrs = {ipaddress.ip_address(i[4][0]) for i in infos}
    if not addrs or not all(_ip_allowed(a) for a in addrs):
        raise BlockedURL("address not allowed")
    return str(sorted(addrs, key=lambda a: a.version)[0])


def validate_url(url: str) -> tuple[str, str, int]:
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise BlockedURL("scheme/host not allowed")
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise BlockedURL("port not allowed")
    return p.scheme, p.hostname, port


async def safe_get(url: str, *, read_timeout: float = 5.0, max_redirects: int = 3) -> Fetched:
    for _ in range(max_redirects + 1):
        scheme, host, port = validate_url(url)
        ip = await resolve_public(host, port)
        # Pin the validated IP for the connection (prevents DNS rebinding); keep SNI/Host.
        transport = httpx.AsyncHTTPTransport(retries=0)
        async with httpx.AsyncClient(
            transport=transport, timeout=read_timeout, follow_redirects=False
        ) as client:
            # Connect to the validated IP (no second DNS lookup → no rebinding). For TLS,
            # sni_hostname makes the handshake and certificate check use the real hostname.
            netloc = urlsplit(url).netloc
            ip_host = ip if ":" not in ip else f"[{ip}]"
            pinned = url.replace(netloc, f"{ip_host}:{port}", 1)
            headers = {
                "User-Agent": UA,
                "Accept": "text/html,text/plain;q=0.9",
                "Host": host if port in (80, 443) else f"{host}:{port}",
            }
            extensions = {"sni_hostname": host} if scheme == "https" else {}
            async with client.stream("GET", pinned, headers=headers, extensions=extensions) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in ("text/html", "text/plain", "application/xhtml+xml"):
                    raise BlockedURL("content type not allowed")
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                return Fetched(
                    url, ctype, bytes(body).decode(r.encoding or "utf-8", errors="replace")
                )
    raise BlockedURL("too many redirects")
