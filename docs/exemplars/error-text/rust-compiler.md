---
view-types: [error-text]
conventions:
  - "Every hard error is identified by an error code matching the pattern `E[0-9]{4}` (e.g. `E0501`, `E0308`) — the code is stable across compiler versions"
  - "Error output begins with a severity label followed by the code in brackets: `error[E0308]: mismatched types`"
  - "Each diagnostic block includes a `-->` source location line in the form `file.rs:line:column` immediately after the header"
  - "Annotated source lines are printed verbatim with line numbers left-padded to a fixed width, and the offending span is underlined by `^` characters on the following line"
  - "The `^` underline may be followed by an inline message explaining the span (e.g. `^^^^ expected integer, found &str`)"
  - "Supplementary context regions (e.g. the conflicting borrow site) appear as additional source blocks within the same diagnostic, each prefixed with a note label"
  - "The trailing `error[EXXXX]` line references the online index using the pattern `For more information about this error, try \`rustc --explain E0XXX\``"
  - "Warnings use the `warning:` prefix without a code when they cannot be suppressed; lints carry codes of the form `[lint-name]` in square brackets"
  - "Multiple diagnostics are separated by a blank line; a summary line `error: aborting due to N previous errors` closes the output block"
axes: {tone: didactic, structure: annotated-source, link-to-docs: error-code-only}
taxonomy-version: 1
source-url: https://doc.rust-lang.org/error-index.html
last-reviewed: 2026-05-13
---

# rust-compiler error-text conventions

The Rust compiler diagnostic system is built around stable, human-readable error codes in the `E[0-9]{4}` namespace. Every hard error carries a code that is constant across compiler releases, deliberately designed to be grep-friendly and linkable to the online error index. The invocation `rustc --explain E0308` retrieves the full prose explanation including examples of triggering and correct code, forming a two-level documentation strategy: the inline diagnostic identifies the problem precisely, the explain output teaches the concept.

Diagnostics are laid out as annotated-source blocks. After the error header and source location (`file.rs:line:column`), the compiler prints the relevant source lines with their original indentation intact, then underlines the offending span with `^` characters on the next line. When a diagnostic involves multiple sites — for example, a borrow conflict spanning two functions — each site is a separate annotated block within the same error record, labeled with `note:` or `help:`. This makes every diagnostic spatially anchored rather than descriptive-only: the programmer sees the exact tokens that caused the problem without leaving the terminal.

The tone is explicitly didactic. The compiler does not merely report that something went wrong; it explains the type-system rule being violated, names the expected and found types, and often provides a code suggestion in a `help:` block. This verbosity is a deliberate design choice: the compiler is the primary learning surface for Rust's ownership rules, and the error output is where most users first encounter concepts like lifetime parameters and borrow scopes.
