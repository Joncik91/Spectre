---
view-types: [observability]
conventions:
  - "Metric names use snake_case throughout (e.g. `http_requests_total`, not `httpRequestsTotal` or `http-requests-total`)"
  - "Counter metric names end with the `_total` suffix; names without that suffix must not be of type counter"
  - "Histogram metrics expose exactly three companion series: `<name>_bucket`, `<name>_sum`, and `<name>_count`; absence of any one is a violation"
  - "Each metric is preceded by a `# HELP <name> <one-line description>` comment line and a `# TYPE <name> <type>` comment line, in that order, with no lines between them and no blank lines before the samples"
  - "The `# TYPE` comment uses exactly one of the four Prometheus types: `counter`, `gauge`, `histogram`, or `summary`; no other values are valid"
  - "Label names use snake_case; label values are treated as opaque strings but must not be empty unless the metric definition explicitly permits it"
  - "Label sets for a given metric are bounded to an enumerable domain (e.g. `status_code` limited to HTTP status classes, `method` limited to HTTP verbs); unbounded dimensions such as user-id or request-id must not appear as metric labels"
  - "The scrape endpoint is exposed at `/metrics` on a dedicated port (default 9090 for Prometheus itself; exporters conventionally use the port registered in the Prometheus default port allocations list)"
  - "Timestamps are omitted from exposition output unless the metric source is a batch job; real-time scraped metrics must not include per-sample timestamps"
axes: {metric-model: prometheus-four-types, cardinality: bounded-labels, collection: pull-scrape}
taxonomy-version: 1
source-url: https://prometheus.io/docs/practices/naming/
last-reviewed: 2026-05-13
---

# prometheus observability conventions

Prometheus metrics follow a strict naming and typing contract that enables automated dashboards and alerting rules to operate without per-metric configuration. Every metric name is a flat snake_case string in the global namespace; there are no namespaced paths or dot-separated segments. Type suffix conventions carry semantic meaning: `_total` marks a monotonically increasing counter, `_seconds` or `_bytes` marks the base unit, and histograms require exactly three derived series (`_bucket`, `_sum`, `_count`). A reviewer can validate any exposition output mechanically by checking suffix membership against the declared `# TYPE` and confirming the three histogram companions are present as a set.

Cardinality is a first-class constraint rather than an afterthought. Labels that enumerate a bounded domain — HTTP status classes, RPC method names, deployment region — are acceptable; labels that grow with user activity or request identity are not. The practical test: if the number of distinct label combinations can grow unboundedly as production traffic increases, the label is high-cardinality and belongs in a trace, not a metric. Exporters that violate this rule cause memory pressure in the Prometheus server proportional to the cardinality explosion.

The pull-scrape collection model means the Prometheus server initiates all data collection by GET-ing each target's `/metrics` endpoint on a configurable interval (default 15 seconds). Timestamps in the exposition text are therefore redundant for live processes and must be omitted — Prometheus records the scrape time as the sample timestamp. Batch jobs that terminate between scrapes are the sole exception; they push to a Pushgateway, which holds the metrics until the next scrape. This architecture inverts the classic push model: availability of the target, not the target's own schedule, gates data collection.
