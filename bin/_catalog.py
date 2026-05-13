"""bin/_catalog.py — Metis catalog loader for v1.0 exemplars.

Loads exemplar entries from:
  - Plugin catalog: <PLUGIN_ROOT>/docs/exemplars/<view-type>/<slug>.md
  - User overlay:   ~/.spectre/exemplars/<view-type>/<slug>.md
  - Axis taxonomy:  <PLUGIN_ROOT>/docs/exemplars/<view-type>/axes.yml
                    ~/.spectre/exemplars/<view-type>/axes.yml (overlay)

Each exemplar markdown file has YAML frontmatter (delimited by --- lines)
followed by a body. The loader uses a stdlib-only hand-rolled YAML subset
parser sufficient for the catalog's shapes (no PyYAML dependency, matching
the bin/_glossary.py constraint).

Supported YAML shapes in frontmatter:
  scalar:           key: value
  inline list:      key: [a, b, c]
  inline mapping:   key: {a: 1, b: 2}
  block list:       key:
                      - a
                      - b
  block mapping:    key:
                      a: 1
                      b: 2

Axis taxonomy (axes.yml) supports the same shapes plus a top-level
taxonomy-version: <int> field and an axes: <block-mapping>.

Public API:
  load_catalog() -> Catalog
  lookup(slug) -> Exemplar | None
  by_view_type(view_type) -> list[Exemplar]
  axes(view_type, taxonomy_version=None) -> AxisTaxonomy | None

Stdlib only. No third-party deps.
"""
from __future__ import annotations

import os
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Plugin/user paths
# ---------------------------------------------------------------------------

def _plugin_root() -> pathlib.Path:
    """Return the plugin install root.

    Honors CLAUDE_PLUGIN_ROOT (set by Claude Code when the skill runs from
    the cached plugin) and falls back to walking up from this file's
    location so direct module invocation also works.
    """
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return pathlib.Path(env)
    return pathlib.Path(__file__).resolve().parent.parent


