"""C1 follow-up — recover the real client IP behind the two-tier Pi edge.

Why (the defect this pins)
--------------------------
The deployed request path is NOT a single nginx hop:

    client → Pi5 edge reverse proxy (192.168.100.50) → frontend nginx → backend

The Pi5 edge is the public TLS terminator and *replaces* ``X-Forwarded-For``
with the real client address, but the TCP peer the frontend nginx sees is the
edge, so plain ``$remote_addr`` is the edge's own address for *every* visitor.
The frontend then forwarded ``$remote_addr`` as ``X-Forwarded-For`` — so the
backend's rate-limit key (slowapi ``get_remote_address`` →
``request.client.host``) collapsed to the upstream proxy for everyone: one
caller could exhaust the shared login/callback limits.

The earlier C1 fix only covered the Docker nginx→uvicorn tier
(``--forwarded-allow-ips``) and missed this edge tier.

Fix
---
The frontend nginx recovers the client address with the realip module, trusting
ONLY the exact edge address::

    set_real_ip_from 192.168.100.50;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;

and keeps OVERWRITING the forwarded chain with the recovered ``$remote_addr``
(``proxy_set_header X-Forwarded-For $remote_addr;``): the backend sees exactly
one client IP and never a client-supplied chain. ``real_ip_recursive on`` walks
the forwarded chain right-to-left and picks the first untrusted hop, so a
client-injected prefix cannot win. Because trust is a single exact address — not
a CIDR range and never ``*`` — a caller reaching the frontend directly (the
published :3000 port, whose peer is not the edge) keeps its real peer address
and cannot forge a client IP.

Tests
-----
* Config-level assertions always run (trust is a single exact address; the
  realip directives and the overwrite are present and ordered).
* A real nginx probe (skipped without docker) proves the behaviour end to end:
  a request from the trusted peer has its ``X-Forwarded-For`` honoured (and a
  forged prefix dropped), while a request from any other peer keeps its real
  peer address and cannot forge a client IP.

Docker cannot originate from ``192.168.100.50`` in a throwaway test, so the
probe substitutes a fake trusted address (TEST-NET-3, ``203.0.113.50``) in an
otherwise-identical copy of the config and assigns the probe client that
address on a dedicated test network.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests -> repo root
NGINX_CONF = REPO_ROOT / "frontend" / "nginx.conf"

# The production edge address this frontend must trust — and only this one.
TRUSTED_EDGE_IP = "192.168.100.50"

# Fake trusted peer / nginx / untrusted peer used by the docker probe, chosen
# from TEST-NET-3 (RFC 5737) so the throwaway subnet cannot clash with a real
# route (the operator's LAN is also 192.168.100.0/24, which must not be
# re-created as a docker bridge).
FAKE_EDGE = "203.0.113.50"
FAKE_NGINX = "203.0.113.10"
FAKE_UNTRUSTED = "203.0.113.99"
FAKE_SUBNET = "203.0.113.0/24"
FAKE_CLIENT_XFF = "91.92.207.133"

NGINX_IMAGE = "nginx:alpine"


def _conf_text() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


def _server_level_block(text: str) -> str:
    """Return the server-level directives (before the first `location`)."""
    idx = text.index("location ")
    return text[:idx]


def _set_real_ip_from_values(text: str) -> list[str]:
    values: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("set_real_ip_from"):
            values.append(line[len("set_real_ip_from"):].strip().rstrip(";").strip())
    return values


# ── Config-level guards (no docker required) ──────────────────────────


def test_trusts_exactly_the_one_edge_address():
    values = _set_real_ip_from_values(_conf_text())
    assert values == [TRUSTED_EDGE_IP], (
        "the frontend nginx must trust exactly the Pi edge address "
        f"{TRUSTED_EDGE_IP!r} (found {values!r}). Trusting a range, a second "
        "address, or '*' would let a direct caller forge its client IP."
    )


def test_never_trusts_a_range_wildcard_or_all():
    text = _conf_text()
    for forbidden in ("0.0.0.0/0", "::/0", "set_real_ip_from all;", "set_real_ip_from *;"):
        assert forbidden not in text, f"over-broad realip trust present: {forbidden!r}"


def test_recovers_client_from_forwarded_for_recursively():
    text = _conf_text()
    assert "real_ip_header X-Forwarded-For;" in text
    assert "real_ip_recursive on;" in text


def test_still_overwrites_forwarded_for_with_remote_addr():
    """The recovered client is what gets forwarded — never a client chain."""
    text = _conf_text()
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in text
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in text
    assert "proxy_set_header X-Forwarded-For $http_x_forwarded_for;" not in text
    # X-Real-IP carries the same recovered value.
    assert "proxy_set_header X-Real-IP $remote_addr;" in text


def test_realip_directives_are_server_level_and_precede_forwarding():
    """realip must be configured before the headers that depend on $remote_addr."""
    text = _conf_text()
    server_level = _server_level_block(text)
    assert "real_ip_header X-Forwarded-For;" in server_level, (
        "real_ip_header must be a server-level directive, not buried in a location"
    )
    assert "set_real_ip_from" in server_level
    assert text.index("real_ip_header X-Forwarded-For;") < text.index(
        "proxy_set_header X-Forwarded-For $remote_addr;"
    ), "realip must be applied before $remote_addr is forwarded"


# ── Behavioural guard (real nginx; needs docker) ──────────────────────


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _wrapper_conf(trusted_ip: str) -> str:
    """An http{} wrapper embedding the repo server block.

    The stub upstream on :8000 echoes the ``X-Forwarded-For`` nginx actually
    forwarded, reached by pointing ``backend`` at 127.0.0.1 (the same trick the
    token-logging test uses), so the probe observes the header the real backend
    would receive.
    """
    src = _conf_text()
    assert f"set_real_ip_from {TRUSTED_EDGE_IP};" in src
    src = src.replace(f"set_real_ip_from {TRUSTED_EDGE_IP};", f"set_real_ip_from {trusted_ip};")
    return (
        "worker_processes 1;\n"
        "pid /run/nginx.pid;\n"
        "error_log /var/log/nginx/error.log warn;\n"
        "events { worker_connections 1024; }\n"
        "http {\n"
        "  include /etc/nginx/mime.types;\n"
        "  default_type text/plain;\n"
        "  access_log /var/log/nginx/access.log;\n"
        "  server { listen 8000; access_log off;"
        ' location / { return 200 "XFF=$http_x_forwarded_for"; } }\n'
        + src
        + "}\n"
    )


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _probe(base_url: str, peer_ip: str, network: str, xff: str) -> str:
    """Send ``X-Forwarded-For: xff`` to the config from a container at peer_ip."""
    result = _run(
        [
            "docker", "run", "--rm",
            "--network", network, "--ip", peer_ip,
            "--entrypoint", "wget", NGINX_IMAGE,
            "-qO-", "--header", f"X-Forwarded-For: {xff}",
            f"{base_url}/api/v1/products",
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


@pytest.mark.skipif(not _docker_available(), reason="docker not available")
def test_real_nginx_recovers_client_ip_from_trusted_edge(tmp_path):
    conf = tmp_path / "nginx.conf"
    conf.write_text(_wrapper_conf(FAKE_EDGE), encoding="utf-8")

    network = "c1_realipprobe_net"
    name = "c1_realipprobe_nginx"
    _run(["docker", "rm", "-f", name])
    _run(["docker", "network", "rm", network])
    created_net = _run(["docker", "network", "create", "--subnet", FAKE_SUBNET, network])
    if created_net.returncode != 0:
        pytest.skip("could not create test network: " + (created_net.stdout + created_net.stderr).strip()[:200])
    try:
        run = _run(
            [
                "docker", "run", "-d", "--name", name,
                "--network", network, "--ip", FAKE_NGINX,
                "--add-host", "backend:127.0.0.1",
                "-v", f"{conf.as_posix()}:/etc/nginx/nginx.conf:ro",
                NGINX_IMAGE,
            ],
        )
        if run.returncode != 0:
            out = run.stdout + run.stderr
            if "Unable to find image" in out or "manifest unknown" in out:
                pytest.skip("nginx image unavailable: " + out.strip()[:200])
            raise AssertionError(out)

        base = f"http://{name}"  # user-defined network DNS resolves the name
        for _ in range(40):
            try:
                if _run(
                    ["docker", "exec", name, "wget", "-qO-",
                     "http://127.0.0.1/api/v1/products"],
                    timeout=30,
                ).returncode == 0:
                    break
            except subprocess.SubprocessError:
                pass
            time.sleep(0.3)
        else:
            pytest.skip("nginx container never became ready")

        # Trusted peer: the forwarded client IP is honoured.
        assert _probe(base, FAKE_EDGE, network, FAKE_CLIENT_XFF) == f"XFF={FAKE_CLIENT_XFF}"

        # Trusted peer: a forged leftmost prefix cannot win (recursive walks to
        # the rightmost untrusted hop).
        assert _probe(base, FAKE_EDGE, network, f"1.2.3.4, {FAKE_CLIENT_XFF}") == (
            f"XFF={FAKE_CLIENT_XFF}"
        )

        # Direct/untrusted peer: the spoofed value is ignored and the true peer
        # is forwarded instead.
        assert _probe(base, FAKE_UNTRUSTED, network, "10.0.0.1") == f"XFF={FAKE_UNTRUSTED}"
    finally:
        _run(["docker", "rm", "-f", name])
        _run(["docker", "network", "rm", network])
