# Matched counterfactuals at actual visited deployment parents

This is a **new prospective experiment design and executable synthetic kernel**.
It supplements the original study without changing recovery07, its source
freezes, scientific trajectories, endpoints, thresholds or conclusions. No real
scientific payload was decoded to choose this design. This directory has no
scientific execution CLI or native model adapter, and it does not grant artifact
admission. Its current tests establish software behavior on synthetic states.

The immediate objective is concrete: determine what the deployed field's chosen
action actually does relative to all other registered actions **at the same
visited parent**, with the same guard, future tape and baseline continuation.
The original deployment trace records only its selected action; a development
calibration bank cannot supply these missing counterfactuals.

## 1. Three different questions

| Question | Experiment that answers it | What that evidence does not establish |
|---|---|---|
| At an actual visited parent and its original future tape, was the chosen action better than the baseline action? | Extension I below: four complete matched realized tails, both observers, fixed panels | A conditional expectation over fresh future tapes, a confidence certificate, or the value of the complete deployed policy |
| At those fixed physical parent states, what is the average advantage under a newly declared future randomness law? | Separately registered Extension II: a fixed sixteen CRN replications per parent | Expected advantage under a new deployment occupancy distribution, new task generalization or LLM scale |
| Does the controller improve a deployed system on new trajectories, tasks or large language models at a justified cost? | A separate full-trajectory, source-disjoint transfer study with independent registration | This cannot be inferred by counting the 384 reused parent states or their simulated branches as independent new models |

Extension I deliberately closes the first missing quantity. An explicit
conditional-tail experiment and a genuine deployment study provide the next
steps; changing the label on the first result cannot supply the others.

## 2. Fixed population and estimands

Every target is fixed before inspecting outcomes. B includes all original
`field12` deployments: seeds 17, 29 and 43, schedules 106000 through 106015,
and all six decision boundaries. C includes both architectures, all evaluation
seeds 801 through 808, schedule 8000, the `field` policy and all six boundaries.
No selection is made using overrides, acceptance, activity, predictions, norms,
cost, endpoint quality or the eventual sign of an effect.

| Stage | Target paths | Visited parents | Four-action tails | Additional fixed audit tails |
|---|---:|---:|---:|---:|
| B | 48 | 288 | 1,152 | 288 |
| C | 16 | 96 | 384 | 96 |
| Total | 64 | 384 | 1,536 | 384 |

The original full-study admission still requires all 240 B paths, all 32 C
paths, the fourteen jobs, thirty finalizer seals and the complete artifact
chain. Selecting field paths as the new target population does not waive those
original completeness requirements. It is an explicitly declared question about
the field controller, not an outcome-dependent omission of controls.

Let `s` be one exact complete visited parent, `a` one of the original four
actions, `b` its original baseline action, and `omega_original` its original
remaining tape. Each arm applies `a` for one full guarded block and then applies
`b` at every remaining clock. For observer `o` and fixed scoring role `r`, define

\[
Q^{b,\omega_{\rm original}}_{o,r}(s,a)
= \text{mean fixed-panel score of the resulting terminal state},
\]

\[
A_{o,r}(s,a)=Q_{o,r}(s,a)-Q_{o,r}(s,b),\qquad
G_{o,r}(s)=\max_{a\in\{0,1,2,3\}}A_{o,r}(s,a).
\]

The deployed action is locked as `a_hat` before generating any new branch.
Report its advantage `A(s,a_hat)`, the attainable finite-action gain `G(s)`,
and finite-panel regret `G(s)-A(s,a_hat)`. The baseline arm guarantees
`G(s) >= 0`; a negative chosen advantage is retained. The maximum is an exact
enumeration over four realized fixed-panel values. It is not a population
oracle, an unbiased maximum over noisy unobserved expected values, or a claim
that the chosen action is globally optimal.

This is a one-action intervention followed by a **baseline** tail. It is not
the value of following the field controller at every subsequent decision. The
original B/C whole-policy endpoint contrasts remain the evidence for that
different question and are not replaced, reweighted or recertified here.

## 3. Exact visited-parent reconstruction

