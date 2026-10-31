# Round-two feedback and runtime contract

This extension preserves the first round's source and evidence. It tests a new
heteroscedastic feedback task and a count-carrying event receiver. No outcome is
prespecified to favor the analytic representation. The direct conditional
Gaussian and independently conditioned probit are strong same-information controls.

## Public information, hidden target and improvement event

For each episode, the initial draft is \(A\sim N(0,1)\), hidden error is
\(E\sim N(0,0.8^2)\), and private target is \(Y=A+E\). Public sensor variance
\(s^2\) is independently drawn from \(\{0.04,0.36,1.44\}\). The noisy
self-evaluation is \(S=Y+\sqrt{s^2}Z\), with independent standard Gaussian \(Z\).
Public repair cost \(c\) is independently drawn from \(\{0.03,0.12,0.48\}\).

Draft, self-evaluation, sensor variance and cost cross actual file readbacks.
The acquired residual \(R=S-A\) is delivered as lossless numeric text and PNG
and reopened before native ticks or choice. Target \(Y\) is unavailable to the
policy. It enters supervised training labels and postdecision scoring only.

The training-only Gaussian MLE estimates error variance and sensor-noise scale:

\[
\hat\alpha=\operatorname{mean}(Y-A)^2,\qquad
\hat\lambda=\operatorname{mean}\{(S-Y)^2/s^2\}.
\]

The declared conditional model gives

\[
m={\alpha R\over\alpha+\lambda s^2},\qquad
v={\alpha\lambda s^2\over\alpha+\lambda s^2}.
\]

Repair delivers \(A+a\), where \(a=m\) for unquantized arms and \(a\) is the
receiver mean for event/quantized arms. Stop delivers \(A\). Realized utility is
\(1-(\text{actual final readback}-Y)^2-c\,1_{\rm repair}\). Costs are controlled
task units; execution resources are recorded separately, without money conversion.

Positive realized repair improvement is the event \(2aE-a^2-c>0\).
For \(a>0\) it is a call event above \((a^2+c)/(2a)\); for \(a<0\) it is a put
event below that threshold. For \(a=0,c>0\) the improvement event is empty.
It is not the event \(E>0\), a first-passage event or runtime confidence.

Expected improvement is \(2am-a^2-c\). For this symmetric Gaussian posterior
and \(a=m\), it is positive iff improvement probability exceeds one half.
This is specific to this loss/repair model; arbitrary success probabilities
are not treated as expected utilities.

## Nine arms and matched training opportunity

| Arm | Predictive representation and choice |
| --- | --- |
| gaussian | Trained scalar conditional model; expected-improvement rule |
| probit | Independent dense joint-Gaussian conditioning; equivalent event rule |
| numeric | Native channels for residual, public sensor variance and cost |
| analytic | Native channels for improvement probability, posterior variance and cost |
| event | Same analytic channels using the independent signed-event receiver |
| quantized | Direct-quantization control on the same mean/log-variance grid |
| history | Polynomial/RBF reference with the same three public inputs |
| zero | All three native drives intervened to zero |
| reset | Native state reset before each second tick |

Each native channel executes two original sparse_tick calls. Its second tick
has exactly zero fresh drive. Three channels concatenate intercept, activation
and eligibility coordinates into a 63-coefficient head. History also has 63
coefficients: 20 monomials of degree at most three and 43 RBF centers derived
only from training inputs.

All seven learned heads use 600 full-batch logistic-gradient steps at rate
0.15 for each L2 value in \(\{0.001,0.01,0.1\}\). Development selection considers
thresholds \(0,0.1,\ldots,1\), maximizes realized paired-label utility, and on
ties prefers fewer repairs, stronger L2 and the larger threshold. Threshold
zero means always repair; one means always stop.

Reported binary improvement NLL clips evaluation probabilities to
[1e-12, 1-1e-12]. It is a clipped calibration score, not an unclipped tail
logscore. The auditor independently reconstructs this convention and the
native request/roundtrip counters from retained per-episode receipts.

Event and direct-quantization use mean/log-variance steps 1/64 in this separate
feedback study. They transmit prior and observed-posterior packets to an
independent receiver. Counts, encoder/decoder checkpoints, logical unit-event
cost and serialized packet bytes are retained. Only decoded state supplies
repair magnitude and native channels. This does not establish a new function
class or physical low-energy spiking hardware.

