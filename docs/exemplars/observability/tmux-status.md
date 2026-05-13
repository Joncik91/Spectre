---
view-types: [observability]
conventions:
  - "Status line content is defined via `status-left` and `status-right` option strings; each must be non-empty and use at least one `#(command)` or `#{format}` interpolation so it shows live data rather than a static label"
  - "Refresh interval is configured via the `status-interval` option (integer seconds); the value must be 5 or less for any status component displaying a time-varying measurement (load average, clock, running job count)"
  - "Each status segment is separated from adjacent segments by at least one visible delimiter character (e.g. `|`, space-padded `·`, or bracket pair `[ ]`); adjacent segments must not bleed into each other without a delimiter"
  - "Color directives use the `#[fg=colour,bg=colour]` syntax; raw ANSI escape sequences must not appear in `status-left` or `status-right` strings"
  - "Gauge values (e.g. CPU load, battery percentage) are rendered as a bare number followed by a fixed unit token (e.g. `1.42`, `87%`); no variable-length decorations that would shift adjacent segment positions"
  - "Counter values (e.g. window count, pane count) are rendered as an integer with no decimal point; non-integer rendering of a counter is a violation"
  - "The current window indicator in `window-status-current-format` must be visually distinct from inactive windows via at least one of: bold attribute, differing foreground color, or enclosing brackets — not via text content alone"
  - "Session name, window index, and window name are available via `#{session_name}`, `#{window_index}`, and `#{window_name}` respectively; hardcoded substitutes for these tokens are a violation"
axes: {metric-model: counters-plus-gauges, cardinality: low-fixed-labels, collection: local-direct-read}
taxonomy-version: 2
source-url: https://github.com/tmux/tmux/wiki/Formats
last-reviewed: 2026-05-13
---

# tmux-status observability conventions

The tmux status line is a real-time display updated on a server-side timer, making it the primary human-facing observability surface for terminal multiplexer sessions. Its design space is constrained by two hard limits: the terminal width is fixed and shared with window tab labels, and the refresh granularity is an integer number of seconds. Within those limits, the status line follows a counters-plus-gauges model — integer window and pane counts pair with floating-point load-average or percentage readings — and the entire label set is fixed at session creation time (session name, hostname, a handful of shell-produced values). There are no per-request or per-user dimensions; cardinality is permanently low.

The format string system uses `#{variable}` for tmux's built-in state variables and `#(shell-command)` for external measurements. A status component is only considered live data if it uses at least one such interpolation; a literal string that never changes provides no observability value. Color and attribute changes use the `#[attr=value]` directive and must be self-contained within their segment so that a later segment can reset the terminal state cleanly. Raw ANSI escape sequences embedded in format strings are explicitly prohibited because they bypass tmux's own terminal capability negotiation.

Segment layout conventions treat delimiter characters as mandatory boundaries rather than optional decoration. Without delimiters, adjacent segments with adjacent colors or values visually merge, making it impossible to distinguish where one datum ends and the next begins. The refresh interval constraint — five seconds or less for live measurements — is the status-line equivalent of a dashboard scrape interval: it sets the maximum staleness a human observer must tolerate. A status component that reads a gauge (CPU load, disk usage) but refreshes every 60 seconds presents a misleadingly stale number as if it were current.
