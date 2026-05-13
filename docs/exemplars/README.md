# Spectre Metis Catalog

## What this is

The Metis Catalog is a curated library of exemplar tools whose conventions encode practical know-how for each receiver class. Spec authors bind exemplars in §§9-13 of their v1.0 specs (e.g. `help-text-style: exemplar:help-text:curl`); the evaluator checks adherence at Tier 3. The catalog does not extract metis — it **specifies which existing metis applies**. Each exemplar is a pointer to a tool's own proven conventions, not a paraphrase of them.

## Directory structure

```
docs/exemplars/
  help-text/        — CLI/tool help-text conventions (4 exemplars)
    axes.yml        — axis taxonomy for help-text design space
    curl.md
    gh.md
    git.md
    rustc.md
  error-text/       — error message conventions (4 exemplars)
    axes.yml
    gh.md
    git.md
    postgres.md
    rust-compiler.md
  log-format/       — log line conventions (3 exemplars)
    axes.yml
    nginx.md
    structlog-json.md
    systemd-journal.md
  api-shape/        — API design conventions (3 exemplars)
    axes.yml
    github-graphql.md
    kubernetes-api.md
    stripe-rest.md
  observability/    — metrics + status display conventions (3 exemplars)
    axes.yml
    htop.md
    prometheus.md
    tmux-status.md
```

5 `axes.yml` files + 17 exemplar markdown files total.

## Exemplar file format

Each `<slug>.md` is a YAML-frontmatter block followed by a prose body.

**Required frontmatter fields:**

| Field | Type | Description |
|---|---|---|
| `view-types` | list of strings | Which view-types this entry applies to |
| `conventions` | list of strings | Operationally specific, pass/fail rules |
| `axes` | mapping | Axis name to value, per the view-type's `axes.yml` |
| `taxonomy-version` | int | Must match the current `axes.yml` version |
| `source-url` | string | Canonical docs URL (the tool's own docs) |
| `last-reviewed` | string | Date of last human review (ISO 8601) |
| `supersedes` | string | Optional. Slug of the prior entry this replaces |

**Example:**

```yaml
---
view-types: [help-text]
conventions:
  - "Each option entry begins with the short form (`-X`) followed by the long form
     (`--request`) separated by a comma and a space, or long-form-only for options
     without a short alias"
  - "Options that accept a mandatory argument show the argument placeholder in angle
     brackets immediately after the flag (e.g., `--output <file>`)"
axes: {verbosity: balanced, structure: sectioned, example-density: separate-section}
taxonomy-version: 1
source-url: https://curl.se/docs/manual.html
last-reviewed: 2026-05-13
---

The body explains the conventions operationally: why the tool chose this design,
what tradeoffs it encodes, and what a reviewer should look for when applying them.
```

## Axis taxonomy format

Each view-type's `axes.yml` defines the allowed design-space coordinates for that view.

**Fields:**

| Field | Type | Description |
|---|---|---|
| `taxonomy-version` | int | Bumped whenever axes or value-sets change |
| `axes` | mapping | Axis name to `{values: [...], description: ...}` |

**Example:**

```yaml
taxonomy-version: 1
axes:
  verbosity:
    values: [terse, balanced, verbose]
    description: >
      How much text accompanies each help emission. Terse = one-line flag
      descriptions; balanced = paragraph per topic; verbose = full prose.
  structure:
    values: [flat, sectioned, subcommand-tree]
    description: >
      How help content is hierarchically organized. Flat = single page;
      sectioned = labeled blocks; subcommand-tree = recursive per-subcommand help.
```

## CLI

The `spectre exemplars` command exposes four subcommands:

| Subcommand | Purpose |
|---|---|
| `list [--view-type TYPE] [--json]` | List catalog entries from plugin + user overlays |
| `show <slug>` | Render full frontmatter and body for one exemplar |
| `axes <view-type>` | Show a view-type's axis taxonomy and allowed values |
| `validate` | Check all entries for structural conformance; exits non-zero on any violation |

**Examples:**

```sh
# List all help-text exemplars as JSON
spectre exemplars list --view-type help-text --json

# Inspect a specific exemplar
spectre exemplars show curl

# Inspect the observability axis taxonomy
spectre exemplars axes observability

# Validate the full catalog (run this in CI)
spectre exemplars validate
```

## User overlays

Operators add their own exemplars at `~/.spectre/exemplars/<view-type>/<slug>.md`. The user overlay directory is scanned after the plugin catalog; a user entry with the same `<view-type>:<slug>` key as a plugin entry **shadows** the plugin entry.

`spectre exemplars validate` surfaces every shadow event:

```
shadowed: user overlay ~/.spectre/exemplars/help-text/curl.md replaces plugin entry
          docs/exemplars/help-text/curl.md (key=help-text:curl)
```

Validate exits non-zero when shadows exist so operators can confirm or correct accidental overrides.

## Per-entry review gate (contributors)

Before merging a new or updated exemplar, each entry must pass all of the following:

**1. Conventions are operationally specific.**
Each item in `conventions:` must be phrased as a check a reviewer (human or LLM) can apply to a piece of output and return pass or fail. No subjective or non-testable claims.

- GOOD: `"Each option line begins with the long-form flag followed by short form in parentheses"`
- BAD: `"Easy to read"` — no test
- BAD: `"Terse"` — subjective; no pass/fail boundary

**2. Axes match the taxonomy.**
Every axis name and value declared in `axes:` must appear in the view-type's `axes.yml`. An exemplar cannot declare an axis the taxonomy does not know.

**3. `source-url` resolves to canonical docs.**
The URL must point to the tool's own documentation, not a third-party blog or mirror. Conventions must be traceable to passages in that source.

**4. `supersedes` chains do not cycle.**
If `supersedes` is set, follow the chain to verify it terminates. A cycle (A supersedes B, B supersedes A) is a validation error.

## Validation

`spectre exemplars validate` enforces the per-entry review gate mechanically:

- Surfaces all parse errors (missing required fields, malformed YAML subset)
- Checks every exemplar's `axes:` against the taxonomy (unknown axis names, out-of-range values)
- Checks `taxonomy-version` pin against the current `axes.yml` version
- Detects `supersedes` cycles
- Reports user-overlay shadowing events

Exit code is 0 only when no errors or shadows are detected. **CI should run this on every PR that touches `docs/exemplars/` or `~/.spectre/exemplars/`.**

## Extending the catalog

**Adding a convention to an existing exemplar:**
Edit the `conventions:` list in the relevant `<slug>.md`. Apply the per-entry review gate before merging. The `taxonomy-version` pin does not need to change unless axes change.

**Adding a new exemplar:**
Add `<slug>.md` under the appropriate view-type directory. The frontmatter must declare `axes:` values that exist in the view-type's current `axes.yml`. Pass the per-entry review gate before merging.

**Adding a new axis to an existing view-type:**
Add the axis under that view-type's `axes.yml` and bump `taxonomy-version`. Existing exemplars pinned to the old version continue evaluating against that pin until explicitly upgraded — no forced migration.

**Adding a new view-type:**
Create a new directory, ship an `axes.yml` with at least two axes, and seed at least one exemplar covering the meaningful design philosophies represented in that view-type's design space. New view-types also require walker and evaluator wiring updates — file an issue before writing files so the scope is agreed.
