# P41 frozen native private-Head pool evidence

This package preserves the completed eight-process P41 run. The original report,
plan, all eight raw JSON outputs, eight stderr files, two Head artifacts,
crosscheck, validation, scripts and logs are copied without byte changes.
The original narratives and absolute `/tmp` paths remain as historical records;
`manifest.json` maps those paths to this portable package. Raw logs distinguish
initial/environment-blocked attempts from the final successful scoped checks.

- Original source: `f8855a7ac07af47b618199a3a9ccb87ff9552a5c`; tree `231ed14ea73a71c6d2ac3fe353b1779419154f53`.
- Original report SHA256: `f4ed9cce8f33cb26764933cbc2b950239c9b7e2f8360410b051467a50ca8abe0`.
- Raw observations retained: **32768 dispatch samples + 128 full-fanout samples**.
- Each mode used 1, 32, 256 and 4096 private owned Head allocations, exercised
  before timing. These replicate **two fixed trained artifacts**, not thousands
  of independently learned tasks.
- Native timers exclude JSON/pipe IO and reference validation. Fanout has only
  16 samples per process; its median and maximum are descriptive, not p99.
- All samples remain, including the variable gated-4096 run. The fixed serial
  order on a shared host cannot establish an intrinsic architecture cost ranking.
- Self `/proc` RSS/RssAnon includes inputs, source buffers, private weights,
  allocator and runtime. This is not physical-page attestation or Encoder memory.
- **Head-only; non-target-device; no energy measurement; no new independent
  quality trial; no training/calibration changes; no policy or production authority.**

The original `requests.jsonl` (16,988,720 bytes) and executable (2,673,320 bytes)
are deliberately omitted. Their complete original sizes and SHA256 digests are
in `input-references.json`; `RECONSTRUCT.sh` gives exact-source input and build
commands. The original bytes were rehashed during packaging. Cached inputs can
be reconstructed from the existing pinned P40/research evidence without an
Encoder. A rebuilt executable must be identified by its actual hash; source
identity is not compiler attestation or a promise of a byte-identical build.
Original measurement reports are never rewritten to describe a later rebuild.

## Integrity and publication

Run `sha256sum -c SHA256SUMS` inside this directory. The checksum list includes
`manifest.json`; the manifest indexes every payload file, excluding itself and
`SHA256SUMS` to avoid circular digests. A final external package receipt pins
both index files. The two omissions are explicit and do not remove any timing
sample. `references/p40/` retains the paired reference ledgers used by the
original crosscheck; other P40 dependencies retain their repository paths and
hashes rather than being silently treated as package contents.

The remote same-tree commit mapping may be appended as separate publication
metadata later. Keep source SHA/tree inside the original report and plan intact.
No benchmark, model inference, encoding or training was rerun while packaging.
The new shell reproduction recipe is documentation, not an additionally executed
test. Original local tests and native checks keep their own source/time scope;
this package makes no claim that remote CI has completed.

## Repository publication paths

The archived Rust snapshots use `.rs.source` suffixes so repository formatters
do not rewrite historical evidence with a different configuration. Their bytes
and original Git blob identities are unchanged. The initial package README and
indexes are retained separately; the current `manifest.json` and `SHA256SUMS`
cover the publication paths. Run the original packager followed by
`checks/publication_package.py` to reproduce this mechanical transformation.
No original measurement, timing sample, trained weight or test log is changed.
