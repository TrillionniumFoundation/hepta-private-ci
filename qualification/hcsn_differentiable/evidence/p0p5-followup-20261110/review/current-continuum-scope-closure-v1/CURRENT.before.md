# HCSN research: current evidence and qualified scope

Updated 2026-11-10. HCSN is a **regenerative probability flow and content memory
network constrained by a shared generator**. Its numerical operators, learned
observation updates and content memory have separate evidence requirements.
The legacy He--Xiong equity kernel already exists and is not being reinvented.

The [P0--P5 evidence index](evidence/p0p5-20261110/README.md) binds each new claim
to exact source, runtime, data, configuration, model, raw execution records and
independent review. Historical source snapshots and failed attempts remain
unchanged. This page supersedes their status summaries, not their evidence.

## Admission status

| Gate | Current evidence | Status |
| --- | --- | --- |
| Mathematical/API contract | Versioned definitions, drift regimes, reset and repeated-readout semantics | Defined and tested |
| Local numerical regression | 92 tests and four unchanged error-budget fixtures on the archived source | Passed within those fixtures |
| Actual training-domain accuracy | Recorded posteriors, physical visits, finite schedules and high-precision derivatives | Selected fixtures pass; full training domain HOLD |
| Fair, sufficiently trained real-task benefit | Full-data development attempts and independent replay; output-interface diagnosis | HOLD |
| Endogenous optimal boundary | Independent finite DP/QVI fixture, three boundary groups | Finite fixture only; neural/continuum benefit HOLD |
| Real asynchronous multimodal benefit | Existing real localization data; new non-diffusion controls | HOLD |
| Repository-wide CI | Exact run identities recorded separately from local science tests | No all-green claim |
| Scaling, energy and production adoption | No measured comparative scientific benefit yet | Gated |

## P0: definitions and a reproducible source chain

The authoritative [model](MODEL.md) and [machine-readable contract](semantic_contract.json)
fix the objects below. The original financial equity, regenerative reference
and differentiable network are related through shared first-passage mathematics,
not by identifying their payoff functions or their boundary problems.

| Symbol | Meaning |
| --- | --- |
| `E` | Original He--Xiong equity under its financial cash flows and default boundary; implemented in `qualification/hcsn/reference.py` |
| `C_T` | Killed single-cycle running value plus survival-terminal reward; absorption payoff is separately declared |
| `U_T`, `U` | Finite/perpetual regenerative value with reset, delay, repeated events and terminal reward paid once |
| `F(T,x)` | First-hit probability for one killed active cycle |
| `G_q(T,x)` | Discounted first-hit mass; `1-G_q` is not survival |
| `M(t)` | Expected cumulative event count, potentially greater than one |
| `J(t)` | Instantaneous regenerative event-rate density `dM/dt`, not the first-hit density after regeneration |

The network's legacy `call`/`interval_value` is an interval reward feature,
not `E` or global `U`. Summing terminal-bearing interval features pays that
terminal feature repeatedly and is not a valid regenerative value calculation.
For the allowed single interval `dt <= refractory`, `risk` and
`expected_events` are the same conditional interval event quantity; they are
not two independent mechanisms. Dividing it by `dt` gives an interval-average
rate, not instantaneous `J`.

A pure readout query does not change state. Calling `forward` again with
`dt=0, observed=True` repeats observation conditioning and content writing.
Padding with `observed=False, valid_mask=False` preserves the physical state,
although the sequence-position counter advances. Zero elapsed time therefore
does not by itself mean a read-only query.

With fixed positive reset distance, negative drift has finite mean cycle
`d+x_r/(-mu)`. Zero drift hits almost surely but has infinite mean cycle time.
Positive drift has a nonzero escape probability and a finite total number of
future events almost surely. The constructor allows crossing zero; this does
not qualify a stationary firing-rate objective or a trainable domain.