The original B and C deployments do not archive a literal tensor checkpoint at
every visited decision. Pretending those files already exist would hide the
main implementation requirement.

For B, a registered adapter must reconstruct the original public generator,
local adapter initialization, context, source-freeze binding and frozen head,
then replay the original field trajectory in order. At each decision it must
compare the complete parent packet with the original trace's `before` hash,
recompute the unchanged original feature/head decision, and match the original
choice and semantic transaction fields. After the actual selected transition,
it must append exactly the original controller history and match the next
recorded parent packet, or the sealed terminal checkpoint at the last decision.
Physical dynamics comparisons use the original `dynamics_identity`, which
separates controller history and excludes only `path_kind` from its cursor.

For C, the starting point is the actual sealed evaluation warmstart for that
architecture and seed. Loading a new random initialization or rerunning warmup
and assuming equivalence is insufficient. The adapter restores the original
model, optimizer, gradients, RNG and modes; reconstructs the context and
immutable teacher; verifies the context identity and original head; and matches
every recorded full-state hash and semantic transition. Its compressed trace
must be joined to `COMPLETE.inventory` by the original checkpoint identity,
with shared fields checked before the two divergence-summary fields are added.

The feature/head output, original head artifact, original trace descriptor,
exact parent identity and expected selected successor are written to a choice
lock before the first new counterfactual. Head refitting, a new gate, altered
action multipliers, changed guards, clipping or a convenient fallback are not
permitted during reconstruction. Any mismatch makes the new experiment
incomplete; it never authorizes an approximately matching parent.

For every matched arm:

1. Read and literally restore the sealed parent, verifying all complete-state
   and immutable-context identities before work.
2. Run the unchanged original guarded transaction for the specified first
   action, including its actual gradient work and guard scoring.
3. Advance the logical clock even after rejection. Rejection restores the
   original entry training state; it does not refund work or time.
4. Follow the original baseline action on the exact registered remaining tape
   through the original horizon, retaining every guard and rollback receipt.
5. Seal and independently read back the literal first successor and terminal
   checkpoint before any new terminal-label scoring.

All four actions execute in order `0,1,2,3`. A further independent reconstruction
of action `canonical_parent_ordinal % 4` repeats the complete tail and must
match its semantic transitions and state identities exactly. This audit action
is fixed independently of predictions and outcomes. Finally, the original
chosen transition is replayed from the parent and advances the real original
trajectory, with its original history update. Counterfactual labels are never
fed back to that continuation.

The runtime adapter should compose the original `StudyAdapter.transition` and
`Context.block` kernels. It must **not** call the original complete bank builders
or `architecture_bank.tail` as convenient wrappers: those helpers also score
terminal labels and would cross this new experiment's global scoring barrier.

## 4. Guards, state activity and equality controls

The guard compares a candidate to the original fixed reference panel. Its
`guard_delta` is not the matched baseline-tail advantage. Each candidate sees
the same reference; the reference is not updated using its sibling arms.

A rejected chosen action can still differ from the baseline arm, because the
baseline may make an accepted update. Therefore rejection alone does not imply
zero advantage. Conversely, an accepted override can be physically ineffective.
If the first committed physical state equals the first baseline-arm state at
the same clock and tape, the deterministic baseline tails must agree. If their
terminal states agree, their emitted outputs and scores must also agree on
every paired panel. The kernel rejects contradictions instead of interpreting
them as a controller benefit.

Archive both native transaction identities and complete-state identities. B's
native parameter/SGD hashes differ from its codec component recipe; comparisons
stay within a recipe. C's named-parameter inventory excludes buffers. Report
candidate changes, committed changes, first-successor component differences,
complete physical differences and controller-history differences separately.
The full parent and first-successor tensors make C component resolution
available in this new experiment; the original deployment traces are not
retroactively claimed to have recorded it.

## 5. Terminal scoring and empirical calibration

All 64 path shards must finish the complete trajectory population and publish
their immutable artifacts before any new terminal scoring begins. The new
endpoint-access freeze binds the full set of 384 parents, 1,536 first successors
and 1,536 terminal checkpoints, the original source allocation, both frozen
observers, new scorer sources and the complete immutable provider inventory.
Its provenance is this extension, not a fictitious amendment of the old gate.

