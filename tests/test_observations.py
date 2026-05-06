"""Observe-leg JSONL halt log. Stdlib + pytest only."""
import json
import pathlib
import pytest

from bin import observations


def test_observations_version_is_0_4_1():
    assert observations.OBSERVATIONS_VERSION == "0.4.1"


def test_fingerprint_halt_is_deterministic_for_same_inputs():
    fp_a = observations.fingerprint_halt(action="rm -rf /tmp/foo", classifier_label="destructive-delete: rm -rf")
    fp_b = observations.fingerprint_halt(action="rm -rf /tmp/foo", classifier_label="destructive-delete: rm -rf")
    assert fp_a == fp_b


def test_fingerprint_halt_differs_for_different_actions():
    fp_a = observations.fingerprint_halt(action="rm -rf /tmp/foo", classifier_label="destructive-delete: rm -rf")
    fp_b = observations.fingerprint_halt(action="rm -rf /tmp/bar", classifier_label="destructive-delete: rm -rf")
    assert fp_a != fp_b


def test_fingerprint_halt_differs_for_different_classifier_labels():
    fp_a = observations.fingerprint_halt(action="echo hi", classifier_label="permission-change: chmod")
    fp_b = observations.fingerprint_halt(action="echo hi", classifier_label="destructive-delete: rm -rf")
    assert fp_a != fp_b


def test_fingerprint_halt_returns_64_char_hex_sha256():
    fp = observations.fingerprint_halt(action="x", classifier_label="y")
    assert len(fp) == 64
