# `learning.eval` production contract

This file is the normative public-surface, durability and ownership contract for
`learning.eval`. The architectural guide, native mapping, Lane E matrices and
execution dossiers may add detail but may not weaken this contract. Generated
lexical source truth is recorded in
[`docs/modules/learning.eval/CURRENT_STATUS.json`](../../docs/modules/learning.eval/CURRENT_STATUS.json).

## Authority boundary

An evaluation may establish eligibility for a later independent consumer. It
never selects, activates, promotes, deploys or releases a candidate. Evaluation,
attempt, admission, archive, checkpoint, compaction and qualification receipts
remain `AuthorityPosture::DENY_ALL`.

Source presence, source tests and repository CI are not target-host qualification,
independent acceptance, activation or release authority.

## Public and internal surfaces

| Surface | Classification | Required use |
|---|---|---|
| `RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison` | default product evaluation ingress | persists intent before provider/holdout access and records consumption before observations are released |
| `RecordedProductEvaluationRunnerV1::qualify_and_persist_with_artifacts` and selected-host qualification methods | default product qualification ingress | derive the canonical typed archive, verify current V2/V3 evidence, and persist/anchor the exact bytes before decision and publication |
| `RecordedProductEvaluationRunnerV1::qualify_and_persist` | crate-internal unarchived composition helper | never cross-crate product ingress; retained only for owner-local tests and composition beneath the archived entrypoint |
| `freeze_product_evaluation_plan_v1` | production plan freeze | freezes metric roles, estimator mapping and candidate/baseline temporal identities before holdout use |
| `CrossFoldPlanV1::execute_temporal_cross_fit_v1` | bounded statistical source executor | executes every preregistered temporal fold and requires exact lineage and recomputed output-digest equality |
| `SequentialPlan::estimate_cluster_intervals_v1` | fixed-analysis sequential confidence source | adds conservative clustered intervals under a preregistered absolute return envelope; it is not anytime-valid |
| `admit_signed_eligibility_v2` | consumer-bound non-product admission | authenticates one exact evaluation and binds an authority-free result to one concrete consumer use |
| `decide_with_signed_evidence_v2` / `decide_with_signed_longitudinal_evidence_v3` | crate-internal verification primitives | never cross-crate product ingress |
| `ProductEvaluationRunnerV1` | raw compatibility runner | crate-private by default and public only with `trusted-inprocess-eval` |
| `FencedFinalHoldoutOwnerV1` + `FinalHoldoutCasStoreV1` | required contended holdout owner | linearizable CAS, writer fencing and accepted-or-unknown recovery |
| `ReconciledProductQualificationSinkV1` | canonical publication adapter | load-before-write and exact read-after-indeterminate reconciliation |
| `LockedFileProductEvaluationAttemptJournalV1` | concrete attempt journal | complete lifecycle, capacity reservation, unresolved index, checkpoint and tail replay |
| `AnchoredProductEvaluationAttemptJournalV1` | default durable journal capability | acknowledges append only after file sync and independent anchor CAS |

The `trusted_inprocess` compatibility module is absent from default builds.
Production manifests must exclude `trusted-inprocess-eval`, including transitive
feature unification. Compiler-negative fixtures, not comments or lexical scans,
are required to prove the default public boundary. Those fixtures also require
that another crate cannot call the unarchived recorded qualification helper.

## Statistical source contracts

### Temporal cross-fit

`CrossFoldPlanV1::execute_temporal_cross_fit_v1` executes an already frozen
analysis contract. It canonicalizes fold order and requires:

- exact one-to-one coverage of declared folds;
- exact training and held-out principal, episode and window lineage sets;
- no held-out decision identity reused across folds;
- bounded aggregate rows and action cells;
- actual `fit_temporal_fold` model and prediction digests equal to the
  preregistered fold digests.

The executor does not authenticate caller-supplied provenance and does not turn
synthetic fixtures into real future-calendar efficacy evidence.

### Sequential confidence

`SequentialPlan::estimate_cluster_intervals_v1` layers conservative fixed-analysis
cluster intervals over finite-horizon PDIS/DR. The confidence plan, minimum
cluster count and absolute trajectory-return envelope are preregistered. Too few
clusters, an observed estimate outside the envelope, or a declaration below the
plan-level contribution bound is a typed evidence gap. Observed sample maxima,
including observed nuisance predictions or discounts, cannot establish the
range required by the concentration bound.

