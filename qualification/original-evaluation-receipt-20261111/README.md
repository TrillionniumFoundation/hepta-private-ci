# Original Evaluation receipt owner: component evidence

This candidate adds `OriginalCellEvaluationReceiptOwnerV1`. It signs the exact
Learning Evaluation receipt reconstructed from the original completed Cell
execution and authenticated qualification. It does not assemble production
learning stage ports or establish an ordinary task-to-FinalUse loop.

The current code candidate is PR #5896 commit
`c1d6537f7d979e1ad792eee796c6709d23a86697`, tree
`e7762b742e6baff12e447a89f40ae1cfb68aa7e1`. Its native qualification status at
this checkpoint is **PENDING_HOSTED_LINUX**. This evidence is published on a
separate qualification-only branch based on that commit; it does not advance
the code PR or cancel its current tests.

The 56 focused source checks and full 225-boundary caller scan belong to the
earlier source `30692d721d67321df0414c5c3f990449d7b9fea8`, tree
`790bf1330fde0ee51d9f9ea40848f3dc5d2afcb4`. The focused checks originally ran on
local commit `9f5e5b99831c6c19ecb231c3a5c2fbdc83febac5`, which has exactly that
same tree. The full scan ran on published `30692d7` with a clean source tree.

`SOURCE_COMPARISON.json` compares the complete 14,415-path Git inventories. The
only change from `30692d7` to `c1d6537` is one explicit
`use pretty_assertions::assert_eq;` import in the Model test module. Every
production file and guard is byte-identical, including the protected source,
boundary definitions, CALLERS manifest, scanners and focused Python QA. The
original scan was not rerun on `c1d6537`; no historical native result is
transferred to it. The production Evaluation owner retains frozen revision 4
SHA-256 `44e1c771ae778f2637178eb0a19a540349969485a20f2e86f45896cb381a7dd7`.

## What the component actually connects

The original host explicitly supplies its already enrolled Evaluator key,
immutable signing configuration, exact Training snapshot and frozen scope,
sealed Cell comparison, original execution journal, original Cell journals,
original Trainer evidence connection, signature file and independent witness.
The owner creates no keys, trust entries, role registrations or connections.

The signing path performs these operations in order:

1. Reject a new attestation at or after the work deadline using the owner host's
   current `SystemTime`.
2. Read the completed execution with `CellEvaluationRunnerV1::readback_completed`.
   The private store wrapper accepts only the original execution key and rejects
   both `claim` and `complete`.
3. Revalidate the complete recovered snapshot and its original Training prefix,
   then use `prepare_cell_learning_evaluation_v1` to authenticate the sealed
   qualification and derive the exact Learning Evaluation payload.
4. Read the original Training attestation through the existing
   `LearningIterationEvidenceClientV1`, verify the full enrolled principals and
   controller separation, and re-read the original execution before claiming.
5. Commit a durable Pending record through the existing `LearningOwnerJournalV1`
   before invoking the signing closure. The closure checks the current work
   deadline again and signs the canonical Learning Evaluation receipt domain.
6. Persist the completed signature and independent witness, then re-read Trainer
   evidence and the original execution. Revalidate the exact payload, full
   signer identity, signature validity and final journal witness before ACK.

`recover` and `readback` preserve the original signed bytes and issue time. They
do not sign, renew an expired signature, resolve ambiguous Pending, claim a new
execution or release a holdout. Missing or invalid original evidence is an error.
An authenticated Ineligible or InsufficientEvidence decision retains its real
NoUpdate meaning. A TrainingNoUpdate iteration cannot enter this Evaluation owner
because construction requires an exact Training cut whose next stage is
Evaluation.

## Recorded checks

`SOURCE_MANIFEST.json` pins the current code and the original check identities.
The retained historical manifest pins the actual commands, unchanged scanner
and original raw logs. `RESULT.json` records source-specific checks and native
status; a running or failed command is not a PASS.
`NATIVE_COVERAGE.json` separately records the exact declared test selection:
both Linux full-library workflows include Model 7, Evaluation 5 and Original
Training 6. That selection record does not claim the tests have executed.

The following targeted source suites passed on the `30692d7` source tree:

| Suite | Passed tests |
| --- | ---: |
| Original Evaluation receipt owner | 9 |
| Existing Cell Learning Evaluation adaptation | 8 |
| Generation Learning evidence | 6 |
| Evaluation execution recovery | 7 |
| Q24 Model proposal material owner | 9 |
| Original Training receipt owner | 4 |
| Original owner and publication boundaries | 13 |
| Total | 56 |

