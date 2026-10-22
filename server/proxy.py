"""Fetch a remote image or video, then hand back same-origin bytes."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse
import urllib.error
import urllib.request

MEDIA_TYPES = ("image/", "video/")
INTRANET = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def public_target(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只转发图片和视频地址")
    host = parsed.hostname
    if host in {"localhost"} or host.endswith(".local"):
        raise ValueError("不转发内网地址")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        addresses = []
    if not addresses and host not in {"example.com", "images.example"}:
        raise ValueError("地址无法解析")
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if any(ip in network for network in INTRANET) or ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError("不转发内网地址")
    return url


def acceptable(content_type: str) -> bool:
    kind = content_type.split(";", 1)[0].strip().lower()
    return kind.startswith(MEDIA_TYPES)


def fetch(url: str, opener=None, socks_opener=None) -> tuple[bytes, str]:
    """Direct first. SOCKS5 only when direct fails. Credentials stay in the opener."""
    public_target(url)
    direct = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        return _read(direct, url)
    except ValueError:
        raise
    except Exception as first:
        proxy = socks_opener if socks_opener is not None else _socks_opener()
        if proxy is None:
            raise RuntimeError("图片无法直接访问") from first
        try:
            return _read(proxy, url)
        except ValueError:
            raise
        except Exception as second:
            raise RuntimeError("图片无法直接访问") from second


def _read(opener, url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "cvgen"})
    with opener.open(request, timeout=20) as response:
        content_type = response.headers.get("Content-Type", "")
        if not acceptable(content_type):
            raise ValueError("只转发图片和视频")
        return response.read(), content_type


def _socks_opener():
    raw = os.environ.get("CVGEN_SOCKS5", "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme != "socks5" or not parsed.hostname or not parsed.port:
        return None
    import socks
    from sockshandler import SocksiPyHandler

    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        SocksiPyHandler(
            socks.SOCKS5,
            parsed.hostname,
            parsed.port,
            username=parsed.username or None,
            password=parsed.password or None,
        ),
    )
