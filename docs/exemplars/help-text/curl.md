---
view-types: [help-text]
conventions:
  - "Top-level usage line reads exactly `curl [options...] <url>` (or multi-URL variant); no subcommands appear in this line"
  - "Help text emitted to stdout when invoked with `--help`; exit code is 0"
  - "Each option entry begins with the short form (`-X`) followed by the long form (`--request`) separated by a comma and a space, or long-form-only for options without a short alias"
  - "Option description begins on the same line as the flag pair, with at least one space or tab separating the flag column from the description column; the flag column is left-aligned and padded to a consistent width throughout the OPTIONS section"
  - "Related options are grouped into named sections (e.g., `Authentication`, `TLS`, `Proxy`) using a header line in all-caps or title-case followed by a blank line before the first option in the section"
  - "Every section header appears on its own line with no leading whitespace and is separated from the preceding option block by at least one blank line"
  - "Options that accept a mandatory argument show the argument placeholder in angle brackets immediately after the flag (e.g., `--output <file>`)"
  - "The EXAMPLES section appears after all OPTIONS sections; each example is a bare `curl` invocation on its own line with no expected-output annotation below it"
  - "The manual URL `https://curl.se/docs/manpage.html` or equivalent reference line appears at or near the end of the help output"
axes: {verbosity: balanced, structure: sectioned, example-density: separate-section}
taxonomy-version: 1
source-url: https://curl.se/docs/manual.html
last-reviewed: 2026-05-13
---

# curl help-text conventions

curl's help text follows a sectioned, flag-table design inherited from its Unix roots. The top-level usage line is a single non-hierarchical template (`curl [options...] <url>`) — there are no subcommands, so the entire option surface is flat. Options are listed in alphabetical order within named topic sections (Authentication, TLS, Output, Proxy, etc.) rather than a single undifferentiated wall. Each section header is visually distinct: all-caps or title-case, zero indentation, preceded and followed by a blank line. This gives the reader a scannable map without requiring them to read every flag to find what they need.

Flag formatting is two-column: short form then long form on the left (e.g., `-u, --user`), description text on the right starting at a fixed column offset. When a flag accepts a mandatory argument, the placeholder appears in angle brackets immediately after the long form (`--output <file>`). Options that take no argument have nothing appended. This rule is strict enough that a reviewer can pass/fail any single option line mechanically: does the flag column appear first, is the argument placeholder present iff the flag takes one, and does the description start at a consistent column?

The EXAMPLES section is physically separate — it appears after all option sections, never interleaved. Each example is a bare `curl` invocation, one per line, with no inline annotation for expected output. The philosophy is breadth over depth: show many realistic command shapes so the reader can find their use case by pattern-match, rather than explaining any single example in detail. This tradeoff means the examples are less self-contained than a runnable-block style, but the help text stays compact enough to page through in a terminal.
