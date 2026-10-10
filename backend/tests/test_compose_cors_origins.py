"""Regression tests for the docker-compose CORS_ORIGINS shadowing bug.

Defect
------
``docker-compose.yml`` loaded the backend config from ``backend/.env`` via
``env_file:`` **and** also declared, in the backend service's ``environment:``
block::

    - CORS_ORIGINS=${CORS_ORIGINS:-}

Docker Compose interpolates ``${CORS_ORIGINS:-}`` from the *project-root*
``.env`` file or the shell — **never** from the service's ``env_file`` — and a
value in ``environment:`` takes precedence over ``env_file:``. So when the root
variable was unset the interpolation yielded ``""`` and injected an **empty**
``CORS_ORIGINS`` into the container, shadowing the real deployed origin from
``backend/.env``. ``app/main.py`` then fell back to ``http://localhost:5173``,
so a production deployment served cross-origin requests from the wrong (dev)
origin — or, with credentials enabled, rejected the real one.

Guard
-----
* A structural test asserts the backend service's ``environment:`` block does
  **not** re-declare ``CORS_ORIGINS`` (the fix) while still pinning the settings
  that legitimately belong there (``PYTHONUNBUFFERED=1``).
* A raw-text test asserts the compose file never interpolates ``${CORS_ORIGINS``
  anywhere, so a project-root ``.env``/shell value cannot reach the container.
* Docker-backed tests (skipped when the docker CLI is unavailable) resolve a
  **hermetic** fixture compose that reuses the repo's actual ``environment:``
  block, and prove the intended origin from an ``env_file`` survives when the
  root variable is unset **and** that a spoofed root value cannot override it.

The fixture uses only non-secret placeholder values and never reads, copies or
depends on the real ``backend/.env``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"

# The compose file docker-compose.yml must load the backend config from.
COMPOSE_ENV_FILE = "backend/.env"

# Non-secret origin used by the hermetic fixtures below.
FIXTURE_ORIGIN = "https://intended.example"
SPOOF_ORIGIN = "https://evil.example"


def _compose() -> dict:
    return yaml.safe_load(DOCKER_COMPOSE.read_text(encoding="utf-8"))


def _backend_service() -> dict:
    return _compose()["services"]["backend"]


def _as_map(environment) -> dict:
    """Normalise an ``environment:`` block (list of K=V or mapping) to a dict."""
    if environment is None:
        return {}
    if isinstance(environment, dict):
        return {str(k): ("" if v is None else str(v)) for k, v in environment.items()}
    result: dict[str, str] = {}
    for entry in environment:
        key, _, value = str(entry).partition("=")
        result[key.strip()] = value
    return result


def _env_files(service: dict) -> list[str]:
    env_file = service.get("env_file")
    if env_file is None:
        return []
    if isinstance(env_file, str):
        return [env_file]
    return [str(e) for e in env_file]


# ── Structural guards (no docker required) ────────────────────────────


def test_backend_service_loads_backend_env_file():
    assert COMPOSE_ENV_FILE in _env_files(_backend_service()), (
        f"docker-compose.yml must load {COMPOSE_ENV_FILE!r} via env_file."
    )


def test_backend_environment_does_not_shadow_cors_origins():
    """Regression: CORS_ORIGINS must not be re-declared in ``environment:``.

    ``environment:`` overrides ``env_file:``, and the interpolation default
    resolves from the project root — so any ``CORS_ORIGINS`` here shadows the
    authoritative value in ``backend/.env`` (with an empty string when unset).
    """
    env = _as_map(_backend_service().get("environment"))
    assert "CORS_ORIGINS" not in env, (
        "docker-compose.yml re-declares CORS_ORIGINS in the backend environment: "
        "block. `environment:` takes precedence over `env_file:` and interpolates "
        "from the project-root .env/shell (NOT backend/.env), so it shadows the "
        "real origin with an empty string. Remove it; backend/.env is the single "
        "source of truth."
    )


def test_backend_environment_preserves_other_settings():
    """The fix must not drop the settings that legitimately live in environment:."""
    env = _as_map(_backend_service().get("environment"))
    assert env.get("PYTHONUNBUFFERED") == "1", (
        "the backend environment: block must keep PYTHONUNBUFFERED=1"
    )


def _iter_string_values(obj):
    """Yield every string anywhere in a parsed-YAML structure."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from _iter_string_values(key)
            yield from _iter_string_values(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_string_values(item)


def test_compose_never_interpolates_cors_origins():
    """No compose interpolation of CORS_ORIGINS in any parsed value.

    Compose only interpolates YAML *values*, never comments, so this inspects the
    parsed structure. A ``${CORS_ORIGINS...}`` value lets a project-root
    .env/shell value (unset -> empty) reach the container, which is exactly the
    shadowing we removed.
    """
    offenders = [s for s in _iter_string_values(_compose()) if "${CORS_ORIGINS" in s]
    assert not offenders, (
        "docker-compose.yml interpolates ${CORS_ORIGINS...}; this resolves from "
        "the project-root .env/shell and can shadow or spoof the value from "
        "backend/.env. Load CORS_ORIGINS via env_file only."
    )


# ── Behavioural guards (resolve a hermetic fixture; need docker) ──────
#
# These build a throwaway compose project whose backend ``environment:`` block
# is the repo's own block, verbatim, plus a controlled env_file. Resolving it
# with `docker compose config` therefore reproduces the repo's real behaviour
# without ever touching backend/.env. If someone reintroduces the
# `${CORS_ORIGINS:-}` entry, the fixture resolves it and the assertions fail.


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _build_fixture(project_dir: Path) -> Path:
    """Write a hermetic compose project reusing the repo's environment block."""
    (project_dir / "fixture.env").write_text(
        "# non-secret test fixture\n"
        "JWT_SECRET=fixture-not-a-real-secret\n"
        f"CORS_ORIGINS={FIXTURE_ORIGIN}\n",
        encoding="utf-8",
    )
    compose = {
        "services": {
            "backend": {
                "image": "alpine",
                "env_file": ["./fixture.env"],
                # The repo's own backend environment: block, verbatim.
                "environment": _backend_service().get("environment"),
            }
        }
    }
    compose_path = project_dir / "docker-compose.yml"
    compose_path.write_text(yaml.safe_dump(compose), encoding="utf-8")
    return compose_path


def _resolve_backend_env(project_dir: Path, compose_path: Path, extra_env: dict) -> dict:
    # Force the interpolation variable to a known state regardless of the caller.
    env = {k: v for k, v in os.environ.items() if k != "CORS_ORIGINS"}
    env.update(extra_env)
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "config", "--format", "json"],
        cwd=str(project_dir), capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, (
        f"`docker compose config` failed:\n{result.stderr}"
    )
    config = json.loads(result.stdout)
    return _as_map(config["services"]["backend"].get("environment"))


