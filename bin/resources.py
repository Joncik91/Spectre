"""Resource node parsing + extraction from action commands. Stdlib only."""
import re
from dataclasses import dataclass
from typing import Iterable

KNOWN_KINDS = {"port", "db_connection", "api_quota", "file_lock"}

_QUOTED_STRING_RE = re.compile(r'''(?:"[^"]*"|'[^']*')''')
_PORT_RE = re.compile(r"\b(?:--port[= ]|:|-p\s+)(\d{2,5})\b")
_HTTP_SERVER_RE = re.compile(r"\bhttp\.server\s+(\d{2,5})\b")


@dataclass
class Resource:
    id: str
    kind: str
    identifier: str
    capacity: int
    description: str = ""


def _strip_quoted(s: str) -> str:
    return _QUOTED_STRING_RE.sub(" ", s)


def parse_resources(md: str) -> list[Resource]:
    """Parse Resource nodes from graph manifest markdown."""
    pattern = re.compile(
        r"^## Resource:.*?\n+```yaml\n(.*?)\n```",
        re.DOTALL | re.MULTILINE,
    )
    out: list[Resource] = []
    seen_ids: set[str] = set()
    for m in pattern.finditer(md):
        body = m.group(1)
        fields = {}
        for line in body.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip().strip('"').strip("'")
        kind = fields.get("kind", "")
        if kind not in KNOWN_KINDS:
            raise ValueError(f"unknown resource kind: {kind!r}")
        try:
            capacity = int(fields.get("capacity", "0"))
        except ValueError as e:
            raise ValueError(f"capacity must be int: {fields.get('capacity')!r}") from e
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        rid = fields.get("id", "")
        if rid in seen_ids:
            raise ValueError(f"duplicate resource id: {rid}")
        seen_ids.add(rid)
        out.append(Resource(
            id=rid,
            kind=kind,
            identifier=fields.get("identifier", ""),
            capacity=capacity,
            description=fields.get("description", ""),
        ))
    return out


def extract_resources_from_action(command: str) -> list[Resource]:
    """Heuristic extraction of Resources from a shell command."""
    scrubbed = _strip_quoted(command)
    out: list[Resource] = []
    for m in _PORT_RE.finditer(scrubbed):
        port = m.group(1)
        out.append(Resource(
            id=f"res-port-{port}",
            kind="port",
            identifier=port,
            capacity=1,
        ))
    for m in _HTTP_SERVER_RE.finditer(scrubbed):
        port = m.group(1)
        if not any(r.identifier == port for r in out):
            out.append(Resource(
                id=f"res-port-{port}",
                kind="port",
                identifier=port,
                capacity=1,
            ))
    return out
