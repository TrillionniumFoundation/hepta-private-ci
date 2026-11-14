# Actual default daemon memory path

The current local qualification is the separately frozen **SessionLease cycle**
below, completed at 2026-10-25 14:58 UTC. `session-lease-result.json` and
`session-lease-source-sha256.json` identify its actual executed bytes. The
original `local-result.json` and `executed-source-sha256.json` remain unchanged
and identify the earlier process cycle; their success is not used as a proxy
for the later lifecycle change. Independent hosted execution remains pending.

The local engineering qualification passed: the normal Linux
`codex-hepta-agentd` executable ran against a separate controlled issuer,
the actual Objective and NDU owners, the registered source writer, and one
retained pretrained adapter. It delivered the raw decoder answer once,
refused delivery after signed revocation, drained normally, and rejected
the old authority cut on a legitimate successor process generation.
Production authority and protected-clock qualification remain **false**.

`local-result.json` binds the completed attempts, model and process receipts.
`executed-source-sha256.json` identifies the 21 implementation, qualification
and workflow files at execution. The larger source inventory contains 467
files and has identical before/after SHA-256
`67e92c756a27968cf375b3cbaf7a32b875d6cfd0d70f423b299a0025722b11e2`.
This local run used frozen working-tree bytes; it is not represented as a
clean committed-source hosted result. Final fix/format is a subsequent root
stage with its own bridge, and no tests follow that stage.

## Product path

The explicit paired CLI arguments are
`--native-memory-bootstrap PATH --native-memory-bootstrap-digest SHA256`.
The prior startup path is preserved when they are absent. This opt-in surface
is Linux-only and selects the named `linux-local-compatibility-v1` profile.

The closed bootstrap descriptor binds the actual Agent and spawn generation,
private source anchor, signed source lease, retained claim, model configuration,
selected NDU journal, durable authority snapshot and nonce journal, signed
successor feed, policy, shadow profile, and private control socket. The owner
decoder bounds and closes nested claim schemas; decoding a claim does not
grant authority. Actual source/journal admission is still required.

Bootstrap restores the actual authority at its validated retained head, then
applies a higher-revision externally signed feed. It never invents a feed
timestamp or uses source authority, source owner, NDU and Objective epochs
interchangeably. The process clock checks actual Linux boot identity, uptime
and wall time and latches drift; these observations are not protected time.

The bounded local socket accepts one enrollment per daemon startup.
`prepare` returns the exact external grant binding and opaque prepared ID.
`execute` consumes that ID once and returns hashes/counters. `deliver`
performs asynchronous source validation followed by exact query, Objective,
NDU and binding checks, then writes without another await. `revoke` applies
a real signed monotonic feed without waiting for the session lock. The
surface bounds connections to four and frames to one MiB.

## Completed gates

| Gate | Selected / passed | Retained attempt |
|---|---:|---|
| Retained claim decoding and actual owner rejection | 2 / 2 | `retained-tests-002` |
| Signed source, private pins and local clock | 4 / 4 | `trust-tests-005` |
| Actual default process, pre-dispatch revoke and stale restart | 1 / 1 | `process-tests-007` |
| Actual default process, one trained read and post-delivery revoke | 1 / 1 | `process-positive-001` |

The positive command took 62.851 seconds, including compilation; its selected
test took 45.680 seconds. Issuer PID 659475, daemon PID 659840 and model child
PID 659946 are distinct. The raw model start record and supervisor receipt
both identify the daemon as the child's parent. The daemon's normal exit
was 0, with acknowledged Drain, run release and SIGTERM; no SIGKILL was used.

The raw answer was `order`, without postprocessing, received facts or retrieval
results. Actual cost was one decoder query and one feature forward, with
zero added training. The fixed 96-update completion-CE checkpoint was reused.
The worker reported 3,821,469 microseconds decoder latency, peak RSS of
1,131,909,120 bytes, and 539,903,232 parameter bytes excluding allocator
overhead. Those measurements are distinct from full command wall time.
The known case is previously exposed: independent future-task count is zero.

After the successful delivery, signed revocation caused the next delivery
to fail with `Revoked`; another execute of the consumed prepared request
was refused. The issuer then advanced the real fleet lifecycle through
Stopped generation 4 to Starting generation 5, rebound the old descriptor
cut to the new generation, and the actual restarted binary failed with
`pinned file drift`. This verifies stale authority rejection beyond merely
rejecting an obsolete process generation.

## Preserved failures and scope resolution

All failed builds and attempts remain in the raw control directory, with
receipt hashes listed in `local-result.json`. They exposed missing retained
claim decoding, incomplete Objective evidence, duplicate feed application,
an incorrectly placed AuthBus replay checkpoint, and insufficient cleanup
and restart assertions. Each correction was exercised before the final
successful attempt; failed runs are not counted as successes.

The final assertion-style pass exposed that agentd has no `pretty_assertions`
development dependency (`trust-tests-004`, compile failure, zero tests).
The root retained the existing dependency scope: agentd uses its original
standard macro; memory uses its existing `pretty_assertions` dependency.
The four agentd tests then passed in 005. This macro correction is explicitly
recorded and is not described as a formatting-only equivalence.

## Independent hosted qualification

The new workflow is restricted to a same-repository PR with exact head branch
`codex/memory-native-tick-process-qualified-20261025`, and checks out the PR
head SHA. There is no simultaneous push trigger. Its execution had **not yet
occurred** when this local receipt was written. Intermediate native stages use
the `codex/memory-native-tick-` prefix so the older training workflow skips them.

