---
view-types: [help-text]
conventions:
  - "Top-level `git --help` emits a paged man-page-style document to stdout (or invokes the pager); `git help <command>` opens the full man page for that command in the system pager"
  - "Top-level help groups subcommands into named categories (e.g., `start a working area`, `work on the current change`, `examine the history`) each printed as a section header followed by a two-column list of subcommand-name and one-line description"
  - "Each subcommand's synopsis section lists all flag permutations as separate SYNOPSIS lines (one per major usage pattern), using `[<options>]` for the common options placeholder and named angle-bracket arguments for required positional args (e.g., `git commit [-m <msg>] [--] [<pathspec>...]`)"
  - "Flags in the OPTIONS section are formatted as two-column entries: flag(s) on the left with no leading indent (man-page `.TP` style), description paragraph below indented by one level; multi-form flags list all synonyms on the same line separated by `, ` (e.g., `-m <msg>, --message=<msg>`)"
  - "Each subcommand man page contains a DESCRIPTION section of at least two prose paragraphs before the OPTIONS section; it does not begin with the option list directly"
  - "The EXAMPLES section in a subcommand man page shows each example as a fenced or indented shell command followed by a prose explanation of what it demonstrates; examples are not bare invocations — each one is annotated"
  - "Deprecated flags or aliases are documented with an explicit deprecation notice in their OPTIONS entry; they are not silently omitted"
  - "The SEE ALSO section at the end of each man page lists related git subcommands by name (e.g., `gitrevisions(7)`, `git-rebase(1)`)"
axes: {verbosity: balanced, structure: subcommand-tree, example-density: separate-section}
calibrated-for: [cli-power-user, cli-novice]
taxonomy-version: 1
source-url: https://git-scm.com/docs/git-help
last-reviewed: 2026-05-13
---

# git help-text conventions

git's help system is built on Unix man pages, not ad-hoc `--help` strings. Running `git --help` or `git help git` opens the `git(1)` man page; running `git help commit` opens `git-commit(1)`. This means the full help system inherits man-page formatting conventions: SYNOPSIS, DESCRIPTION, OPTIONS, EXAMPLES, SEE ALSO sections in that order, with `.TP`-style two-column flag entries. The top-level `git --help` output (when not redirected to the pager) shows a grouped command listing — not a flat alphabetical list — with category headers like "work on the current change" that hint at workflow rather than implementation.

The subcommand-tree is one level deep for most commands (`git commit`, `git rebase`) but two levels deep for porcelain groupings (`git remote add`, `git submodule update`). Each level of the tree has its own man page. The SYNOPSIS section of each page lists all supported invocation patterns as separate lines — `git commit [-m <msg>]` and `git commit --amend` appear as distinct SYNOPSIS entries rather than one combined template with all flags shown. This exhaustive SYNOPSIS style trades compactness for completeness: a reader can find their pattern by scanning the synopsis without reading the full OPTIONS section.

The EXAMPLES section is a physically separate block appearing after OPTIONS, consistent with git's man-page heritage. Examples are annotated: each command is followed by a paragraph or indented comment explaining the scenario, not just the mechanics. The verbosity level is balanced — the descriptions are dense prose rather than one-liners, but stop short of the tutorial style found in some modern CLIs. Deprecated flags appear inline with an explicit deprecation notice rather than being silently removed, which preserves backwards-reference validity for users consulting old documentation or scripts.
