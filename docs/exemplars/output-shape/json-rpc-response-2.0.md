---
view-types: [output-shape]
conventions:
  - "Every response object must contain a `jsonrpc` member with the string value `\"2.0\"` exactly; no other version string is valid under this spec"
  - "The `id` member must be present and must equal the `id` of the request being responded to; when the request `id` was null or the request was a notification (no `id`), a response must not be sent"
  - "A response must contain either a `result` member or an `error` member, never both simultaneously; a response with neither member is non-conformant"
  - "The `result` member may be any JSON value including null; its structure is defined by the server method, not by the protocol"
  - "The `error` member, when present, must be an Error Object containing an integer `code` field, a string `message` field, and an optional `data` field of any type"
  - "Error codes in the range -32768 to -32000 are reserved for pre-defined protocol errors: -32700 (Parse error), -32600 (Invalid Request), -32601 (Method not found), -32602 (Invalid params), -32603 (Internal error); server-defined errors use codes outside this range"
  - "Batch responses: when a request array is sent, the response is an array of individual response objects in any order; the client matches responses to requests via the `id` field"
axes: {envelope: json-rpc-2.0, success-error-split: exclusive-union, schema-binding: none}
calibrated-for: [programmatic-consumer, library-consumer, api-consumer, sdk-author]
taxonomy-version: 1
source-url: https://www.jsonrpc.org/specification
last-reviewed: 2026-05-15
---

# json-rpc-response-2.0 output-shape conventions

JSON-RPC 2.0 defines a minimal response envelope: four possible members (`jsonrpc`, `id`, `result`, `error`), one of which (`result` or `error`) is exclusive. The exclusive-union property is the structurally load-bearing constraint. A client that inspects both members — treating a response as success if `result` is truthy even when `error` is also present — is implementing the protocol incorrectly, because a conformant server will never send both.

The `id` field is the correlation mechanism. When a call carries `id: 42`, the response carries `id: 42`. When a call is a notification (no `id` member), no response is sent at all — this is a deliberate protocol choice to enable fire-and-forget messaging without reserving response capacity. A client that expects a response to a notification will hang; a server that sends a response to a notification is non-conformant.

Error codes from the reserved range (-32768 to -32000) carry stable cross-implementation meaning and must not be repurposed by server implementations. The `data` field in an Error Object is unconstrained and is the canonical extension point: it may carry structured diagnostic information (stack traces, field-level validation failures) without altering the top-level protocol shape. Servers that embed extended error information in the `message` string instead of `data` are technically conformant but operationally harder to parse programmatically.
