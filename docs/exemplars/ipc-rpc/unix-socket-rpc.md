---
view-types: [ipc-rpc]
conventions:
  - "The server creates an AF_UNIX socket of type SOCK_STREAM and binds it to a filesystem path; the path must be unlinked before bind or bind will return EADDRINUSE"
  - "Each JSON-RPC message is terminated by a single newline byte (0x0A); no other framing is added; the receiver reads until it encounters a newline, then parses the accumulated bytes as a single JSON-RPC object"
  - "Messages on a UNIX socket connection are ordered and lossless within a single connection; no message-level sequence numbers are needed for ordering, but JSON-RPC id fields are still required for request/response correlation"
  - "Connection lifecycle: server calls accept() to obtain a client file descriptor; for each complete newline-delimited frame the server reads, it writes exactly one newline-delimited response frame (for non-notification requests) or nothing (for notifications); EOF on the read side signals client disconnect and the server closes its end"
  - "The socket file descriptor is inherited by child processes unless O_CLOEXEC (or SOCK_CLOEXEC on Linux) is set at creation time; the server must set O_CLOEXEC on both the listening socket and each accepted file descriptor to prevent leaking the IPC channel into subprocesses"
  - "SIGPIPE is generated when writing to a socket whose read end has been closed; servers must either install SIG_IGN for SIGPIPE or use MSG_NOSIGNAL on send calls, and must handle EPIPE from write/send as a normal disconnect event"
axes: {transport: unix-socket, framing: newline-delimited, lifecycle: persistent-session}
calibrated-for: [library-consumer, api-consumer, sdk-author]
taxonomy-version: 1
source-url: https://pubs.opengroup.org/onlinepubs/9699919799/functions/bind.html
last-reviewed: 2026-05-15
---

# unix-socket-rpc ipc-rpc conventions

JSON-RPC 2.0 over a UNIX domain socket combines two independently specified protocols. The transport (AF_UNIX SOCK_STREAM) provides a reliable, ordered, full-duplex byte stream between two processes on the same host. The framing (newline-delimited JSON) turns that byte stream into a sequence of discrete messages. Neither layer knows about the other: the socket does not understand JSON, and JSON-RPC does not know it is running over a UNIX socket.

The newline-delimiter convention is simple but fragile if the JSON serializer emits embedded newlines inside string values. A conformant implementation must ensure that no newline character appears inside the JSON text before the message-terminating newline. The canonical approach is to disable pretty-printing (all JSON in one line) — POSIX imposes no constraint on JSON shape; the newline-delimited convention is a stack-level protocol agreement, not a POSIX requirement.

The O_CLOEXEC discipline is operationally important in any server that spawns subprocesses: without it, a forked child inherits the listening socket and all accepted connection file descriptors. The child holds a reference to the socket even after exec, which prevents the OS from delivering EOF to the client when the server closes its copy. Setting O_CLOEXEC at socket creation eliminates the inheritance path entirely without requiring per-fork close calls.

SIGPIPE handling is mandatory for any persistent-session server. A client that exits while the server is mid-write causes SIGPIPE delivery; the default disposition terminates the process. The correct disposition is SIG_IGN (or MSG_NOSIGNAL) so that write returns -1 with EPIPE instead, which the server handles as a clean disconnect and closes the accepted file descriptor.