The formerly missing localization evidence was restored byte-for-byte from the
original native package. The new integrity checker validates size/SHA256,
ZIP CRC and member safety, and relative Markdown file links. Integrity is
separate from whether a scientific claim is justified. The earlier
[75-test/18-interface-fit record](evidence/localization-v2-20261108/README.md)
and [first math-closure snapshot](evidence/math-closure-20261108/README.md)
remain historical. They earn no new full-training or old S81 completion credit.

## P1: train-visited numerical qualification

[Training-domain tools](TRAINING_DOMAIN.md) capture actual priors/posteriors,
physical parameters, source/model/data/configuration digests, event counts,
valid observations and visited ranges. Truncated or partial traces cannot pass.
The independent reference uses 80-digit arithmetic, continuum basis integrals
and separately evaluated finite renewal continuations. Future observations are
disabled in those continuations: this checks the reconstructed starting law,
not equivalence to an exact continuous observation filter.

The [exact v8 recorder scope audit](evidence/p0p5-20261110/review/v8-recorder-scope-v1/RESULT.json)
establishes a further limit for fresh42. Its 4,096-record and 32-MiB caps retain
a chronological prefix of completed main-training microbatch forwards before
the optimizer step. Even ignoring the byte cap, microbatch size eight permits
at most 32,768 sample-position-layer states: 1.2243% of the 2,676,480 states
visited over the minimum thirty epochs. This is a theoretical upper bound,
not a measured retained count or a random coverage sample. Content state is
not retained, and the per-capture model digest identifies inner-network tensors,
not the complete model/checkpoint file. Final-checkpoint replay must therefore
be reported as supplemental final-model evaluation; it cannot restore missing
optimization-time visits or qualify the whole training trajectory.

The new stable log-first-hit primitive retains finite log F/log G when FP64
probability underflows. Twenty-one sampled cases include near-boundary,
short/long time, low-noise and drift-zero crossings, with first-order derivative
checks. This does not establish relative accuracy of every rare event, FP32,
second derivatives or the entire constructor range.

### Positive results and retained counterexamples

The [P1 summary](evidence/p0p5-20261110/p1/summary.json) and its authenticated
archive bind the following results to their exact configurations.

| Experiment | Measured result | Interpretation |
| --- | --- | --- |
| Endpoint 2, 135 grid/phase/gap combinations | 0/135 pass the original 1% all-basis perpetual-pressure gate | Repeating tiny gaps forever can expose fixed-grid projection error; this is not the actual finite data sequence |
| 128 active cells, endpoint 4.8, selected trained posteriors | Perpetual/short checks pass, but a 32-gap continuation reaches 1.6404% scaled count error | Rejected for that finite-schedule gate |
| 256 active cells, endpoint 4.8, content width 4, two short Adam updates | All 256 recorded A01 posteriors pass; maximum perpetual scaled value error 0.230232% | Scoped to the recorded model and visits |
| Same width-4 candidate, actual 128-gap continuation | Maximum scaled error across value/count/discounted count/active probability 0.702721%; mass residual 6.55e-15 | Selected finite continuation passes the original 1% gate |
| Same candidate, actual A04 burst containing 8e-7 and 1e-7 second gaps | Selected 8/32-gap continuations pass | Does not qualify arbitrarily repeated tiny gaps |
| Trainable mu/sigma/boundary/reset, two 16-event Adam updates on a 32-cell grid | Full discrete-forward AD/FD error at most 7.64e-11; continuum-basis AD/80-digit FD error at most 2.14e-14; value error 3.27336% | Gradient agreement passes; numerical value admission remains HOLD |

The 128-cell and 256-cell candidates were initialized and trained separately;
their learned posteriors differ. Their individual failure/pass results are not
a same-posterior grid-convergence experiment or a causal attribution to grid
size alone.

All reported scaled errors use `abs(error)/max(1,abs(reference))`. For a
reference below one this is an absolute-error scale, not a relative-percent
rare-event guarantee. Quadrature refinement and residual estimates are
measured sensitivities, not certified total error bounds.

