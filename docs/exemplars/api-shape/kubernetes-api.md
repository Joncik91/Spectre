---
view-types: [api-shape]
conventions:
  - "Every resource object must have four top-level fields: `apiVersion` (e.g. `apps/v1`), `kind` (e.g. `Deployment`), `metadata.name` (string), and `spec` or `data` depending on resource type; absence of any of these is a parse error before admission"
  - "Namespaced resources are addressed at `/apis/<group>/<version>/namespaces/<namespace>/<plural-kind>/<name>`; cluster-scoped resources omit the `/namespaces/<namespace>` segment"
  - "API versioning is embedded in the URL path using the pattern `/api/v1/` (core group) or `/apis/<group>/<version>/` (extension groups); version changes produce a new path segment, not a header"
  - "Error responses carry an `application/json` body with `apiVersion: v1`, `kind: Status`, `status: Failure`, a human-readable `message`, a machine-readable `reason` string (e.g. `NotFound`, `AlreadyExists`, `Conflict`), and an integer `code` matching the HTTP status"
  - "Watch operations are initiated by adding `?watch=true` to a list URL; the response is a newline-delimited stream of JSON objects each with a `type` field (ADDED, MODIFIED, DELETED, ERROR) and an `object` field containing the full resource"
  - "Optimistic concurrency is enforced via `metadata.resourceVersion`; a PUT or PATCH that omits `resourceVersion` may be rejected or may silently stomp concurrent writes — conformant clients always echo it back"
  - "Server-side apply uses `PATCH` with `Content-Type: application/apply-patch+yaml` and requires a `fieldManager` query parameter; absence of `fieldManager` returns HTTP 400"
  - "List responses are JSON objects with `apiVersion`, `kind` ending in `List` (e.g. `PodList`), `metadata.resourceVersion`, and an `items` array; they are never bare JSON arrays"
  - "All timestamps in resource metadata (`creationTimestamp`, `deletionTimestamp`) are RFC 3339 UTC strings (e.g. `2026-05-13T12:00:00Z`); epoch integers are not accepted"
axes: {style: rest-resource, error-model: status-plus-body, versioning: url-path}
calibrated-for: [library-consumer, api-consumer, webhook-subscriber, sdk-author]
taxonomy-version: 1
source-url: https://kubernetes.io/docs/reference/using-api/api-concepts/
last-reviewed: 2026-05-13
---

# kubernetes-api api-shape conventions

The Kubernetes API server exposes a REST interface where every object is a typed, versioned resource identified by group, version, and kind (GVK). The URL structure is load-bearing: the API group and version appear directly in the path (`/apis/apps/v1/`) rather than in a header or query parameter. This means a client can determine the full GVK of any resource by parsing the URL alone, with no out-of-band versioning negotiation. Reviewers can apply a mechanical test to any request: does the path's group+version segment match the `apiVersion` field in the request body? Mismatches indicate a client bug or a misconfigured proxy.

Object identity and mutation semantics depend on fields that must be present in every resource: `apiVersion`, `kind`, `metadata.name`, and (for namespaced resources) `metadata.namespace`. The `metadata.resourceVersion` field is the concurrency token — it is set by the server on every write and must be echoed on subsequent updates. A PUT or PATCH that carries a stale `resourceVersion` returns HTTP 409 Conflict with a `Status` body whose `reason` is `Conflict`. This is the primary optimistic locking mechanism in the API; there are no ETags or separate lock endpoints.

Error responses are themselves typed Kubernetes objects: every non-2xx response body is a `Status` resource with `apiVersion: v1`, `kind: Status`, a `reason` enum, and a `code` integer. This means error parsing uses the same object model as success parsing — a conformant client can deserialize all responses through the same `TypeMeta` + `ObjectMeta` path and branch on `kind == "Status"`. The `reason` field is the machine-readable discriminant; the `message` field is human-readable and must not be parsed programmatically.