Let `H` be the frozen horizon, `W` the cumulative importance-weight ceiling and
`T` be one for a separate terminal value and zero otherwise. The validator uses
the global reward/terminal range `[-1, 1]`, prediction range `[-129, 129]` and
discount range `[0, 1]` to bound PDIS by `(H + T) W` and DR by
`129 + 130 H W + 129 (H - 1) W + T W`, plus conservative Q32 rounding error.
Both exact propensity products and the products of numerically rounded ratios
use outward admission bounds. A declared envelope must cover the larger bound;
it may exceed the old unweighted-return ceiling of 129. Nonrepresentable bounds
fail closed. These deliberately conservative intervals require adequate
independent sample size; tightening them needs a preregistered, justified global
model/range contract, rather than an estimate inferred from the same sample.

Cluster labels remain supplied evidence requiring independent provenance. This
surface does not provide anytime-valid confidence sequences, adaptive-stopping
safety, exchangeability proof or causal identification.

### ESS certification from original propensities

Admission certifies effective sample size from the original logged propensity
ratios. Round-to-nearest/ties-to-even weights and receipt ESS remain deterministic
point diagnostics; they cannot certify the preregistered support floor. With
`S = 2^32` and raw evaluation/behavior probabilities `e` and `b`, OPE encloses
each true weight by `L/S <= e/b <= U/S`, with `L = floor(e*S/b)` and
`U = ceil(e*S/b)`. Sequential OPE
starts each trajectory at `L = U = S` and updates every prefix with
`L = floor(L*e/b)` and `U = ceil(U*e/b)`. Support is checked at each depth.

For nonnegative weights, the true ESS lies between
`LB = (sum L)^2 / sum U^2` and `UB = (sum U)^2 / sum L^2`. The finite Q32
certificate admits when `floor(LB*S) >= F` for the frozen raw ESS floor `F`, or
exact positive-weight equality proves `ESS = n` at a floor no greater than `n`.
A finite upper certificate with `floor(UB*S) < F` establishes insufficient support;
a nonuniform interval that remains unresolved returns `OpeError::NumericalSupportGap`
or `SequentialEvidenceGap::NumericalSupportGap`. That outcome establishes
neither insufficient true ESS nor a satisfied floor. Zero `sum U^2` establishes
no support; zero `sum L^2` leaves the upper certificate unresolved. Since true
ESS is at most the row/trajectory count `n`, `UB >= n` need not be represented.
The arithmetic uses checked integers and outward bounds without `f64` or an
unbounded rational-ESS implementation.

A floor above `n` is insufficient support. At a floor exactly equal to `n`,
Cauchy equality permits admission only for identical positive true weights.
OPE proves ratio equality by `u128` cross-products; different probability
encodings of the same ratio remain valid. Sequential equality compares the
original prefix ratio products using two fixed 129-limb `u64` buffers. At
`horizon <= 128`, each side contains at most 256 factors bounded by `2^32`;
the endpoint `2^8192` needs 8,193 bits and fits exactly within 129 limbs. This
fallback proves equality only, rather than arbitrary exact ESS. Existing caps
remain 1,000,000 OPE rows, 4,096 sequential trajectories, 65,536 total steps and
weight/ratio bounds of 50. Near-floor nonuniform data may require a stronger
preregistered arithmetic profile; the current finite certificate fails closed.

## Signed admission and typed recovery

For a successful product qualification, the canonical order is:

1. freeze plan, roles, estimand and measurement semantics before final-holdout
   access;
2. reserve the complete remaining journal lifecycle before admitting a new
   attempt;
3. append and acknowledge `IntentPersisted` before provider manifest lookup or
   final-holdout CAS;
4. consume the exact frozen plan through the authoritative fenced owner;
5. append and acknowledge `HoldoutConsumed` before the provider releases
   observations;
6. compute the bound estimates and append `ComparisonSealed`;
7. build a canonical typed archive from the actual evaluation receipt,
   qualification context, signed evidence and timing evidence;
8. inside `learning.eval`, verify current trust, objective, scope, authority
   epoch, signature lifetime, revocation and required actor/key/credential/
   controller separation; V3 additionally verifies observer and time evidence;
9. persist the verified canonical bytes create-only under the selected-host
   binding, acknowledge `QualificationArtifactsPersisted`, then append
   `QualificationDecided` and `PublicationPending` before invoking the evidence
   writer;
10. append `Published` only after the exact durable publication record is
    observed.

Recovery accepts typed archived inputs, not a caller-created
`SignedEvaluationDecisionV1`. The module rebuilds the exact bundle and re-runs
current V2/V3 verification. A cached, expired, revoked, wrong-scope or
context-substituted decision cannot advance publication.

`admit_signed_eligibility_v2` remains narrower than product qualification: it does
not consume a holdout, publish product evidence or confer selection/activation
rights.

The Agentd measured-outcome consumer must bind the sealed qualification to current
owner state and a signed exact-use payload over run, objective, snapshot,
predecessor context, candidate set, selected candidate, evaluation, execution
and publication identity. Computing a fresh digest for arbitrary request fields
is not sufficient.

### Single-outcome receipt integrity and migration

