import base64
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from .jobs import job_directory, run_worker
from .models import AcquisitionError, Limits


def validate_url(url: str) -> tuple[str, str, int]:
    try:
        if len(url) > 8192 or re.search(r"[\x00-\x20\x7f\\]", url):
            raise ValueError
        p = urlsplit(url)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username is not None or p.password is not None:
            raise ValueError
        host = p.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = p.port if p.port is not None else (443 if p.scheme == "https" else 80)
        if port != (443 if p.scheme == "https" else 80) or "%" in host:
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9.-]+", host):
                raise ValueError from None
        else:
            ensure_public(address)
        return p.scheme, host, port
    except (ValueError, UnicodeError):
        raise AcquisitionError("unsafe_url") from None


def ensure_public(address):
    # Reject mapped, transition and scope-bearing IPv6 as well as all non-global IPs.
    if (not address.is_global or address.is_multicast or address.is_reserved
            or address.is_unspecified or address.is_loopback or address.is_link_local
            or (address.version == 6 and (address.ipv4_mapped or address.sixtofour or address.teredo
                or address in ipaddress.ip_network("64:ff9b::/96")
                or address in ipaddress.ip_network("64:ff9b:1::/48")))):
        raise AcquisitionError("non_public_address")


def resolve_public(host: str, port: int) -> list[tuple]:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise AcquisitionError("dns_failed")
    for _, _, _, _, target in addresses:
        ensure_public(ipaddress.ip_address(target[0]))
    return addresses


def public_url(url: str | None) -> str | None:
    """Export no signed URLs/fragments. Keep only public identity query parameters."""
    if not isinstance(url, str):
        return None
    try:
        scheme, host, port = validate_url(url)
    except AcquisitionError:
        return None
    p = urlsplit(url)
    authority = f"[{host}]" if ":" in host else host
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if k in {"v", "id"}
                       and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v)])
    return urlunsplit((scheme, authority, p.path or "/", query, ""))


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, scheme, host, port, addresses, timeout):
        super().__init__(host, port, timeout=timeout)
        self.scheme = scheme
        self.addresses = addresses

    def connect(self):
        family, kind, proto, _, target = self.addresses[0]
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(self.timeout)
            sock.connect(target)  # Numeric sockaddr from the validated DNS answer; no second lookup.
            if self.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            self.sock = sock
        except BaseException:
            sock.close()
            raise


@dataclass
class FetchResult:
    url: str
    body: bytes
    headers: dict[str, str]
    status: int
    wire_bytes: int


def fetch_pinned(url: str, limits: Limits, max_bytes: int, *, method="GET",
                 headers: dict | None = None, data: bytes | None = None) -> FetchResult:
    """Runs only in the bounded worker; parent kills DNS/header/slow-body stalls too."""
    if method not in {"GET", "HEAD", "POST"} or (data and len(data) > 65536):
        raise AcquisitionError("request_not_allowed")
    allowed_headers = {"accept", "accept-language", "user-agent", "content-type", "origin", "referer"}
    outgoing = {k: v for k, v in (headers or {}).items() if k.lower() in allowed_headers}
    outgoing.update({"Accept-Encoding": "gzip", "Connection": "close", "User-Agent": "FoodiefyEvidence/1.0"})
    deadline = time.monotonic() + limits.stage_seconds
    for redirect in range(limits.redirects + 1):
        scheme, host, port = validate_url(url)
        addresses = resolve_public(host, port)
        connection = PinnedConnection(scheme, host, port, addresses, max(.01, deadline - time.monotonic()))
        try:
            p = urlsplit(url)
            target = urlunsplit(("", "", quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                                quote(p.query, safe="=&?/%:@!$'()*+,;~-._"), ""))
            connection.request(method, target, body=data, headers=outgoing)
            response = connection.getresponse()
            response_headers = {k.lower(): v for k, v in response.getheaders()}
            if response.status in {301, 302, 303, 307, 308}:
                location = response_headers.get("location")
                if not location or redirect == limits.redirects:
                    raise AcquisitionError("redirect_limit")
                url = urljoin(url, location)
                validate_url(url)
                # Never replay a POST or origin/referrer on a redirected request.
                method, data = "GET", None
                outgoing = {"Accept-Encoding": "gzip", "Connection": "close", "User-Agent": "FoodiefyEvidence/1.0"}
                continue
            declared = response_headers.get("content-length")
            if declared and int(declared) > max_bytes:
                raise AcquisitionError("response_too_large")
            encoding = response_headers.get("content-encoding", "identity").lower()
            if encoding not in {"identity", "gzip"}:
                raise AcquisitionError("unsupported_content_encoding")
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
            chunks, size, wire = [], 0, 0
            while True:
                if time.monotonic() >= deadline:
                    raise AcquisitionError("stage_timeout")
                chunk = response.read1(min(65536, max_bytes - wire + 1))
                if not chunk:
                    break
                wire += len(chunk)
                if wire > max_bytes:
                    raise AcquisitionError("response_too_large")
                decoded = decoder.decompress(chunk, max_bytes - size + 1) if decoder else chunk
                size += len(decoded)
                if size > max_bytes or (decoder and decoder.unconsumed_tail):
                    raise AcquisitionError("response_too_large")
                chunks.append(decoded)
            if decoder and (not decoder.eof or decoder.unused_data):
                raise AcquisitionError("invalid_compression")
            return FetchResult(url, b"".join(chunks), response_headers, response.status, wire)
        finally:
            connection.close()
    raise AcquisitionError("redirect_limit")


class SafeFetcher:
    def __init__(self, limits: Limits, temp_root: Path | None = None):
        self.limits, self.temp_root = limits, temp_root

    def fetch(self, url: str, *, max_bytes: int | None = None, method="GET", headers=None, data=None,
              timeout_seconds: float | None = None) -> FetchResult:
        validate_url(url)
        limits = self.limits if timeout_seconds is None else self.limits.model_copy(
            update={"stage_seconds": min(self.limits.stage_seconds, max(.01, timeout_seconds))})
        with job_directory(self.temp_root) as job:
            run_worker("fetch", {"url": url, "limits": limits.model_dump(),
                               "max_bytes": max_bytes or self.limits.html_bytes, "method": method,
                               "headers": headers, "data": base64.b64encode(data).decode() if data else None},
                       job, limits)
            result = json.loads((job / "result.json").read_text())
            if "error" in result:
                raise AcquisitionError(result["error"])
            return FetchResult(body=(job / "body.bin").read_bytes(), **result)
