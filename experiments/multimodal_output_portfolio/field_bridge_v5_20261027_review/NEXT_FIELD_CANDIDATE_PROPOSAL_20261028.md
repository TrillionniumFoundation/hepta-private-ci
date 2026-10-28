# One bounded post-V5 development candidate

**Status: NOT_REGISTERED / NOT_EXECUTED.** This is a review draft, not an
execution contract or an efficacy result. No new model, bank, head fit, rollout,
endpoint or holdout was executed for this proposal. Source checkout inspected:
`hepta@5b7bef4e5788f2cea2546f0cb620af471b4fbcf7`.

## Decision and immediate blocker

One candidate merits a bounded mechanism study: **baseline-aligned, guard48,
paired-advantage control with a separate fixed-head calibration partition**.
The useful intervention is new aligned labels and matched dynamics. Merely
renaming the old Q differences as advantages does not create a new predictor.

Do not start this study now. It requires at least **2 GiB of allocatable local
space**, measured using `statvfs.f_bavail * f_frsize`, with sufficient free
inodes, after preserving all prior canonical evidence. Current space is below
that requirement; even read-only process startup encountered ENOSPC. Reserve
space for raw evidence, its archive and a literal restore, with a conservative
500 MiB raw cap and no deletion of incomplete or adverse scientific evidence.
The storage estimate must be checked against the actual serializer before
registration. Exceeding a resource limit aborts the study with partial evidence;
it does not authorize omitting raw outputs or deleting another study.

Historical exact-regression causation is also unresolved. This proposal neither
removes that failure nor grants admission. A separate current-run integrity PASS
must not be represented as a historical or overall qualification PASS.

## Evidence motivating this candidate, and evidence against optimism

V5 executed 72 paths and all 288 adaptive decisions fell back to baseline.
Same-guard field/richer terminal parameter and optimizer identities matched
ordinary; the candidate was REJECTED. Its frozen audit remains FAIL. The
baseline is action 2 for seed 17 and action 3 for seeds 29 and 43, while the old
bank continuation for seed 17 is action 1. Seeds 29/43 were already aligned.

The following are descriptive calculations from the **old fit bank**, not
predictions of the proposed development bank or evidence for a new effect:

| Seed | Old reference | Baseline | Rows with a positive realized contrast /24 | Mean rowwise best contrast | Maximum contrast | V5 shared tau |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 17 | 1 | 2 | 16 | 0.00152215 | 0.00361153 | 0.01948005 |
| 29 | 3 | 3 | 16 | 0.00388592 | 0.01466419 | 0.02710728 |
| 43 | 3 | 3 | 13 | 0.00386579 | 0.01841908 | 0.02463359 |

Old field/richer OOF advantage RMSE is approximately 0.006–0.009. This is large
relative to the available mean contrasts; changing the seed-17 reference alone
cannot solve the predictive problem. The old greedy contrasts are mixed and
often negative. These facts justify testing alignment, not expecting a pass.

For a fixed design matrix and ridge penalty, let `L` be the ridge fitting
operator. Then `L(Y_a - Y_b) = L(Y_a) - L(Y_b)`. The current implementation has
the same response-independent normalization and penalty for all four outputs.
Direct advantage fitting with unchanged rows/features/lambda is therefore the
same predictor, apart from numerical arithmetic. Its structural baseline-zero
anchor is useful bookkeeping; it is not an empirical improvement by itself.

## Single proposed algorithm

Keep the three original frozen models, eight rank-eight adapters, SGD settings,
four multiplier actions `[0, .25, 1, 2]`, 288 scheduled microsteps and six
48-step decisions. Use **guard48 only**, unchanged from the V3 learning kernel:
compare with the immutable original guard baseline, restore the complete
transaction state on rejection, advance the clock and charge rejected work.
Zero action still executes and charges gradients/guard without optimizer advance.

Fix `b(17)=2`, `b(29)=b(43)=3`; do not reselect ordinary. Use only the already
exposed `development_gradient`, `development_rehearsal`, `development_probe`
and `development_guard` roles to generate the bank. The task/clean development
roles remain endpoint-only in this new execution, although they are already
exposed historically and cannot become independent confirmation again.

For each seed and each schedule 6000–6003, run two predetermined prefix paths:
the constant baseline and the corresponding old balanced exploration path.
At each of their six decision states, fork all four candidate actions. Each
branch executes its first guard48 transaction, then the same baseline `b` for
all remaining transactions through step 288. Use paired data/noise tapes,
identical context/guard identities and the same reward-observer probe panel.

Define the stored label `A(s,a;omega) = G_b(s,a;omega) - G_b(s,b;omega)`.
Store all four raw branch outcomes and their pairing; baseline advantage is
structurally zero. A branch label is a **realized reference-tail contrast**,
not an exact expected Q and not a prediction of the replanned deployed policy.
Clock, optimizer, guard and remaining-budget semantics are part of this target.

This produces 48 designed rows per seed. Fix schedules 6000–6002 (36 rows) for
fitting and schedule 6003 (12 rows) for calibration. Both prefix types for one
schedule stay together. Record duplicate state identities; these rows are not
independent samples. Never refit on calibration rows after setting the gate.

