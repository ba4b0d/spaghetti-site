"""C1 — client-IP trust behind the reverse proxy (rate-limit key integrity).

slowapi keys the login/callback rate limits on ``get_remote_address`` →
``request.client.host``. Behind nginx the TCP peer is the *proxy*, so uvicorn's
``ProxyHeadersMiddleware`` must rewrite ``request.client`` from the forwarded
headers — but ONLY when the peer is the trusted proxy. If it does not (the
default ``--forwarded-allow-ips 127.0.0.1`` never matches nginx's Docker IP),
every real client collapses into a single bucket, so one caller can exhaust the
shared login limit; if it trusts ``*``, any client can forge its own key.

These tests prove the mechanism with a real ASGI transport (httpx AsyncClient):

* through the trusted proxy, two different ``X-Forwarded-For`` values are two
  different clients (own buckets);
* a direct, untrusted peer cannot forge its client IP via ``X-Forwarded-For``;
* the deployment (docker-compose + nginx) pins exactly that single trust.
"""
import asyncio
import re
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

TRUSTED_PROXY_IP = "172.28.0.2"
REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests -> repo root


def _build_app(limit: str = "3/minute") -> ProxyHeadersMiddleware:
    """A minimal app keyed EXACTLY like the real one (get_remote_address)."""
    limiter = Limiter(key_func=get_remote_address)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/probe")
    @limiter.limit(limit)
    def probe(request: Request):  # noqa: ANN202
        return {"client": request.client.host}

    # Same middleware uvicorn installs for --proxy-headers, trusting only nginx.
    return ProxyHeadersMiddleware(app, trusted_hosts=TRUSTED_PROXY_IP)


async def _probe(client, ip):
    return await client.get("/probe", headers={"X-Forwarded-For": ip})


async def _exhaust(client, ip, cap: int = 25) -> int:
    """Send requests until one is rate-limited; return how many passed."""
    passed = 0
    while passed < cap:
        r = await _probe(client, ip)
        if r.status_code == 429:
            return passed
        assert r.status_code == 200, r.text
        passed += 1
    raise AssertionError("client never hit the rate limit")


def _run(app, peer_ip, coro_factory):
    async def scenario():
        transport = ASGITransport(app=app, client=(peer_ip, 0))
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            return await coro_factory(c)

    return asyncio.run(scenario())


def test_trusted_proxy_separates_distinct_clients():
    async def scenario(c):
        first = await _probe(c, "203.0.113.10")
        assert first.status_code == 200
        assert first.json()["client"] == "203.0.113.10"

        passed = await _exhaust(c, "203.0.113.10")
        assert passed >= 1

        # A *different* real client behind the same proxy keeps its own bucket.
        other = await _probe(c, "203.0.113.11")
        assert other.status_code == 200, other.text
        assert other.json()["client"] == "203.0.113.11"

    _run(_build_app(), TRUSTED_PROXY_IP, scenario)


def test_trusted_proxy_selects_closest_untrusted_hop():
    # A client-supplied X-Forwarded-For prefix must not become the selected
    # client: uvicorn picks the rightmost untrusted hop, i.e. the address the
    # trusted proxy actually saw.
    async def scenario(c):
        r = await c.get("/probe", headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.20"})
        assert r.status_code == 200
        assert r.json()["client"] == "203.0.113.20"

    _run(_build_app(), TRUSTED_PROXY_IP, scenario)


def test_direct_untrusted_peer_cannot_spoof_client_ip():
    peer = "198.51.100.200"

    async def scenario(c):
        r = await _probe(c, "10.0.0.1")
        assert r.status_code == 200
        assert r.json()["client"] == peer          # forged value ignored

        passed = await _exhaust(c, "10.0.0.1")     # keyed on the real peer
        assert passed >= 1
        # A different forged value is the SAME real peer → still exhausted.
        r2 = await c.get("/probe", headers={"X-Forwarded-For": "10.0.0.99"})
        assert r2.status_code == 429

    _run(_build_app(), peer, scenario)


# ── Deployment trust configuration ──────────────────────────────────

def _compose_text() -> str:
    return (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_compose_pins_proxy_and_trusts_only_it():
    text = _compose_text()
    assert "--proxy-headers" in text
    m = re.search(r'--forwarded-allow-ips["\']?\s*,\s*["\']?([^\s"\',\]]+)', text)
    assert m, "backend must pass --forwarded-allow-ips"
    trusted = m.group(1)
    assert trusted == TRUSTED_PROXY_IP, trusted
    assert "*" not in trusted
    # The proxy (frontend / nginx) is pinned to exactly that static IP, and a
    # fixed subnet exists so the static assignment is valid.
    assert f"ipv4_address: {trusted}" in text
    assert "subnet:" in text
    # Never trust every proxy.
    assert not re.search(r'forwarded-allow-ips"\s*,\s*"\*"', text)


def test_nginx_overwrites_forwarded_for_and_proto():
    conf = (REPO_ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    # Overwrite with the real peer, so no client-supplied chain reaches the
    # backend where the rate-limit key is derived.
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in conf
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in conf
    # Scheme comes from nginx, not a client-spoofable header.
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in conf
    assert "proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;" not in conf
