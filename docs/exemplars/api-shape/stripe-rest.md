---
view-types: [api-shape]
conventions:
  - "Resource collections use plural nouns; individual resources are addressed at /<collection>/<id> (e.g. GET /v1/charges/ch_123, not GET /v1/charge/ch_123)"
  - "All requests must include an Authorization header of the form `Authorization: Bearer <key>`; API keys in query strings are rejected"
  - "API version is specified via the `Stripe-Version` request header (e.g. `Stripe-Version: 2024-06-20`); absence falls back to the account's pinned version, never a query parameter"
  - "Every error response has a top-level `error` object with a `type` field set to exactly one of: api_error, card_error, idempotency_error, invalid_request_error, rate_limit_error"
  - "Every error object includes a human-readable `message` string and, where applicable, a machine-readable `code` string (e.g. `card_declined`, `missing`) and a `param` string naming the offending parameter"
  - "List endpoints return a JSON object with a `data` array, a boolean `has_more`, and a string `url`; they never return a bare JSON array"
  - "Pagination is cursor-based: callers pass `starting_after=<id>` or `ending_before=<id>`; offset-based page/offset params are not supported"
  - "Idempotency is opt-in via `Idempotency-Key` request header; replayed responses set the `Idempotent-Replayed: true` response header"
  - "Successful responses use 200 for GET/POST/DELETE; 204 is not used — deletions return a `{id, object, deleted: true}` JSON body with 200"
  - "All monetary amounts are integers in the smallest currency unit (e.g. cents for USD); floating-point amounts are never accepted"
axes: {style: rest-resource, error-model: error-code-taxonomy, versioning: header}
calibrated-for: [library-consumer, api-consumer, webhook-subscriber, sdk-author]
taxonomy-version: 1
source-url: https://docs.stripe.com/api
last-reviewed: 2026-05-13
---

# stripe-rest api-shape conventions

Stripe's REST API is a textbook example of resource-oriented design hardened for payment-critical reliability. The URL hierarchy is shallow and noun-based: every entity type lives under `/v1/<plural-noun>`, and nested resources are either embedded or reached via a second-level collection path (e.g. `/v1/customers/{id}/sources`). POST is used for both creation and update — there are no PATCH or PUT endpoints — which means the body is always a partial representation. Reviewers can mechanically verify this: if a path contains a verb, it's non-conformant; if an update uses PUT, it's non-conformant.

Error handling is the most distinctive aspect of the API shape. Every non-2xx response carries a top-level `error` object with a stable `type` enum, a human-readable `message`, and often a machine-readable `code` and `param`. The `type` field has exactly five values, each corresponding to a distinct failure class: `card_error` for declined cards, `invalid_request_error` for bad inputs, `api_error` for server faults, `idempotency_error` for replay conflicts, and `rate_limit_error` for throttling. A reviewer checking any error response can pass/fail the `type` presence and value-set in one step, with no ambiguity.

Versioning is header-driven, not URL-driven. The `/v1/` prefix in the path is a static namespace segment — it does not change with API evolution. Actual version pinning happens via the `Stripe-Version` date-string header (e.g. `2024-06-20`). New accounts are pinned to the latest version at signup; upgrades are explicit and per-account. This means two callers hitting the same URL path may receive structurally different responses depending on their pinned version, so any conformance check that ignores the version header is incomplete.
