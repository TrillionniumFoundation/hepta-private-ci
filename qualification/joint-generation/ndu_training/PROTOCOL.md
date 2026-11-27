# NDU training contribution: TRAIN diagnostic d1

Base: `0aca16714390ca045a53cece9644992b7990fc9c`, verified PR #3451 head.
Independent branch: `research/ndu-training-budget-20261023`. Do not edit the
joint-generation prototype branch, content-control work or dynamic-scheduling work.
Only the selected Codex cloud environment is used. No deployment, merge,
permission change, persistent credential, user computer or formal evaluation.

## Hypothesis and fixed estimand

N's cross-seed contribution may be sensitive to request minibatch variation and
to a mismatch between risk-sensitive directions and raw decoded outcomes.
The existing implementation already exactly marginalizes all 12 by 12 outputs;
there is no sampled-output gradient to Rao-Blackwellize further. A single
alternative, proportional target-class stratification, tests request variance.
Both A and N receive both estimators, one fixed learning rate, identical bases,
CE anchor 0.2, minibatches of 64 and identical candidate/draw opportunities.
Rho stays 1.5. No utility, decoder observer, endpoint or risk-parameter search.

For each request x, L_A(x)=0.2 CE(x)-E_pq R_x and
L_N(x)=0.2 CE(x)+log E_pq exp(-1.5 R_x)/1.5; the TRAIN objective is mean_x L(x).
This is not modality-loss logsumexp. The log never moves outside the request
average. For N, with K=exp(-rho(R-min R)), Z=p'Kq, the negative utility logit
gradients are (p*(Kq)/Z-p)/rho and (q*(p'K)/Z-q)/rho. They are exact conditional
marginals of the tilted joint law. Stable/log-domain agreement is measured.

For target stratum j with original population mass P_j and fixed draw count n_j,
each request has weight B*P_j/n_j. This multiplies both CE and utility gradients.
Thus E[g_hat]=sum_j P_j E[g|j], preserving the complete objective. Its covariance
is sum_j P_j^2 Cov(g|j)/n_j; IID covariance is Cov(g)/B. Eliminating between-class
variation can help, but finite integer allocation need not lower every variance.
No global per-batch renormalization, outcome-based grouping or class reweighting.
Counts are floor(1+(B-12)P_j), with remaining slots assigned by descending
fractional remainder and numeric-class ties. Sampling is with replacement.

Fixed constant rho can support an entropic Bellman/tower recursion with the
appropriate additive cost, conditioning and controlled paths. This experiment
does not learn a temporal continuation value: state is the current scene and
instruction; control is the text/image policy; the stochastic output path is
one independently sampled pair conditional on that request. A future multi-step
model must specify content state and transitions and use p(a)p(b|a), rather than
the product of averaged marginals. Handmade checks verify conditional recursion,
the path-mixture counterexample and the cross-request-log counterexample.
Adjoint Matching's KL-control dual is not silently substituted for this objective.

Primary references: [Expected Policy Gradients](https://jmlr.org/papers/v21/18-012.html)
supports conditional action integration; [Risk-Sensitive Exponential Actor Critic](https://arxiv.org/html/2602.07202)
discusses entropic gradient/numerical issues and conditional value functions;
[Risk sensitive optimal stopping](https://arxiv.org/abs/1912.02486) concerns a
separate risk-sensitive stopping setting; [Adjoint Matching](https://arxiv.org/html/2409.08861)
uses a separately specified stochastic optimal-control formulation. None proves
benefit for this finite generator or for the proposed request estimator.

## Execution, cost and stopping

Construct only existing r2 TRAIN (seed 130101, 192 independent physical sources,
3072 rows); all instructions and two variants remain together. No validation,
old formal test, new formal source or opening marker is touched. Do not use
CORE c1 results to tune. Source and this plan are committed and hash frozen before
the first construction. Output refuses existing directories. There is one run.

Shared decoder300 and dense supervised500 use the existing equations and seeds
11/23/47. Adaptation clones reset Adam clocks equally, as the existing candidate
construction does. Both systems get two estimators, six seed/candidate models
in total, the same folded mixed encoder and native Adam. A/N order alternates.
At 128 updates retain exact stream hashes, model/Adam state and full TRAIN
outcomes for an opportunity-matched comparison. Then useful updates continue
under each system's SAME 10 process-CPU second / 12 billion declared-unit cap.
Cheaper A can get more updates; same common draw prefixes remain comparable.
No counter padding or unused critic. Maximum 1024 complete rounds is a hard stop.

Full shared preparation, compiler child CPU, all three bases, BOTH candidates,
gradient diagnostics, TRAIN scoring, matching snapshots, final exports and
actual native always-full PNG/caption/JSON service all count for each system.
All scheduler CPU is attributed in full to both. Unit prices are unchanged
WorkLedger prices, not hardware FLOPs. Sampler metadata/memory and interpreter
work count in CPU; additional request-weight arithmetic has an explicit charge.
Reserve 650M units and 0.8 CPU seconds for final work. Actual breaches fail and
stop the run; forecasts cannot erase them. Final administrative result writing,
source development, handmade tests, browsing and later descriptive analysis
are separately retained R&D, with no matched lifetime-cost claim.

The gradient panel is the first 64 hash-sorted TRAIN physical sources, all their
rows and both views. Twelve fixed minibatches per estimator measure parameter
gradient variance against its exact panel/view mean; no seed or panel search.
Measure CE-versus-utility scale/cosine, N-versus-raw directions, finite gradients,
cached/log-domain error and actual six-parameter movement. All seeds are retained.
All TRAIN scores use the original independently decoded observer and a truly
corrupted decoder negative control. Service uses the first eight TRAIN rows per
target class, one measurement per model, retaining its sample and full costs.
Reference CPU is the pre-candidate median of the three base service costs.
Descriptive complete CPU-net uses the unchanged price .02, H=100000 and B/(3H),
charging BOTH search candidates even when inspecting one. It is not confirmation.

There is no candidate selection and no significance stopping. Report each
same-estimator N-A contrast, all seeds, and the strongest observed additive
candidate as a descriptive effective baseline. TRAIN improvements cannot establish
generalization or repair CORE c1. If stratification does not reduce N variance
for every seed, or final N-minus-A is nonpositive for any seed on raw utility or
joint success, this candidate is not a robust TRAIN remedy. Do not add candidates.

## Future confirmation: review draft, not authorization

Before any confirmation, parent review must receive a complete immutable history:
r1's narrow success and padding limitation; every retained r2 build t1 through
t11 including preparation failures and timing/OOF diagnostics; CORE c1 t1's TRAIN
construction failure; CORE c1 t2's sole consumed formal failure (all six intervals
crossed zero); codec handmade/source work; this diagnostic including failures;
and every other parallel/subsequent candidate and formal look. Exact commits,
artifact hashes, counts of looks and cumulative R&D costs must be reconciled from
the historical receipts. The current delegation alone is not that complete ledger.

Use new physical-source TRAIN/validation/formal seeds derived once from a newly
registered salt; prove physical/input-hash disjointness from every prior source,
group all variants/instructions, bind raw reconstruction artifacts, code and
protocol. Parent must approve the exact one-shot global and run markers, opened
exclusively before formal construction; no run-directory bypass. No formal seed,
data, marker or evaluator is created here. Preserve consumed markers forever.

Repeated confirmation requires an explicit family-wide error budget. Historical
CORE c1's .05 opportunity is spent and cannot be retroactively reassigned; merely
calling another test '95%' does not retain a .05 probability for ever claiming
success. Parent must disclose the number of prior looks and approve either a new
family with its narrower interpretation or a prospective continuing bound, e.g.
alpha_new,k=.025/2^k, k>=1, whose future sum is .025 and whose union bound together
with the spent .05 is .075, conditional on valid individual tests. Missing prior
looks can make even that bound unavailable. Do not claim global .05 retroactively.
The existing 2000-replicate percentile bootstrap is approximate; small alpha
requires a separately justified inferential method and adequate resolution.

Freeze one final estimator, fixed rho/anchor, selection, useful full-budget A,
and all endpoints before new validation. Require raw decoded utility, joint
success and complete CPU-net N-A gains, greedy retention and corruption/budget
guards as a conjunction; six-endpoint joint content claims remain a separate
parent decision. No endpoint substitution, seed dropping, changed interval,
reopening c1, or relabeling a prior failure. Scope remains two modalities and
a twelve-code decoder; typed AV is reserved but generation is unaccepted.
