# V8 preparation: complete V7b stop census and conditional data design

This is a post-run diagnostic preparation package. It changes no V7/V7b source,
trajectory, result, selection, or scientific verdict. No new solver, encoder, or
confirmation-label access has occurred. All previously selected V5/V6 roles are
development data.

## 1. Complete stop census

The exact sealed V7b census contains 864 outputs: 766 complete and 98 stopped.
There are zero actual exceptions. Every stopped slot is retained in
`stop-census.json`, along with the status and original result digest of all 864
slots.

| Policy | Finite nonlinear repair rejected | Tangent QP infeasible | Numerical certificate unresolved | Total stopped |
|---|---:|---:|---:|---:|
| myopic_h1 | 14 | 0 | 4 | 18 |
| loss2_h8 | 25 | 37 | 0 | 62 |
| future_field_h8 | 15 | 0 | 3 | 18 |
| Total | 54 | 37 | 7 | 98 |

All 37 tangent-infeasible cases stop at committed step 24. Of these, 36 are V5
AGNews gated cases and one is a V5 AGNews linear case. These certificates apply
only to the corresponding Loss2 terminal linear predictor, not the real nonlinear
Adam trajectory. All 44 first-round QP failures bypass the existing nonlinear
repair entirely.

All seven unresolved QPs have stationarity exactly zero and complementary
slackness below the fixed 1e-8 bound. Their primal residuals are
1.126795900509292e-10 to 6.601130198014005e-10, above the required 1e-10. Their
phase-I separating lower bounds are negative. These are numerical qualification
failures; they are not certified infeasible nonlinear problems.

The 54 nonlinear failures exhaust a bounded search along one clipped direction:
the old-panel gradient sum weighted by current positive excess. Every failed
prospective step reports parameter-hold outside the original action box. The
best actually tried maximum old-panel excess ranges from
6.023738910343468e-6 to 4.433106165224743e-4. At that best trial, 35 cases violate
one panel and 19 violate two. These counts describe competing inequalities;
gradient-angle conflict was not computed and is not asserted.

In 37 of those 54 rejected blocks, the verifier had found 1–6 safe prospective
steps before failure. The original H8 atomic-commit rule adopts none of that
prefix. This fact must not be changed retrospectively or counted as completed
updates.

### Configuration census

Entries are `repair rejected / tangent infeasible / unresolved`.

| Config | H1 | Loss2 H8 | Field H8 | Total stopped |
|---|---:|---:|---:|---:|
| 00 | 0 / 0 / 2 | 6 / 3 / 0 | 1 / 0 / 1 | 13 |
| 01 | 0 / 0 / 0 | 0 / 3 / 0 | 2 / 0 / 1 | 6 |
| 02 | 0 / 0 / 0 | 6 / 3 / 0 | 3 / 0 / 0 | 12 |
| 03 | 0 / 0 / 0 | 0 / 3 / 0 | 3 / 0 / 0 | 6 |
| 04 | 3 / 0 / 0 | 3 / 3 / 0 | 3 / 0 / 0 | 12 |
| 05 | 0 / 0 / 1 | 1 / 3 / 0 | 1 / 0 / 1 | 7 |
| 06 | 2 / 0 / 1 | 3 / 3 / 0 | 0 / 0 / 0 | 9 |
| 07 | 3 / 0 / 0 | 0 / 4 / 0 | 2 / 0 / 0 | 9 |
| 08 | 3 / 0 / 0 | 3 / 3 / 0 | 0 / 0 / 0 | 9 |
| 09 | 1 / 0 / 0 | 0 / 3 / 0 | 0 / 0 / 0 | 4 |
| 10 | 2 / 0 / 0 | 3 / 3 / 0 | 0 / 0 / 0 | 8 |
| 11 | 0 / 0 / 0 | 0 / 3 / 0 | 0 / 0 / 0 | 3 |

## 2. Existing safe witnesses and their limits

The original 71-origin, four-branch diagnostic is reused only when complete
physical-state digest, configuration, original thresholds, training context,
old-panel identities, action box and horizon agree. There are 51 exact matches.
Fifty have an already executed, actually verified Full/field H8 safety witness:
27 current tangent failures and 23 current repair rejections. One exact match
has no such witness. No mismatched origin is counted as repaired.

Thus actual original-box H8 feasibility is already established at 50/98 stopped
origins. Feasibility remains unknown at 48/98. None is asserted globally
nonlinearly infeasible. A Full risk-planner witness is evidence of existence,
not permission to replace a Loss2 policy with Full or a demonstration that one
shared fallback completes the remaining 32-step trajectory.

## 3. All 98 exact inputs ready for a separately frozen diagnostic

`stop-origins/manifest.json` binds all 98 state directories, original method,
configuration, status, horizon, four original anchors, training/panel hashes,
and original stopped controller plus last attempted plan/repair records. All
2,150 original committed Adam updates were replayed; every receipt and complete
state digest matched, and every exported state reload matched exactly.

The export makes zero new solver calls. Each physical state still satisfies all
four original old-panel thresholds. Original controllers remain stopped and
are not relabelled resumable.

The intended action arrays from the final unsuccessful attempt were not saved
by the historical runner. The terminal controller retains its previous adopted
plan. It must not be used as the failed attempt's intention. If those actions
are needed, deterministic reconstruction by the original planner is a new,
separately charged diagnostic call. Alternatively, a new protocol can prescribe
the same proposal-generation rule for every registered method before executing
any new repair test.

