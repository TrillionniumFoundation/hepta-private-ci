# Paired full-information evaluation profile

Status: the affected crate passed all 127 tests, including the existing OPE and
locked-store regressions, before and after the versioned envelope representation
change. A separate application integration passed with all 360 actual rows of
the completed full-002 NDU-controller versus dev-static future comparison.
The unit and application fixtures use explicit local deterministic witness keys.
No new scientific observations, external credentials, qualification, or promotion
are issued. The actual replay instructions and scope are in the v6
`OWNER_PAIRED.md`.

## Why this has a distinct entry point

The existing temporal/OPE comparison requires the two policies to share the
logged decision, selected action, outcome, and behavior probabilities. Two
policies that were actually executed can produce different final outcomes.
Those observations enter `ProductEvaluationRunnerV1::evaluate_paired_profile`;
they never enter an OPE row and have no invented propensity or cross-fit fold.
The original temporal entry points and signature profiles remain unchanged.

The initial paired profile is permanently tagged as previously observed
engineering evidence. Its plan freezes candidate/baseline identities, exact
source/context/version manifests, source code, metric, distinct Audit-B and
Reward-A artifacts, required text/image modalities, and the entire escrowed
outcome bundle. Freezing an already observed bundle is not preregistration.
Even favorable descriptive thresholds cannot grant qualification or promotion.

## Existing owner and storage migration

The same `FencedFinalHoldoutOwnerV1`, binding, fence, CAS store, and locked journal
are used for both profiles. The new `consume_paired` stages a transition, commits
the existing CAS, and only then returns a sealed consumption receipt. Conflict
and indeterminate writes poison the owner as before. Rejected writes never
release data. A later provider/evaluation failure leaves consumption recorded;
it cannot be erased to try another analysis.

This is **not a purely additive Rust storage API change**:
`FinalHoldoutCasRecordV1.journal` now has the versioned
`HoldoutJournalSnapshotV2` type. Direct consumers of that public field must
migrate. `HoldoutJournalSnapshotV2::try_from(FinalHoldoutJournalSnapshotV1)`
validates and imports an old snapshot while preserving every legacy receipt,
sequence, predecessor, head, and record digest. There is no mixed-to-V1 downgrade.

The existing `consume(&CrossFoldPlanReceiptV1)` signature remains unchanged.
Legacy-only file headers, fence/event-1 encoding, journal hash domains, CAS state
hashes, and recovery retain their original interpretation. Event 2 introduces
the paired plan. An old reader rejects a mixed history rather than silently
ignoring it. The new reader replays both variants and rejects changed, duplicated,
omitted, out-of-order, or rolled-back records using the existing minimum anchor.

Plan ID, final-window ID, and complete-cohort reuse checks span both profiles.
The paired cohort digest sorts the original source-unit identities independently
of case names, policy, grouping, or observed values. The host must retain the
same authoritative binding and common source-cohort identity convention.
Detecting overlapping _different_ cohorts remains a source-owner obligation;
this journal stores cohort commitments, not a global per-source allocation index.

## Release, complete pairing, and signatures

Only manifest metadata is read before consumption. The provider's outcome
release runs after successful CAS. The owner then verifies exactly one baseline
and one candidate observation for every frozen `(source case, seed)`, equal
public context and modeled-budget ceiling, exact arm/version/observer/metric
pins, distinct actual execution and observation receipts, and original output
digests. Actions, output bytes, and finalized outcomes may differ between arms.
The complete census is mandatory; unsuccessful observations cannot be dropped.

Existing `LearningEvidenceVerifierV1` authenticates Generator, Observer, and
Evaluator attestations under a host-owned trust snapshot. All three roles and
controllers must be separated. The evaluator signs only the owner-derived,
sealed result. A separate typed sink method publishes this distinct profile
through the host's evidence owner and returns a digest after durable commit.
Receivers can revalidate the signed/publication receipts. The regression fixture
uses a real fsync-backed file sink; a production host adapter is not supplied.
Local fixture signatures do not authenticate an external evaluator.

An exact retry returns the original consumption record and the same frozen data
and execution digest. It cannot replace the bundle, metric, candidate, baseline,
or source identity. A changed plan on an already consumed window/cohort rejects
before release. This is idempotent recovery, not a second independent experiment.

## Statistical and fulfillment scope

Registered Q32 joint losses are bounded in `[0,1]`. Within each source case the
candidate-minus-baseline loss and factual-error differences are averaged over
the fixed seeds. Source cases, not repeated seed rows, determine the interval
sample size. Integer arithmetic rounds the mean outward and uses a conservative
Hoeffding radius with the frozen family size and alpha. The bounds require
independent source-case draws and are conditional on the frozen models. They
provide no coverage for training-seed uncertainty or empirical CVaR.

Missing required text or image outputs are retained as fulfillment failures;
the result then exposes no paired quality interval or passing threshold flag.
The owner does not synthesize missing outcomes or assign abstention an invented
joint-output utility. Equal modeled ceilings are recorded explicitly and do
not assert equal consumed wall time, energy, or work.

The existing eval/OPE/locked-store suite, paired unit tests, and actual v6 owner
replay have passed. Independent review identified and corrected the source-to-case
mapping binding and required an independent original-row-log pin. The application
provider checks the actual locked store before each release. After journal
recovery the owner derives and authenticates the same result again, and its
stable publication encoding must equal the original persisted bytes. The
transport-only first-use/retry marker is outside that stable encoding.