Fit one field12 and one richer30 linear head per seed, using the existing
feature definitions and fit-partition-only normalization. Fix ridge **1.0**,
without a grid or subsequent feature/ridge selection. Fit the three nonbaseline
advantages and set the baseline output to zero. Use the same raw development
features for fitting and deployment; no old fit-to-development origin correction
is needed. Record the complete transformation and numerical convention.

For each seed and head separately, fix the empirical one-sided rule
`tau = max(0, max_calibration,a!=b [predicted_advantage - realized_advantage])`.
Select a unique predicted best nonbaseline action only when its predicted
advantage is strictly greater than tau; otherwise choose `b`. Ties keep `b`.
The two representations use the same calibration procedure/data, not an
outcome-selected common threshold. No quantile search, hand-set multiplier,
threshold grid, temperature or threshold relaxation is allowed.

The one-sided form follows the actual decision question: if the overprediction
error were bounded by tau at **every deployed state/action**, this gate would
ensure nonnegative reference advantage and the finite-horizon policy-improvement
argument would apply. A maximum on 12 dependent calibration rows does **not**
establish that bound on new occupancies. `certificate=false` remains mandatory.

## Required state and evidence

The available V3 checkpoint format stores parameters and optimizer but does not
persist incoming gradients or RNG. Old BANK state hashes cannot reconstruct a
full branch point. Generate new states; use a new schema holding parameters,
optimizer, incoming gradients, RNG, clock, schedule identity, immutable guard
baseline, context/input identities and remaining budget. Test literal round-trip
restoration and branch-order invariance before scientific execution.

Persist every parent and branch-terminal checkpoint, raw terminal probe output,
four-way branch commitment, actual chosen prefix replay, transaction trace,
cost receipt and failure. Verify parent immutability, action/baseline pairing,
selected-prefix replay and unchanged frozen base. Record whether each candidate
actually changes post-guard state relative to the baseline; action intent alone
is not effective action coverage. No free action-zero or rejected computation.

## Closed-loop evaluation and stopping rules

After one bank, one fit and one calibration, freeze both heads and all taus.
Run ordinary, field and richer on the four fixed schedules and three seeds:
**36 complete paths**. All paths must seal before new task/clean endpoint
evaluation under both frozen observers. Measure all features actually computed;
the existing common30 measurement does not make field12 a cheap observer.
Ordinary skips unused feature instrumentation. No online refitting, extra
counterfactual shadow rollouts or iterative dataset aggregation is in scope.

Report per seed/schedule: attempted and accepted nonbaseline choices, distinct
post-guard states, first divergence, fallback/tie rates, predicted margins,
calibration errors, retained/rejected microsteps, task/clean outcomes and full
gradient/feature/teacher/observer/checkpoint CPU/wall cost. Report reward and
compute separately; no unmotivated utility-per-second conversion is invented.

Keep the old numerical benchmark margins unchanged as a **development screen**:
pooled field-over-ordinary strictly greater than .001; pooled field-over-richer
strictly positive; each-seed corresponding differences nonnegative; frozen
task gain nonnegative per seed and at least .005 pooled; clean delta at least
-.01 per seed; both observers required. These are not fresh confidence tests,
and a favorable screen does not close the original B03–B07/B09 criteria.

Stop immediately on source/role/state/trace integrity failure or resource cap.
After sealed rollouts, zero field overrides plus matching baseline terminal
identities is an inactive-candidate rejection; do not lower tau to create
activity. A nonzero override count is only a mechanism check, not efficacy.
Complete the prespecified comparisons if the candidate is active; no optional
extension, seed dropping, best checkpoint selection or favorable subgroup claim.
One study ends with rejected / favorable-development-only / execution-incomplete.
None of these outcomes opens a new holdout automatically.

## Exact work ceiling and preservation

Bank: `3 seeds * 4 schedules * 2 prefixes * (4 * 21 tail blocks + 6 prefix blocks)
* 48 = 103,680` scheduled gradient microsteps; 144 state measurements and 576
branch terminal labels. No branch-cache savings are assumed. Evaluation adds
`36 * 288 = 10,368` scheduled microsteps and 144 adaptive state measurements.
Total **114,048** scheduled microsteps, plus separately charged feature backward
work and scoring. Six head fits; no CV/grid fits. Planned maximum elapsed worker
time: **3 hours**, with a **6 CPU-hour** ceiling; preserve incomplete evidence
and stop on exhaustion. Old bank receipts were approximately 927–968 seconds
per seed for half this bank size, so roughly 110–140 minutes is a planning
estimate, not a runtime guarantee. Endpoint/verification costs remain explicit.

Preserve V5 REJECTED, its original FAIL, all thresholds and all old source bytes.
Raw persistence remains subject to the existing specific authorization boundary;
this draft authorizes no upload and does not use a new filename to avoid it.
Inputs already exist locally; storage and historical integrity investigations
remain prerequisites to deciding whether to register this candidate.

Sources inspected: V3 `training_bank.py`, `training_policy.py`, `learning.py`,
`training_features.py`, `source_roles.py`, its three saved BANK/CONTROLLERS and
COMPLETE records; V5 `PROTOCOL.json`, `CALIBRATION.json`, `EXECUTION_REVIEW.md`,
`V5_NUMERIC_DIAGNOSIS` and the original `v5_run` path/phase resource receipts.
