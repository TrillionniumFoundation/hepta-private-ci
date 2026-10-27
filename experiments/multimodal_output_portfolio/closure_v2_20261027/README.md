# Multimodal NDU closure, second continuation

This continuation implements and tests the six requested research priorities.
It does **not** qualify an all-modal foundation model for production. Several
mechanism defects are repaired, and real feedback, risk and natural-task effects
are demonstrated within their declared tasks. The strict admission tail gate,
direct generator training benefit and retention gates did not pass. Those
results remain failures, with their original thresholds and raw outputs.

Draft review: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4070

## Acceptance ledger

| Requested result | Evidence obtained | Current boundary |
| --- | --- | --- |
| One physical event must not become independent evidence twice | Explicit event identity, deduplication, alias/conflict/cold-restore checks, separate prior and likelihood fits, independently reconstructed tables | Repaired in the bounded evidence engine. Two ranks from one audio encoder remain views of one event. They are not two modalities. |
| Joint target prior and observation likelihood must be separately identifiable | Constructed dependent priors, distinct-file paired observations, new-speaker likelihood evaluation and posterior/payoff checks | Some likelihood scores improve; real held-out posterior and payoff superiority of the joint model is not established. |
| Future backups must describe the actual deployed continuation | Native owner transitions, refusal/admission, expiration, cold recovery, final actions, costs and emitted media independently replayed | Execution semantics align. Semantic tail probability estimation still fails the new strict qualification. |
| Risk preference must be capable of changing a real optimal choice | Fixed actions with different actual success, error and abstention payoffs; 654 decisions change between risk settings | Demonstrated for the frozen finite action law. This is not a proof of global optimality for an unrestricted generator. |
| Numeric feedback must precede a controllable action and affect external reward | Delivered first output, scalar feedback, native state update, hold/cold restore, later keep/swap action and new delivery | Positive causal intervention result. A history policy and linear memory reproduce the same decisions, so no exclusive native-memory advantage is claimed. |
| Generator updates must improve actual outputs under matched information and compute, with retention | Direct output-based Gaussian gradient, equal search grids, three fixed seeds, frozen selection, independent held-out generation and audits | **Failed.** Neither the required risk benefit nor retention qualification passed. No test-set retuning or promotion. |
| Natural tasks must improve actual quality/cost | Real speech transcripts, receipt answers/annotated images and video interpolation frames, all reopened and independently scored | Bounded positive results. Speech synthesis, semantic video generation, entity-independent document generalization and global adaptive-policy superiority remain unproven. |

Detailed evidence and runnable implementations:

- [Joint evidence and deployment selection](evidence/README.md)
- [Native feedback, continuation and strict admission](control/README.md)
- [Direct generator gradient and held-out qualification](joint/README.md)
- [Natural task quality, cost and source audits](natural/README.md)
- [Observed dependency failures and compatibility repairs](ci/dependency-remediation/REMEDIATION.md)

## What the optimization problem means

An encoder can initialize the state of a controlled generation process. It is
not sufficient for that state to contain an embedding alone. The state must also
carry event provenance, remaining resources, partially delivered outputs, neuron
memory, owner/admission status and the version of the deployed continuation.

Let a joint output portfolio have externally scored utility `U`, and let `C_t`
be the actual incremental cost of executing action `a_t`, including rejected
attempts and control work. One concrete risk-sensitive NDU is the entropic
certainty equivalent:

\[
J_\gamma(\pi)=-\frac{1}{\gamma}\log
\mathbb E_\pi\!\left[\exp\{-\gamma(U-\textstyle\sum_t C_t)\}\right].
\]

This is an implemented choice of risk functional, not a definition forced by
the Hepta architecture. Its risk-neutral limit is expected net utility. A joint
terminal utility can account for cross-modal consistency; summing independent
per-modality rewards would omit those interactions.

For this choice, a multiplicative Bellman recursion is natural:

\[
W_T(s)=\mathbb E[e^{-\gamma U}\mid s],\qquad
W_t(s)=\min_{a\in\mathcal A(s)}
\mathbb E[e^{\gamma C_t}W_{t+1}(S_{t+1})\mid s,a],\qquad
V_t(s)=-\gamma^{-1}\log W_t(s).
\]

The law inside the expectation must be the joint law of actual observations,
owner outcomes, refusals, state changes and final outputs. Conditional
factorization is valid only between justified event blocks. Repeated views of
one event do not acquire new probability factors. An evaluation-time oracle is
a comparison arm; it is not an admissible deployed continuation.

The analogy with Merton's problem is therefore useful for sequential allocation
and risk preference. Generated candidates are not automatically self-financing
financial assets, and there is no justified geometric-Brownian or CRRA wealth
assumption here. The current finite-action backup is a tractable experimental
instance of stochastic control, not a solved continuous all-modal HJB problem.

## Joint evidence: proper likelihood is not sufficient for deployment