| Stage | Probe | Task | Clean | Rows per candidate: probe / task / clean |
|---|---|---|---|---:|
| B | `development_probe` | `qualification_task` | `qualification_clean` | 512 / 2,048 / 812 |
| C | `fit_probe` | `final_task` | `final_clean` | 512 / 3,952 / 988 |

Both observers score every candidate. Source-pair identities, condition order,
noise seeds, emissions and all utility definitions remain those of the pinned
original scorer. Retain uint8 images, UTF-8 captions, output hashes, the paired
source/condition keys and both observers' values, together with literal artifact
bytes/SHA and readback evidence. Re-score the three frozen B generators and
sixteen C warmstarts on task and clean panels as explicitly costed references.
There are 4,646 candidate/reference score artifacts in this design.

For the frozen head, use **reward-probe** advantage for the aligned prediction
diagnostic, because that is the quantity its training targets represented.
For every nonbaseline action report prediction minus realized advantage,
squared error and exceedance of the original frozen threshold. Report the same
quantity for the locked selected action. No threshold, coefficient, norm cutoff
or action is chosen using these new labels. Nonfinite scores or a reproduction
mismatch fail reconstruction; they are not silently repaired.

These observations can reveal empirical overprediction at deployed parents.
They cannot turn the original dependent calibration maximum into a probability
bound. The probe remains a reused training-context panel, and the deployment
parents share heads, seeds and trajectory history. The audit observer is a
different frozen observer, not a fresh independent task sample. Task and clean
effects are reported alongside the probe diagnostic, including the chosen
candidate's clean score relative to its original frozen generator or own
warmstart. No new confidence interval, significance cutoff or efficacy gate is
introduced in Extension I.

All per-parent results are retained. Summaries first average the six decisions
within each complete path and then equal-weight the fixed paths within each
original seed. C architectures stay separate and paired by seed. Because the
grid has exactly six decisions per path and all sixteen B schedules, the pure
kernel's equal-parent mean within seed is algebraically the same weighting.
It never treats 384 parents or 1,536 arms as 384 or 1,536 new independent models.

### Frozen full-state and history predictors on the same B field occupancy

The original B `bank.measure` already produces the 12-coordinate field,
54,740-coordinate current-state feature and 114-coordinate history feature at
each field visited parent. The original A artifacts contain all three frozen
heads. Before any new counterfactual is computed, the native adapter must score
all three with the unchanged original `choose`, each head's own calibration
threshold and the original baseline action. Persist all three head descriptors,
predictions, chosen actions, fallback and outside-fit-norm diagnostics in the
same choice lock. The field predictor must exactly match the actual deployed
choice; the two shadow choices never advance the original trajectory.

Reuse the same four realized `Q` values to report each fixed predictor's chosen
gain and regret, under both observers and every scoring role. Report
`full_current_state minus field12` and `history6 minus field12` chosen-gain
increments, retaining negatives and zeros. This adds 576 head evaluations over
the 288 B parents and zero counterfactual gradient steps. The original field
evaluation is reused; its expensive feature probes are fully charged. No head,
feature scale, gate or action is fitted or chosen using the new values.

This comparison has a precise population: the original field controller's
visited parents. It does not estimate the history or full-state controllers'
own closed-loop state distributions. C has only its original field head, so no
C full-state or history comparator is invented. A better frozen predictor on
these states would diagnose an estimator-specific shortfall; it would not prove
an information-theoretic lower bound or an information oracle. All three can
fail, and a worse full-state head does not prove the field contains all useful
information. The original W reflection's reachability limitation remains.

An irreducible H12-information claim would need a separately declared
estimator-class comparison with grouped train/calibration/test splits and
independent label budgets. Selecting a new estimator on these diagnostic
results and reporting its fit to the same labels would not answer that question.

## 6. Complete new-work cost and bounded execution

