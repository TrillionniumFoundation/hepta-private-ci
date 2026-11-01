# ZIP 9.1.2: retain BZip2 with independently licensed codecs

Published MIT crate archive SHA-256:
`ec2e3161de27091f18a831d9494e9c53378a34833af5c1dda35ad85849da18d6`.

All default feature names and compression capabilities are retained. The
`bzip2` and `bzip2-rs` feature names select the Apache-2.0 OxiArc BZip2 encoder
and decoder through private I/O adapters. Both writing and reading remain
available at levels 1 through 9, including legacy randomized-block decoding.
Other codecs and encryption are unchanged.

The previous libbz2-rs-sys package declares bzip2-1.0.6, outside the repository's
current license policy. Switching to bzip2-sys would not solve that problem:
its published archive bundles the same separately licensed C implementation,
despite the bindings' MIT/Apache Cargo metadata. This change neither relabels
that code nor adds an allowlist exception. It adopts a separately published
Apache-2.0 implementation and retains its license.

The single-stream decoder preserves following ZIP headers, input errors and
checksums. The encoder preserves flush-then-continue and underlying-writer
access. Regression tests include exact stream boundaries, legacy randomized
blocks, corruption, truncation and all levels. Independent Python/libbz2 tests
must verify files in both directions, including multi-block data. These are
candidate source changes until their actual CI evidence is reviewed; this note
does not claim they have already passed.