The new evidence qualification uses 2,400 AudioMNIST WAV files from speakers
21--32 and 115,200 actual UTF-8 qualification deliveries. An independent audit
re-encodes every WAV, reconstructs all five model tables and reopens every
delivery. Files containing the same digit are no longer reused as a hidden
equality indicator in distinct-event pairs.

For same-event top-1/runner-up ranks, the joint conditional model improves
conditional NLL by 0.040322 (95% paired interval: 0.019775 to 0.059334 improvement),
but worsens posterior NLL by 0.037538 and MAP accuracy by 1.875 percentage points
(95% interval: -3.1667 to -0.7500 points). The stronger baseline already respects
the structural exclusion that top-1 and runner-up cannot be the same label.
Distinct-event likelihood comparisons include zero in their intervals.

The deployment selector now checks posterior scoring, MAP behavior, mean utility
and risk certainty equivalent using historical fit/validation data. It rejects
the harmful rank model. That repair prevents promotion by a misleading
likelihood-only score; it does not turn a negative held-out result into a gain.
The newly selected distinct-event model is a historical selection result and
has not acquired a second fresh-test claim.

The task has real risk tradeoffs: correct, wrong and abstain actions deliver
payoffs +0.99, -0.51 and -0.003 respectively. For the strong baseline, changing
gamma from 0 to 2 changes 654 actions; errors fall from 23.25% to 10.625%, while
abstentions rise from 0.0417% to 27.2917%. The gamma-2 CE comparison between joint
and baseline remains inconclusive. A risk-responsive task and a superior learned
joint risk model are separate requirements.

## Native continuation: a real feedback effect, a real tail failure

The original new-source feedback qualification comprises 128 source pairs and
five arms: 640 actual episodes, 32,000 native kernels and 640 cold recoveries.
Numeric feedback raises strict semantic success from 42.96875% in the zero
intervention arm to 53.90625%. The paired difference is +10.9375 percentage points
(97.5% interval: +4.6875 to +17.1875); net utility improves by 0.191424
(97.5% interval: +0.092391 to +0.299510).

Feedback is delivered after an actual first image/text output and before a later
controllable action. It does not provide the private target. The mechanism audit
checks actual native state and durable bytes, not just a surrogate memory.
History and a ten-dimensional linear-memory comparison yield identical actions
and final bytes. They deliberately pay the same native-kernel budget, so this
comparison does not establish an intrinsic native compute advantage. The zero
arm is an intervention on this policy, not a separately optimized blind policy.

The subsequent strict admission qualification freezes a new calibrator and uses
424 ID and 600 declared-OOD pairs from disjoint source pixels and new corruption
and generation RNG namespaces. It executes 1,024 episodes, 51,200 kernels and
1,024 cold recoveries. Independent full replay reproduces execution, costs,
scoring and gate values.

| Frozen gate | Actual new qualification | Decision |
| --- | --- | --- |
| Full ECE <= 0.03 | 0.00834964 | Pass |
| Declared-OOD false admission and one-sided 95% upper <= 0.004999 | 0/600; upper 0.004980443 | Pass within these declared OOD conditions |
| Actual selective ID coverage >= 0.25 | 116/424 = 0.273585 | Pass |
| Additional semantic error / ID <= 0.004999 | 3/424 = 0.00707547; one-sided upper 0.0181846 | **Fail** |

The predicted overall entropic moment is 0.988576; the actual moment is
1.110088. Smaller moments are better. The three wrong commits are independently
confirmed semantic errors, despite correct owner/cold-state behavior and high
public-observer confidence. A low average calibration error does not control
this tail objective.

The selected calibration subset contains only 70 successes out of 70 attempts.
Its Jeffreys point estimate is 0.992958, but its one-sided 95% success lower bound
is about 0.958107, below the approximately 0.984197 required for the gamma-2 commit
decision. In the selected-action moment, an incorrect outcome contributes about
403 times as much as a correct one. The calibration source pixels are disjoint
from head fitting and earlier calibration, but belong to the generator's
historical training pool; this is not fresh-source calibration for the entire
generator stack.

The admission promotion check requires the additional semantic-tail gate. Its
actual denial test leaves live owner status and durable bytes unchanged.
Production authority remains DENY_ALL. There is no new filter designed from the
three qualification errors and no replacement test cohort.

## Direct generator training: valid gradient, negative qualification

The implemented actor has 19,068 trainable parameters and controls 12 bounded
latent means in a frozen generator. It uses actual decoded PNG and UTF-8 outputs
to score antithetic Gaussian perturbations. With output cost `c`, the estimator
is the batch mean of `(c(z+) - c(z-)) * epsilon / (2 sigma)`. This is the
conditional Gaussian-smoothed **moment-cost** gradient before clipping. It is
not an unbiased gradient of a logarithm of a finite sample mean, nor of Adam's
update, and it is not a global-optimality theorem.