def _user_overlay_root() -> pathlib.Path:
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return pathlib.Path(home) / ".spectre" / "exemplars"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class CatalogError(Exception):
    """Raised when an exemplar file cannot be parsed."""

    def __init__(self, path: pathlib.Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


@dataclass
class Exemplar:
    slug: str
    view_types: list[str]
    conventions: list[str]
    axes: dict[str, str]
    taxonomy_version: int
    source_url: str
    last_reviewed: str
    supersedes: str = ""
    body: str = ""
    origin: str = "plugin"   # "plugin" or "user"
    path: str = ""


@dataclass
class AxisTaxonomy:
    view_type: str
    taxonomy_version: int
    axes: dict[str, "AxisDefinition"]
    origin: str = "plugin"


@dataclass
class AxisDefinition:
    name: str
    values: list[str]
    description: str = ""


@dataclass
class Catalog:
    exemplars: dict[str, Exemplar] = field(default_factory=dict)   # key -> Exemplar (key is "<view-type>:<slug>")
    taxonomies: dict[str, AxisTaxonomy] = field(default_factory=dict)   # view_type -> AxisTaxonomy
    parse_errors: list[CatalogError] = field(default_factory=list)
    # (key, plugin_path, user_path) for each user-overlay entry that shadows a plugin entry
    shadowed: list[tuple[str, str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# YAML subset parser (stdlib only)
# ---------------------------------------------------------------------------

_INLINE_LIST_RE = re.compile(r"^\[(.*)\]$")
_INLINE_MAP_RE = re.compile(r"^\{(.*)\}$")


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _parse_inline_list(raw: str) -> list[str]:
    inner = _INLINE_LIST_RE.match(raw.strip()).group(1)
    if not inner.strip():
        return []
    return [_strip_quotes(item.strip()) for item in inner.split(",")]


def _parse_inline_map(raw: str) -> dict[str, str]:
    inner = _INLINE_MAP_RE.match(raw.strip()).group(1)
    result: dict[str, str] = {}
    if not inner.strip():
        return result
    for pair in inner.split(","):
        if ":" not in pair:
            continue
        k, _, v = pair.partition(":")
        result[k.strip()] = _strip_quotes(v.strip())
    return result


def _parse_yaml_block(text: str) -> dict[str, Any]:
    """Parse the YAML subset used by exemplar frontmatter and axes.yml."""
    result: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0

    def _line_indent(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        # Top-level key (indent 0)
        if _line_indent(line) != 0:
            i += 1
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        rest = m.group(2).strip()
        if rest == "":
            # Look ahead: block list or block mapping
            block_lines: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() == "" or nxt.strip().startswith("#"):
                    j += 1
                    continue
                if _line_indent(nxt) == 0:
                    break
                block_lines.append(nxt)
                j += 1
            result[key] = _parse_block(block_lines)
            i = j
            continue
        # Inline value
        if rest.startswith("["):
            result[key] = _parse_inline_list(rest)
        elif rest.startswith("{"):
            result[key] = _parse_inline_map(rest)
        else:
            result[key] = _strip_quotes(rest)
        i += 1
    return result


def _parse_block(lines: list[str]) -> Any:
    """Parse an indented block — either a list (lines starting with '-') or a mapping."""
    if not lines:
        return {}
    # Detect: list if all non-empty lines after dedent start with "- "
    first_indent = min(len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.strip())
    dedented = [ln[first_indent:] if len(ln) >= first_indent else ln for ln in lines]
    if all(ln.startswith("- ") or ln.strip() == "" for ln in dedented if ln.strip()):
        items: list[Any] = []
        for ln in dedented:
            if not ln.strip():
                continue
            item = ln[2:].strip()
            if item.startswith("["):
                items.append(_parse_inline_list(item))
            elif item.startswith("{"):
                items.append(_parse_inline_map(item))
            else:
                items.append(_strip_quotes(item))
        return items
    # Mapping
    return _parse_yaml_block("\n".join(dedented))


# ---------------------------------------------------------------------------
# Exemplar parser
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

_REQUIRED_EXEMPLAR_FIELDS = ("view-types", "conventions", "axes", "taxonomy-version", "source-url", "last-reviewed")


def _parse_exemplar_file(path: pathlib.Path, origin: str) -> Exemplar:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise CatalogError(path, "missing YAML frontmatter (--- ... ---)")
    fm_text, body = m.group(1), m.group(2)
    fm = _parse_yaml_block(fm_text)

    for req in _REQUIRED_EXEMPLAR_FIELDS:
        if req not in fm:
            raise CatalogError(path, f"missing required frontmatter field {req!r}")

    view_types = fm["view-types"]
    if not isinstance(view_types, list):
        raise CatalogError(path, "view-types must be a list")

    conventions = fm["conventions"]
    if not isinstance(conventions, list):
        raise CatalogError(path, "conventions must be a list")

    axes = fm["axes"]
    if not isinstance(axes, dict):
        raise CatalogError(path, "axes must be a mapping")

    try:
        taxonomy_version = int(str(fm["taxonomy-version"]).strip())
    except (ValueError, TypeError) as exc:
        raise CatalogError(path, f"taxonomy-version must be an integer: {exc}")

    return Exemplar(
        slug=path.stem,
        view_types=view_types,
        conventions=conventions,
        axes={k: str(v) for k, v in axes.items()},
        taxonomy_version=taxonomy_version,
        source_url=str(fm["source-url"]),
        last_reviewed=str(fm["last-reviewed"]),
        supersedes=str(fm.get("supersedes", "") or ""),
        body=body.strip(),
        origin=origin,
        path=str(path),
    )


def _parse_axes_file(path: pathlib.Path, view_type: str, origin: str) -> AxisTaxonomy:
    text = path.read_text(encoding="utf-8")
    fm = _parse_yaml_block(text)
    if "taxonomy-version" not in fm:
        raise CatalogError(path, "missing taxonomy-version")
    if "axes" not in fm or not isinstance(fm["axes"], dict):
        raise CatalogError(path, "missing or malformed axes mapping")
    try:
        tv = int(str(fm["taxonomy-version"]).strip())
    except (ValueError, TypeError) as exc:
        raise CatalogError(path, f"taxonomy-version must be an integer: {exc}")
    axes: dict[str, AxisDefinition] = {}
    for name, defn in fm["axes"].items():
        if not isinstance(defn, dict):
            raise CatalogError(path, f"axis {name!r} must be a mapping")
        values = defn.get("values", [])
        if not isinstance(values, list):
            raise CatalogError(path, f"axis {name!r} values must be a list")
        axes[name] = AxisDefinition(
            name=name,
            values=[str(v) for v in values],
            description=str(defn.get("description", "")),
        )
    return AxisTaxonomy(view_type=view_type, taxonomy_version=tv, axes=axes, origin=origin)


# ---------------------------------------------------------------------------
# Catalog loader
# ---------------------------------------------------------------------------

_LOAD_CACHE: Catalog | None = None


def _scan_root(root: pathlib.Path, origin: str, out: Catalog) -> None:
    if not root.exists():
        return
    for view_dir in sorted(root.iterdir()):
        if not view_dir.is_dir():
            continue
        view_type = view_dir.name
        # axes.yml
        axes_path = view_dir / "axes.yml"
        if axes_path.exists():
            try:
                taxonomy = _parse_axes_file(axes_path, view_type, origin)
                out.taxonomies[view_type] = taxonomy   # user overlay wins because scanned after
            except CatalogError as exc:
                out.parse_errors.append(exc)
        # Exemplars — keyed by "<view-type>:<slug>" so the same slug can appear
        # under multiple view-types (e.g. gh.md exists under help-text/ AND
        # error-text/). Spec bindings reference the fully-qualified key.
        for md_path in sorted(view_dir.glob("*.md")):
            if md_path.name.lower() == "readme.md":
                continue
            try:
                ex = _parse_exemplar_file(md_path, origin)
                key = f"{view_type}:{ex.slug}"
                # Detect user-overlay shadowing: a user entry replacing a
                # plugin entry with the same key. Plugin pass runs first so
                # any pre-existing entry at this key is plugin-origin.
                if origin == "user" and key in out.exemplars:
                    prior = out.exemplars[key]
                    if prior.origin == "plugin":
                        out.shadowed.append((key, prior.path, str(md_path)))
                out.exemplars[key] = ex
            except CatalogError as exc:
                out.parse_errors.append(exc)


def load_catalog(force_reload: bool = False) -> Catalog:
    global _LOAD_CACHE
    if _LOAD_CACHE is not None and not force_reload:
        return _LOAD_CACHE
    cat = Catalog()
    _scan_root(_plugin_root() / "docs" / "exemplars", "plugin", cat)
    _scan_root(_user_overlay_root(), "user", cat)
    _LOAD_CACHE = cat
    return cat


def lookup(key: str) -> Exemplar | None:
    """Lookup an exemplar by `<view-type>:<slug>` key, or by bare slug if
    unambiguous (returns None when the bare slug matches more than one
    view-type — caller must qualify; see lookup_status() to distinguish
    not-found from ambiguous)."""
    cat = load_catalog()
    if ":" in key:
        return cat.exemplars.get(key)
    matches = [ex for k, ex in cat.exemplars.items() if k.endswith(f":{key}")]
    if len(matches) == 1:
        return matches[0]
    return None


def lookup_status(key: str) -> tuple[str, list[Exemplar]]:
    """Detailed lookup. Returns one of:
      ("found",       [exemplar])  — exact match (qualified or unambiguous bare)
      ("not-found",   [])
      ("ambiguous",   [match-1, match-2, ...])  — bare slug matches >1 entry
    Callers that need to differentiate ambiguity from missing-from-catalog
    use this instead of bare lookup().
    """
    cat = load_catalog()
    if ":" in key:
        ex = cat.exemplars.get(key)
        return ("found", [ex]) if ex is not None else ("not-found", [])
    matches = [ex for k, ex in cat.exemplars.items() if k.endswith(f":{key}")]
    if len(matches) == 1:
        return ("found", matches)
    if len(matches) == 0:
        return ("not-found", [])
    return ("ambiguous", matches)


def by_view_type(view_type: str) -> list[Exemplar]:
    return [ex for ex in load_catalog().exemplars.values() if view_type in ex.view_types]


def axes(view_type: str, taxonomy_version: int | None = None) -> AxisTaxonomy | None:
    tax = load_catalog().taxonomies.get(view_type)
    if tax is None:
        return None
    if taxonomy_version is not None and tax.taxonomy_version != taxonomy_version:
        return None
    return tax


def validate_catalog() -> list[str]:
    """Run structural checks on the loaded catalog and return error strings.

    Checks:
      - All parse_errors surface
      - Every exemplar's view-types include at least one with a defined axes.yml
      - Every exemplar's axes keys appear in its view's axis taxonomy
      - Every exemplar's axes values are in the taxonomy's allowed value-set
      - supersedes chains do not cycle
    """
    cat = load_catalog()
    errors: list[str] = [f"{e.path}: {e.reason}" for e in cat.parse_errors]
    # User-overlay shadowing — informational; surfaced so operators who
    # accidentally drop a stale overlay can spot it. Listed as warnings
    # (validate still returns non-zero so CI catches stale overlays).
    for key, plugin_path, user_path in cat.shadowed:
        errors.append(
            f"shadowed: user overlay {user_path} replaces plugin entry "
            f"{plugin_path} (key={key})"
        )

    for ex in cat.exemplars.values():
        for view_type in ex.view_types:
            tax = cat.taxonomies.get(view_type)
            if tax is None:
                errors.append(f"{ex.path}: view-type {view_type!r} has no axes.yml taxonomy")
                continue
            if ex.taxonomy_version != tax.taxonomy_version:
                errors.append(
                    f"{ex.path}: taxonomy-version {ex.taxonomy_version} != "
                    f"catalog taxonomy-version {tax.taxonomy_version} for view-type {view_type!r}"
                )
            for axis_name, axis_value in ex.axes.items():
                axis_def = tax.axes.get(axis_name)
                if axis_def is None:
                    errors.append(
                        f"{ex.path}: axis {axis_name!r} not in taxonomy for view-type {view_type!r}"
                    )
                    continue
                if axis_value not in axis_def.values:
                    errors.append(
                        f"{ex.path}: axis {axis_name!r}={axis_value!r} not in allowed values "
                        f"{axis_def.values} for view-type {view_type!r}"
                    )

    # supersedes cycle detection
    for slug, ex in cat.exemplars.items():
        seen = {slug}
        cur = ex.supersedes
        while cur:
            if cur in seen:
                errors.append(f"{ex.path}: supersedes cycle through {cur!r}")
                break
            seen.add(cur)
            nxt = cat.exemplars.get(cur)
            if nxt is None:
                # dangling reference is allowed (supersedes a not-yet-cataloged predecessor)
                break
            cur = nxt.supersedes

    return errors
