# learning.operator convergence — 2026-09-25

## Scope and claim boundary

This is a source/engineering convergence record, not a release, activation,
independent scientific acceptance or exact-head CI receipt. The changes continue
PR #990 / `work/product-convergence-20260923`; no parallel owner or storage engine
is introduced. The default full Agentd learning bootstrap remains unfinished.

## Delivered source changes

- Freeze and final fitting materialize actual authenticated current LedgerWriter
  records. The complete frozen plan and root-authorized learning trust
  distribution must remain unchanged. Same-receipt replacement of targets,
  actions, sensors, profile or generation is rejected.
- Raw tabular/world-model fitting, membership-only V2 wrappers and raw prediction
  require the explicit qualification feature. Default Cargo API probes check one
  positive owner/loaded path and twelve negative import/private-state cases.
  Bazel has a separate testonly qualification target, not a product dependency.
- Agentd evaluation V2 and governed candidate admission V2 require an already
  persisted, sealed ProductQualificationReceiptV1. They cannot manufacture a
  product qualification by passing signed metrics directly to a raw comparator.
  The existing fenced holdout and evidence sink remain the issuing owner.
- Shared Terminal recovery bundle V2 retains the training trust distribution
  inside signed artifact bytes and compares it with current ledger trust at
  reload and use. V1 is rejected, not silently reinterpreted or retrained.
- Per-operation tests are linked in the module map. Lane E checks its actual
  twenty operations and six operator cases. Only exact disabled-feature items
  are excluded from product-writer scanning; unrelated live code stays checked.

## Local observations before signed publication

The operator regression suite ran **31 tests, all passing**, plus one explicitly
ignored measurement workload. Default API compilation ran **13 controls, all
passing** (one positive and twelve required failures). The two Python negative
suites ran **11 tests, all passing**. Strict operator all-target Clippy passed.
The full Intelligence library suite ran **87 tests, all passing** after the
fixtures obtained actual durable qualifications from ProductEvaluationRunnerV1.
No eligibility/confidence threshold was weakened: the positive fixture uses a
prespecified 2,048-row balanced behavior-policy holdout, not invented intervals.

These are local presubmit observations, not proof that every subsequent candidate
SHA, all-target integration, every platform or the full Lane E workflow passed.
The complete Agentd runtime test/build and final CI results must be read separately.

The explicit owner history/quality measurement retained all durable writes and
correctness checks but timed out at its bounded **600-second** watchdog. One
scale completed: 128 records / 32 action pairs. Its observed append-pair p95 was
8,269,231 microseconds, owner-materialized fitting 5,492 microseconds, reopening
1,164,705 microseconds and prediction p95 2,963 nanoseconds. Process peak resident
memory was 5,788 KiB. This run did not control concurrent host load. The synthetic
32-row held-out fixture had zero candidate MSE versus 156,250 ppm for a zero
baseline; this is a simple known-profile engineering control, not field gain.
See LOCAL_MEASUREMENTS_20260925.json. The 512/2,048-record scales did not complete,
so no successful long-history resource qualification is claimed.

`just bazel-lock-update` failed downloading the repository-pinned V8 15.0.245.2
source archive with `Premature EOF` (exit 37). Its archive version and integrity
were not changed. A separately bounded retry uses the official source and must
match the existing integrity before being admitted to a local distdir.

## Still required for the six requested acceptance conditions

1. Obtain passing final exact-head and synthetic-merge CI, including required
   Cargo/Bazel parity and shared gates. Static Lane E verification alone is not
   the full lane; source-map observations must be rebound to the signed candidate.
2. Preserve the actual owner-row regression protections on all future product
   training profiles; generic membership wrappers are not a replacement.
3. Keep the raw feature absent from normal dependencies and use only independent
   artifact-owner admission for production pins. A locally calculated hash does
   not create independent authority.
4. Assemble the **normal Agentd bootstrap and request lifecycle** for freeze,
   training, independent evaluation, signed publication, selection, feedback and
   rollback. A directly callable SharedReplayHost is not that default loop.
5. Persist independently retained minimum trust/owner frontiers outside model
   rollback files, and finish the cross-stage publish-ACK-loss/recovery matrix.
   The old artifact plus an old self-contained trust snapshot cannot establish
   current authority; new bundle fields alone do not provide this bootstrap.
6. Complete the larger real-durability workload measurements on a controlled
   host and investigate owner append/recovery costs before adding a more complex
   learner. Do not disable sync, drop records or invent a timing qualification.

## Follow-up: exact-source CI and file-lock regression

Source implementation commit `e61a5265bc9a33e51c084f8060064c6332c26a65`
was published on the same PR #990 branch, with a valid GitHub signature. Lane E
run `36152857538` executed 388 package tests successfully, but its later coverage
step failed in `longer_divergent_history_cannot_skip_the_retained_minimum_prefix`
with `recover store: Busy`; this was a test failure before a line-coverage result,
not evidence of an insufficient coverage percentage.

Two independent regressions then reproduced the lock-release defect: retaining
a duplicate file descriptor after dropping the owner or rejecting a constructor
kept the OS lock alive. Both tests failed on the old implementation. The acquired
holdout-file guard now explicitly unlocks on both normal and failed exits, and
never unlocks a failed contender. After the fix, the complete evaluation library
ran 117 tests with 117 passing. The independent 85% line-coverage threshold is
unchanged and still requires its final CI run.

The real `terminal_cell_owner` integration target also completed: both normal
owner decision/outcome/training/reload/withdrawal and shared recall/replay/
training/signed recovery tests passed (2 passed; 2 explicitly skipped helper/
measurement tests). The shared path includes an actual child process rejecting
recovery under changed root-authorized learning trust and signed recovery bundles
with legacy or substituted trust identities. This is still engineering integration,
not the normal default Agentd learning bootstrap or live field efficacy.
