# Code-pair reconciliation: fixed TRAIN-only draft, NOT EXECUTED

This draft follows the parent's new content-control proposal. It neither
implements nor executes a reconciler, new forward, R reconstruction, Q
evaluation, service, training or formal test. Weak head anchoring is paused.
The refiner and fixed1:1 failures, all CORE/r2 results and consumed test markers
are unchanged. No formal alpha is spent by this proposed TRAIN diagnostic.

## One finite decoder candidate and fixed models

Bind only the strong saved dense H/A models from
`runs/content-control-train-r2-20261023`: seeds11/23/47, selected LR.01/full,
original input/physical-source hashes and unchanged learned12-code RGB decoder.
Do not substitute weaker base logits or rejected refiner/alt models. No model
parameters, encoder, critic or risk coefficient are trained/searched. This is
joint content **decoding**, not evidence of improved content-parameter training,
dynamic scheduling, NDU training, AV or an open-world model.

The candidate receives an original request's already computed p[12],q[12] and
independent sampled codes t,i. It may use those inputs only. No target, R,
semantic-observer result, rendered pixels, source identity or future observation
is visible to it. A new authorized capture of strong-model TRAIN probabilities
is needed because they were not persisted; the current inspection does not
perform it. Once captured, exact quality analysis reuses the same immutable
probabilities across all thresholds/implementations, with full capture cost.

Exactly three thresholds: tau in{0,log2,infinity}; no confidence/risk threshold
search beyond that set. **Draft action rule**, fixed before any new probability
evaluation, uses diagonal joint support D(c)=p(c)*q(c):

```
if t == i or tau == infinity: KEEP(t,i)
else if D(t) > exp(tau)*D(i): TRUST_TEXT(t,t)
else if D(i) > exp(tau)*D(t): TRUST_IMAGE(i,i)
else: KEEP(t,i)
```

tau0/log2 use multipliers1/2, strictly greater comparisons. Equality, including
both supports zero, means KEEP. One positive/one zero support chooses the
positive one for finite tau; infinity always keeps. Before executable freeze,
one canonical comparator must avoid probability-product underflow/overflow and
pass exact/high-precision boundary fixtures. Both implementations share that
same comparator. No epsilon or tie rule is chosen using real TRAIN scores.
This is one declared likelihood-support rule, not a choice among alternative
gate formulas. If the parent's portable reference uses another rule, reconcile
the draft/source identity before any real-data evaluation rather than compare
formulas and select a winner.

TRUST_TEXT keeps the sampled text code and renders its code with the ORIGINAL
pixel decoder. TRUST_IMAGE keeps the image code and emits that code's ORIGINAL
caption. Code reconciliation occurs before final rendering. There is one actual
final PNG/caption generation, without rendering/discarding an initial image
merely to create workload. Agreement can still be wrong; this rule is not a
ground-truth or external-observer feedback loop.

## Mandatory equivalent static law and executable two-stage comparator

For every request n, enumerate ALL144 original pairs with P_n(t,i)=p_n(t)q_n(i).
With the declared map f_tau, compile the exact pushforward:

```
Q_n(a,b) = sum_(t,i) P_n(t,i) * 1[f_tau(t,i) == (a,b)]
```

Keep Q[12,12], not just its marginal vectors. Compare:

1. **Static compiled joint**: build Q, sample its144-state categorical law,
   using row-major index `12*a+b`, and render the chosen final pair using
   unchanged decoders.
2. **Two-stage code repair**: sample original t~p and i~q independently, apply
   the declared map using only p,q,t,i,tau, then render the final pair.

Both have the SAME exact output law Q by construction. Their exact quality
must agree within the frozen numerical tolerance; a quality discrepancy is an
implementation failure, not dynamic gain. Samplers use different random-draw
geometries, so equality is distributional rather than pointwise PNG/RNG parity.
Use fixed independent seed namespaces, all retained; no favorable draw selection.