The new suite checks four exact existing call edges and four new closed owner
ports. Every edge and port rejects an injected unregistered caller. It also
removes reviewed guards and changes the deadline comparison operators for original identity, Training cut,
signature deadlines, source reads before signing and after completion, canonical
payload, current witness, and read-only execution access. Generic functions use
the existing bounded ordered-marker mechanism; these source checks do not claim
to prove every possible Rust semantic rewrite. Neither caller scanner was
changed. `just fmt` and the staged diff check also exited successfully.

The complete original repository caller scanner ran separately on the
published `30692d7` commit, with one Python process, one allowed CPU and nice level 10.
Its actual stdout, stderr and exit status are retained under `source-checks`.
It exited 0 with `PASS_HEPTA_CALLER_CLOSED_SET`, covering 6304 Rust files,
225 boundaries, 225 privileged inventory entries and 219 protected files.
The retained receipt reports `authorityGranted=false`; all four new owner
entrypoints still have empty production caller sets. The source remained clean
at commit `30692d721d67321df0414c5c3f990449d7b9fea8` after the scan.

The parent-coordinated native run uses the clean published source and the
existing repository `just test` entrypoint. It retains the original CI
`CARGO_PROFILE_TEST_DEBUG=0`, `CARGO_PROFILE_DEV_DEBUG=0` and
`CARGO_INCREMENTAL=0`, with one build job and initially two CPU cores. Its result must be
read from the retained run record, not inferred from the 56 Python tests.

The first run of this fixed source, `model-evaluation-native-attempt4`, exited
101 before executing any of the new tests. `rust-lld` terminated with signal 7
(Bus error) while linking the `sentry-contexts` dependency build script. The
complete original log is retained under `native-attempts`; its root cause is not
established by that diagnostic. Attempt 5 reused the same source, command and CI
profile after superseded build outputs outside the source tree were removed,
then ended with rustc SIGKILL while compiling `codex-rmcp-client`. Attempt 6 used
one CPU and reached `codex-app-server`, then failed with explicit ENOSPC while
creating a temporary directory. All three ended before executing the new tests.
The parent stopped further same-graph local native retries. Scoped `just fix`
maintenance is recorded separately and is not a native PASS.

The hosted daemon job for the same fixed `30692d7` source also failed before test
execution, for an actual source error: 18 E0659 macro-resolution errors in
`cell_q24_model_proposal_tests.rs`. Its glob import made `assert_eq` ambiguous
between `pretty_assertions` and the standard prelude. The original full job log
and source-bound execution record are in `hosted-attempts`; the recorder observed
zero passed tests and zero failed test cases because compilation failed first.

The corrective Evaluation successor is
`c1d6537f7d979e1ad792eee796c6709d23a86697`, tree
`e7762b742e6baff12e447a89f40ae1cfb68aa7e1`. It incorporates the Model fix's explicit
`use pretty_assertions::assert_eq;` import while retaining every assertion and
the production implementation. The original scanner PASS remains attributed to
`30692d7`; no old native result is transferred to the successor. Successor native
qualification is pending and is tracked separately in `RESULT.json`.

On the corrective `c1d6537` source, the required scoped
`just fix -p codex-hepta-agentd --locked` completed with exit 0 in 77.176 seconds,
followed by `just fmt` exit 0. Neither command changed a source file, and the
whole tree remained `e7762b742e6baff12e447a89f40ae1cfb68aa7e1` and clean. The
original maintenance manifest, logs and resource observations are retained under
`maintenance`, with every copied file's SHA-256 verified. This is successful
maintenance/type-checking evidence; it executed no native tests.

## Native behavior tests and their fixture provenance

Five new native tests cover exact signed receipt recovery across all three
authenticated evaluation decisions, substituted custody and execution namespace,
unsigned NoUpdate rejection, lost acknowledgements around Pending/completion,
source disappearance before signing and after completion, and refusal to renew
an expired original signature. These tests were added to
`learning_iteration_evaluation_evidence_tests.rs`.

They reuse the existing `LearningFixture`, including 8192 synthetic clusters and
synthetic Generator/Evaluator keys. The fixture uses the actual native Cell
evaluation runner, Cell journals, holdout CAS, signed Product execution store,
signature journal and independent file witness. The retained fixture execution
store is borrowed by the new owner. Existing Model `with_training` support and
actual Q24 candidate/fixed manifest binding are preserved.

