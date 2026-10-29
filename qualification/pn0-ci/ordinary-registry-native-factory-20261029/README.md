# PN0 ordinary Windows Registry factory follow-up

This is the next source dependency in the existing PN0 plan. Local root alone
integrates, commits and normally pushes the original docs branches. ROG's HEAD
remains d3284e385e2b6037dd86752ddd246b616144a87c with uncommitted source WIP.
Root reports integrating the five prerequisite source commits into local
42e8701fb92a65f8bd5b4c45df932ce08489e4e7 and copying the prior nine WIP files;
that is neither publication nor native qualification. Do not reapply or overwrite
those files to consume this new delta. Preserve all concurrent root changes.

## Producer and actual consumer

The Windows `DurablePromptRegistry::open_state_dir` previously always returned
UnsafeStateDirectory at its I/O boundary. It now produces the same native
evidence required by the opaque backend: actual process principal and retained
parent/ancestry/NTFS checks, exact fresh-or-existing directory handling, original
marker ownership lock, and existing schema/configuration/digest/extent recovery.
Unsafe paths, missing existing markers, wrong principals and native validation
failures still refuse. It does not cast a path or a DTO into authority.

The original 8192 UTF-16-unit path bound is unchanged; the new factory stops its
length scan at the first excess unit. That is a bounded input scan, not a claim
of physical quota or preemption of native I/O.

Agentd's original prompt pipeline now consumes this public factory on Windows
as it already did on Unix. Its one-use Registry wrapper is removed, while the
separate runtime native producer, 8MiB state boundary and final revalidation of
both held owners remain. Original store/file/record limits and all native
security checks remain. No dependency, lock, BUILD, workflow, token restriction
identity, peer check, grant or provider is added or relaxed.

The new three Windows test sources exercise the public factory directly. A
positive name-only fixture never precreates or authorizes its directory. Bare
existing state is deliberately produced with the genuine native creator only
for a negative test; the public factory must refuse to seed it. Corrupt cold
state must be rejected without rewriting its bytes. Cleanup is armed only after
real success, with the actual owner declared later and therefore dropped first.
It is best-effort fixture cleanup, not OS reclamation or cross-error custody.
The crate's existing standard assertions are retained without adding a diagnostic
dependency. All original tests and assertions remain.

## Actual validation

Recorded commands ran on the ROG d328 WIP graph, not root's new integrated
dependency/source tuple:

- The original Linux package first ran 50PASS/0skip in 9.000185579 seconds.
  After the helper cfg correction, the same package ran the same fifty named
  tests, 50PASS/0skip in 2.435212177 seconds. These are two recorded source stages,
  not one hundred independent tests. Windows-only tests were not run on Linux.
- Linux scoped strict Clippy exited0 on both source stages, finally in
  0.800864325 seconds, preserving `-D warnings`.
- Windows-GNU cfg(test) strict Clippy first actually failed after 6.703100166
  seconds. Eight test-only helpers and their type import were enabled on Windows
  although their only consumers were already in Unix-only test modules. The
  original failure is retained. Their cfg now matches those existing consumers;
  no test entry point, body, selector or lint flag changed. The same strict
  Windows command then exited0 in 1.147749521 seconds. No Windows test binary was
  linked or executed; this includes the three new native regression sources.
- Final `just fmt` exited0 in 0.372687398 seconds, changing only line wrapping in
  the new Windows test file. No tests were repeated after formatting.

The complete Agentd package and original Windows native16+4/query/terminal
groups are NOT_RUN for this candidate. None of these component results qualify
bf36 or a later root tuple. No old model/worker/SDK/supervisor/PN1/native budget
was reset, and no CI push, dispatch, cancellation, retry, merge or production
activation occurred.

## Original evidence and provenance

The new bf36 Bazel packet was independently read: 376 archived files, three
official ZIPs, 2,824,147 bytes of complete job logs and 269,340 compact records.
It contains 25 failed execution records for 14 targets, not 25 independent tests
or process birth/wait witnesses. Eleven supplied source files match actual bf36
Git bytes; the three jobs checked out c4f58 with bf36's tree.

The supplied proto is the official Bazel9.3.0 schema plus one extra final LF.
Its captured reader's short Git identifier was malformed. The separate
append-only correction records both exact content hashes and the actual
GitHub-fetched official blob, leaving all original files and parse results
untouched. No new compact-log parse or CI retry was used to erase that mistake.

The x64 base-merge56/112 receipt is only one lane, and its large original ZIP
was not delivered in this packet. This read does not reverify it or grant
four-lane qualification. Original ARM cancellations remain recorded. The macOS
Clippy log404/BlobNotFound does not establish a transient cause or authorize a
retry. Original native deletion and child-exit1 failures remain OPEN.

## Remaining dependencies and acceptance

Generic Registry initialization is only the first boundary. The intelligence
and other ordinary callers subsequently reach FinalUse; no genuine Windows
protected-time plus externally durable exact frontier CAS composition was found
in the reviewed source scopes. Real Unix checkpoint and holdout CAS producers
exist, but they are not interchangeable providers for this interface. No memory
frontier, SystemTime, self-signed receipt or private constructor is substituted.

Windows AF_UNIX peer checks still return Unsupported. They remain enforced;
PID lookup is not a connection-bound TokenUser proof. Core's original injection
fence also stays enforced. A snapshot of existing completion fences cannot
prove future quiescence, so no partial wait/retry or fixture replacement is
presented as a core lifecycle fix.

Created-directory custody across public errors, full token/ACL/PE-DLL/namespace/
desktop/stdio/Job/caller and terminal ownership, ordinary real-model three-round
installation, genesis, I09/I10/next-task readback, release, PN1 and independent
WAN retain their original order and bounds. No unknown charge is refunded.
`task_complete=false`, `merge_ready=false`, **NO_GO**.

One frozen independent source review now uses deterministic gzip transport. The [frozen record index](../frozen-record-encoding-20261029/manifest.json) maps its original path and Git blob to the archive and verifies exact decoded bytes. Its original wording and claim limits remain unchanged.