@pytest.fixture()
def compose_project(tmp_path: Path) -> tuple[Path, Path]:
    if not _docker_compose_available():
        pytest.skip("docker compose CLI not available")
    compose_path = _build_fixture(tmp_path)
    return tmp_path, compose_path


def test_env_file_origin_survives_when_root_variable_unset(compose_project):
    """The intended origin from env_file must not be shadowed by an empty value."""
    project_dir, compose_path = compose_project
    resolved = _resolve_backend_env(project_dir, compose_path, extra_env={})
    assert resolved.get("CORS_ORIGINS") == FIXTURE_ORIGIN, (
        "the env_file CORS_ORIGINS was shadowed when the project-root variable "
        f"was unset; got {resolved.get('CORS_ORIGINS')!r}, expected "
        f"{FIXTURE_ORIGIN!r}. docker-compose.yml must not set CORS_ORIGINS in "
        "`environment:`."
    )


def test_root_variable_cannot_spoof_container_origins(compose_project):
    """A project-root/shell CORS_ORIGINS must not override env_file's value."""
    project_dir, compose_path = compose_project
    resolved = _resolve_backend_env(
        project_dir, compose_path, extra_env={"CORS_ORIGINS": SPOOF_ORIGIN}
    )
    assert resolved.get("CORS_ORIGINS") == FIXTURE_ORIGIN, (
        "a project-root/shell CORS_ORIGINS reached the container and replaced "
        f"the env_file value: got {resolved.get('CORS_ORIGINS')!r}. The backend "
        "must take CORS_ORIGINS only from backend/.env via env_file."
    )
