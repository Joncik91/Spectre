---
view-types: [ipc-rpc]
conventions:
  - "The parent process spawns the child with its stdin and stdout connected to pipes; the child reads JSON-RPC request objects from stdin (fd 0) and writes JSON-RPC response objects to stdout (fd 1)"
  - "Each JSON-RPC message on stdin and stdout is a single UTF-8 JSON object terminated by a single newline byte; the child must not emit any non-JSON output to stdout (debug output must go to stderr, fd 2)"
  - "EOF on stdin signals orderly shutdown: when the parent closes the write end of the stdin pipe, the child's read on stdin returns 0 bytes; the child must flush any buffered output to stdout, then exit with status 0"
  - "The child must not read from stdin and write to stdout concurrently in a single-threaded implementation unless the child uses non-blocking I/O or a select/poll loop; a blocking read on stdin while stdout is full causes deadlock if the parent is also blocked writing"
  - "SIGTERM sent to the child is a request for graceful shutdown: the child should stop accepting new requests, complete any in-flight request, flush stdout, and exit; SIGKILL is the parent's fallback if the child does not exit within a timeout"
  - "The child's exit status is the machine-level shutdown indicator: exit 0 = clean shutdown; exit non-zero = crash or protocol error; the parent must read the exit status via waitpid to avoid leaving zombie processes"
axes: {transport: stdin-stdout, framing: newline-delimited, lifecycle: child-process-boundary}
calibrated-for: [library-consumer, sdk-author, api-consumer]
taxonomy-version: 1
source-url: https://pubs.opengroup.org/onlinepubs/9699919799/functions/waitpid.html
last-reviewed: 2026-05-15
---

# subprocess-rpc ipc-rpc conventions

The stdin/stdout JSON-line protocol treats the child process lifetime as the session lifetime. The parent opens the channel by spawning the child; the parent closes the channel by closing its write end of the stdin pipe; the protocol ends when the child exits. Every JSON-RPC exchange happens inside that lifecycle boundary — there is no connect or reconnect; there is only spawn and terminate.

The newline-terminated framing rule carries an important constraint for the child: stdout must be used exclusively for JSON-RPC responses. Any diagnostic or log output emitted to stdout corrupts the framing stream from the parent's perspective. The child must redirect all non-response output to stderr. Implementations that mix log lines into stdout produce unparseable frames the first time a log statement fires.

The deadlock scenario in single-threaded implementations is a classic producer/consumer problem: if both parent and child are blocked on writes (parent writing to the child's stdin pipe, child writing to the parent's stdout pipe) and neither pipe has buffer space, neither can proceed. The solution is either a threaded or async read-write loop, or use of non-blocking I/O with select/poll on both pipe file descriptors. Single-threaded synchronous implementations that read one frame then write one frame avoid the deadlock only when the parent follows the same alternating pattern — a fragile assumption.

SIGTERM-based graceful shutdown gives the child the opportunity to complete an in-flight request and flush its output buffer before exiting. The parent should wait a bounded interval after sending SIGTERM (typically 5–30 seconds depending on expected request latency) before escalating to SIGKILL. The parent must call waitpid after the child exits to collect its exit status and prevent a zombie process entry in the process table.