## 4. What a shared feasibility repair must establish

A prospective shared filter can address both documented weaknesses: reject
no method solely because its task predictor's old-loss tangent is infeasible,
and search the joint four-panel feasible region rather than one clipped ray.
Its success is not established by this preparation package.

The diagnostic should freeze the proposal rule, original physical box,
zero-slack anchors, iteration/evaluation budget, ordering, numerical handling,
and failure labels before execution. Every one of the 98 origins must run under
the same rule; all failed and unresolved attempts remain in the result census.
The filter may use complete optimizer state and old-panel derivatives equally
for every method, but it must not silently substitute a Full current-task risk
planner for one baseline.

Acceptance requires actual independent replay of each accepted nonlinear step,
all four old losses at or below their original anchors, action coordinates
inside the original box, and exact full-state/receipt/cursor identity. Solver
success alone is insufficient. Failure of a bounded search remains unresolved
unless an appropriate global certificate exists. Any phase-I slack variable is
an internal objective, not permission to accept positive physical retention
slack.

Passing local origin tests would resolve a local feasibility-search question.
The subsequent complete development run must still include every registered
candidate and comparator trajectory, all 32 real updates, costs for failed
proposals and repair, and independently restored states. Shared access and
attempt budgets must match. All policy outputs and task/head means must be
reported; neither an all-hold controller nor a completed but unhelpful policy
earns scientific acceptance. Fresh confirmation is conditional on meaningful
development utility and a separately frozen protocol.

## 5. Consumed identities and remaining source capacity

The identity check covers 9,216 previously selected, pairwise distinct AGNews /
DBpedia components: 2,304 per task per V5/V6 round. Each task therefore has
4,608 consumed components. V7 and V7b use those same components and introduce
zero new sources. All original training, probe, validation, old-test and
future-test roles are now development-only. Exclude all selected identities,
not only rows used in a particular gradient call.

The earlier complete graph also excluded matching normalized identities from
all 422,935 UCI titles and all 18,846 cleaned 20News messages/subjects. The
normalization and graph identities are pinned in `source-evaluation-design.json`.
Exact duplicate exclusion does not establish absence of semantic paraphrases
or exposure during encoder pretraining.

| Source | Remaining official-test rows per class | Balanced future maximum | Conditional future proposal | Balanced future left |
|---|---|---:|---:|---:|
| AGNews | 1464, 1495, 1355, 1321 | 5284 | 5120 | 164 |
| DBpedia | 4736, 4740, 4743, 4743 | 18944 | 8192 | 10752 |

These are prior source-only graph counts after all V5/V6 exclusions, with both
archive hashes rechecked now. No CSV was parsed or new label read this round.
The unused proposed V7 hash partition supplied old/current capacity counts; a
final V8 salt and class counts must be frozen and rechecked before selection.
The old/current partition is a hash split, not claimed temporal ordering.

If the mechanism warrants confirmation, one feasible conditional design has,
per task, old/current training sets of 4096 each, four 512-row planning panels
per domain, separately sealed 1024-row old/current validation sets, 16384 old
test rows, and the future-test counts above. This is 35,840 AGNews rows and
38,912 DBpedia rows. No such cohort has been selected, encoded or evaluated.

The fixed external acceptance remains the original 12-contrast family:
future upper bound strictly below −0.001, old upper bound at most zero, cost
ratio at most 3, and required 32-step completion for candidate and both primary
comparators across all 12 fits. Three repeated seeds are averaged within each
paired source component before class-stratified component inference; they do
not triple the independent source count.

Using the already disclosed conservative variance estimates and a normal
approximation for planning, 5120/8192 future rows require true improvements
around 0.00567 / 0.00510 for a conservative 80% family-success target. A true
gain of only 0.003 would require roughly 27,904 / 34,458 future rows, beyond
the remaining balanced capacities. These are conditional planning estimates,
not new criteria or guaranteed power. A negative development mean of −0.003
alone is therefore not enough to justify spending the nearly exhausted AGNews
confirmation pool. Larger N cannot repair an effect in the wrong direction.

Implementation must add deterministic chunked prediction above the historical
16,384-row head limit and bounded-memory bootstrap sampling with exact frozen
PCG64 draw ordering. Validation/final labels remain evaluator-owned and sealed
until protocol, code, complete predictions and replay audit are fixed; no
validation-based retuning after that release. The module contracts and required
independent statistical audit are recorded in the JSON design receipt.

## Evidence identities

| Artifact | SHA256 |
|---|---|
| Complete stop census | `f3dbf2d06ca8064634b50a04dc70d5ab78d05c4a81423941324838979ca6d1f3` |
| All 98 exact origin manifest | `929d43714529995317be8aa8b7da4e6e0c57ef07418ea533b9d843bc605eb03c` |
| Source/evaluation design receipt | `46aa9cf86b4ec1dadc1df909789a90441bae2c52cf6a6c51ae702bb79ee7edf9` |
| Original V7b complete seal | `e3ad867157e293e0c80eee6a2985583688e851fee9ff98c68323f6fa83af6131` |
| Original V7b source closure | `1a112e348eeaa06645896f1121c2ceab3f73e36caa967d1abda72bc462c7f110` |

Two focused census tests passed: exact witness identity rejects altered origins,
thresholds and contexts; feasible per-panel values from different failed trials
cannot be combined into a fictitious safe action. The materialization itself
also checked all 98 exact state/receipt prefixes and complete snapshot reloads.