The frozen width-4 candidate uses 256 active cells, one returning tail, 16
remaining-time cells, endpoint 4.8, refractory 0.2, tail rate 1, quadrature 32,
initial log standard deviation 0.08; actual physics are mu
-0.11999999999999998, sigma 0.35, log boundary 0, absolute reset
1.3771277643359572 and discount 0.15. These visits do not automatically qualify
a width-16 model, another trained checkpoint, positive drift, or another data law.

A separate [width-16 v6 audit](evidence/p0p5-20261110/p1/width16-v6/INDEX.md)
now binds the actual common-adapter, two-update model. All 512 recorded training
visits pass its perpetual-value checks; the maximum scaled value error is
0.229731%. Another 768 records are supplemental final-checkpoint evaluations,
not additional training visits. Two A04 records at tiny gaps fail the
infinite-repeat pressure gate, with scaled value errors 147.245% and 261.527%.
The total 1,278/1,280 pass count must not obscure those failures.

All five preregistered actual finite schedules pass the unchanged 1% scaled
gate. The 128-gap fixture has reference count 1.807107886; its largest reported
value/count/discounted-count/active-probability scaled error is 0.567008%, and
its mass residual is 5.88e-15. In the short burst, count error 0.104962% on this
scale corresponds to about 1.06% relative to its reference count below 0.1.
The finite pass therefore remains a scaled-error claim. The independent review
binds all five starting laws and gap lists. Neither this probe nor the earlier
width-4 experiment admits the eventual full-training checkpoints.

The first 256-cell job was externally killed with exit 137; its cause is
unknown and it remains incomplete. A separately bound immutable resume
completed the retained checks. The exploratory 135-case report lacked full
source capture; a fresh source-bound reproduction confirms its 0/135 result
and is the basis for the current claim. Neither history is rewritten.

## P2: real-data training and fair comparison

The [executable temporal-core protocol](../../proposals/localization-v3/README.md)
uses all 89,216 ABC training events and all 31,952 D development events in
nonoverlapping 256-event windows. A fresh official-data download and
preparation reproduced the original manifest bytes and all 484 episode hashes.
E is excluded before training preparation interprets its records. Historical
E schema/clock/global-gap exposure is still disclosed in the earlier evidence;
that history prevents claiming an untouched prospective test selection.

For each seed, every arm uses the same actual frozen 25-to-16 frontend and
16-to-11 output head. The roster is GRU, official CfC, official recurrent PLIF,
an analytic event-time LIF reference, official S4D-Lin, causal Transformer and
HCSN. The event-time method differentiates actual analytic crossing times
within a fixed active set; it is not a reproduction of the published EventProp
training system. This CPU FP64 Transformer is not a qualified optimized GPU
baseline. State grids, content dimensions, real-scalar parameter counts,
kernel work, all tuning opportunities and failures must remain visible.

An [operator-level profile](evidence/p0p5-20261110/review/attention-cpu-path-v1.md)
does confirm CPU flash-attention forward/backward and 1,809 one-thread MKL
DGEMM calls on the profiled cloud host for the actual 32-by-256 training shape.
That host's instruction set is not the native Xeon campaign host's identity;
the profile does not establish the latter's exact dispatch path or GPU/energy
efficiency.

### Completed raw-output diagnostic

The original campaign completed **36/36 full-data attempts**: six baselines,
three seeds and two learning rates, with 30--40-epoch bounds. Only **2/36** met
the predeclared combined training-adequacy criterion. Independent review
recomputed every saved-logit metric, checked model/data/update/source identities,
and reproduced one fresh forward per core exactly. All 36 evidence checks
passed. A verified execution is not an adequately trained model.

