---
view-types: [api-shape]
conventions:
  - "All GraphQL operations (queries, mutations, subscriptions) are POSTed to a single endpoint: `https://api.github.com/graphql`; GET requests to this endpoint are not supported"
  - "Request body is a JSON object with a required `query` string field containing the GraphQL document, and an optional `variables` object; no multipart encoding"
  - "Every response is a JSON object containing a `data` key (null or object), an `errors` key (array or absent), or both; a response with neither key is non-conformant"
  - "Each object in the `errors` array has a `message` string and a `locations` array of `{line, column}` objects pointing into the query document"
  - "Successful responses that partially fail (field-level errors) return HTTP 200 with both `data` and `errors` present; HTTP 4xx/5xx indicates a transport or auth failure, not a GraphQL error"
  - "Authentication is via `Authorization: Bearer <token>` header; unauthenticated requests to the v4 endpoint return HTTP 401 with an error body, not a GraphQL `errors` array"
  - "Node IDs are opaque base64-encoded global identifiers; callers must not construct or decode them — they are only valid as inputs to `node(id:)` queries or mutation fields that accept IDs"
  - "Pagination uses cursor-based connections: list fields expose `edges[].cursor`, `pageInfo.hasNextPage`, `pageInfo.hasPreviousPage`, `pageInfo.startCursor`, and `pageInfo.endCursor`; offset pagination is not available"
  - "Rate limiting is communicated via a `rateLimit` query field (`limit`, `cost`, `remaining`, `resetAt`) and `X-RateLimit-*` response headers; callers must check both to avoid silent quota exhaustion"
axes: {style: graphql, error-model: status-plus-body, versioning: breaking-only-on-major}
calibrated-for: [library-consumer, api-consumer, sdk-author]
taxonomy-version: 1
source-url: https://docs.github.com/en/graphql
last-reviewed: 2026-05-13
---

# github-graphql api-shape conventions

GitHub's GraphQL API (v4) consolidates the entire surface into a single POST endpoint at `https://api.github.com/graphql`. Unlike REST APIs where the URL encodes the resource, here the resource and operation are fully described by the GraphQL document in the request body. A reviewer checking any inbound request can apply a single structural rule: is it a POST to the canonical endpoint with a `Content-Type: application/json` body containing a `query` string? If not, it's non-conformant. GitHub does not support `GET`-based GraphQL or persisted query hashes in the v4 API.

The error model is GraphQL-native, not HTTP-native. A field resolver failure returns HTTP 200 with a response body that contains both a `data` object (with null in place of the failed field) and an `errors` array describing what failed and where. HTTP 4xx only surfaces for transport-level problems: missing auth (401), malformed JSON (400), or rate limit hard stops (403). This bifurcation is operationally significant: a monitoring check that only watches HTTP status codes will miss all partial failures. A compliant client must inspect the `errors` key on every 200 response.

Versioning follows a breaking-only-on-major model. GitHub increments the API major version (v3 → v4) only on breaking changes, and the GraphQL schema evolves additively within v4 — new fields and types are added without a version bump, deprecated fields carry `@deprecated` annotations with a reason string, and removal is preceded by a documented deprecation window. This means a caller cannot detect schema additions by checking a version header; they must introspect the schema or track GitHub's changelog. The practical consequence for conformance checking is that any field present in a query response is additive and safe to ignore; absence of an expected field should trigger a schema-drift alert, not a version mismatch.
