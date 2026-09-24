"""SSRF-안전 HTTP fetch.

사용자가 넣은 임의 URL을 서버가 fetch 하므로, 내부 대역으로의 요청을 막는다.
- scheme http/https 만 허용
- DNS resolve 후 *실제 IP* 를 검증(모든 A/AAAA 레코드)
- 검증한 IP로 연결을 **핀닝**(Host 헤더 + TLS SNI 는 원래 호스트명 유지) → DNS rebinding 방지
- redirect 를 수동으로 따라가며 매 홉의 최종 IP를 재검증
- connect/read timeout, 최대 응답 크기, redirect 횟수 제한
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urljoin

import httpx

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}

# 명시 차단 대역(요구사항) + 기타 비공개/예약 대역
_BLOCKED_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",      # loopback
        "10.0.0.0/8",       # private
        "172.16.0.0/12",    # private
        "192.168.0.0/16",   # private
        "169.254.0.0/16",   # link-local
        "100.64.0.0/10",    # CGNAT / tailnet 포함
        "0.0.0.0/8",        # this-network
        "::1/128",          # ipv6 loopback
        "fc00::/7",         # ipv6 unique-local
        "fe80::/10",        # ipv6 link-local
        "::ffff:0:0/96",    # ipv4-mapped ipv6
    )
]

# 하드닝 기본값 (P1)
MAX_BYTES = 5 * 1024 * 1024      # 응답 최대 5MB
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 20.0
MAX_REDIRECTS = 5


class BlockedURLError(Exception):
    """차단된(내부 대역/비허용 scheme/초과) URL."""


def _ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        return True
    return any(ip in net for net in _BLOCKED_NETS)


def _resolve_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        raise BlockedURLError(f"DNS 해석 실패: {host}")
    ips = []
    for info in infos:
        ip = info[4][0]
        if _ip_blocked(ip):
            raise BlockedURLError(f"차단된 내부 대역: {host} → {ip}")
        ips.append(ip)
    if not ips:
        raise BlockedURLError(f"해석된 IP 없음: {host}")
    # 중복 제거(순서 유지)
    return list(dict.fromkeys(ips))


def _validate(url: str):
    """(parsed, [validated_ips]) 반환. 차단이면 BlockedURLError."""
    p = urlparse(url)
    if p.scheme not in ALLOWED_SCHEMES:
        raise BlockedURLError(f"허용되지 않은 scheme: {p.scheme!r}")
    host = p.hostname
    if not host:
        raise BlockedURLError("호스트 없음")
    h = host.lower()
    if h in BLOCKED_HOSTNAMES or h.endswith(".localhost"):
        raise BlockedURLError(f"차단된 호스트명: {host}")
    # 리터럴 IP 직접 입력
    try:
        ipaddress.ip_address(host)
        if _ip_blocked(host):
            raise BlockedURLError(f"차단된 IP: {host}")
        return p, [host]
    except ValueError:
        pass
    return p, _resolve_ips(host)


class _Resp:
    __slots__ = ("text", "content", "status_code", "url")

    def __init__(self, text, content, status_code, url):
        self.text = text
        self.content = content
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None
            )


def safe_get(url: str, *, headers: dict | None = None,
             max_bytes: int = MAX_BYTES, max_redirects: int = MAX_REDIRECTS) -> _Resp:
    """SSRF-안전 GET. 검증 IP 핀닝 + 수동 redirect 재검증 + 크기/시간 제한."""
    timeout = httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT,
                            write=CONNECT_TIMEOUT, pool=CONNECT_TIMEOUT)
    base_headers = dict(headers or {})
    current = url
    # IP 핀닝으로 호스트가 IP로 바뀌어 httpx 쿠키 도메인 매칭이 깨지므로, 리다이렉트
    # 체인 동안 쿠키를 직접 누적한다. 단, 호스트별 jar 로 분리해 redirect 대상이 바뀔 때
    # 이전 호스트의 쿠키가 새 호스트로 새지 않게 한다.
    cookie_jars: dict[str, dict[str, str]] = {}
    with httpx.Client(timeout=timeout, follow_redirects=False, verify=True,
                      limits=httpx.Limits(max_connections=4)) as client:
        for _ in range(max_redirects + 1):
            p, ips = _validate(current)
            host = p.hostname
            ip = ips[0]
            # 검증한 IP로 핀닝 — netloc 을 IP로 교체(포트 유지), Host/SNI 는 원래 호스트명
            netloc = f"[{ip}]" if ":" in ip else ip
            if p.port:
                netloc += f":{p.port}"
            pinned_url = p._replace(netloc=netloc).geturl()
            req_headers = dict(base_headers)
            req_headers["Host"] = host if not p.port else f"{host}:{p.port}"
            jar_key = host.lower()
            cookie_jar = cookie_jars.setdefault(jar_key, {})
            if cookie_jar:
                req_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie_jar.items())
            extensions = {"sni_hostname": host} if p.scheme == "https" else {}
            req = client.build_request("GET", pinned_url, headers=req_headers,
                                       extensions=extensions)
            resp = client.send(req, stream=True)
            try:
                # 응답의 Set-Cookie 누적(name=value 만; 현재 호스트 jar 에만 저장)
                for sc in resp.headers.get_list("set-cookie"):
                    nv = sc.split(";", 1)[0].strip()
                    if "=" in nv:
                        k, v = nv.split("=", 1)
                        if v.strip():
                            cookie_jar[k.strip()] = v.strip()
                if resp.is_redirect and "location" in resp.headers:
                    current = urljoin(current, resp.headers["location"])
                    resp.close()
                    continue
                total = 0
                chunks = []
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise BlockedURLError(f"응답이 최대 크기({max_bytes}B)를 초과")
                    chunks.append(chunk)
                content = b"".join(chunks)
                enc = resp.encoding or "utf-8"
                status = resp.status_code
            finally:
                resp.close()
            return _Resp(content.decode(enc, errors="replace"), content, status, current)
    raise BlockedURLError(f"redirect 횟수({max_redirects}) 초과")