| Stage | Original-path replay | Four-action tails | Fixed audit tails | Total scheduled microsteps |
|---|---:|---:|---:|---:|
| B | 13,824 | 193,536 | 48,384 | 255,744 |
| C | 1,536 | 21,504 | 5,376 | 28,416 |
| Total | 15,360 | 215,040 | 53,760 | 284,160 |

These are physical scheduled gradient steps, including zero actions and rejected
blocks. They do not include the separately recorded feature-direction probes,
teacher/observer forwards, state captures, serializations, restore/readback,
endpoint scoring, download or archival work. Those costs must be measured, not
estimated from this table.

The first new-task operation must start a source-pinned real wait4 owner already
available in a pinned engineering image. It owns preparation children before
scientific execution: provider metadata/download, source verification, runtime
installation if needed, input downloads, runtime/resource checks, every replay,
branch, score, report and transfer. The scientific child still uses the exact
qualified original runtime. A new task does not inherit a previous unmeasured
setup phase and call its cost zero.

Record inclusive child CPU, parent self CPU, elapsed wall, peak RSS and physical
work, with nested intervals for preparation, replay, all guarded tails, audit,
actual continuation, endpoint scoring and delivery. Inclusive parent intervals
already contain descendants; do not add their CPU again. Sum work/CPU only
across proven disjoint shards, and distinguish the sum of shard wall times from
overall elapsed time when jobs overlap. Charge unsuccessful commands, rejected
updates, failed shards and every permitted retry. A retry requires its own
identity and retained failed costs; it cannot select a favorable outcome.

Provider image pull or boot may precede this in-container owner. Publish actual
provider step wall where available and explicitly retain unavailable CPU as
unknown. A whole-system cost or adoption claim remains unavailable if any setup,
launcher, final-delivery or historical interval is unknown. Newly recovered or
measured work never cancels missing old costs.

The uncompressed **pixel arrays alone** total 9,511,067,776 bytes, before captions,
score arrays, state checkpoints or metadata. The original 1 GiB RAW limit is not
a suitable storage contract for this additional study. Use 64 prespecified path
shards, immutable archives and independent byte readback. This design allows at
most two science shards concurrently with an 8 GiB cgroup and original numerical
thread settings. Exact disk and time ceilings must be externally registered
after outcome-free resource qualification. Failure to fit a ceiling fails the
complete extension; it does not permit dropping a parent, arm, emission or
reference. Provider job limits remain additional hard bounds.

Final publication closes measurements in stages: a receipt cannot attest that
its own future serialization or upload was already inside an earlier archive.
Retain the final outer wait4 and delivery closure in a later artifact, with any
unmeasured final wrapper tail made explicit.

## 7. Separate conditional-expectation extension

Extension I uses a complete original state that includes the future replay tape
and RNG. Under deterministic kernels, its conditional realized value is fixed.
An expectation over *new* future randomness is a different experiment and a
different conditioning statement.

Extension II would retain the same verified physical parameters, optimizer,
incoming gradients, controller history, fixed panels and clock, while drawing
new exogenous future tapes from a separately registered law. It must not claim
that the full original state is unchanged: its future tape/RNG has changed.
The new state contract must reproduce the original-tape special case exactly
without weakening or monkeypatching the original scientific validators.

Fix sixteen replications per parent in advance. Derive random streams from a
new fixed study salt, stage, original seed, schedule, decision, replication
index, future step and channel. Exclude action from that derivation, and exclude
C architecture so both architectures use the same replica labels. Each of the
four actions gets the same future random numbers within a replication. No
additional replication is requested after inspecting a sign or interval.

This gives 24,576 primary tails and 6,144 predetermined audit tails: 3,440,640
primary and 860,160 audit microsteps, plus any explicitly required parent
reconstruction. Parent reconstruction costs zero *new gradient steps* only if
the literal Extension-I parent checkpoints pass a real input gate; download,
readback and restore still cost work. These counts are not bundled invisibly
into Extension I.