The frozen random head imposes materially different confidence limits on
bounded core outputs. GRU and default CfC are bounded; PLIF emits binary
spikes. Independent analysis found a strict argmax witness for every class in the
declared output-domain relaxation: there is no algebraic class obstruction
from the head alone. This does not show those recurrent dynamics can reach
every witness. It did find low achievable confidence for some output domains. This motivates a common learnable identity-initialized
linear adapter in every core, charged to its parameter and compute cost.
The added adapter is functionally a trainable linear readout despite the
stored common head remaining frozen. It does not prove that the head explains
every training failure.

A fresh adapter pilot uses the same training-only 256-update memorization
criterion, then resets for one full epoch. Five of six baseline cores pass
that diagnostic. PLIF did not pass the raw-spike 1,024-update extension or the
eight-configuration 256-update grid (seven completed, one timed out). Fresh
membrane and EMA-spike-trace readouts both passed with 1,024 updates. The
spike-trace candidate's first observed passing checkpoint was update 768,
versus 1,024 for membrane;
its final diagnostic accuracy/present-class F1 were 0.9921875/0.9905527.
It uses the declared event-indexed recurrence trace = 0.75*trace + 0.25*spike.
This selects a trainable SNN configuration without lowering the criterion; all
extra diagnostic opportunities are charged. One main epoch is not sufficient
training, and cross-host timing changes are not adapter speedups. Historical
raw-output results remain an interface diagnostic, not a mechanism ranking.
The current runner separates strict best-checkpoint selection from the plateau
stopping threshold; the original run keeps its original checkpoint rule.

### Fresh 42-fit campaign and explicit cap continuation

The [frozen v8 plan](evidence/p0p5-20261110/p2/campaign-v2-plan.json) and
[original native launch receipt](evidence/p0p5-20261110/p2/campaign-v2-native-launch.json)
bind seven cores, seeds 101/211/307, and learning rates .001/.003. Every arm
receives the same learnable 272-parameter adapter, frozen common tensors,
effective batch 32, and training-only diagnostic checked every 64 updates up
to 1,024. Main training has 30--100 epoch bounds, .002 significant-improvement
delta and ten-epoch patience. D macro-F1 .30 is the predeclared resource-to-quality
target; it is a development selection target, not confirmation performance.

The original controller uses nine workers, with six HCSN fits first in its
roster. There is no separate baseline semaphore; baseline concurrency can
grow after HCSN workers finish. Its nominal per-fit wall ceiling is 14,400
seconds, but a 15,000-second campaign deadline shortens later fits' actual
grants. Comparisons must use each outer receipt's actual hard ceiling and
retain censoring, rather than claiming every fit received four hours.

The campaign was dispatched at 14:49:15 UTC. A recovered
[read-only native snapshot](evidence/p0p5-20261110/p2/native-recovery-v2/native-status-query-stdout.json)
at 16:40:46 UTC observed all 36 baseline attempts completed: 26 met the declared
adequacy heuristic, seven reached the epoch cap and three reached a plateau
but failed memorization. A later
[native progress observation](evidence/p0p5-20261110/p2/native-hcsn-progress-1801-v1.json)
read at 18:01 UTC reports all six HCSN diagnostics passed, 36--37 complete
main epochs, and six original jobs still
running. These are
intermediate epoch records; original HCSN terminal results have not yet been
observed and the original jobs were not restarted.

At least one observed baseline reached its 100-epoch cap while still improving.
A separately declared C1 extension restores complete model/configuration,
optimizer, RNG and plateau state, preserves the inherited best checkpoint,
and uses only the original fit's remaining actual wall allowance. It adds no
new seed, learning rate or diagnostic. Its validation costs are recorded;
actual continuation steps, preflight/controller work and extra calendar time
must be reported as a separate phase when it runs.
It is not retrospectively treated as the original 100-epoch protocol.

