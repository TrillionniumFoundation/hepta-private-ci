# Stable legacy hashing

This crate is maintained with this repository and owns the exact legacy hash
contract required by Starlark 0.14.2 and BM25 2.3.2. It has no runtime dependencies.
It implements only the two hash states and three digest entry points those consumers
need; it is not a copy of the archived fxhash package under a new package name.

The rotation/multiplication algorithm originates in the Rust project and was
published in [fxhash 0.2.1](https://crates.io/crates/fxhash/0.2.1), under
MIT OR Apache-2.0. Copyright 2015 The Rust Project Developers. See the repository
LICENSE for the Apache-2.0 terms. The reference crate archive and source digest are
recorded in HEPTA_SOURCE.json.

The implementation preserves 32-bit and 64-bit outputs, native-endian byte decoding,
low-word-first u64 writes into the 32-bit state, inherited signed/u128 Hasher methods,
and per-write chunk boundaries. Starlark truncates its 64-bit result to 32 bits at
its existing call site; BM25 preserves its u32/u64/usize embedding IDs. Neither
consumer's tokenization, map order, serialization, nor scoring is changed.

The current rustc-hash algorithm produces different values and cannot substitute
for an existing ID format. ccl-fxhash and ritehash have no recent registry releases;
introducing another dormant fork would not establish a useful maintenance owner.

Future fixes belong here and must preserve the golden compatibility vectors. A
format or algorithm change requires an explicit consumer migration and versioned
compatibility boundary. This hash is not cryptographic and is not intended to
defend hash tables exposed to adversarial collision input.

Validation compares this implementation with the unmodified official fxhash
0.2.1 crate in a separate, non-workspace oracle. That reference is not a dependency
of any production or test target in this workspace. Committed tests retain concrete
legacy vectors rather than keeping an archived dependency in the active graph.

## Repository formatting provenance

`HEPTA-formatting.patch` records the subsequent mechanical changes from
`just fmt`; it does not belong to the functional maintenance patch. The
original bytes are stored as `HEPTA-formatting.patch.evidence.gz`. From the
repository root, run `python3 qa/repository-consolidation/20261115/restore_raw_evidence.py /path/to/new-directory`
to recover the patch at its original relative path.
The source metadata records both pre-format and final hashes. Targeted tests
were run before the required final fix/format step, in the order specified by
the repository instructions.
