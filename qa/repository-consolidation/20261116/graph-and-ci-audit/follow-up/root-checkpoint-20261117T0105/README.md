# Source and validation checkpoint: 2026-11-17

This package retains the original audit records for source candidate
`4a5630661b1fee17582b452520c32fb5805831aa` (tree
`3c2c8718270bc8c45eb22918e81fbc35cc695189`). It is an intermediate
integration checkpoint. It does not establish that the whole repository,
the complete combined source tree, or Windows CI has passed.

## Contents and recovery

The compressed manifest describes 382 original logical files, 299 unique
content objects, and their original SHA-256 identities and file modes.
The 22 independently compressed parts reconstruct one 10,166,675-byte archive,
SHA-256 `837babed62f917422204e5d20551f7f3a63a3f377b0f7b5ade05ef5d0bcfc309`.
Every captured byte and original mode was verified during assembly.

Run `python3 restore.py /absolute/path/to/new-directory` on a POSIX host.
The destination must not exist. The helper verifies each part, the complete
archive, every content object, every logical file, and every restored mode.
It rejects traversal, duplicate paths, nonregular archive members, and
overwriting an existing destination. Source paths in the manifest are origin
labels, never restoration destinations.

The manifest records all 307 exclusions and their reasons. Rebuildable helper
executables, source working copies already retained as exact Git objects,
duplicate immutable API blob responses, private Git indexes, and runtime
metadata are excluded. In particular, the 560,168,728-byte helper executable is
represented by its actual hash, original build invocation and build receipts.
No excluded executable is presented as an embedded artifact.

## Scope of retained evidence

The package includes the three preceding ordinary merges, the five new
ordinary merges, the reviewed 14-file source and workflow correction, three
Windows launch and source-pin corrections, the B4 guard correction, the
Windows 128-bit file identity proposal and its independent review, the bounded
checkpoint repair, the reviewed control source layer, the canonical receipt
tag repair, four original formatter runs, and their original immutable
creation records. Each ordinary merge retains its actual incoming parent and
explicit per-path conflict resolution.

It also includes both full B4 gate results; the original helper build and
ten-case replay; the frozen failed full native run records; the ROG diagnostic
handoff; and the formatter scope correction. The separately published
control-layer, checkpoint, final 369-test, and v6/fresh-reference packages
contain their own complete manifests and recovery instructions.

## Validation boundaries

- The original formatter passed on the actual candidate with 13,817 inputs
  unchanged. Its complete index contains 30,178 paths. The earlier v2 selected
  input result remains retained, together with the v3 correction explaining
  the physical input scope.
- The original B4 suite passed 1,344 tests. The complete caller verifier passed
  with 1,645 boundaries, 819 protected rows, and 7,552 Rust files. Those runs
  used the earlier `9839d541` source plus the four B4 changes, not this complete
  later source tree. No production authority was granted.
- The exact ten previously failing helper-related cases passed after the
  original helper builder completed. The unchanged full earlier run remains
  1,971 passed, 11 failed, three timed out, and 193 originally skipped. The
  selected replay does not replace that full result.
- The four diagnostic cases passed on an instrumented ROG source using tmpfs.
  This does not resolve the unchanged desktop ext4 timeout and latency
  failures or prove a particular performance cause.
- The final control-layer run passed all 369 tests in its recorded source
  composition. Seven new Windows-only tests were not run on Linux.
- The v6 package records the original command sequence and a separate exact
  nextest 0.9.103 replay of 552 tests. It retains reused prerequisites,
  original filters and ignored tests, and host-environment differences.

Ordinary branch coverage at this candidate is 1,835 of the original 7,230
eligible heads, leaving 5,395. The captured reference snapshot contains 104
protected HIA-related heads and no protected ancestry intersection. A fresh
reference check is required before publication. Main, protected references,
and branch deletions are outside the changes represented by this package.
