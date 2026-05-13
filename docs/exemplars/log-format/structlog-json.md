---
view-types: [log-format]
conventions:
  - "Each record is exactly one line of JSON terminated by `\\n`; no multiline JSON, no pretty-printing"
  - "The `timestamp` key is present in every record with an ISO 8601 UTC value in the form `YYYY-MM-DDTHH:MM:SS.ffffffZ`"
  - "The `level` key is present in every record with a lowercase string value from the Python logging set: `debug`, `info`, `warning`, `error`, `critical`"
  - "The `logger` key identifies the source component as a dot-separated Python module path (e.g., `myapp.api.auth`)"
  - "The `event` key carries the human-readable message string; it is never omitted and never `null`"
  - "All context variables bound via `structlog.contextvars.bind_contextvars()` appear as top-level keys alongside `timestamp`, `level`, `logger`, and `event`"
  - "The `exc_info` key, when present, contains the formatted exception traceback as a single string with embedded `\\n` characters — it does not span multiple JSON records"
  - "Log level is changeable per-logger at runtime without process restart via `structlog`'s stdlib `logging` integration and `logging.setLevel()` calls"
axes: {structure: json-lines, identification: timestamp-level-source, verbosity-gradient: dynamic-runtime}
taxonomy-version: 1
source-url: https://www.structlog.org/en/stable/
last-reviewed: 2026-05-13
---

# structlog-json log-format conventions

structlog with the `JSONRenderer` processor emits one JSON object per line, making every record directly ingestible by log aggregators such as Loki, Elasticsearch, or Datadog without a parsing step. The canonical processor chain — `TimeStamper(fmt="iso", utc=True)`, `add_log_level`, `JSONRenderer()` — guarantees the `timestamp`, `level`, and `event` keys on every record. The `logger` key is added when structlog is configured with `stdlib` integration (`structlog.stdlib.add_logger_name`).

Context propagation is the primary differentiator from plaintext or logfmt loggers. Operators bind request-scoped fields (e.g., `request_id`, `user_id`, `trace_id`) at request ingress using `structlog.contextvars.bind_contextvars()` and they appear automatically on every record emitted during that request's lifetime. Reviewers can assert correlation completeness by confirming that every record within a single HTTP request shares identical bound-context key values.

Verbosity is dynamic because structlog delegates level filtering to the Python `logging` module. Any component's minimum level can be changed at runtime by calling `logging.getLogger("myapp.component").setLevel(logging.DEBUG)` via a management endpoint, a signal handler, or a control-plane API — no restart required. This makes the gradient genuinely runtime-adjustable per logger path, not just a startup configuration.
