"""Outbound-request safety for user-supplied URLs (webhooks).

The check happens at send time, after DNS resolution, and the request then goes to the address that
was checked, so a name that resolves to a public address when saved and a private one later (DNS
rebinding) can't reach internal services. Redirects are the caller's job to refuse.
"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_URL = 2048
# Translation prefixes that embed an IPv4 address, which could be a private one.
_EMBEDDING = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("2002::/16"))

_getaddrinfo = socket.getaddrinfo  # seam for tests


class UnsafeTarget(ValueError):
    """The URL is malformed or points somewhere we won't send to. Permanent."""


class ResolutionError(Exception):
    """DNS failed. May be temporary."""


@dataclass
class Resolved:
    url: str  # the original URL with the host replaced by the checked address
    ip: str
    host: str  # original hostname, for the Host header and TLS name checks
    host_header: str
    tls_name: str | None  # None when the original host is an IP literal


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _is_public(ip.ipv4_mapped)
        if any(ip in net for net in _EMBEDDING):
            return False
    return ip.is_global and not ip.is_multicast


def parse(url: str, *, allow_private: bool) -> tuple[str, str, int]:
    """Static checks. Returns (scheme, host, port) or raises UnsafeTarget."""
    if len(url) > MAX_URL:
        raise UnsafeTarget("URL is too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeTarget("URL is not valid") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeTarget("URL must start with https://")
    if scheme == "http" and not allow_private:
        raise UnsafeTarget("URL must use https")
    if not parts.hostname:
        raise UnsafeTarget("URL has no host")
    if parts.username is not None or parts.password is not None:
        raise UnsafeTarget("URL must not contain a username or password")
    host = parts.hostname.rstrip(".").lower()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not allow_private and not _is_public(literal):
        raise UnsafeTarget("URL points at a private or reserved address")
    return scheme, host, port or (443 if scheme == "https" else 80)


def resolve(url: str, *, allow_private: bool) -> list[Resolved]:
    """Every address the host resolves to, all checked. Raises UnsafeTarget if any is not public:
    one bad answer is enough to refuse, since the OS could pick it."""
    scheme, host, port = parse(url, allow_private=allow_private)
    parts = urlsplit(url)
    try:
        infos = _getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ResolutionError(f"could not resolve {host}") from exc
    addresses = list(dict.fromkeys(info[4][0].split("%")[0] for info in infos))
    if not addresses:
        raise ResolutionError(f"could not resolve {host}")
    out = []
    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False
    default_port = 443 if scheme == "https" else 80
    host_header = host if port == default_port else f"{host}:{port}"
    if ":" in host:
        host_header = f"[{host}]" + ("" if port == default_port else f":{port}")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not allow_private and not _is_public(ip):
            raise UnsafeTarget("URL resolves to a private or reserved address")
        netloc = f"[{address}]" if ip.version == 6 else address
        netloc += "" if port == default_port else f":{port}"
        pinned = parts._replace(netloc=netloc).geturl()
        out.append(Resolved(pinned, address, host, host_header, None if is_literal else host))
    return out
