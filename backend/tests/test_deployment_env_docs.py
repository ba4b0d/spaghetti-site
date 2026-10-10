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


def _env_example_entries() -> list[tuple[str, str]]:
    """(key, value) for every non-comment ``KEY=value`` line."""
    entries: list[tuple[str, str]] = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        entries.append((key.strip(), value.strip()))
    return entries


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
