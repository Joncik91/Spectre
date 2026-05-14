---
view-types: [error-text]
conventions:
  - "Error messages are emitted to stderr; gh exits nonzero on any failure"
  - "The error line begins with `X` (a red cross rendered via ANSI) followed by the failure description in sentence case (e.g. `X Failed to create pull request: Validation Failed`)"
  - "When the API returns a structured error body, gh extracts and appends the human-readable `message` field on the same line after a colon separator"
  - "A `--help` suggestion is appended as a separate line when the error is caused by incorrect CLI usage: `Run 'gh <command> --help' for usage.`"
  - "OAuth and authentication errors include the full URL to re-authenticate: `https://github.com/login/oauth/authorize?...`"
  - "When gh opens a browser URL as part of a flow and the browser cannot be launched, the full URL is printed to stdout so the user can copy it"
  - "Multi-line responses from the GitHub API (e.g. validation errors on multiple fields) are printed one error per line, each prefixed with `- `"
  - "Exit code 1 is used for operational failures (API errors, network failures); exit code 2 is used for misuse (bad arguments, missing required flags)"
axes: {tone: conversational, structure: what-why-how, link-to-docs: full-url}
calibrated-for: [cli-power-user, cli-novice]
taxonomy-version: 1
source-url: https://cli.github.com/manual/
last-reviewed: 2026-05-13
---

# gh error-text conventions

The GitHub CLI targets an audience comfortable with GitHub's web UI but not necessarily with Unix tooling conventions, so its error text is written in plain sentence-case prose rather than the terse imperative style common in Unix tools. The primary error line is prefaced with a rendered `X` symbol (using ANSI red when the terminal supports it) that mirrors the visual language of GitHub's web interface. The message that follows names both the operation that failed and the API's own explanation, joined by a colon, so the user can correlate the output against GitHub's status page or documentation without decoding internal codes.

Authentication and browser-based flows receive special treatment: when gh cannot open a browser, it falls back to printing the full authorization URL to stdout, keeping the flow unblocked in headless environments like CI runners and SSH sessions. This is the clearest example of gh's conversational philosophy — it anticipates that the user may be in an unusual environment and surfaces the next-step URL rather than failing silently or emitting a generic "browser not found" message.

Usage errors are separated from operational errors by exit code (2 vs 1) and include an inline pointer to the relevant `--help` page. This means a caller can distinguish "bad input" from "good input, but GitHub refused it" purely by inspecting the exit code, enabling automated retry logic that is scoped to the correct failure category.
