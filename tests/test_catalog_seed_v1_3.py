"""tests/test_catalog_seed_v1_3.py — v1.3 catalog seed: input-shape, output-shape, ipc-rpc.

Six tests:
  1-2. input-shape exemplars are present in the loaded catalog.
  3-4. output-shape exemplars are present.
  5-6. ipc-rpc exemplars are present.
  7.   validate_catalog() returns no errors for the full catalog.
  8.   Each new exemplar's calibrated-for values are all in _ALL_FINGERPRINTS.
"""
from __future__ import annotations

import pytest

from bin import _catalog
from bin._catalog import CatalogError, load_catalog, validate_catalog
from bin._catalog import _ALL_FINGERPRINTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_catalog(monkeypatch):
    """Force catalog reload before each test so prior test state does not bleed."""
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)
    yield
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NEW_KEYS = [
    "input-shape:cli-argparse-shape",
    "input-shape:openapi-request-body",
    "output-shape:json-rpc-response-2.0",
    "output-shape:openapi-response-envelope",
    "ipc-rpc:unix-socket-rpc",
    "ipc-rpc:subprocess-rpc",
]


# ---------------------------------------------------------------------------
# Tests: exemplar presence
# ---------------------------------------------------------------------------

def test_input_shape_cli_argparse_shape_in_catalog():
    """input-shape:cli-argparse-shape is loadable and present in the catalog."""
    cat = load_catalog()
    assert "input-shape:cli-argparse-shape" in cat.exemplars, (
        "expected input-shape:cli-argparse-shape in catalog; "
        f"available input-shape keys: {[k for k in cat.exemplars if k.startswith('input-shape:')]}"
    )


def test_input_shape_openapi_request_body_in_catalog():
    """input-shape:openapi-request-body is loadable and present in the catalog."""
    cat = load_catalog()
    assert "input-shape:openapi-request-body" in cat.exemplars, (
        "expected input-shape:openapi-request-body in catalog; "
        f"available input-shape keys: {[k for k in cat.exemplars if k.startswith('input-shape:')]}"
    )


def test_output_shape_json_rpc_response_in_catalog():
    """output-shape:json-rpc-response-2.0 is loadable and present in the catalog."""
    cat = load_catalog()
    assert "output-shape:json-rpc-response-2.0" in cat.exemplars, (
        "expected output-shape:json-rpc-response-2.0 in catalog; "
        f"available output-shape keys: {[k for k in cat.exemplars if k.startswith('output-shape:')]}"
    )


def test_output_shape_openapi_response_envelope_in_catalog():
    """output-shape:openapi-response-envelope is loadable and present in the catalog."""
    cat = load_catalog()
    assert "output-shape:openapi-response-envelope" in cat.exemplars, (
        "expected output-shape:openapi-response-envelope in catalog; "
        f"available output-shape keys: {[k for k in cat.exemplars if k.startswith('output-shape:')]}"
    )


def test_ipc_rpc_unix_socket_rpc_in_catalog():
    """ipc-rpc:unix-socket-rpc is loadable and present in the catalog."""
    cat = load_catalog()
    assert "ipc-rpc:unix-socket-rpc" in cat.exemplars, (
        "expected ipc-rpc:unix-socket-rpc in catalog; "
        f"available ipc-rpc keys: {[k for k in cat.exemplars if k.startswith('ipc-rpc:')]}"
    )


def test_ipc_rpc_subprocess_rpc_in_catalog():
    """ipc-rpc:subprocess-rpc is loadable and present in the catalog."""
    cat = load_catalog()
    assert "ipc-rpc:subprocess-rpc" in cat.exemplars, (
        "expected ipc-rpc:subprocess-rpc in catalog; "
        f"available ipc-rpc keys: {[k for k in cat.exemplars if k.startswith('ipc-rpc:')]}"
    )


# ---------------------------------------------------------------------------
# Tests: frontmatter parses without CatalogError
# ---------------------------------------------------------------------------

def test_all_new_exemplars_parse_without_error():
    """Each of the six new exemplars parses without raising CatalogError.

    Confirmed by the catalog having zero parse_errors attributable to
    the new exemplar paths.
    """
    cat = load_catalog()
    new_view_prefixes = ("input-shape", "output-shape", "ipc-rpc")
    new_parse_errors = [
        e for e in cat.parse_errors
        if any(prefix in str(e.path) for prefix in new_view_prefixes)
    ]
    assert new_parse_errors == [], (
        f"unexpected CatalogError(s) for new v1.3 exemplars: {new_parse_errors}"
    )


# ---------------------------------------------------------------------------
# Test: validate_catalog() clean
# ---------------------------------------------------------------------------

def test_validate_catalog_returns_no_errors():
    """validate_catalog() returns an empty error list for the full catalog
    including the six new v1.3 exemplars."""
    errors = validate_catalog()
    assert errors == [], (
        f"validate_catalog() returned {len(errors)} error(s):\n"
        + "\n".join(errors)
    )


# ---------------------------------------------------------------------------
# Test: calibrated-for values are all in _ALL_FINGERPRINTS
# ---------------------------------------------------------------------------

def test_new_exemplar_calibrated_for_values_are_known():
    """Every calibrated-for value in the six new exemplars is in _ALL_FINGERPRINTS."""
    cat = load_catalog()
    bad: list[str] = []
    for key in _NEW_KEYS:
        ex = cat.exemplars.get(key)
        if ex is None:
            bad.append(f"{key}: not found in catalog")
            continue
        for fp in ex.calibrated_for:
            if fp not in _ALL_FINGERPRINTS:
                bad.append(f"{key}: unknown fingerprint {fp!r}")
    assert bad == [], "unknown fingerprint values found:\n" + "\n".join(bad)
