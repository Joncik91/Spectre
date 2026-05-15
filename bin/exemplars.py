"""bin/exemplars.py — CLI for the v1.0 metis catalog.

Subcommands:
  list [--view-type TYPE] [--json]   list catalog entries (plugin + user)
  show <slug>                        render full body + frontmatter for one exemplar
  axes <view-type>                   show that view's axis taxonomy
  validate                           check all entries for structural conformance

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# v1.1.1 Fix G: see bin/walker.py for the rationale on this sys.path shim.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bin import _catalog  # noqa: E402


def _cmd_list(args: argparse.Namespace) -> int:
    cat = _catalog.load_catalog()
    if args.view_type:
        items = [(k, ex) for k, ex in cat.exemplars.items() if args.view_type in ex.view_types]
    else:
        items = list(cat.exemplars.items())
    items.sort(key=lambda kv: kv[0])
    if args.json:
        payload = [
            {
                "key": k,
                "slug": ex.slug,
                "view-types": ex.view_types,
                "conventions": ex.conventions,
                "axes": ex.axes,
                "taxonomy-version": ex.taxonomy_version,
                "source-url": ex.source_url,
                "last-reviewed": ex.last_reviewed,
                "supersedes": ex.supersedes,
                "origin": ex.origin,
                "path": ex.path,
            }
            for k, ex in items
        ]
        print(json.dumps(payload, indent=2))
        return 0
    if not items:
        print("EXEMPLARS: 0", file=sys.stderr)
        return 0
    print(f"EXEMPLARS: {len(items)}")
    for k, ex in items:
        axes_str = ", ".join(f"{ak}={av}" for ak, av in ex.axes.items())
        print(f"  [{ex.origin}] {k:36s} axes=({axes_str})")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    ex = _catalog.lookup(args.slug)
    if ex is None:
        print(f"ERROR: exemplar {args.slug!r} not found", file=sys.stderr)
        return 2
    print(f"slug: {ex.slug}")
    print(f"path: {ex.path}")
    print(f"origin: {ex.origin}")
    print(f"view-types: {', '.join(ex.view_types)}")
    print(f"taxonomy-version: {ex.taxonomy_version}")
    print(f"source-url: {ex.source_url}")
    print(f"last-reviewed: {ex.last_reviewed}")
    if ex.supersedes:
        print(f"supersedes: {ex.supersedes}")
    print("axes:")
    for k, v in ex.axes.items():
        print(f"  {k}: {v}")
    print("conventions:")
    for c in ex.conventions:
        print(f"  - {c}")
    print()
    print(ex.body)
    return 0


def _cmd_axes(args: argparse.Namespace) -> int:
    tax = _catalog.axes(args.view_type)
    if tax is None:
        print(f"ERROR: no axis taxonomy for view-type {args.view_type!r}", file=sys.stderr)
        return 2
    print(f"view-type: {tax.view_type}")
    print(f"taxonomy-version: {tax.taxonomy_version}")
    print(f"origin: {tax.origin}")
    print("axes:")
    for name, defn in tax.axes.items():
        print(f"  {name}: {', '.join(defn.values)}")
        if defn.description:
            print(f"    description: {defn.description}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    errors = _catalog.validate_catalog()
    if not errors:
        cat = _catalog.load_catalog()
        print(f"OK exemplars.validate count={len(cat.exemplars)} taxonomies={len(cat.taxonomies)}")
        return 0
    print(f"FAIL exemplars.validate errors={len(errors)}", file=sys.stderr)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bin.exemplars")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list catalog entries")
    p_list.add_argument("--view-type", help="filter to one view-type")
    p_list.add_argument("--json", action="store_true", help="emit JSON")
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="show one exemplar")
    p_show.add_argument("slug")
    p_show.set_defaults(func=_cmd_show)

    p_axes = sub.add_parser("axes", help="show a view-type's axis taxonomy")
    p_axes.add_argument("view_type")
    p_axes.set_defaults(func=_cmd_axes)

    p_validate = sub.add_parser("validate", help="check catalog structural conformance")
    p_validate.set_defaults(func=_cmd_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
