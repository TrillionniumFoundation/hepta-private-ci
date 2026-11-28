# Native opaque final-answer observation evidence

The selected native suite passed **26/26** tests. The separate required scoped
`just fix` did **not** pass: its Clippy child received SIGKILL 9. These outcomes
must remain separate. No SFT or useful-work result is claimed.

## Accepted scope

The new native profile retains one prompt and one observed final answer as
`RecordOnly { unverified_capture_sha256 }`. It refuses task history, native
features/labels, upgraded identity/execution flags, and replayed material. The
existing terminal signature domain refuses this observation before Memory
context retrieval, dataset freeze, signature construction, fitting, or Ledger
mutation.

The native two-record owner does not receive the referenced SDK capture and
semantic-receipt originals. It therefore does not rerun source verification or
authenticate the teacher execution, model weights, human consent, or declared
outcome. This is an explicitly limited intake boundary, not a training bridge.

## Reproduce the selected controls

Use the repository-pinned Rust 1.96.0 and nextest 0.9.152. The original toolchain
manifest, component/download hashes, CMake wheel provenance, command arguments,
and selected environment are retained in the archive and `PROTOCOL.json`.

```sh
just test -p codex-hepta-agentd --lib --locked \
  -E 'test(record_identity) | test(paired_binding_tests)'
```

The filter ran existing byte/canonical identity, native owner, deadline,
cancellation, late Evaluator, event binding, and Memory revocation controls plus
five new opaque-profile regressions. Its 960 unselected tests were not executed.
The successful attempt took 134.015672 seconds including remaining compilation;
nextest itself reported 6.027 seconds. Original warnings are retained.

## Preserve failed observations

`RESULTS.json` distinguishes five actual build/test attempts, a separate
pre-Cargo ENOSPC recorder failure, and the failed Clippy invocation. Attempt 4
was a real compile error in our new test code, repaired by an explicit macro
import. Attempts 1 and 2 repaired missing native build prerequisites. Attempt 3
and scoped Clippy were interrupted by SIGKILL; peak RSS was not measured, and
the signal alone does not establish an OOM cause. Clippy really used one Cargo
build job. No lint success is inferred from the passing tests or formatting.

The final `just fmt` and `git diff --check` were observed to exit zero in the
session; their raw stdout was not separately persisted. After the passing test,
only five inline `/*maximum*/` comments changed Rust bytes. Removing exactly
those comments reproduces the tested module hash. The other ten final changed
files match the passing-test hashes exactly. All 640 pre-Clippy source hashes
also match after this same comment normalization. The parent merge afterward
added Python evidence only. No test was rerun after these finalization steps.

## Verify the original archive

`ARCHIVE.json` names every member, its original byte length and SHA-256, and the
archive hash. Every member was read back and compared byte for byte before this
evidence commit. The archive contains original logs/records, official public
toolchain metadata, the tested opaque module, and a separately labelled derived
source-byte mapping. The empty failed-recorder file is intentionally preserved.
It contains neither a build target nor live user captures or credentials.

The code-only commit is `65d55b71ff61a1451710e3540edd5381def58988`.
The publication manifest snapshot identifies that code commit, not the later
evidence commit. The latest recorder is retained for audit; each original
attempt record, rather than a reconstructed replay, specifies what ran.
