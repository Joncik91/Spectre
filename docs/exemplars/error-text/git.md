---
view-types: [error-text]
conventions:
  - "Error messages are emitted to stderr; git exits nonzero on any failure"
  - "First line states the failed operation using a lowercase verb phrase (e.g. `error: failed to push some refs`, `fatal: not a git repository`)"
  - "Severity prefix is one of exactly three tokens: `error:`, `fatal:`, or `hint:` — no other prefixes are used"
  - "The `fatal:` prefix is used when git cannot continue; `error:` when the operation failed but git may emit further diagnostics"
  - "When a remote operation fails, git prints the remote's stderr verbatim under a `remote:` prefix, one line per remote line"
  - "Hint lines are emitted only after the primary error and begin with `hint:` followed by an actionable imperative (e.g. `hint: Use --rebase instead of --merge`)"
  - "No URLs, man-page references, or exit-code identifiers appear in error output — the message is self-contained"
  - "Object references in error messages use the canonical form git accepts as input (e.g. full ref paths like `refs/heads/main`, not friendly aliases)"
axes: {tone: terse, structure: what-why-how, link-to-docs: none}
calibrated-for: [cli-power-user]
taxonomy-version: 1
source-url: https://git-scm.com/docs
last-reviewed: 2026-05-13
---

# git error-text conventions

Git errors follow a strict three-tier severity vocabulary: `fatal:` halts the process entirely, `error:` signals a failed operation that may have partial output, and `hint:` appends optional remediation guidance. The prefix appears at column zero with no indentation, and every message after it is lowercase. There are no error codes, no man-page links, and no formatting beyond plain ASCII — the contract is that stderr is machine-parseable by simple prefix splitting.

The what-why-how pattern surfaces implicitly rather than with labeled sections. The first sentence names the failed operation ("failed to push some refs to 'origin'"), the second qualifies why ("Updates were rejected because the remote contains work that you do not have locally"), and `hint:` lines complete the trio with a concrete next step ("hint: Integrate the remote changes (e.g. `git pull ...`) before pushing again"). Remote output is quarantined under a `remote:` prefix so tooling can strip it without losing local diagnostics.

Because git emits no documentation links, users are expected to combine the severity prefix and the operation phrase to search the man pages manually. This matches git's design philosophy of a minimal, composable output surface where the caller — whether a human or a wrapping tool like IDEs and CI runners — controls how context is surfaced.