The new job runs no-model owner/currentness/default-process gates, recovers
the exact already qualified run 40188170696 / artifact 12598070717, registers
and executes one decoder query without training, audits the raw process
lifecycle, then performs final fix/format with no following tests. The
hosted adapter has its own exact prior artifact pin; it is not substituted
for the local adapter in this receipt.

The restore helper was exercised offline against the actual pinned
62,788,755-byte ZIP and base. It selected ten regular files totaling
1,967,792 bytes and verified original source, training receipt, adapter,
lineage, source document and base inventory. No network/model/training call
occurred in that recovery. Authenticated download remains a hosted step.
The old ZIP and base weights are excluded from the new artifact upload and
from these compact Git evidence files.

## SessionLease lifecycle correction and new qualification

The preceding final `just fix002` failed with ENOSPC and also diagnosed the
repository-denied Tokio mutex guard held across an await. Its failure is
preserved. The new implementation takes an owned `Session` from a short
`std::sync::Mutex<Option<Session>>` and returns it in `Drop`. A competing call
fails busy. Failed or cancelled execution retains the consumed prepared read
and attempted state. Poison or an unexpected occupied return slot closes the
runtime; the code never clears poison, replaces another session, or resets a
spent enrollment to a fresh default. Revocation remains independent of this
session, and the final delivery guard still has no await before the write.

| New cycle gate | Selected passed | Retained attempt |
|---|---:|---|
| Owned session identity, busy, real authorization error, pending cancellation, poison and occupied return | 6 / 6 | `session-lease-tests-002` |
| Actual default process pre-dispatch revocation, retained attempted state and consumed replay | 1 / 1 | `process-tests-008` |
| Actual default process single trained read, signed revocation, replay, Drain and stale restart | 1 / 1 | `process-positive-002` |

The unit run filtered out 198 other tests; each process run filtered out the
other process test. The pending-task cancellation test is unit coverage, not
a claim of actual daemon cancellation during decoding. The negative process
returned `attempted=true`, `completed=false` after its rejected Execute and
refused the repeated prepared request. It made zero model calls.

Registration 004 binds 469 source files, with before/after inventory SHA-256
`16896d2a7559f75a37d1692c4a41218b7f97de3df0c5f9a091b1681f2a3386f2`.
Its compact manifest identifies 23 implementation, qualification and workflow
files. Only the runtime digest changed from 003 because two shared Python
files had been formatted: `parametric_model.py` has identical raw AST; the
margin-loss file also changes leading docstring whitespace. Other immutable
base, adapter and profile pins are unchanged. These are distinct execution
bytes, not a claim that the previous 42-file Python inventory is identical.

The positive used issuer PID 746781, daemon PID 746820 and worker PID 746918.
The worker's parent was the actual daemon. Its raw answer was `order`, with
no retrieval, supplied facts or postprocessing. It used one decoder query,
one feature forward and zero new training, reusing the fixed 96-update
checkpoint. Decoder latency was 3,767,842 microseconds, worker peak RSS
1,131,999,232 bytes, and parameter bytes excluding allocator overhead
539,903,232. Full command wall time was 49.216 seconds, inclusive waited-child
CPU 49.468 seconds; the selected test took 46.556 seconds. Nested worker
measurements are attribution and are not added to that command cost again.

The raw audit joins the exact request, response, source and checkpoint,
post-delivery signed revocation, consumed replay, acknowledged Drain, run
release, SIGTERM and exit 0. All three processes exited. The actual successor
process at generation 5 again refused the retained old authority cut.
Independent future-task count remains zero; the known answer is previously
exposed. Production authority and protected-clock qualification remain false.

The failed offline dependency attempt, capacity refusals, successful cold
build and all process costs are separately retained. After registration,
shared disk space fell below the 300 MB positive reserve, so no model ran
until the root moved its verified inactive check-cache archive to a sealed
memory file. The sole positive then ran once, without retry. The current
executed-source copies were sealed before the root's subsequent final
fix/format; this cycle schedules no further tests or model calls afterward.

## Final tools and publication identity

After this new cycle, `just fix --locked -p codex-hepta-memory -p codex-hepta-agentd`
completed with exit 0 in 88.447 seconds (86.919 waited-child CPU seconds).
Warnings remain; this is not a claim of warning-free strict Clippy. Its only
owned automatic edit replaces an immediately invoked no-argument closure in
one SessionLease test with an equivalent block. The body has no return,
question-mark, break or await; the Result and lease Drop scope are preserved.
A second automatic edit removed two unused imports from an unrelated existing
test; that file was restored to its exact SHA-verified pre-command bytes.

An unscoped `just fmt` from `codex-rs` in the isolated publication checkout
then completed with exit 0 in 1.141 seconds. All three Python helpers retain
identical raw ASTs. The exact Rust patch and both sets of source hashes are
retained; no blanket Rust AST identity is asserted. There were no further
native tests or model calls after these final tools. `publication-format.json`
bridges these publication bytes to the executed sources. Independent hosted
qualification remains a separate result, not implied by this local success.

## Remaining boundaries

The issuer is an actual external process used as an integration fixture,
not a deployed production authority. Same-UID private files/socket peers
are trusted. This qualification provides no protected-clock, external
frontier, local rollback resistance, distributed quorum or physical-hardware
attestation. A currentness observation immediately before a write is not a
lease preventing another thread from revoking immediately afterward.

Recovery requires the exact retained source/profile/current-context
namespace and never falls back to a new journal on error. Migration of an
old shadow journal across a host generation or feed version is not
implemented. The parameter checkpoint remains retained separately, but the
one-enrollment surface does not qualify a continuous production lifecycle.
Future-task superiority, long-stream accuracy and net compression remain
separate open gates.
