"""I3 — never log the ``/pay/<token>`` bearer token.

The path segment after ``/pay/`` *is* the credential, so nginx must not write
those requests to the access log — for every case variant (``/PAY/``,
``/Pay/``), since React Router matches case-insensitively. The security headers
the page relies on (no-referrer, no-store, CSP, …) must stay in place.

Config-level assertions always run. A real ``nginx -t`` syntax check runs only
when Docker is available, so the committed config is validated by nginx itself.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests -> repo root
NGINX_CONF = REPO_ROOT / "frontend" / "nginx.conf"


def _conf_text() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


def _pay_location_block(text: str) -> str:
    """Extract the ``location ~* ^/pay/ { … }`` block via brace matching."""
    start = text.index("location ~* ^/pay/ {")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError("unbalanced /pay/ location block")


def test_pay_location_uses_case_insensitive_regex():
    assert "location ~* ^/pay/ {" in _conf_text()


def test_pay_location_disables_access_log():
    assert "access_log off;" in _pay_location_block(_conf_text())


def test_pay_location_retains_security_headers():
    block = _pay_location_block(_conf_text())
    for header in (
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header Referrer-Policy "no-referrer" always;',
        'add_header Cache-Control "no-store" always;',
        'add_header Content-Security-Policy',
    ):
        assert header in block, header


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.mark.skipif(not _docker_available(), reason="docker not available")
def test_nginx_conf_passes_real_syntax_check():
    proc = subprocess.run(
        [
            "docker", "run", "--rm",
            # proxy_pass resolves `backend` at config-load time; give it a stub
            # address so `nginx -t` validates our config rather than DNS.
            "--add-host", "backend:127.0.0.1",
            "-v", f"{NGINX_CONF.as_posix()}:/etc/nginx/conf.d/default.conf:ro",
            "nginx:alpine", "nginx", "-t",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        # Only skip on infrastructure problems (image/network), never mask an
        # actual syntax error.
        if "Unable to find image" in out or "manifest unknown" in out or "lookup" in out:
            pytest.skip("nginx image unavailable: " + out.strip()[:200])
    assert proc.returncode == 0, out
    assert "syntax is ok" in out