`ProductQualificationReceiptV1::validate_integrity` binds the complete signed
decision under the evidence preimage domain
`hepta.intelligence-eval.product-qualification.v4`: evaluation, candidate and
baseline IDs, disposition, the length and order of failed metrics, evidence,
trust and authentication digests, and decision authority. It also retains the
execution, publication, objective, dataset, principal, snapshot and claim-scope
bindings. Mutating any public decision field invalidates the receipt. The outer
`hepta.intelligence-eval.product-qualification-receipt.v1` seal domain remains
unchanged; it now seals the v4 evidence digest.

An old domain-v3 in-memory receipt cannot be relabeled as v4. Reverify its real
evaluation or typed archive evidence and issue a fresh receipt; downstream
candidate/use signatures over the old `evidence_digest` must also be reissued.
The typed archive, attempt-journal and publication wire formats are unchanged.
This migration does not rewrite published history or authorize a repeat write.
The immutable multi-outcome receipt retains its existing digest profile.

## Final-holdout ownership

### Single-host compatibility

`DurableFinalHoldoutJournalV1` is valid only when the host supplies an authorized
regular file, an exclusive namespace, independently retained current anchor and
durable containing-directory semantics. A local file lock is not a distributed
lock.

### Contended deployment

A contended deployment must implement `FinalHoldoutCasStoreV1` with linearizable
compare-and-swap semantics. The authoritative record binds scope, owner identity,
positive monotonic fence generation, lease digest, complete replayable history
and state digest. A newer generation takes ownership only through CAS and stale
writers fail on their next transition.

An accepted-or-unknown write returns `Indeterminate`, poisons the live owner and
requires reload and reconciliation. Missing evidence is never interpreted as
permission to consume the holdout again.

`LockedFileFinalHoldoutCasStoreV1` provides a concrete single-filesystem backend
with an OS lock, checksummed append, fsync and an independently retained minimum
anchor. Cross-host deployment additionally requires external evidence that the
actual shared storage provides linearizable lock/CAS/fsync and directory
semantics.

The concrete backend accepts a live CAS transition only when its complete
canonical replay equals the supplied record. Recovery retains one semantic
journal and syncs the recovered file before returning. For `N` plan records,
`F` fence events and `B` file bytes, its current worst-case source cost is
`O(B + N² + F(N + 1))`, with `O(B + N)` memory under fixed backend ceilings.
The v2 registry's full sorted-table digest and snapshot copying still contribute
quadratic cost as plan history grows.

The optional native canonical-journal cache is an optimization capability, not
an unchecked snapshot constructor. Owner recovery still validates the loaded
record and compares its complete snapshot with the cache before restoring the
owner's admission limit. The locked-file backend supplies this cache, making
repeated in-process takeovers `O(N)` each for `N` retained records. Across `N`
new plans and `F` cached takeovers, source work remains `O(N² + F(N + 1))`, apart
from storage synchronization latency. The default `None` cache implementation
continues strict `O(N²)` snapshot replay per recovery; generic stores repeatedly
recovering between plans may still incur cubic total work. Every historical
registry-prefix digest remains strictly verified on that fallback path.
Source profiles with multiple synthetic plans and reopen/compaction checks
establish fixture behavior, not linear scaling, full-capacity service objectives
or target-host latency qualification.

### Verified compaction

`LockedFileFinalHoldoutCasStoreV1::compact_into` writes a new target and replays
retained state through normal CAS. It returns only when final record and anchor
equal the source. The source is never truncated by compaction and remains the
forensic predecessor until the host durably installs the successor and receipt.
Compaction cannot erase prior final-holdout use.

## Attempt lifecycle, capacity and checkpoints

The successful lifecycle is:

```text
IntentPersisted
  -> HoldoutConsumed
  -> ComparisonSealed
  -> QualificationArtifactsPersisted
  -> QualificationDecided
  -> PublicationPending
  -> Published
```

Known pre-consumption rejection may terminate as `RejectedBeforeHoldout`; known
post-consumption evaluation failure may terminate as `Failed`. Exact duplicate
transitions are idempotent. Skipped phases, changed plan/holdout/archive/request,
conflicting terminal states, truncated frames or a concurrent writer fail closed.

### Capacity reservation

Before a new intent is admitted, `AttemptCapacity::project` reserves the
worst-case remaining success phases in both bytes and event count. New work is
rejected when the reservation would cross journal limits. Existing admitted work
retains its completion budget and later admissions cannot consume it.

The ordered unresolved-attempt index is rebuildable from canonical history and
updated with the addressed transition. `pending(after, limit)` is bounded to
1..1024 and traverses unresolved identities rather than all completed history.
The index is never a source of truth.

### Independently anchored checkpoint and tail replay

