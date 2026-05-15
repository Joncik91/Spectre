---
view-types: [input-shape]
conventions:
  - "A Request Body Object in OpenAPI 3.1 has a required `content` field whose keys are media type strings (e.g. `application/json`); the absence of `content` is a schema violation"
  - "Each media type entry contains a `schema` field whose value is a Schema Object or Reference Object conformant to JSON Schema draft 2020-12 (OpenAPI 3.1 aligns with JSON Schema 2020-12, not draft-07)"
  - "The `required` boolean field on the Request Body Object defaults to `false` when absent; an omitted body on a required=true operation is a 400-level error"
  - "Sending `Content-Type: application/json` binds the request body to the schema under that media type key; other content types (e.g. `application/x-www-form-urlencoded`) bind to their respective schema entries"
  - "A `$ref` in a Schema Object is resolved against the document's `#/components/schemas` namespace or an external URI; inline schema and referenced schema are semantically equivalent after resolution"
  - "The `nullable` keyword is not valid in OpenAPI 3.1 (it was a 3.0 extension); use `type: [string, null]` or `oneOf` with a null type entry to express an optional-valued field"
  - "Multiple content types on one operation are valid; the server selects the binding by matching the `Content-Type` header to the `content` map keys using media-type pattern matching (RFC 7231 §3.1.1.5)"
axes: {arg-style: json-body, optionality: schema-validated, separator-support: content-type-boundary}
calibrated-for: [programmatic-trusted, programmatic-untrusted, api-consumer, library-consumer]
taxonomy-version: 1
source-url: https://spec.openapis.org/oas/v3.1.0#request-body-object
last-reviewed: 2026-05-15
---

# openapi-request-body input-shape conventions

OpenAPI 3.1 describes the request body via the Request Body Object, which differs from path and query parameters in one important structural respect: the body's schema is not a single schema but a map from content type to schema. A single operation can declare `application/json` and `application/x-www-form-urlencoded` bodies with distinct schemas — the consumer's `Content-Type` header determines which schema applies. A reviewer checking an operation must match the schema to the incoming content type before validating the payload; applying the JSON schema to a form-encoded body (or vice versa) produces meaningless results.

The alignment with JSON Schema 2020-12 (replacing the 3.0/draft-07 alignment) has one frequently-mishandled consequence: the `nullable` keyword is invalid in 3.1 and must not appear in specs targeting that version. The canonical replacement is a type array (`type: [string, null]`) or a `oneOf` with a null branch. Tools that silently accept `nullable: true` in 3.1 documents are applying 3.0 parsing rules.

The `required` field on the Request Body Object governs whether the body itself may be absent — it does not govern individual fields inside the schema (field-level required is expressed inside the Schema Object's `required` array). This distinction matters: `required: false` on the body means the entire body may be omitted; it says nothing about which fields inside a provided body are mandatory.
