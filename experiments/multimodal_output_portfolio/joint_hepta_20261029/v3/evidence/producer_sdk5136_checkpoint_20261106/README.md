# Integrated SDK producer and complete graph comparison

This independent packet preserves the exact #5136 integrated producer (358 ZIP
members, 324 source files, 360 committed entries, 21 native commands), its original
logs, both audits and its original API identities. The complete older #5119 ZIP
and original SDK proposal ZIP are retained as distinct source-bound inputs.

The new local read-only comparison consumes the complete original Cargo.lock,
MODULE.bazel.lock and metadata.json members from the two integrated producer ZIPs.
The unchanged 170-line SDK guard passes all three comparisons: only the reviewed
two dependency edges differ, all 1,528 package identities and every other metadata
field/feature remain unchanged, and MODULE bytes are identical. This does not
recover or reclassify the earlier proposal-private metadata.

Run `python3 -O -B restore.py /absolute/empty/directory` to verify every container
and restore inert files. The fixed reader performs no archived-code execution.
The original ZIPs remain ZIPs; their members are not automatically extracted.
Recorded audit scripts retain their original workspace paths and must not be
described as directly runnable from an arbitrary restored directory. Every
recorded original command, stdout, stderr and complete raw input identity is
available without executing those scripts.

The INDEX lists the complete retained roster and original filesystem modes.
Restored files use inert mode 0644; original modes remain recorded metadata.
Each bounded gzip member contains an exact segment of one XZ archive, preserving
the original bytes while preventing random compressed fragments from being
mistaken for source text. No spelling exclusion or existing packet was changed.

The first local log export's extra newline and correction, the failed optional
tree API call, original SDK custody limit, and prior source-specific results are
kept. Producer success is separate from ARM, Windows, business tests and aggregate
qualification. No pending native job is counted as a pass here.
