---
view-types: [help-text]
conventions:
  - "Help text emitted to stdout when invoked with `--help` or `help <subcommand>`; exit code is 0 in both cases"
  - "Top-level help lists available subcommand groups (e.g., `repo`, `pr`, `issue`) each on its own line, left-aligned, with a one-line description starting at column 17 (padding with spaces to align)"
  - "Each subcommand's own help page opens with a one-line summary sentence on the first line after `Usage:`, with no trailing period"
  - "The `Usage:` section shows the exact invocation template including required and optional argument placeholders using angle brackets for required (`<number>`) and square brackets for optional (`[flags]`)"
  - "Every leaf subcommand help page includes a `EXAMPLES` section containing at least one fenced or indented runnable command; each example command is followed by a prose line or comment describing what it does"
  - "Flag lines in the `FLAGS` section list the long form first (`--flag`), then the short form (`-f`) if one exists, separated by a comma; the description starts at a consistent column offset of at least 18 characters from the flag"
  - "Flags that accept a value show the value type immediately after the flag name with no space and preceded by a space+`<type>` pattern (e.g., `--limit <int>`)"
  - "The `LEARN MORE` or `See also` block at the end of every help page contains at least one URL pointing to the official gh manual or GitHub documentation"
  - "Subcommand groups that have aliases list them explicitly under an `ALIASES` label in the help output"
axes: {verbosity: verbose, structure: subcommand-tree, example-density: runnable-blocks}
calibrated-for: [cli-power-user]
taxonomy-version: 1
source-url: https://cli.github.com/manual/
last-reviewed: 2026-05-13
---

# gh help-text conventions

gh (GitHub CLI) uses a strict subcommand-tree structure: every noun (`repo`, `pr`, `issue`, `release`, etc.) is a top-level group, and actions (`create`, `list`, `view`, `merge`) are sub-subcommands beneath each group. Running `gh --help` shows only the group layer; running `gh pr --help` shows only the pr subcommands; running `gh pr create --help` shows the full flag set and examples for that leaf. This recursive delegation means help text at each level is narrow and purposeful — no single page tries to document more than one level of the hierarchy.

Verbosity is deliberately high at the leaf level. Each leaf help page carries a usage template, a full flag table, and an EXAMPLES section with runnable commands. Examples are not bare invocations: each is followed by a prose description or inline comment explaining the scenario (e.g., "# create a draft PR targeting the main branch"). This makes the examples self-contained enough for copy-paste use without opening a browser. The tradeoff is that `gh pr create --help` output is long — typically 40-80 terminal lines — but the subcommand-tree structure means the user navigated to it intentionally and expects depth.

Flag formatting follows a long-form-first convention: `--web, -w` rather than `-w, --web`. Value-type placeholders appear in angle brackets after a space (`--limit <int>`, `--assignee <login>`). The `LEARN MORE` footer at the bottom of every leaf page links to the canonical online manual, providing an escape hatch to full documentation when the in-terminal text is insufficient. `gh` treats its help text as a first-class product surface — updates to commands ship with updated help text in the same PR, and the manual site is generated from the same source.