tau=infinity is the original product law. The efficient static identity sampler,
original factorized decoder and two-stage KEEP are implementation aliases and
should be executed once with explicit receipt aliases. An explicitly materialized
144-state Q identity is a mathematical/execution reference, not an excuse to
call an unneeded expensive static implementation the strongest baseline. All
common-subexpression/caching optimizations must be visible and fairly priced.
Compare actual best useful static compilation with actual two-stage work.

If static compilation gives the same quality more cheaply, the conclusion is
joint decoding benefit with a cheaper static implementation. If two-stage
sampling is cheaper, that establishes an implementation-level efficient sampler
under the measured profile, not new information, learned scheduling, or a
dynamic-quality advantage over the identical law. No runtime repeats or refiner
expansion are authorized by a favorable threshold result.

## Exact reward, risk and joint success

Recover the SAME original actual decoded reward tensor from each frozen
decoder and original `data.py` observer equations; hash R and the decoder/source.
Use it unchanged for every threshold and both execution forms. R/target/decoded
semantics are evaluation-only. Never construct reward from the repaired outputs
in a way that changes the observer's preferences or feeds decisions.

The parent's fixed entropic interface is mandatory, per request:

```
ce_n = utility.certainty_equivalent(
    R_rows.reshape(N,144), Q_rows.reshape(N,144), rho=1.5, axis=1)
ce_mean = mean(ce_n)
joint_success_n = sum_ab Q_n(a,b) * [text_sem(a)==target_n]
                                      * [image_sem(b)==target_n]
```

The local helper signature has been read and matches this interface. Do NOT
call `joint_value_and_grad` for repaired Q: it internally rebuilds an independent
p*q law. Do not multiply Q's repaired marginals, average branch CEs instead of
their outcome law, or move the request mean into the logarithm. Raw expected
R, code disagreement, semantic disagreement, text/image marginal correctness
and pixel error remain visible; code agreement alone is not task success.

rho is fixed1.5, with no sweep. The source H/A models were trained with their
previous supervised/additive recipes; this NEW decoding probe at the existing
entropic profile is not a retroactive change to their old objectives/results.
Every new CE contrast compares the same fixed rho1.5 against its own KEEP law,
not new CE against old raw expected-utility scalars. No NDU model benefit is
inferred without separately provided frozen model provenance.

## Greedy behavior is a separately versioned probe contract

Store original `t_g=argmax(p)` and `i_g=argmax(q)`, with the original first-index
tie rule. Apply f_tau to THAT pair, using the same original probabilities. Save
original pair, action, repaired pair and its offline decoded metrics separately.
This is neither argmax(Q) nor argmax of repaired marginals. Q sampling metadata
alone is insufficient to reconstruct this greedy profile, so the bundle must
retain/bind its original heads and `original-head-argmax-then-reconcile-v1` rule.
Use a new `code-pair-reconcile-probe-v1` behavior ID. No existing formal bundle
contract/result is silently changed or recycled for this probe.

## Minimal cohort and complete budget proposal

Exact quality: all768 existing inner TRAIN rows,48 complete physical sources
with16 rows each, per seed/model. No new sources, filtering or labels-as-control.
There is no new fit or LR selection. All three thresholds are reported.
Predeclare tau=log2 as the primary readiness contrast; tau0 is the aggressive
secondary and infinity the identity control. A secondary win cannot replace a
failed primary. Any later choice remains exploratory, not confirmation.

Actual complete-service timing/output: one fixed64-row fit cohort per seed,
the same evenly spaced indices used by the original pre-selection calibration.
For each model family, execute all3 thresholds x2 implementation forms x3 seeds:
1152 actual requests total, counterbalancing form order by threshold/seed.
The identity aliases avoid a duplicate run; explicitly materialized Q identity
remains the static reference. One wave only; no fast repeat/minimum selection.
This limited cohort is not a population or per-request latency qualification.

Each actual service request includes a fresh ORIGINAL head forward, its real
Q-build/sample or original-sample/map, and final decoder/PNG/hash/JSON work.
Separate offline cached-head quality analysis may share probabilities, but may
not make runtime heads free or amortize an input-specific Q across unrelated
inputs. No discarded renders, fake diagnostics or unexecuted padding are used
to equalize runtime. The original two-full-equivalent declared per-request cap
must also hold for BOTH forms after implementation inventory is frozen.

