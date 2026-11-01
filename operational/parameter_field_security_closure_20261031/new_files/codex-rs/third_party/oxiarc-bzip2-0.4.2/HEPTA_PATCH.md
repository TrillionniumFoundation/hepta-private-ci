# OxiArc BZip2: embedded single-stream adapters

Published Apache-2.0 crate archive SHA-256:
`feb108898a9c36e0bc6eea3eb6d832598c1176ee1d8de285e8e25a70599ffbbf`.
The license, encoder/decoder algorithms, CRC validation, compression levels,
legacy randomized-block support, and ordinary multi-stream API remain.

ZIP needs an embedded-stream contract: after one BZip2 stream, container bytes
must remain unread. The added constructor returns its reader on header errors,
disables the private 4 KiB read-ahead, stops after the first validated stream,
and exposes the underlying reader. Existing multi-stream construction is
unchanged. Interrupted reads are retried at the byte-input boundary.

The encoder gains underlying-writer access and a flush operation that emits a
pending block and complete bytes without padding or ending the stream. This
preserves ZIP's ability to flush and continue writing. No algorithm is removed.
The ZIP adapter and independent Python/libbz2 interoperability tests exercise
these boundaries. Ordinary decode can retain a decoded block in memory; this
backend change requires evaluation of its performance and resource behavior.

