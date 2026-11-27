# Preserve path-free authorized-read error contracts over RPC

The fac3 macOS Intel remote escape test rejected the file but failed because
`map_authorized_read_remote_error` flattened the local PermissionDenied error
into a generic InvalidInput message. Source review also identified the same
loss for a local InvalidData overflow: the server emits internal error -32603,
which the client previously flattened to Other before the original strict
oversize assertion could be reached.

Map only two exact existing (code, message) pairs to their original error kind:
(-32600, `Permission denied`) and (-32603, `authorized file read exceeds bound`).
Both messages are fixed and path-free. Other codes, mismatched pairs, and
messages with appended secret paths retain the existing redacted fallback.
Seven table cases verify those boundaries. The existing end-to-end exact-bound,
oversize-without-prefix, symlink escape, parent escape, and capability-gating
assertions are retained. No filesystem authorization or wire error code changes.

The full failed job 139157914163 log SHA-256 is
`8964a6d7466046c18d3293b708260ae01702e51142bcf0b8daefbf753fed5f71`.
The overflow failure is a source-derived prediction, not a second observed
native failure. Formatting/source review alone does not qualify this change.
