---
view-types: [log-format]
conventions:
  - "Each record contains a `MESSAGE=` field with the human-readable log text"
  - "Priority is encoded in `PRIORITY=<n>` where n is a single digit 0–7 matching syslog levels (0=emerg, 1=alert, 2=crit, 3=err, 4=warning, 5=notice, 6=info, 7=debug)"
  - "Source unit identified by `_SYSTEMD_UNIT=<unit-name>.service` (or .socket, .timer, etc.)"
  - "Wall-clock timestamp stored as `_SOURCE_REALTIME_TIMESTAMP=<microseconds-since-epoch>` (uint64, UTC)"
  - "Monotonic timestamp stored as `_SOURCE_MONOTONIC_TIMESTAMP=<microseconds>` for within-boot ordering"
  - "Originating process identified by `_PID=<integer>` and `_COMM=<executable-name>`"
  - "Boot session identified by `_BOOT_ID=<32-hex-char UUID>` — stable per boot, changes on reboot"
  - "Machine identified by `_MACHINE_ID=<32-hex-char UUID>` — stable across reboots per host"
  - "Each field is a `KEY=value` pair; multi-line binary values encoded as `KEY\n<uint64-le-length><raw-bytes>`"
  - "Kernel messages carry `_TRANSPORT=kernel`; userspace journal messages carry `_TRANSPORT=journal`"
axes: {structure: key-value, identification: full-correlation, verbosity-gradient: six-syslog-levels}
taxonomy-version: 1
source-url: https://www.freedesktop.org/software/systemd/man/systemd.journal-fields.html
last-reviewed: 2026-05-13
---

# systemd-journal log-format conventions

The systemd journal stores log records as collections of key-value fields rather than a single line of text. Each record is a discrete structured entry in the binary journal database; exporters such as `journalctl -o export` or `journalctl -o json` render records one at a time with all fields present. Fields prefixed with `_` are trusted (set by the journal daemon itself); fields without the prefix come from the submitting process and are untrusted.

Identification in the journal is multi-layered. Every record carries a wall-clock timestamp (`_SOURCE_REALTIME_TIMESTAMP`), a monotonic timestamp for within-boot ordering (`_SOURCE_MONOTONIC_TIMESTAMP`), a boot-scoped UUID (`_BOOT_ID`), a machine-scoped UUID (`_MACHINE_ID`), and the originating unit name (`_SYSTEMD_UNIT`). This combination is sufficient for distributed log correlation when journal export is forwarded to a central store — the `_MACHINE_ID` + `_BOOT_ID` + monotonic timestamp triple is globally unique within a fleet.

Verbosity follows the full eight-level syslog scale encoded numerically in `PRIORITY`. Operators filter by priority using `journalctl -p <level>` (e.g., `-p err` shows err, crit, alert, and emerg). Because the journal stores all levels and filters on read rather than at write time, log producers should emit at the most specific level available; post-hoc filtering is lossless.
