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
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/tests -> repo root
NGINX_CONF = REPO_ROOT / "frontend" / "nginx.conf"


def _conf_text() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


def _location_block(text: str, header: str) -> str:
    """Extract a ``location … { … }`` block via brace matching."""
    start = text.index(header)
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError(f"unbalanced location block: {header}")


def _pay_location_block(text: str) -> str:
    """Extract the ``location ~* ^/pay/ { … }`` block via brace matching."""
    return _location_block(text, "location ~* ^/pay/ {")


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


# ── I3 residual — the token is also in the /api/v1/commerce/invoices/ API path,
# which the pay page calls on every load. The generic `^~ /api/` block logs it;
# these assertions pin the dedicated no-log blocks that must actually win. ──

def test_invoice_api_prefix_is_longer_than_generic_api_prefix():
    """A longer `^~` prefix wins by longest-match, so it is NOT shadowed."""
    text = _conf_text()
    specific = "location ^~ /api/v1/commerce/invoices/ {"
    generic = "location ^~ /api/ {"
    assert specific in text
    assert generic in text  # generic block is unchanged
    # The specific block is declared before the generic one (order-independent
    # for prefixes, but keeps intent obvious) and could not be a plain `~*`
    # regex: an `^~` prefix match stops regex evaluation.
    assert text.index(specific) < text.index(generic)


def test_invoice_api_prefix_disables_access_log_and_proxies_identically():
    block = _location_block(_conf_text(), "location ^~ /api/v1/commerce/invoices/ {")
    assert "access_log off;" in block
    # no URI in proxy_pass ⇒ the request URI is forwarded to the backend
    # unchanged, matching the generic `^~ /api/` behaviour.
    assert "proxy_pass http://backend:8000;" in block


def test_invoice_api_has_case_insensitive_companion_block():
    block = _location_block(_conf_text(), "location ~* ^/api/v1/commerce/invoices/ {")
    assert "access_log off;" in block
    assert "proxy_pass http://backend:8000;" in block
    # must precede the static-asset regex so a token-like "/…/<token>.js" is
    # still proxied+redacted rather than served from the immutable-cache branch.
    text = _conf_text()
    assert text.index("location ~* ^/api/v1/commerce/invoices/ {") < text.index(
        "location ~* \\.(js|css|"
    )


@pytest.mark.skipif(not _docker_available(), reason="docker not available")
def test_real_nginx_probe_never_logs_the_invoice_token(tmp_path):
    """Run the real config and prove, by request probes, that the token is not
    written to the access log while ordinary API requests still are."""
    repo_server = _conf_text()
    wrapper = (
        "worker_processes 1;\n"
        "pid /run/nginx.pid;\n"
        "error_log /var/log/nginx/error.log warn;\n"
        "events { worker_connections 1024; }\n"
        "http {\n"
        "  include /etc/nginx/mime.types;\n"
        "  default_type text/plain;\n"
        "  access_log /var/log/nginx/access.log;\n"
        "  server { listen 8000; access_log off;"
        " location / { return 200 \"UPSTREAM:$request_uri\"; } }\n"
        + repo_server
        + "}\n"
    )
    conf = tmp_path / "nginx.conf"
    conf.write_text(wrapper, encoding="utf-8")

    name = "i3probe_pytest"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)
    run = subprocess.run(
        [
            "docker", "run", "-d", "--name", name,
            "--add-host", "backend:127.0.0.1",
            "-p", "0:80",
            "-v", f"{conf.as_posix()}:/etc/nginx/nginx.conf:ro",
            "nginx:alpine",
        ],
        capture_output=True, text=True, timeout=180,
    )
    try:
        assert run.returncode == 0, run.stdout + run.stderr
        port_out = subprocess.run(
            ["docker", "port", name, "80"], capture_output=True, text=True, timeout=60
        ).stdout.strip()
        if not port_out:
            pytest.skip("could not resolve forwarded port: " + port_out)
        port = int(port_out.split(":")[-1])
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/ready", timeout=1).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            pytest.skip("nginx container never became ready")

        token = "PYTESTINVOICETOKEN42"
        body = urllib.request.urlopen(
            base + f"/api/v1/commerce/invoices/{token}"
        ).read().decode()
        assert "UPSTREAM" in body, body
        # case variant must also be proxied (and not logged)
        urllib.request.urlopen(
            base + f"/API/v1/Commerce/Invoices/{token}"
        ).read()
        # an ordinary API request must STILL be logged
        urllib.request.urlopen(base + "/api/v1/products").read()

        logs = subprocess.run(
            ["docker", "logs", name], capture_output=True, text=True, timeout=60
        )
        out = logs.stdout + logs.stderr
        assert token not in out, "token leaked into the nginx access log"
        assert "/api/v1/products" in out, "ordinary access logging was disabled"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)