Mean and risk objectives receive the same information and search budget: two
sigmas, three fixed seeds, 600 steps per candidate, three checkpoints and the
same validation set. The complete grids execute 7,200 steps and 1,843,200 actual
training deliveries; the development pilot is separately counted. Independent
gradient probes check 4,608 actual bundles. Training output streams are hashed;
individual training images are not all retained. Every qualification output is
retained and independently reopened.

Selection is frozen before the single new test and clean-retention evaluation.
One risk seed selects the original fallback. All 27,648 qualification bundles
(55,296 PNG/text members) are audited; fallback bytes exactly match the original.

| CE difference, averaged over the three fixed seeds | Estimate | Paired 97.5% source-pair interval |
| --- | ---: | --- |
| Risk actor minus original | -0.004180 | [-0.010147, +0.001739] |
| Risk actor minus matched Gaussian-noise control | -0.000444 | [-0.006155, +0.005418] |
| Risk actor minus mean actor | +0.001563 | [-0.006675, +0.009560] |
| Mean actor minus original | -0.005743 | [-0.015163, +0.003651] |

The clean-retention risk-minus-original interval is [-0.033094, +0.019835],
which fails the frozen -0.01 non-inferiority margin. All four study acceptance
flags are false. The intervals describe source-pair variation conditional on
these three seeds, not a seed-population or writer-population guarantee. No
successful joint-training claim follows from the implemented gradient alone.

## Natural outputs: explicit comparison and independence boundaries

**Video.** Eight new DAVIS scenes produce 640 actual interpolation PNGs. A scalar
trained on old data improves PSNR over the same fixed DIS engine at alpha 0.5 by
0.971631 dB (95% scene interval: +0.258125 to +1.693381). Relative to the previous
learned Farneback policy, quality meets the original -0.25 dB non-inferiority
margin and CPU falls by 0.015667 seconds per frame. This is a trained fixed
interpolation policy, not an adaptive-policy or semantic-video-generation claim.

**Speech.** A 50-parameter encoder-only gate, fitted on old sources, chooses
beam 1 or 5 before the first decoder. On 64 utterances from 16 new speakers it
chooses beam 1 on 52 utterances. WER increases by 0.00234375 relative to beam 5
(95% speaker interval: -0.000859 to +0.005797), within the frozen +0.01 margin.
The original five-arm study and timing asymmetry are preserved. A separately
frozen timing correction repeats only the two primary arms, with the same
sources, policies and decoder parameters, for 256 executions. Every output and
encoder hash is identical. Under one common delivery/read-back boundary, CPU
changes by -0.0790695 seconds (95% interval: -0.0995368 to -0.0587180); wall time
changes by -0.0790995 seconds. Including both arms' JSON bookkeeping also retains
the saving. Fixed greedy is cheaper and itself passes the beam-5 quality margin
on this cohort, so adaptive superiority over all fixed policies is unproven.

**Documents.** The first 24-name qualification's quality interval includes zero.
It remains inconclusive. One predeclared fixed-policy replication on 128 unused
normalized merchant-name groups produces 512 answer/image pairs. Quality gains
0.0203961 over strong rules (97.5% interval: +0.0103271 to +0.0316707); the
quality-minus-0.01-times-CPU utility gains 0.0202914. CPU itself increases by
0.010470 seconds, with an interval containing zero. This is a quality benefit,
not a speedup over rules.

A source-only merchant-alias graph then identifies repeated physical stores and
additional conservative corporate/branch overlaps. The 128 names represent 126
audited physical components; six receipts are removed in the most conservative
sensitivity analysis, leaving 122 receipts and 120 components. Its equal-entity
quality difference is +0.0217559 (97.5% interval: +0.0112582 to +0.0344336).
Identified overlap does not explain the measured gain, but this is a post hoc
sensitivity analysis. The original replication is not relabeled as a
preregistered qualification on 128 independent new merchants. Unidentified
aliases and template correlation remain limitations.

## Reproduction and custody

Each study supplies frozen protocols, source identities, executed source
snapshots, selected models, raw decisions/deliveries, independent audit programs
and failure records. Raw archives include exact execution sources because
binding checks intentionally reject a changed decoder, calibration or policy.
Repository formatting must not be mistaken for evidence that a newly edited
runtime was qualified. See the study archive receipts for exact hashes and
the final artifact manifest for durable download identities.

The strict admission allocation is separate from the earlier allocation:
[original allocation](SOURCE_ALLOCATION.json) and
[admission allocation](CONTROL_ADMISSION_SOURCE_ALLOCATION.json). New decisions
are never silently moved into training. The remaining 2,112 unallocated official
test pixels are not spent on additional attempts to rescue these failed gates.

Dependency repair is also an acceptance gate. The saved same-version cargo-deny
diagnostic contains 22 errors. TLS locks were regenerated by actual Cargo and
Bazel commands; additional parser/archive/platform migrations require real
resolved-graph and workspace verification. No advisory ignore, feature removal
or scan-scope reduction is used to turn a failing dependency check green.
