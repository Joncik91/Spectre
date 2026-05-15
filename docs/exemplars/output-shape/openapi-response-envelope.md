---
view-types: [output-shape]
conventions:
  - "A Response Object in OpenAPI 3.1 requires a `description` field (a string); `content` and `headers` are optional"
  - "HTTP status codes in the Responses Object map keys may be specific (`\"200\"`, `\"404\"`) or wildcard (`\"2XX\"`, `\"4XX\"`, `\"5XX\"`); a specific code takes precedence over a wildcard for the same status"
  - "The `content` field maps media type strings to Media Type Objects; the Media Type Object's `schema` field is a JSON Schema 2020-12 (or Reference Object) describing the response body for that content type"
  - "The `Content-Type` response header value determines which Media Type Object schema applies to the body; the server selects the content type using the `Accept` request header and the operation's `content` map"
  - "The `default` key in the Responses Object covers all HTTP status codes not explicitly listed; it is used for error envelopes that apply across many status codes (e.g. a uniform error body for all 4XX and 5XX responses)"
  - "Headers declared in the Response Object's `headers` field are in addition to `Content-Type` and `Content-Length` which are described via the `content` map, not via `headers`"
  - "Combining schemas across status codes via `$ref` is standard practice; a shared error envelope schema (e.g. `#/components/schemas/ErrorBody`) may appear in multiple Response Objects via Reference Object"
axes: {envelope: http-status-body, success-error-split: status-plus-body, schema-binding: openapi-3.1}
calibrated-for: [programmatic-consumer, api-consumer, library-consumer, sdk-author]
taxonomy-version: 1
source-url: https://spec.openapis.org/oas/v3.1.0#response-object
last-reviewed: 2026-05-15
---

# openapi-response-envelope output-shape conventions

The OpenAPI 3.1 Response Object describes what a server sends back for a given HTTP status code. The structure is declaration-first: an operation's `responses` field is a map from status code string to Response Object, and each Response Object contains a `content` map from media type to schema. The status code is the first discriminator (is this a 200 or a 404?); the `Content-Type` header is the second (which schema governs this 200's body?). Both discriminators must be applied before schema validation is meaningful.

Wildcard keys (`"2XX"`, `"4XX"`) allow one Response Object to cover a range of codes — useful when the error envelope is uniform across all client errors. The precedence rule (specific code beats wildcard) means a server can declare a generic `"4XX"` error envelope and also override it with a specific schema for `"422"` validation failures without ambiguity.

The `default` key is distinct from wildcards: it is the fallback for any status code not named in the map, including codes outside the standard ranges. OpenAPI uses it idiomatically for error schemas that apply to all unexpected outcomes. A client consuming an undocumented status code can find a schema for the body via `default` if the API author declared one; without `default`, the client must treat the body as opaque.
