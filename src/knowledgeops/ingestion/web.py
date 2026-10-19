"""No proxy inheritance. DNS is validated AND the connection is pinned to a resolved IP."""
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit


def resolve_public(host, port):
    addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("URL_BLOCKED: only public Internet addresses are permitted")
    return addresses[0]


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self.ip = ip

    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)


class PinnedHTTPS(PinnedHTTP):
    def connect(self):
        super().connect()
        self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


def fetch_page(url, max_bytes=5 * 1024 * 1024, timeout=20):
    deadline = time.monotonic() + timeout
    for _ in range(4):
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            raise ValueError("INVALID_URL")
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        if port not in (80, 443):
            raise ValueError("URL_PORT_BLOCKED")
        ip = resolve_public(parts.hostname, port)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("URL_TIMEOUT")
        cls = PinnedHTTPS if parts.scheme == 'https' else PinnedHTTP
        conn = cls(parts.hostname, port, ip, remaining)
        try:
            path = parts.path or '/'
            if parts.query:
                path += '?' + parts.query
            conn.request('GET', path, headers={'User-Agent': 'KnowledgeOps/0.1', 'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError("INVALID_REDIRECT")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"WEB_HTTP_{response.status}")
            content_type = response.getheader('Content-Type', '').lower()
            if 'text/html' not in content_type:
                raise ValueError("WEB_NOT_HTML")
            data = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("URL_TIMEOUT")
                if conn.sock:
                    conn.sock.settimeout(remaining)
                part = response.read1(min(65536, max_bytes + 1 - len(data)))
                if not part:
                    break
                data.extend(part)
                if len(data) > max_bytes:
                    raise ValueError("WEB_TOO_LARGE")
            return bytes(data), url
        finally:
            conn.close()
    raise ValueError("TOO_MANY_REDIRECTS")