One cumulative ledger per H/A family includes ALL new thresholds/implementations,
probability capture, original-R recovery/observations, exact CE/Q calculations,
source/input checks, actual service/calibration, trace and profile export.
Each family additionally inherits its FULL prior nine-candidate build/search:

| Family | Inherited CPU seconds | Inherited units | Remaining under10s/12B |
|---|---:|---:|---|
| H | 5.023574262 | 11,664,350,313 | 4.976425738s /335,649,687 units |
| A | 5.409933441 | 11,664,058,551 | 4.590066559s /335,941,449 units |

Proposal: cap ALL additional probe work at3.0 CPU seconds AND250M declared
units per family, inside the unchanged10s/12B whole-family limits. This is not
a per-threshold/model allowance. Thus prospective complete ceilings are
8.023574262s/11,914,350,313 units for H and8.409933441s/11,914,058,551 for A.
The smaller actual remainder always governs. No old research failure is a
budget credit; no old feature-cache preparation is silently treated as selected
model inference. New byte/hash/allocation work has actual CPU and byte counters,
not invented hardware-FLOP prices. Candidate exports, losses and failures stay.

This envelope is a draft, not a measured admission guarantee. Before execution,
freeze complete operator inventories for comparator/Q scatter, probability
capture, CE helper, observer,144-state sampling and original sampling/repair,
plus complete CPU guards. Include actual implementation/compile/setup costs.
If a full atomic phase cannot fit, preserve the refusal and do not relax the
caps or retry a smaller favorable cohort. Final lossless administrative archival
is recorded separately without budget credits. This probe has no new training;
any claim about spending sampler savings on model updates would require a
different prospective TRAIN protocol and is not made here.

## Readiness, checks and retention before any future run

Hand-array checks must cover mass/nonnegativity, identity infinity, zero support,
ties/boundaries, wrong-consensus and misleading-confidence cases, exact static/
two-stage pushforward equivalence, requestwise entropic CE, true joint success,
the original-argmax greedy rule, and real decoder/output/budget conservation.
Include asymmetric R to expose a/b transposition and explicit examples where
the contracted greedy result differs from joint MAP or repaired-marginal argmax.
Predeclare float64 row-mass/CE/law parity tolerances1e-12; exact high-precision
fixtures must determine comparator boundary behavior. No neural critic is added.

The parent reports its independent HAND reference passed12 tests,48 exact-law
checks and192 per-request CE comparisons, maximum difference1.46e-16. No code
package/commit/test log accompanied that message; these are parent-reported
mathematical checks, not tests executed here or project-benefit evidence. Integrate
and hash the portable source before claiming local parity. There is no need to
wait for that package to finish this availability inspection/draft.

For the primary log2 probe to have TRAIN content-decoding readiness, exact CE
and joint success must both improve over fixed-model KEEP without per-seed
greedy retention worse than.02; all costs and marginal-correctness changes must
be reported. An agreement-only win or a cheaper inferior static comparator is
insufficient. Static and two-stage quality must remain identical; report their
actual cost difference with no dynamic-quality label. Report every model,
threshold, source and failure. Descriptive paired seed/source intervals may be
reported with fixed2000/77431 bootstrap, explicitly selection-used TRAIN and
without simultaneous-coverage/formal claims.

Retain original p/q and argmax pairs, frozen R/decoded semantic table hashes,
Q once per request/threshold (shared evidence rather than duplicated per form),
all action/mass/metric arrays, actual sampled initial/final pairs, RNG profiles,
cost/PNG receipts and bounded content-addressed output bytes. Runtime PNG work
is still performed and charged even if archival deduplicates equal PNG bytes.
Freeze source/protocol/input identities and get separate parent execution
authorization before one real-data probe. No training, repaired sampling,
quality evaluation, formal opening or serving has occurred under this draft.
