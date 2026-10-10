"""Deployment-preflight regression tests for env documentation.

These guard the deployment docs against drifting from the code that consumes
them. They deliberately do **not** import the app (so they run even when
``JWT_SECRET`` is unset) — they read the docs and the source as text.

Guarded invariants:

* ``backend/.env.example`` and the README "Environment Variables" table must
  document exactly the same set of keys (no doc drifts ahead/behind the other);
* the JWT signing variable is documented as ``JWT_SECRET`` and the stale
  ``JWT_SECRET_KEY`` name is never an assignment key in ``.env.example``
  (regression: the example file used to define ``JWT_SECRET_KEY`` while
  ``app/routers/auth.py`` reads ``JWT_SECRET``);
* every documented key is actually referenced by the backend source, so docs
  never document a fictional variable;
* no real secret value is committed — secret-bearing keys are blank or a
  ``replace-with-…`` placeholder.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

ENV_EXAMPLE = BACKEND_DIR / ".env.example"
README = REPO_ROOT / "README.md"
APP_DIR = BACKEND_DIR / "app"
ROOT_ENV_EXAMPLE = REPO_ROOT / ".env.example"
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"

# The env file docker-compose.yml actually loads into the backend container.
# Compose does NOT inject a root .env into the container, so any doc that claims
# that (or points deployers at a root .env for the backend) misdirects them into
# a crash loop: app/routers/auth.py raises at import when JWT_SECRET is unset.
COMPOSE_ENV_FILE = "backend/.env"

# Keys whose documented value must never be a real secret.
SECRET_KEYS = {
    "JWT_SECRET",
    "INITIAL_ADMIN_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ADMIN_CHAT_ID",
    "DIGIPAY_CLIENT_ID",
    "DIGIPAY_CLIENT_SECRET",
    "DIGIPAY_USERNAME",
    "DIGIPAY_PASSWORD",
    "SMS_IR_API_KEY",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
}

# Backticked uppercase identifiers that name an env key.
_KEY_TOKEN = re.compile(r"`([A-Z][A-Z0-9_]+)`")


def _env_entries(path: Path) -> list[tuple[str, str]]:
    """(key, value) for every non-comment ``KEY=value`` line in *path*."""
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        entries.append((key.strip(), value.strip()))
    return entries


def _env_example_entries() -> list[tuple[str, str]]:
    return _env_entries(ENV_EXAMPLE)


def _env_example_keys() -> list[str]:
    return [k for k, _ in _env_example_entries()]


def _readme_table_keys() -> list[str]:
    """Env keys named in the README "Environment Variables" table.

    Only the key column (the first cell) of each data row is read, so a row's
    *description* mentioning another identifier (e.g. the caution that the
    variable is ``JWT_SECRET`` and not ``JWT_SECRET_KEY``) is not mistaken for a
    documented key.
    """
    lines = README.read_text(encoding="utf-8").splitlines()
    header = next(
        (i for i, ln in enumerate(lines)
         if ln.strip().startswith("| Variable |") and "Default" in ln),
        None,
    )
    assert header is not None, "README env-var table header not found"

    keys: list[str] = []
    for line in lines[header + 1:]:
        if not line.lstrip().startswith("|"):
            break  # table ended
        cells = line.split("|")
        if len(cells) < 2:
            continue
        keys.extend(_KEY_TOKEN.findall(cells[1]))
    return keys


def _app_source() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in sorted(APP_DIR.rglob("*.py"))
    )


# ── Alignment: the two docs must agree ───────────────────────────────

def test_env_example_and_readme_document_the_same_keys():
    env_keys = set(_env_example_keys())
    readme_keys = set(_readme_table_keys())

    assert env_keys == readme_keys, (
        "backend/.env.example and the README env table have drifted apart.\n"
        f"  only in .env.example: {sorted(env_keys - readme_keys)}\n"
        f"  only in README:       {sorted(readme_keys - env_keys)}"
    )


def test_no_duplicate_keys_in_env_example():
    keys = _env_example_keys()
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    assert not duplicates, f"duplicate keys in .env.example: {duplicates}"


def test_every_documented_key_is_consumed_by_the_backend():
    source = _app_source()
    undocumented = [
        key for key in _env_example_keys()
        if f'"{key}"' not in source and f"'{key}'" not in source
    ]
    assert not undocumented, (
        "documented but never read by the backend: " + ", ".join(sorted(undocumented))
    )


# ── JWT variable-name regression ─────────────────────────────────────

def test_jwt_variable_is_documented_as_jwt_secret_not_key():
    env_keys = _env_example_keys()

    assert "JWT_SECRET" in env_keys, ".env.example must define JWT_SECRET"
    assert "JWT_SECRET_KEY" not in env_keys, (
        ".env.example must not define JWT_SECRET_KEY — auth.py reads JWT_SECRET"
    )

    readme_keys = _readme_table_keys()
    assert "JWT_SECRET" in readme_keys
    assert "JWT_SECRET_KEY" not in readme_keys


def test_backend_source_reads_jwt_secret_and_never_the_stale_name():
    source = _app_source()
    assert '"JWT_SECRET"' in source or "'JWT_SECRET'" in source
    assert "JWT_SECRET_KEY" not in source, (
        "backend source still references the stale JWT_SECRET_KEY name"
    )


# ── No committed secret values ───────────────────────────────────────

def test_secret_keys_are_blank_or_placeholders():
    values = dict(_env_example_entries())
    for key in sorted(SECRET_KEYS):
        assert key in values, f"secret key {key} missing from .env.example"
        value = values[key]
        assert value == "" or value.lower().startswith("replace-with-"), (
            f"{key} in .env.example must be blank or a 'replace-with-...' "
            f"placeholder, got a real-looking value"
        )


def test_env_example_contains_no_jwt_or_key_like_value():
    for key, value in _env_example_entries():
        assert not value.startswith("eyJ"), f"{key} looks like a real JWT"
        # A long unbroken base64/hex run (>=40 chars) is a secret, not config.
        assert not re.search(r"[A-Za-z0-9_\-]{40,}", value), (
            f"{key} looks like an embedded secret"
        )


# ── Deployment guidance that must stay documented ────────────────────

def test_public_site_origin_default_is_https():
    values = dict(_env_example_entries())
    assert values.get("PUBLIC_SITE_ORIGIN", "").startswith("https://"), (
        "the documented PUBLIC_SITE_ORIGIN default must use HTTPS"
    )


def test_staging_digipay_caution_is_documented():
    readme = README.read_text(encoding="utf-8").lower()
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8").lower()
    # CAUTION text lives in .env.example; README carries the same warning in
    # its DIGIPAY_ENV row.
    assert "staging" in readme and "never combine it with live" in readme
    assert "never use it with live merchant credentials" in env_example


def test_bootstrap_admin_password_scope_is_documented():
    readme = README.read_text(encoding="utf-8").lower()
    # INITIAL_ADMIN_PASSWORD applies only when no users exist and never resets
    # the live admin.
    assert "empty users table" in readme
    assert "never resets" in readme or "never resets the live admin" in readme


def test_cors_origins_must_be_the_real_deployed_origin():
    readme = README.read_text(encoding="utf-8").lower()
    assert "cors_origins" in readme
    assert "exact" in readme and "origin" in readme


# ── Compose wiring vs. docs — root .env.example drift guard ──────────
#
# Regression (I1): a root .env.example claimed "This file is loaded by docker
# compose when placed in the project root." Compose only loads backend/.env via
# env_file (and interpolates CORS_ORIGINS), so a deployer who seeded a root .env
# booted a backend with no JWT_SECRET -> RuntimeError at auth.py import -> crash
# loop. These tests pin the compose wiring and force the root example to redirect
# instead of misdirect.


def _compose_env_files() -> list[str]:
    """Paths listed under docker-compose.yml's ``env_file:`` key.

    Parsed as text (no YAML dependency) to match this module's docs-as-text
    approach. Handles both the scalar and the ``- path`` list form.
    """
    files: list[str] = []
    in_env_file = False
    indent = 0
    for line in DOCKER_COMPOSE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        leading = len(line) - len(line.lstrip())
        if stripped.startswith("env_file:"):
            rest = stripped[len("env_file:"):].strip()
            in_env_file = True
            indent = leading
            if rest:
                rest = rest.strip("[]")
                files += [
                    part.strip().strip("'\"")
                    for part in rest.split(",")
                    if part.strip()
                ]
            continue
        if in_env_file:
            if leading > indent and stripped.startswith("-"):
                files.append(stripped[1:].strip().strip("'\""))
            elif leading <= indent:
                in_env_file = False
    return files


def test_docker_compose_loads_backend_env_file():
    files = _compose_env_files()
    assert COMPOSE_ENV_FILE in files, (
        f"docker-compose.yml must load {COMPOSE_ENV_FILE!r} via env_file; Compose "
        "does not inject a root .env into the backend container."
    )


def test_root_env_example_does_not_claim_docker_compose_loads_it():
    if not ROOT_ENV_EXAMPLE.exists():
        return  # deleting the stray root example is an acceptable resolution
    text = ROOT_ENV_EXAMPLE.read_text(encoding="utf-8").lower()
    assert "loaded by docker compose" not in text, (
        "root .env.example falsely claims Docker Compose loads it. Compose only "
        f"reads {COMPOSE_ENV_FILE!r} (env_file), so a deployer who seeds a root "
        ".env leaves JWT_SECRET unset and the backend crash-loops at import."
    )


def test_root_env_example_redirects_to_backend_env_example():
    if not ROOT_ENV_EXAMPLE.exists():
        return
    text = ROOT_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "backend/.env.example" in text, (
        "root .env.example must clearly redirect deployers to backend/.env.example"
    )


def test_root_env_example_keys_do_not_drift_from_backend_example():
    if not ROOT_ENV_EXAMPLE.exists():
        return
    backend_keys = set(_env_example_keys())
    stray = sorted(
        key for key, _ in _env_entries(ROOT_ENV_EXAMPLE) if key not in backend_keys
    )
    assert not stray, (
        "root .env.example documents keys absent from backend/.env.example: "
        + ", ".join(stray)
    )
