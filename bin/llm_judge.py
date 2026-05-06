"""Tier 3 DeepSeek client — three-prompt adversarial spec reviewer. Stdlib only."""
import json
import os
import pathlib
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from bin import findings
from bin.findings import Finding, FindingLocation

# Maximum findings surfaced per prompt (cap per spec: 10 × 3 = 30 max)
_FINDINGS_CAP_PER_PROMPT = 10

# Rough token estimate: 1 token ≈ 4 chars
_CHARS_PER_TOKEN = 4

# Spec-wide sentinel location
_SPEC_WIDE = FindingLocation(scope="spec-wide")


def _secrets_path_default() -> pathlib.Path:
    """Return the canonical ~/.spectre/secrets.env path (mirrors setup_wizard)."""
    return pathlib.Path.home() / ".spectre" / "secrets.env"


def _resolve_secrets_file_path(explicit: pathlib.Path | None = None) -> pathlib.Path:
    """Resolve secrets file path: explicit > SPECTRE_SECRETS_FILE env > default.

    Mirrors setup_wizard._resolve_secrets_file_path — kept here to avoid a
    circular import (setup_wizard does not import llm_judge).
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get("SPECTRE_SECRETS_FILE")
    if env_path:
        return pathlib.Path(env_path)
    return _secrets_path_default()


def resolve_api_key(api_key_env: str) -> tuple[str, str] | None:
    """Return (value, source) for *api_key_env*, or None if not found.

    Probe order:
      1. os.environ[api_key_env] — fast path, no disk I/O.
      2. SPECTRE_SECRETS_FILE / ~/.spectre/secrets.env — KEY=value lines,
         with or without surrounding quotes.

    Source strings: "env" | "secrets-file".
    Never logs or returns the key value in an error message.
    """
    # 1. Live environment variable.
    value = os.environ.get(api_key_env)
    if value:
        return (value, "env")

    # 2. Secrets file fallback.
    secrets_path = _resolve_secrets_file_path()
    if secrets_path.is_file():
        try:
            content = secrets_path.read_text(encoding="utf-8")
        except (OSError, PermissionError):
            return None
        prefix = f"{api_key_env}="
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(prefix):
                raw_value = stripped[len(prefix):]
                # Strip surrounding quotes (single or double).
                if len(raw_value) >= 2 and raw_value[0] in ('"', "'") and raw_value[-1] == raw_value[0]:
                    raw_value = raw_value[1:-1]
                if raw_value:
                    return (raw_value, "secrets-file")

    return None


# Three prompt templates (per Plan Decision 2)
_PROMPTS = [
    {
        "kind": "tier3-context-gap",
        "system": (
            "You are an adversarial reviewer. Find concrete missing context that would block correct "
            "execution. Output JSON only: "
            '{findings: [{kind: \'tier3-context-gap\', message: \'...\', step: <int|null>, '
            "suggested_fix: '<≤140>'}]}. Up to 10 findings."
        ),
        "user": (
            "Review this spec for missing context (assumptions, preconditions, system state, "
            "environment variables, version constraints):\n\n{spec_text}"
        ),
    },
    {
        "kind": "tier3-spec-asserts-wrong",
        "system": (
            "You are an adversarial reviewer. Identify factual claims in the spec that contradict "
            "known systemd, python stdlib, or Linux defaults. Output JSON only: "
            '{findings: [{kind: \'tier3-spec-asserts-wrong\', message: \'...\', step: <int|null>, '
            "suggested_fix: '<≤140>'}]}. Up to 10 findings."
        ),
        "user": "Review this spec for factual errors:\n\n{spec_text}",
    },
    {
        "kind": "tier3-attacker-view",
        "system": (
            "You are an adversarial reviewer. If you were an attacker handed this spec to execute, "
            "what would you exploit? Output JSON only: "
            '{findings: [{kind: \'tier3-attacker-view\', message: \'...\', step: <int|null>, '
            "suggested_fix: '<≤140>'}]}. Up to 10 findings."
        ),
        "user": "Review this spec for attack surfaces:\n\n{spec_text}",
    },
]


@dataclass
class JudgeConfig:
    enabled: bool
    api_key_env: str  # name of env var holding the key (not the key itself)
    model: str
    base_url: str = "https://api.deepseek.com/v1"
    budget_tokens_per_spec: int = 50_000
    timeout_s: int = 30


class _NoApiKeyError(Exception):
    """Raised when neither env var nor secrets file provides the API key."""

    def __init__(self, api_key_env: str) -> None:
        self.api_key_env = api_key_env
        super().__init__(f"no-api-key: {api_key_env} not found in env or secrets file")


def _call_deepseek(prompts: dict, *, config: JudgeConfig) -> str:
    """Single API call. Returns response content string. Raises on HTTP / auth errors."""
    key_result = resolve_api_key(config.api_key_env)
    if not key_result:
        raise _NoApiKeyError(config.api_key_env)
    api_key, _source = key_result
    body = json.dumps(
        {
            "model": config.model,
            "messages": [
                {"role": "system", "content": prompts["system"]},
                {"role": "user", "content": prompts["user"]},
            ],
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{config.base_url}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _unavailable(message: str) -> Finding:
    """Return a tier3-unavailable sentinel finding (info severity, not dismissable)."""
    # Truncate message to 140 chars (Finding validator enforces this)
    if len(message) > findings.MAX_MESSAGE_LEN:
        message = message[: findings.MAX_MESSAGE_LEN]
    return Finding(
        tier=3,
        kind="tier3-unavailable",
        severity="info",
        location=_SPEC_WIDE,
        message=message,
        dismissable=False,
    )


def _parse_findings(content: str, expected_kind: str) -> list[Finding]:
    """Parse JSON response content into Finding objects. Raises on malformed content."""
    parsed = json.loads(content)
    raw_items = parsed["findings"]
    result: list[Finding] = []
    for item in raw_items[:_FINDINGS_CAP_PER_PROMPT]:
        kind = item.get("kind", expected_kind)
        # Normalise kind to expected_kind — DeepSeek might vary
        if kind not in findings.KNOWN_KINDS:
            kind = expected_kind
        message = str(item.get("message", ""))[:findings.MAX_MESSAGE_LEN]
        step_raw = item.get("step")
        step = int(step_raw) if step_raw is not None else None
        fix_raw = item.get("suggested_fix")
        fix = str(fix_raw)[:findings.MAX_FIX_LEN] if fix_raw is not None else None
        location = (
            FindingLocation(scope="step", step=step)
            if step is not None
            else _SPEC_WIDE
        )
        result.append(
            Finding(
                tier=3,
                kind=kind,
                severity="info",
                location=location,
                message=message,
                suggested_fix=fix,
                dismissable=True,
            )
        )
    return result


def _run_prompt(prompt_template: dict, spec_text: str, *, config: JudgeConfig) -> list[Finding]:
    """Run one prompt. Returns findings on success; [unavailable] on any failure."""
    prompts = {
        "system": prompt_template["system"],
        "user": prompt_template["user"].format(spec_text=spec_text),
    }
    expected_kind = prompt_template["kind"]
    try:
        content = _call_deepseek(prompts, config=config)
        return _parse_findings(content, expected_kind)
    except _NoApiKeyError:
        # Distinct skip reason: neither env var nor secrets file has the key.
        return [_unavailable(f"Tier 3 skipped (no-api-key): {config.api_key_env} not found")]
    except urllib.error.HTTPError as exc:
        return [_unavailable(f"Tier 3 unavailable: HTTP {exc.code}")]
    except urllib.error.URLError as exc:
        return [_unavailable(f"Tier 3 unavailable: URLError {exc.reason}")]
    except (TimeoutError, socket.timeout) as exc:
        return [_unavailable(f"Tier 3 unavailable: timeout")]
    except json.JSONDecodeError as exc:
        return [_unavailable("Tier 3 unavailable: malformed JSON response")]
    except KeyError as exc:
        return [_unavailable(f"Tier 3 unavailable: missing field {exc}")]
    except RuntimeError as exc:
        return [_unavailable(f"Tier 3 unavailable: {exc}")]
    except Exception as exc:
        return [_unavailable(f"Tier 3 unavailable: {type(exc).__name__}")]


def evaluate(spec_text: str, *, config: JudgeConfig) -> list[Finding]:
    """Run the 3-prompt Tier 3 probing over spec_text.

    Returns Finding list (possibly empty, possibly with tier3-unavailable sentinel).
    Never raises — all failure modes return findings.
    """
    if not config.enabled:
        return []

    # Token budget check (crude: 1 token ≈ 4 chars)
    estimated_tokens = len(spec_text) // _CHARS_PER_TOKEN
    if estimated_tokens >= config.budget_tokens_per_spec:
        return [_unavailable("Tier 3 skipped: spec exceeds budget")]

    all_findings: list[Finding] = []
    for prompt_template in _PROMPTS:
        batch = _run_prompt(prompt_template, spec_text, config=config)
        all_findings.extend(batch)

    return all_findings