Gaussian/probit and event/direct-quantization are deliberate equivalence
controls. All arms acquire the same public information. Original native kernel
parameters remain fixed; fitted head coefficients and conditional parameters
are recorded separately.

## Freeze, execution and independent replay

Formal training seeds are [101, 211, 307, 401, 503]. Feedback data seeds are
10_000_000 + 100*s + j: j=1 for 384 training episodes, j=2 for 128 development
episodes, and j=3 for 256 confirmation episodes. Engineering uses 701/709.
The root study freezes sources, trained artifacts and protocol before creating
formal confirmation data.

feedback_study.train_seed(seed, output, native_binary, native_receipt) saves
models, datasets, compressed full training receipts and actual transport archives.
confirm_seed additionally requires the expected model-file SHA256. Each
confirmation scope retains raw rows and all actual readbacks.

The independent auditor reconstructs conditioning, event directions, count
receiver values, three native channels, frozen scores, choices, costs and
utility. It reopens every PNG with an independent bit decoder and reruns every
original native tick. Chronology is checked from acquisition through native
execution and final delivery to private scoring. This is evidence replay and
source-boundary review, not process-memory isolation proof.

Native executable SHA256 is
b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179.
This session reuses the previous verified archive and does not claim a fresh
build. Original source/build receipts are retained; bytes are verified at launch.

## Versioned runtime and distinct numerical stages

AdaptiveEventRuntime binds the frozen model file, selected entry, dataset,
subject, generation, event configuration, mode and lifetime limit. Only declared
public-history fields and registered horizons are accepted.

Receiver state is separate from encoder state. Pending state is written and
reopened from disk; decoder counts reconstruct the next head input. Missing
observations, propagation, zero emitted counts and neutral terminal probability
are distinct.

Two explicit modes exist:

1. **count_only** feeds decoded mean/variance to the original typed owner.
   Lossy encoding does not inherit the FP64 protected model's density bound.
2. **anchor_guarded** adds an explicit frozen-anchor forecast using the same
   public history. A certified Gaussian Q24 guard follows event decoding.
   The certificate is independently checked on exact parameters returned by
   Rust. This mode is not a pure count-only readout.

Native conversion is ties-to-even signed Q24. Its domain has finite absolute
parameters at most 8; variance is zero or at least \(2^{-24}\), and thresholds
must remain ordered. The guard's mathematical domain and this narrower native
domain are independently enforced.

For \(c=v/v_0>1\), \(d=(m-m_0)/\sqrt{v_0}\), the supremum of excess Gaussian
NLL is \(\frac12\log c+d^2/[2(c-1)]\). For \(c<1\), or \(c=1,d\ne0\), it is
unbounded. Receipts retain bounds before encoding, after naive encoding and on
actual native inputs. Small CDF rounding error is not a density certificate.

After native execution, anchor_guarded separately projects delivered category
counts onto anchor-relative lower bounds with exact Q24 mass. Its certificate
binds stable anchor log-probabilities and each delivered count. Raw native
CDF/counts and corrected delivered counts are separately retained. This
post-native categorical projection is not the exact Gaussian CDF of the guarded
mean/variance.

Calibration must assess the delivered head. Retention's supervised model and
the event-plus-guard composition can differ numerically; utility/calibration
estimates do not automatically transfer between them. Pointwise certificates
are independently checked on actual runtime outputs.

## Persistence, authority and limits

The original NeuronModelPort, NeuronRuntime, SparseJournal and
FileAnchorWitnessStore execute the typed head. Their witness binds raw native
output. A separate versioned adapter delivery witness binds final counts,
composite-state digest, frozen request and original native anchor. The original
Rust witness is never claimed to produce or certify post-native projection.

The adapter witness is written before state acknowledgement. Pending work
blocks retries after partial commits. Qualification uses fresh Python and Rust
processes for duplicate replay and continuation, and tests changed duplicates,
stale CAS, corruption, rollback of adapter owners, original journal rollback,
missing observations, acknowledgement loss and bounded lifetime.

Owners do not share an atomic transaction manager. Partial commits require
explicit reconciliation. Independent files and caller checkpoints detect
accidental partial rollback, but not a hostile administrator rolling back
all files together.

Native confidence stays zero, output abstains and authority is DENY_ALL.
These local research owners do not take over Agentd dispatch. Numerical
protection, calibration, future-task utility, latency and long-term retention
remain separate acceptance questions.
