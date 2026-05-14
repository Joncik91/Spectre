---
view-types: [observability]
conventions:
  - "The header area (top of screen) shows hostname, uptime, and load average for the 1-minute, 5-minute, and 15-minute intervals on a single line, in that order; omitting any interval is a violation"
  - "CPU usage is displayed per-core as a horizontal bar using block characters; a single aggregate bar that hides per-core variation is not permitted when more than one CPU is present"
  - "Memory and swap rows each display: used / total in human-readable units (e.g. `3.21G / 15.6G`) followed by a proportional bar; displaying only the bar without the numeric annotation is a violation"
  - "The process list refreshes at the interval configured by the `delay` setting (default 1.5 seconds, minimum 0.1 seconds); a static snapshot that does not auto-refresh is not htop-compliant"
  - "Each process row exposes at minimum: PID, USER, priority (PRI), nice value (NI), virtual memory (VIRT), resident memory (RES), shared memory (SHR), CPU% (gauge), MEM% (gauge), TIME+, and COMMAND — all eleven columns must be present or the display is considered incomplete"
  - "CPU% and MEM% columns render as floating-point values with exactly one decimal place (e.g. `12.3`); integer rendering or two-decimal rendering are both violations"
  - "Color coding is role-consistent across the process table: kernel threads use one color, user processes another, and zombie processes a distinct third; using the same color for any two of these categories is a violation"
  - "The process list is sortable by any column; the currently active sort column is indicated by a highlight or `>` marker on the column header, not by text annotation in the row"
  - "The search/filter bar (`/` key) appears inline at the bottom of the screen and narrows the process list in real time as characters are typed; a modal dialog that requires confirmation before filtering is a violation"
axes: {metric-model: counters-plus-gauges, cardinality: low-fixed-labels, collection: local-direct-read}
calibrated-for: [on-call-engineer, sre-team, self-operated, cli-power-user]
taxonomy-version: 2
source-url: https://htop.dev/
last-reviewed: 2026-05-13
---

# htop observability conventions

htop is a real-time process monitor whose design contract is a terminal-width, color-coded snapshot refreshed on a sub-second timer. Its observability model is counters-plus-gauges: CPU time, context switches, and I/O bytes are monotonic counters rendered as rates (CPU%), while memory usage, load average, and priority values are gauges read point-in-time from `/proc`. The label set is fixed by the machine's hardware topology — one CPU bar per physical core, one memory bar for RAM, one for swap — so cardinality is permanently low and bounded by the hardware inventory at boot.

The header section is the first thing a human operator reads under pressure, so its layout follows a strict convention: hostname and uptime on the left, load average triplet (1/5/15 min) to its right. The load average triplet is always three numbers in that temporal order; dropping the 15-minute value loses the slow-trend signal that separates a transient spike from a sustained overload. CPU bars are per-core by default because an 8-core system with one core at 100% and seven idle reads as 12.5% aggregate — a number that would not trigger operator attention, yet the system is actually saturated on one dimension.

The process table conventions extend the same precision discipline to per-process rows. CPU% and MEM% use exactly one decimal place because two decimal places implies false precision (the values are sampled, not computed continuously) while zero decimal places loses useful discrimination between a 1.1% and a 1.9% consumer. Color coding for kernel threads, user processes, and zombies must be three distinct visual categories; collapsing any two forces the operator to parse the process name to determine what kind of resource contention they are looking at. The inline real-time filter is operationally load-bearing: when a system has hundreds of processes, the ability to narrow the view without leaving the tool is the difference between a 5-second and a 30-second diagnostic.