The [C1 delivery receipt](evidence/p0p5-20261110/p2/continuation-delivery-tests.json)
reports 24 passing implementation tests: the existing 13 core tests and 11
continuation tests. Five cores match split and uninterrupted complete states
on synthetic data. The [native controller's nine tests](evidence/p0p5-20261110/p2/continuation-controller-v3-tests.json)
cover shortened actual limits, launch accounting and failure/timeout cleanup.
The [actual C1 controller report](evidence/p0p5-20261110/p2/native-c1-completed-v1/RESULT.json)
records seven eligible continuations completed between 16:52:59 and 16:56:17
UTC. All seven report the declared adequacy condition, with cumulative epochs
101--235, unchanged source/common weights and no missing terminal record.
The original baseline study plus C1 therefore reports 33/36 adequately trained
configurations. The three memorization failures remain failures. The
[independent baseline/C1 audit](evidence/p0p5-20261110/review/baseline36-c1-native-v1/v2/output/SUMMARY.json)
confirms that count. It rechecks the exact inputs behind all thirty-six
previously audited baseline records and separately verifies all seven C1
chains, including saved configuration/optimizer/RNG states, journals and fresh
full-D logits. The original C1 execution did not save a resume-start snapshot;
the review cannot directly compare an unrecorded state before its first step.
This evidence does not grant full numerical-domain or scientific-benefit credit.

The [initial strict audit](evidence/p0p5-20261110/review/baseline36-c1-native-v1/v1/output/SUMMARY.json)
passed all thirty-six originals but rejected all seven C1 records because two
clock samples differed. Its failed result and costs remain intact. The separate
supplement verifies each original early/late sampling interval and its complete
outer-process bound, then supplies the later time to the unchanged helper.
Quality cutoffs and charged cumulative costs retain their original later
timestamps; no original log is rewritten or timing tolerance enlarged.
The [complete parent/C1 archive](evidence/p0p5-20261110/p2/native-c1-completed-v1/ARCHIVE-RECEIPT.json)
preserves all seven chains in 252 members, including source, checkpoints,
optimizer/RNG states, logits and journals. Its
[draft upload receipt](evidence/p0p5-20261110/p2/native-c1-completed-v1/DRAFT-UPLOAD-RESULT.json)
verifies all 45,425,233 bytes by authenticated readback; this is an archival
result and does not replace the independent chain audit.

The original C1 producer sampled the phase clock twice per epoch record.
A [separate prospective source fix](evidence/p0p5-20261110/publication/continuation-single-clock-pr.json)
uses one sample for both phase and cumulative cost. Its
[regression evidence](evidence/p0p5-20261110/p2/continuation-single-clock-v1/SUMMARY.json)
records the new test failing on the old source and all twelve continuation
tests passing on the changed source. This source was not used by native C1;
the original logs and strict-review failure remain historical evidence.

A [C2 feasibility package](evidence/p0p5-20261110/p2/c2-feasibility-v2/FEASIBILITY.md)
tests complete-epoch recovery and proposes a separately accounted resource
extension. Independent [metadata counterexamples](evidence/p0p5-20261110/review/clock-c2-independent-v1/COUNTEREXAMPLES.json)
identified three guards missing from the retained first version; the second
version rejects any earlier plateau stop, negative clocks and negative AdamW
second moments. Its twenty-one synthetic tests do not establish eligibility
of any native fit. No C2 training or recurring snapshot process has been launched.
Original terminal resource records and consistent checkpoint/best state are
required before deciding whether any further training is justified.

### Independently verified baseline subset

The [six-core table](evidence/p0p5-20261110/review/baseline36-c1-native-v1/v2/output/CORE_TABLE.json)
selects one learning rate per core by mean D macro-F1 across all three seeds.
Each selected roster uses learning rate 0.003 and has three adequate chains.
D remains tuning data; confirmation subject E has not been scored.

| Core | D macro-F1, mean +/- sample SD | Median first observed D F1 >= 0.30, seconds | All six original fits plus C1 process-wall sum, seconds |
| --- | --- | --- | --- |
| GRU | 0.4250 +/- 0.0112 | 55.6 | 784.3 |
| CfC | 0.3490 +/- 0.0161 | 155.5 | 1,701.9 |
| Surrogate-gradient PLIF | 0.1500 +/- 0.0323 | Not all seeds crossed | 1,309.0 |
| Analytic event-time LIF | 0.3130 +/- 0.0419 | Not all seeds crossed | 3,927.0 |
| S4D-Lin | 0.3669 +/- 0.0243 | 48.7 | 817.1 |
| Causal attention | 0.4026 +/- 0.0487 | 66.3 | 1,461.6 |

The cost column charges both learning rates and all seeds, including failed
memorization and C1. It sums overlapping process durations, not campaign
calendar time; historical tuning, diagnostics and independent review are
separately charged in COSTS.json. Threshold times retain the original report
and epoch-clock conventions. This subset is not the final seven-core
comparison and provides no independent-confirmation or energy result.

The [native attention profile](evidence/p0p5-20261110/review/native-attention-path-v1/worker-result.json)
also observes CPU flash SDPA forward/backward on the actual Xeon E5-2673 v3
host, with AVX2, FP64, one Torch thread and one interop thread. The fixed
32-by-256 ABC batch contains 8,134 valid events and uses an explicit causal
mask. Original source and checkpoint bytes remain unchanged. The
[outer receipt](evidence/p0p5-20261110/review/native-attention-path-v1/RESULT.json)
charges the complete instrumented process; this proves the native dispatch
path, not an optimized GPU result, an ordinary training-time measurement or
an identified assembly-level BLAS microkernel.

### Cost accounting

The raw campaign controller wall time was 2,040.85864 seconds; summed attempt
wall time was 5,573.793 seconds and measured child CPU time was 5,564.147 seconds.
These are different, overlapping accounting scopes and must not be added.
Unknown physical energy, VRAM and historical provider charges remain null.

Exact frozen-table caching keys full physical/configuration tensor identity
and exact time-gap bits. It rejects learnable physics, starts cold for each
fit and clears after checkpoint loading. It changes computational reuse, not
the underlying numerical law. Weighted microbatch accumulation keeps the
whole effective-batch denominator and performs one clip/optimizer step.
The current core implementation has thirteen local behavior tests, including
cached and uncached values/gradients, one-ULP gap separation,
full-batch/microbatch Adam equivalence, weighted epoch aggregation and complete
PLIF checkpoint reconstruction. The earlier ten-test source and its receipts
remain historical. These tests do not grant a larger numerical domain.

The cost probe for the 256-cell, width-16 model and common adapter completed
two 256-event Adam updates: cold step 11.8958 seconds, warm step 1.43981 seconds,
27 cached tables using 16,452,072 tensor bytes, and process peak RSS
925,540,352 bytes. It is a two-update cost measurement, not a complete epoch or
a sufficiently trained HCSN result. The
[recovered original cost records](evidence/p0p5-20261110/p2/native-cost-originals-v1/README.md)
now bind the earlier source-v3 batch-32 failure: zero completed updates,
48.838508 seconds inside the profile, 52.017043 seconds for the complete child,
4,383,834,112 bytes peak RSS, and handled exit code 2 after a CPU allocation
failed under an 8 GiB address-space limit. This was the earlier configuration
without the common learned adapter; it is neither an OS-kill claim nor a
measurement of the later v6 configuration. Its full three-attempt controller
and both successful 128-cell probes are charged in the cost ledger.
Complete same-budget quality and resources-to-quality comparisons remain HOLD.

Separate native effective-batch-32 probes measured microbatch four and eight.
Their warm update times were 25.227 and 21.676 seconds, with peak RSS about
2.307 and 3.671 GB; their losses and gradient norms agreed to roundoff.
The [original micro4/micro8 records](evidence/p0p5-20261110/p2/native-cost-originals-v1/RECOVERY_INDEX.json)
have now been recovered and matched to the prior
[derived result view](evidence/p0p5-20261110/p2/hcsn-effective32-derived-summary.json).
Their previous cost row now points to original bytes; recovery does not charge
the two executions a second time.
These two-update probes do not establish a full-epoch speedup across hosts.

Per-epoch process CPU includes imports; the original fit's final CPU field
subtracts a later starting counter. Those scopes cannot be silently summed.
C1 active-process wall excludes gaps between phases and must be distinguished
from full calendar time. The [cost ledger](evidence/p0p5-20261110/COSTS.json)
keeps controller, process, algorithm, tuning, failed-attempt and independent
audit scopes separate, with unknown energy and incomplete totals left unknown.
C1 adds 198.271888 seconds of controller elapsed time and 499.411218 seconds
of measured child CPU, including its native preflight. Summed continuation
child wall is 492.048214 seconds; these overlapping scopes are not added.

## P3 and P4: independent controls

The [finite QVI oracle](../hcsn_qvi/README.md) compares a fixed threshold,
a directly optimized soft threshold and a finite-state DP/QVI policy.
Their fixture values are 6.02067, 6.20332 and 6.28382. The Bellman residual is
8.89e-16, independent DP disagreement 9.48e-10, implicit cost-gradient error
1.40e-11 and infinity-norm condition number 682.46. Active-set changes invalidate
the fixed-policy derivative. Refinement changes the boundary and condition
number. This is a bounded reflecting CTMDP fixture, not a continuum free-boundary
proof or a trained-network task benefit. Its three tests and raw oracle report
are archived separately.

The [non-diffusion controls](../hcsn_memory_controls/PROTOCOL.md) implement
associative overwrite retrieval, delayed copy and pair composition, with
independent clock/symbol random streams and no query-answer leakage. Their
672 generated episodes contain 48,128 events and 5,376 queries. Three semantic
tests pass; zero model-training runs are credited for this suite. A 25-feature
adapter appends four zeros and uses an explicit validity mask; it cannot reuse
the localization channel mask. Real asynchronous multimodal tasks and these
counterfactual controls still require training and independent confirmation.

## CI, reproducibility and P5

The [evidence index](evidence/p0p5-20261110/README.md) lists exact source capsules,
commands, model and data digests, independent audits, failed-attempt receipts,
cost scopes and draft evidence assets. The repository is public; large raw
assets are retained in an unpublished draft release and require appropriate
repository access. Authenticated byte readback, not a successful upload request,
is the archival check. Main has not been merged or modified by this work.

Local science tests, numerical qualifications, training adequacy, scientific
benefit and overall repository CI remain separate. Hosted science run
42827955616 passed its 92 tests, four original numerical fixtures, historical
evidence checks and QVI/control tests. Its source head and tested PR merge
commit have identical tree 0fd8f2f35e190442025005ca17a4662af522a491; the exact
14-file artifact was downloaded and hash/CRC verified. That earlier run does
not qualify the later training/continuation source or current evidence assembly.
At the [17:37 UTC observation](evidence/p0p5-20261110/publication/ci-observation-1737.json),
the observed old and new canaries passed, while required blocking workflows
remained queued and architecture workflows were queued or in progress.
Source-head and tested-tree identities must be read from the actual job,
rather than inferred from a branch name.

The [API publication receipt](evidence/p0p5-20261110/publication/api-source-prs-v1.json)
binds four draft PRs to exact remote heads and complete source trees equal to
their local commits. The recovered
[original native publisher receipt](evidence/p0p5-20261110/publication/native-v8-publisher-reconciliation.json)
shows exit 1 after a 240-second remote-reference timeout before its push step.
That failed attempt is preserved; the independent API publication did not
overwrite its branch or repeat the original job.

FP32/mixed precision, fused kernels, state compression, event-sparse inference,
HCSN-plus-attention pretraining and ordinary production-entry adoption remain
gated on demonstrated real-task benefit. Exact caching above is a measured
training-enablement change; it is not evidence of energy or scaling superiority.
