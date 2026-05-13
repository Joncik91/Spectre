---
view-types: [error-text]
conventions:
  - "Every error is assigned a five-character SQLSTATE code matching the pattern `[0-9A-Z]{5}` (e.g. `42P01`, `23505`) per SQL standard section 22.2"
  - "Error output in psql and server logs uses labeled fields: `ERROR:`, `DETAIL:`, `HINT:`, `CONTEXT:`, and `LOCATION:` — each on its own line, only present when populated"
  - "The `ERROR:` line contains a terse one-sentence description of the condition using past tense or noun phrase (e.g. `ERROR:  relation \"foo\" does not exist`)"
  - "The `DETAIL:` line supplies additional factual context such as the conflicting key value (e.g. `DETAIL:  Key (email)=(a@b.com) already exists.`)"
  - "The `HINT:` line, when present, contains a concrete actionable suggestion (e.g. `HINT:  No function matches the given name and argument types. You might need to add explicit type casts.`)"
  - "Server-side messages include the SQLSTATE code in structured log output (log_line_prefix or JSON logging) but not in the client-facing psql output by default — `\set VERBOSITY verbose` adds the code to client output"
  - "Error severity is one of: `DEBUG`, `INFO`, `NOTICE`, `WARNING`, `ERROR`, `FATAL`, `PANIC` — exactly these tokens, uppercase, no variants"
  - "Object names in error messages are always double-quoted when they are case-sensitive or contain special characters (e.g. `relation \"MyTable\"` not `relation MyTable`)"
axes: {tone: terse, structure: what-why-how, link-to-docs: error-code-only}
taxonomy-version: 1
source-url: https://www.postgresql.org/docs/current/errcodes-appendix.html
last-reviewed: 2026-05-13
---

# postgres error-text conventions

PostgreSQL error output is structured as a set of labeled fields rather than a single free-form message. The mandatory `ERROR:` line carries a terse diagnosis. Optional subordinate fields — `DETAIL:`, `HINT:`, `CONTEXT:` — appear below it, each providing progressively more operational context without duplicating information. A client that only needs to know whether the operation failed reads the `ERROR:` line; a client building a remediation UI can parse `HINT:` without re-implementing its own diagnostic logic.

The primary reference key is the five-character SQLSTATE code defined by the SQL standard. Every PostgreSQL error condition maps to exactly one code, and the code appears in server logs and in the wire protocol's `ErrorResponse` message. Client libraries expose it as a typed field (e.g. `sqlstate` in libpq, `pgcode` in Go's `pgx`, `code` in node-postgres), enabling application code to branch on structured error classes rather than string-matching. The `23505` unique-violation code is the canonical example: an application can catch exactly that class, surface a user-facing "already registered" message, and let all other codes propagate.

Severity levels are a fixed uppercase enumeration. `ERROR` terminates the current transaction. `FATAL` closes the client connection. `PANIC` crashes the server. This predictable vocabulary means log-analysis pipelines can filter by severity without regular expressions, and monitoring tools can alert on `PANIC` without ambiguity about capitalization or alternate spellings.