`LockedFileProductEvaluationAttemptJournalV1::checkpoint_into` writes a canonical
reducer snapshot to a new regular file and binds the snapshot digest, journal
byte frontier, event count and rolling journal state into a checkpoint record.
The checkpoint record digest is retained under a domain-separated binding in an
independent anchor authority.

`recover_with_checkpoint` requires the normal journal anchor, the derived
checkpoint anchor, the checkpoint file and the original append-only journal. It
first streams the original prefix and verifies checksums, the exact byte/event
frontier and rolling journal digest against the authenticated checkpoint. It
then restores reducer state and replays only complete later frames. It rejects
checkpoint substitution, a checkpoint newer than the normal anchor, same-length
divergent prefixes, stale journal restore, conflicting tail or truncation.
The recovered file is synced before any frontier acknowledgement.

Tail-only describes reducer replay. Prefix verification reads and hashes
`O(B_prefix)` source bytes with a bounded frame buffer; total source-journal reads
and hashing remain `O(B)` including the tail. Snapshot loading and restored
reducer state retain their separate bounded memory costs. This contract does
not promise tail-only I/O.

Checkpointing never truncates or replaces the source journal and never lowers the
normal anti-rollback anchor. A same-process fixture or trait implementation is
not proof of independently administered storage.

## Publication and reconciliation

A production `ProductQualificationPublicationStoreV1` must provide exactly-once
semantic publication keyed by execution digest:

1. load before write;
2. accept an existing record only when all request, decision, trust and
   authentication digests match;
3. reject semantic conflict without overwrite;
4. after `Indeterminate`, retain the pending request and load again;
5. report success only after the exact committed record is observed.

`PublicationPending` is a read-reconciliation state. Absence after an unknown or
submitted write is not permission to call the writer again. A recovered
`QualificationDecided` may perform the first write only after loading the exact
typed archive and completing current internal verification.

At the selected-host first-write boundary, the guard compares the SHA-256 digest
of the complete loaded archive bytes and its original `holdout_record_digest`
before checking current clock/trust and re-verifying the exact V2/V3 decision.
One privately prepared canonical byte sequence supplies both the durable
`QualificationArtifactsPersisted` transition and the initial guard identity.
Cold recovery derives that identity from validated anchored history:
`QualificationArtifactsPersisted.terminal_digest` supplies the byte digest and
`ComparisonSealed.holdout_record_digest` supplies the holdout binding. Reloaded
disk bytes cannot choose a replacement expected digest. Archive substitution,
including a changed outer holdout field with an unchanged signed inner payload,
rejects before publication. After Pending, rejection retains the unresolved
attempt for read reconciliation and does not permit another submission.

## Canonical product and consumer chain

The recorded runner freezes estimator mapping, consumes the final holdout,
records consumption, and only then permits observations to enter estimation.
Candidate and baseline intervals are derived from sealed estimator receipts over
the same authenticated cohort; callers cannot replace final `MetricGateV1`
values after observing the holdout.

All cross-crate recorded qualification entrypoints persist and journal-bind the
canonical typed archive before decision. The lower unarchived method remains
crate-internal and cannot be used to skip `QualificationArtifactsPersisted`.
Single- and multi-outcome paths share the typed archive, publication lifecycle,
selected-host store and recovery controller. The internal single-stream carrier
cannot be extracted to masquerade as multiple independently measured outcomes.

Repository consumers recheck current trust and exact use binding. Every result
remains `DENY_ALL`; eligibility is not selection, promotion, activation, effect
or release authority.

## Qualification evidence

Final source qualification requires one immutable candidate and its ordered-
parent synthetic merge to retain passing artifacts for:

- source identity and clean-tree checks;
- default and compatibility API tests, including rejection of the unarchived
  recorded qualification helper from another crate;
- all-target compilation;
- owner and consumer tests;
- typed archive and two-process cold recovery;
- process-kill fault cuts and publication reconciliation;
- lifecycle reservation, unresolved backlog, checkpoint/tail recovery and
  sustained profile;
- temporal cross-fit and sequential-confidence tests;
- strict Clippy, rustfmt and measured line coverage at or above the declared
  threshold.

Queued, pending, skipped, cancelled or infrastructure-invalid jobs are not
passing evidence.

## Target-host and external gates

Repository source and CI cannot self-issue:

- authenticated target-host identity or independent anchor administration;
- real provider/publication topology and persistent supervisor invocation;
- network-filesystem linearizability or deployment durability;
- real future-calendar outcomes and independent measurement provenance;
- retention, change-point, power, subgroup/privacy, unlearning and backup
  non-resurrection evidence;
- independent semantic/operator acceptance;
- selection, canary, promotion, activation or release authority.

`productionImplementation`, `targetHostQualified`, `independentAcceptance`,
activation and release remain false until their separate evidence and authority
gates pass.