The Trainer transport fixture uses real framed Unix-stream and pidfd mechanisms
with its existing test-only same-UID permission. Public production admission
continues to reject the same-UID/process shortcut. Fixture signatures and
synthetic cohorts are not deployed independent role custody or ordinary task
evidence.

## Production boundaries that remain open work

The following new public entrypoints deliberately have no production callers:

- `OriginalCellEvaluationReceiptOwnerV1::create`
- `OriginalCellEvaluationReceiptOwnerV1::recover`
- `OriginalCellEvaluationReceiptOwnerV1::attest_original_completion`
- `OriginalCellEvaluationReceiptOwnerV1::readback`

The existing Learning Evaluation original-readback assembly, original evidence
client constructor and Root stage-owner assembly remain closed. The host still
has to provide actual original role custody, authenticated process connections,
an evidence-serving lifecycle and ordinary stage assembly. A sealed
qualification is revalidated material; this component does not establish the
qualification publication sink's original custody, cold recovery or revocation.
The generic execution-store parameter likewise depends on the host supplying
the original store rather than a copied authority.

The returned receipt does not authorize Model adoption, selector publication,
CURRENT mutation or C FinalUse. This qualification establishes zero ordinary
complete loops, zero positive adoption loops, zero NoUpdate/rollback production
loops, and no independent C or joint daemon/Root restart acceptance. Those
counters describe what this candidate qualifies, not all historical work in the
repository.

## Historical failures are retained separately

`prior-core-failures/INDEX.json` preserves the a15 Core candidate's original
Actions logs. Three jobs failed while compiling the existing recovery test's
undefined `pending` binding. A separate prospective-merge job correctly rejected
a moved base identity. The complete upstream `6ecfa504` repair is included in the
current Model/Evaluation base; the newer Core successor is `b5019ee9`.

Those historical logs are neither native passes nor current candidate results.
No failure was converted into a NoUpdate result, no assertion was deleted, and
the exact source/base identity guard was retained.

## Acceptance differences and host access

`acceptance-delta/ACCEPTANCE_DELTA.md` provides a six-part current-source review;
its JSON companion retains exact source paths, caller sets and remaining real
inputs. It separates existing durable Training, ordinary Q24/C-source and cold
history components from the production assembly still missing. Model material
authentication and the new original Evaluation receipt owner are implemented
components. They do not supply a production Model proposal payload/dispatch,
original host role custody, original evidence-serving lifecycle or complete
Root stage-owner assembly. The review changed no source and executed no tests.

The read-only host-inventory recovery is recorded in
`host-access/exact-key-recovery.json`. An unfiltered inventory was refused by
the tool's 1 MiB response limit; the two host-filtered calls did not return
within 50 seconds. Neither exact original idempotency key yielded a job ID.
No new job was started, no original shell command was guessed, and no unrelated
job content was exposed. This leaves original host access unestablished; it is
not evidence that those jobs do not exist or that their hosts are offline.

The optional `maintenance/completed-cargo-cache-release.json` records removal
of this task's reproducible Cargo target after all local Rust sessions ended.
Source and evidence were retained. It is resource housekeeping, not test proof.

## Log retention and source-specific failures

`LOG_STORAGE.json` maps historical log paths to the files retained in this
package. Identical duplicate local native logs are stored once. Larger full
logs and resource observations use deterministic gzip; every entry records
both the original uncompressed byte count/SHA-256 and the stored file's byte
count/SHA-256. Decompression was checked byte-for-byte. Original manifests under
`history` and `maintenance/ORIGINAL_MAINTENANCE_MANIFEST.json` remain unchanged;
resolve their original paths through this storage map. Other relative evidence
paths are relative to this qualification directory unless an index states its
own directory explicitly.

`core-current/b501-clippy-failure.json` preserves a separate current Core
candidate's actual macOS Clippy failure. The original guard-plus-assertion scope
in `async_watcher_tests.rs` was rejected by the existing deny lint despite an
explicit `drop` before the next await. The exact `b5019ee9` source file matched
the then-current upstream `cb0598a9` file. Its suggested lexical-scope repair is
separate from this frozen Evaluation source. The complete original job log is
retained; it proves no native pass for either Core's two new tests or the 18
owner tests.
