---
view-types: [log-format]
conventions:
  - "Each record is a single line of free-form text terminated by a newline (`\\n`); no multiline records"
  - "Error log lines begin with the timestamp in the format `YYYY/MM/DD HH:MM:SS` (local time, not UTC)"
  - "Severity label appears immediately after the timestamp, enclosed in square brackets: `[debug]`, `[info]`, `[warn]`, `[error]`, `[crit]`, `[alert]`, `[emerg]`"
  - "Worker PID appears after the severity in the form `<pid>#<tid>:` (e.g., `1234#0:`)"
  - "Error log records include `*<connection-id>` when the record is associated with a client connection"
  - "The human-readable message follows the connection field, ending with `, client: <ip>` and `, server: <name>` fields when a virtual host context is available"
  - "Access log (combined format) timestamp is enclosed in brackets: `[DD/Mon/YYYY:HH:MM:SS +ZZZZ]`"
  - "The `error_log` directive `level` parameter controls the minimum severity emitted; levels are: debug, info, notice, warn, error, crit, alert, emerg"
axes: {structure: plaintext, identification: timestamp-level, verbosity-gradient: debug-warn-error}
taxonomy-version: 1
source-url: https://nginx.org/en/docs/ngx_core_module.html#error_log
last-reviewed: 2026-05-13
---

# nginx log-format conventions

Nginx writes two distinct log streams: the access log (one record per HTTP request) and the error log (operational and diagnostic events). Both streams are plaintext, with one record per line. The error log is the primary source of severity-graded operational information; the access log is structured by a configurable format string but carries no severity field.

Error log records are not machine-parseable by a single universal regex — the message portion is free-form prose that varies by event type. Reviewers should expect to grep or pipe through a pattern that extracts the leading timestamp and bracketed severity rather than attempting full-record parsing. The connection-id field (`*<n>`) is the only correlation handle available within a single nginx instance; there is no request-id or trace-id injected by default.

Verbosity is controlled at startup via the `error_log` directive's `level` parameter. Debug logging requires nginx to be compiled with `--with-debug`; enabling it at runtime on a production server requires a configuration reload, making the gradient effectively startup-gated rather than dynamic. Operators should treat debug as a compile-time and restart-time toggle rather than a live dial.
