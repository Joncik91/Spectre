---
view-types: [help-text]
conventions:
  - "Help text emitted to stderr when invoked with `--help`; exit code is 0"
  - "Top-level usage line reads `rustc [OPTIONS] INPUT` with no subcommand layer; all options appear at the same level"
  - "Each option line begins with a four-space indent, then the long form (`--flag`) without a short-form alias (rustc has very few short aliases); the description follows on the same line after two or more spaces"
  - "Options that accept a value show the value name in angle brackets immediately after the flag name with no space (e.g., `--edition <EDITION>`), using UPPER_SNAKE_CASE for the placeholder"
  - "Unstable or nightly-only flags are grouped in a separate `Available on nightly-only:` block or annotated with `(unstable)` inline; they do not appear interleaved with stable flags in the main section"
  - "Inline examples for a flag appear as a continuation line under the flag description, indented four additional spaces, prefixed with `Example:` or formatted as a code fragment (e.g., `rustc --edition 2021 src/main.rs`)"
  - "The `--explain <ERROR_CODE>` flag appears in the OPTIONS section and its description references the error index; no URL is required but the mechanism for extended help is described inline"
  - "Lints are not listed in `--help` output; the flag `--warn`, `--deny`, `--allow`, `--forbid` appear with a generic `<LINT>` placeholder and a reference directing users to `rustc -W help` for the full lint list"
axes: {verbosity: verbose, structure: sectioned, example-density: inline}
calibrated-for: [cli-power-user, cli-novice]
taxonomy-version: 1
source-url: https://doc.rust-lang.org/rustc/command-line-arguments.html
last-reviewed: 2026-05-13
---

# rustc help-text conventions

rustc is a single-binary compiler with no subcommands. Its help text is a single sectioned page covering all flags: general options, input/output control, codegen options (`-C`), debugging (`-Z`, nightly only), and lint control. The sectioned layout provides visual grouping without requiring the user to discover nested help pages. Because rustc's audience is developers who have already chosen Rust and need to configure a build, the help text assumes familiarity with compiler concepts — it does not explain what linking or optimization means, only which flags control them.

Verbosity is high relative to the number of flags. Where curl gives a single-line description per flag, rustc often gives two to three lines: a description, an inline example using real file names and flag combinations, and occasionally a parenthetical noting the default value or the unit of a numeric argument. The inline example format is consistent: the example appears as a second line under the description, four additional spaces of indent from the flag, formatted as a bare shell snippet. This inline density reflects that many rustc flags have non-obvious semantics (e.g., `-C opt-level` accepts 0, 1, 2, 3, `s`, `z`) where a snippet is more informative than prose alone.

Unstable (`-Z`) flags are separated from stable flags and annotated clearly to signal that nightly toolchain is required. Lint flags (`--warn`, `--allow`, `--deny`, `--forbid`) appear in the main option list with a generic `<LINT>` placeholder and a pointer to `rustc -W help` for the full lint catalog. This indirection keeps the main help text tractable while preserving discoverability — a reviewer can verify this convention by checking that no individual lint names appear in the default `--help` output.
