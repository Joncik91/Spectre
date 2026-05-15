---
view-types: [input-shape]
conventions:
  - "A POSIX utility name consists of lowercase letters and digits; hyphens may appear between name components but not as the first or last character (POSIX.1-2017 §12.1)"
  - "Short options are a single hyphen followed by a single alphanumeric character (e.g. `-x`); they may be grouped without whitespace when they take no argument (e.g. `-abc` equals `-a -b -c`)"
  - "An option-argument may be supplied directly adjacent to its option letter with no whitespace (`-ofile`) or separated by a single space (`-o file`); both forms must be treated identically"
  - "GNU long options use a double-hyphen prefix followed by a word or hyphenated words (e.g. `--output`, `--output-file`); the argument may be supplied as `--option=value` or as two space-separated tokens `--option value`"
  - "The double-hyphen token `--` used alone terminates option scanning; all subsequent tokens are treated as non-option arguments even if they begin with `-` (POSIX.1-2017 §12.2 guideline 10)"
  - "Options that accept optional arguments (GNU extension) must use the `--option=value` form; `--option value` is not parsed as an optional argument — the value would be treated as the next positional argument"
  - "Option processing order: short options in the order given, then long options in the order given; interleaving short and long is permitted unless the implementation explicitly disables it"
  - "Operands (non-option arguments) follow all options; POSIX requires operands to appear after all options unless the implementation supports mixing (signaled by `POSIXLY_CORRECT` absence in GNU implementations)"
axes: {arg-style: gnu-long-flags, optionality: mixed, separator-support: double-dash}
calibrated-for: [programmatic-trusted, programmatic-untrusted, human-typed]
taxonomy-version: 1
source-url: https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap12.html
last-reviewed: 2026-05-15
---

# cli-argparse-shape input-shape conventions

POSIX defines the canonical shape for command-line utility arguments in §12 of the Base Definitions. The foundational rule is that options begin with a single hyphen and a single character; operands are everything that is not an option or an option-argument. This vocabulary — option, option-argument, operand — is precise: a reviewer can label every token in a command line as exactly one of the three before considering what a token means semantically.

Short-option grouping (`-abc`) is permitted for options that take no argument. The moment one option in the group takes an argument, the remainder of the group characters are that argument — e.g. `-obfile` means option `-o` with argument `bfile`, not three options followed by `file`. Implementing parsers must consume options greedily from left to right within a group.

GNU long options (`--word`) extend POSIX by naming options legibly. GNU's canonical reference is the Coding Standards chapter "Standards for Command Line Interfaces" which adds the `--option=value` form and the `--` terminator. The separator rule is critical: `--option value` assigns `value` only to a required argument; for optional arguments, the `=` form is the only unambiguous parse. A parser that accepts `--option value` for optional arguments silently changes behavior when `value` happens to match the next operand.

The `--` separator is the only POSIX-standardized way to pass operands whose text begins with `-`. Every conformant implementation must treat the token sequence `-- -file` as a single operand whose value is the string `-file`. Omitting `--` support creates an exploitable surface when operand content comes from user-supplied data (filenames, search terms, etc.).
