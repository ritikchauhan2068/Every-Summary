"""Bounded public HTTP fetching with DNS pinning and redirect validation."""

import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

import urllib3
from urllib3.util import Timeout

from sourcewise.config import TRUSTED_FETCH_PROXY
from sourcewise.domain import SourceError

USER_AGENT = "Sourcewise/1.0 (user-requested document reader)"
TLS = ssl.create_default_context()


def parse_http_url(url):
    if len(url) > 2048 or any(c.isspace() or ord(c) < 32 or c == "\\" for c in url):
        raise SourceError("Enter a valid HTTP or HTTPS URL.")
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if parts.username or parts.password:
            raise ValueError
        if parts.port not in {None, 443 if parts.scheme == "https" else 80}:
            raise ValueError
        return parts
    except (ValueError, UnicodeError) as exc:
        raise SourceError("Enter a valid public HTTP or HTTPS URL.") from exc


def public_addresses(host, port):
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise SourceError("The source hostname could not be resolved.") from exc
    addresses = list(dict.fromkeys(item[4][0] for item in records))
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip, "ipv4_mapped", None):
            raise SourceError("The submitted hostname must resolve to a public address.")
    return sorted(addresses, key=lambda address: ":" in address)


def get_public(url, limit=3_000_000, allowed_host=None, accept="*/*"):
    response = None
    deadline = time.monotonic() + 25
    def close(connection):
        if isinstance(connection, urllib3.PoolManager):
            connection.clear()
        else:
            connection.close()

    for _ in range(5):
        parts = parse_http_url(url)
        host = parts.hostname.encode("idna").decode("ascii").rstrip(".")
        if allowed_host and not allowed_host(host):
            raise SourceError("The source redirected outside its supported host.")
        port = 443 if parts.scheme == "https" else 80
        addresses = public_addresses(host, port)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "identity"}
        if TRUSTED_FETCH_PROXY:
            pool = urllib3.ProxyManager(TRUSTED_FETCH_PROXY, ssl_context=TLS)
            endpoints = [(pool, url)]
        else:
            headers["Host"] = f"[{host}]" if ":" in host else host
            endpoints = []
            for address in addresses[:3]:
                if parts.scheme == "https":
                    connection = urllib3.HTTPSConnectionPool(
                        address, port, ssl_context=TLS, server_hostname=host, assert_hostname=host
                    )
                else:
                    connection = urllib3.HTTPConnectionPool(address, port)
                endpoints.append((connection, path))
        for pool, target in endpoints:
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SourceError("The source took too long to respond.")
                response = pool.request(
                    "GET", target, headers=headers, redirect=False, retries=False, preload_content=False,
                    timeout=Timeout(connect=min(4, remaining), read=min(8, remaining)),
                )
                break
            except (urllib3.exceptions.HTTPError, OSError):
                close(pool)
        if response is None:
            raise SourceError("Could not connect to the public source.")
        try:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise SourceError("The source returned a redirect without a destination.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise SourceError(f"The source returned HTTP {response.status}. Check access and the URL.")
            payload = bytearray()
            for block in response.stream(65536, decode_content=True):
                payload.extend(block)
                if len(payload) > limit:
                    raise SourceError("The source exceeds the supported download size.")
                if time.monotonic() > deadline:
                    raise SourceError("The source took too long to download.")
            return bytes(payload), response.headers.get("Content-Type", ""), url
        except urllib3.exceptions.HTTPError as exc:
            raise SourceError("The source connection ended before the download finished.") from exc
        finally:
            response.close()
            close(pool)
            response = None
    raise SourceError("The source exceeded the redirect limit.")