Its estimand is the expectation over that declared future-tape law at the fixed
original visited-parent population. It is still not a new policy's occupancy
distribution. Conditional Monte Carlo uncertainty and any trajectory-level
sampling statement must be separately specified before execution. Keep all six
decisions inside their original trajectory block, B models fixed with schedules
clustered within seed, and C architectures paired within seed. Replication
indices remain paired across arms and architectures. A bootstrap over 6,144
independent-looking parent/replica rows would give the wrong unit of inference.
No confidence procedure or certificate for Extension II is implemented here;
its native tape adapter and inferential protocol require a separate freeze.

For deployment occupancy, run a fresh full-trajectory experiment with a fixed
number of new seeds, immutable trained heads, the same all-action shadow audit
at every visited decision and a prospective cost plan. For new tasks, use a
source-disjoint dataset: the original source registry has zero unallocated
eligible MNIST sources. For LLM claims, register an actual autoregressive LLM,
its parameter or adapter intervention, language-task and retention populations,
and real compute comparison. Small multimodal parent replays cannot establish
that transfer, regardless of how many tails are simulated.

## 8. Executable candidate and completion path

`counterfactual.py` implements the fixed grid and work counts, original finite
head decision check, matched four-action sequencing, exact restored-parent and
tail checks, fixed independent audit, selected-successor reconstruction check,
paired finite-panel contrasts, calibration residuals and complete-grid summary.
The backend interface deliberately has no endpoint scorer. The reducer accepts
already verified score summaries and explicitly does not perform admission.

Run the synthetic validation from this checkout:

```sh
python -B -m unittest supplements.parameter_field_visited_counterfactual_20261031.test_counterfactual -v
```

The fixtures cover B and C, early and terminal decisions, paid rejected/zero
work, a rejected action differing from the baseline, changed tapes, wrong parent
or successor hashes, changed choices, failed independent audit, missing work,
contrast signs, fixed shadow-head gates and gain increments, equal-state output
contradictions, unpaired panels, nonfinite scores and all 384 rows with
duplicate/missing-population rejection. They are
not a numerical runtime or model qualification.

The concrete next implementation steps are: freeze the actual original run
binding; implement and qualify the source-pinned native reconstruction/receipt
adapter and real preparation-to-delivery owner; bind resource ceilings and all
64 shard identities; run the full trajectory stage; close its global immutable
checkpoint barrier; score the full fixed candidate/reference grid; then run the
admitted reducer and deliver the actual complete cost/interpretation package.
The original study's negative, inconclusive, integrity and cost dispositions
remain visible throughout. Real execution results must be published separately
from this prospective plan.

## Primary implementation references

All scientific references below are fixed to the original C2 commit rather than
a moving branch:

- [B deployment paths and terminal-only state persistence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bc4e757f5c90f6365f383c1127be710d2ded874a/experiments/parameter_field_fullstudy_20261029/run.py)
- [B complete branch state, restore and physical/history identities](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bc4e757f5c90f6365f383c1127be710d2ded874a/experiments/parameter_field_fullstudy_20261029/branching.py)
- [Original head fit, empirical calibration maximum and deployed choice rule](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bc4e757f5c90f6365f383c1127be710d2ded874a/experiments/parameter_field_fullstudy_20261029/heads.py)
- [C warmstarts, deployment traces and original complete inventory](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bc4e757f5c90f6365f383c1127be710d2ded874a/experiments/parameter_field_fullstudy_20261029/architecture_run.py)
- [C guarded transitions, tape and physical work semantics](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bc4e757f5c90f6365f383c1127be710d2ded874a/experiments/parameter_field_fullstudy_20261029/architecture_kernel.py)
- [Original source allocation and access barriers](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bc4e757f5c90f6365f383c1127be710d2ded874a/experiments/parameter_field_fullstudy_20261029/sources.py)
- [Original B/C endpoint estimands and statistical gates](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bc4e757f5c90f6365f383c1127be710d2ded874a/experiments/parameter_field_fullstudy_20261029/analysis.py)

`PROSPECTIVE_PLAN.json` also records exact bytes/SHA256 for every directly cited
kernel, protocol, source loader and scorer. Before scientific use, the complete
transitive original closure and the whole new adapter/workflow closure must be
externally bound, not just this reference subset.
