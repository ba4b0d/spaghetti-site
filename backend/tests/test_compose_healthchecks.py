"""Container healthchecks must probe a literal ``127.0.0.1``, never ``localhost``.

Defect
------
Both compose healthchecks probed ``http://localhost:...``. Inside the containers
``/etc/hosts`` maps ``localhost`` to ``127.0.0.1`` *and* ``::1``, while nginx
(``listen 80;``) and uvicorn (``--host 0.0.0.0``) bind IPv4 only. BusyBox wget
resolves ``localhost`` to ``::1`` first and gets ECONNREFUSED, so the frontend
reported **unhealthy while it was serving traffic normally** — a false
unhealthy that keeps ``depends_on: service_healthy`` dependents from starting.
(The real image's ``10-listen-on-ipv6-by-default.sh`` does *not* add an IPv6
listener for our custom ``default.conf``, because that file differs from the
packaged default it hashes against.)

Fix
---
Probe the literal loopback address (``http://127.0.0.1:80`` /
``http://127.0.0.1:8000/health``) so the probe cannot resolve to an unbound
IPv6 address.

Tests
-----
* Structural: no healthcheck command in ``docker-compose.yml`` mentions
  ``localhost``, and each probes ``127.0.0.1``.
* Behavioural (skipped without docker): run the real repo nginx config and
  execute the exact frontend healthcheck command inside the container; assert it
  exits 0. The same command with ``localhost`` is shown to fail there, which is
  the false-unhealthy this fix removes.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"
NGINX_CONF = REPO_ROOT / "frontend" / "nginx.conf"


def _compose() -> dict:
    return yaml.safe_load(DOCKER_COMPOSE.read_text(encoding="utf-8"))


def _healthcheck_test(service: str) -> list[str]:
    test = _compose()["services"][service]["healthcheck"]["test"]
    assert isinstance(test, list) and test and test[0] == "CMD", test
    return test


# ── Structural guards (no docker required) ────────────────────────────


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_healthcheck_never_targets_localhost(service):
    command = " ".join(_healthcheck_test(service))
    assert "localhost" not in command, (
        f"the {service} healthcheck probes `localhost`, which resolves to ::1 as "
        "well; the container binds IPv4 only, so the probe can report a healthy "
        "container unhealthy. Use 127.0.0.1."
    )


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_healthcheck_targets_loopback_literal(service):
    command = " ".join(_healthcheck_test(service))
    assert "127.0.0.1" in command, f"the {service} healthcheck must probe 127.0.0.1"


# ── Behavioural guard (real nginx; needs docker) ──────────────────────


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


@pytest.mark.skipif(not _docker_available(), reason="docker not available")
def test_frontend_healthcheck_command_succeeds_and_localhost_fails():
    name = "hc_probe_pytest"
    _run(["docker", "rm", "-f", name])
    run = _run(
        [
            "docker", "run", "-d", "--name", name,
            # proxy_pass resolves `backend` at config load; give it a stub.
            "--add-host", "backend:127.0.0.1",
            "-v", f"{NGINX_CONF.as_posix()}:/etc/nginx/conf.d/default.conf:ro",
            "nginx:alpine",
        ],
    )
    try:
        if run.returncode != 0:
            out = run.stdout + run.stderr
            if "Unable to find image" in out or "manifest unknown" in out:
                pytest.skip("nginx image unavailable: " + out.strip()[:200])
            raise AssertionError(out)

        for _ in range(40):
            if _run(["docker", "exec", name, "wget", "-qO-", "http://127.0.0.1:80"],
                    timeout=30).returncode == 0:
                break
            time.sleep(0.2)
        else:
            pytest.skip("nginx container never became ready")

        # The exact configured healthcheck command must succeed.
        healthcheck = _healthcheck_test("frontend")[1:]  # drop "CMD"
        assert _run(["docker", "exec", name, *healthcheck]).returncode == 0, (
            f"configured frontend healthcheck {' '.join(healthcheck)!r} failed"
        )

        # The old `localhost` form fails in the very same container: this is the
        # false-unhealthy the fix removes (nginx listens IPv4-only, `localhost`
        # resolves to ::1 first).
        legacy = [part.replace("127.0.0.1", "localhost") for part in healthcheck]
        assert _run(["docker", "exec", name, *legacy]).returncode != 0, (
            "expected the legacy `localhost` healthcheck to fail; if nginx now "
            "binds IPv6 too, drop this assertion (the 127.0.0.1 fix is still safe)"
        )
    finally:
        _run(["docker", "rm", "-f", name])
