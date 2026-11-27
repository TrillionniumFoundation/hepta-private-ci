# Executable registration v1: fixed diagonal-support TRAIN decoder probe

This prospectively freezes the parent's reviewed draft at01f7b7527246. Source
and input identity will be committed before ONE real-data run. The source branch
is `research/content-control-budget-20261023`, descending from verified0aca1671.
No formal CORE/r2 inputs/results/markers are opened, and there is no model
training, parameter update, neural critic or risk/schedule/threshold search.
The head-anchor and both previous failed refinement proposals remain unrun or
rejected as recorded; this is a separately authorized fixed-model decoder probe.

## Exactly one support rule

Use `D(c)=p(c)*q(c)` to compare the original independent head law's support for
the TWO consistent hypotheses `(t,t)` and `(i,i)`, for a sampled disagreeing pair.
This is a joint-support comparison, not a posterior probability that either
code is true. It differs from the dot reference's pT(t)/pI(i) rule. Only this
diagonal-support rule is implemented; the other rule is not run/selected.
The parent's reference established general pushforward/CE mathematics, not
validation of this particular rule. Local exact hand tests are required.

For equal codes or infinity: KEEP. For finite multiplier k=1 (tau0) or2
(taulog2): TRUST_TEXT iff D(t)>kD(i), otherwise TRUST_IMAGE iff D(i)>kD(t),
otherwise KEEP. Comparisons are strict. Ties/zero-zero keep. The implementation
accepts only decisions outside a conservative float-product error band, and
uses exact ratios of the underlying float64 probabilities at boundaries or
subnormal products. This protects zero/underflow/tie cases without a fitted
epsilon. Exact integer operation/call/operand-bit counters and actual CPU are
retained. The rule sees ONLY p,q and initial codes, never labels/R/pixels/observer.

TRUST_TEXT renders text code with the original image decoder; TRUST_IMAGE emits
the original caption for image code. Only the final pair is rendered, once.
Exactly tau{0,log2,infinity}; log2 is the ONLY primary,0 the secondary and infinity
the identity. A secondary outcome cannot replace a failed primary.

## Strong models, exact law and fixed behavior

Use frozen selected strong dense H/A(.01/full) model seeds11/23/47 from
`runs/content-control-train-r2-20261023`. No base-cache logits are substituted.
Read the same saved TRAIN input artifact:144 fit/48 inner sources,16 rows/source;
all768 inner rows per model for exact-law quality. Fresh original-model forwards
capture p/q once for this offline analysis; all cost is billed. Runtime service
independently executes its own fresh original head forward on every request.

The original decoded R and semantic tables are recovered once per unique
decoder seed, verified identical for H/A, and fully charged as shared work to
BOTH families. Hash tables/weights/source. R is evaluation-only and unchanged.
Save the two wrong-agreement-minus-one-correct reward contrasts. Explicitly
report both wrong, wrong agreement, wrong disagreement, text-only correct,
image-only correct, joint success, marginal correctness and pixel error; the
unchanged.35 inconsistency penalty can reward wrong agreement over one correct
head. Consistency/CE alone cannot establish content success.

Compile row-major144-state `Q[a,b]=sum_(t,i) p[t]q[i] 1[f(t,i)=(a,b)]`.
Compute requestwise original `certainty_equivalent(R_flat,Q_flat,rho=1.5,axis=1)`
THEN request mean. Do not call the independent-product gradient helper, multiply
repaired marginals or pool requests inside log. This is a new fixed-model
entropic decoding evaluation, not a relabeling of original additive training.
For finite thresholds, independently evaluate original-pair probabilities with
R gathered at f, and check CE/raw reward/joint-success parity against Q within
1e-12. Infinity shares the identity evaluation without an extra CE call.

Original greedy pairs are first-index argmax(p),argmax(q); repair THAT pair with
the same rule. Store both pairs/actions as new probe metadata, separately from
Q sampling. Joint MAP or repaired-marginal argmax is prohibited. All probes use
`code-pair-reconcile-probe-v1`, greedy recipe
`original-head-argmax-then-reconcile-v1`; old formal behavior/results are untouched.

## Exact real-service call/denominator list

`CALLS.json` is part of the frozen identity and enumerates every call, order,
family/model/sampler seed, threshold and aliases. EACH family has three seeds;
EACH model executes the following six64-request batches, once each:

| Actual profile | Threshold | Execution | Calls/seed | Requests/seed |
|---|---|---|---:|---:|
| Q_zero | 0 | explicit144-state compilation/sample | 1 | 64 |
| T_zero | 0 | original pair then repair | 1 | 64 |
| Q_log2 | log2 | explicit144-state compilation/sample | 1 | 64 |
| T_log2 | log2 | original pair then repair | 1 | 64 |
| Q_infinity | infinity | explicit product-Q materialization/sample | 1 | 64 |
| identity | infinity | original independent sampler, no repair | 1 | 64 |

Thus18 actual calls/1152 requests PER family;36 calls/2304 requests total.
Q_infinity executes exactly3 calls/192 requests per family. Identity also
executes exactly3 calls/192 requests per family. Its THREE receipt aliases
`original_factorized_KEEP`, `two_stage_tau_infinity`, `efficient_static_identity`
add ZERO calls, requests or charges. No additional baseline execution is hidden.
Greedy computations are offline metadata, not more real-service requests.
Each batch uses the same64 evenly spaced fit indices. Reverse paired form
order by threshold/seed/family parity; rotate family order by seed. No repeats,
warm fastest selection, common RNG matching fiction or result-dependent cohorts.

Each actual request does fresh full heads, its actual sampling/repair or Q work,
and one final learned RGB decode/PNG/hash/JSON. Preserve sampled original pairs
only where they exist (two-stage/identity); Q sampling has no fabricated ancestry.
Static and two-stage quality are exactly the SAME Q; no dynamic-quality win can
be claimed. Include the efficient identity alongside explicit Q identity. A
cost difference versus one implementation is not superiority to a final best
static system allowed to reallocate savings to training. That comparison remains
future work; it cannot close the parent goal from this probe.

## Both complete and added caps

Each family inherits its FULL original nine-candidate total: H5.023574262s /
11,664,350,313 units; A5.409933441s /11,664,058,551 units. Each one cumulative
family ledger includes all new common/source/input/weight checks, probability
capture, R recovery/observations, all thresholds and law/greedy evaluations,
source/profile/model exports, traces and its18 actual service calls (36 across
the two families).
Shared new work is fully charged to both. All measured active family CPU plus
actual shared scheduler overhead is charged. Model files may be hardlinked to
avoid data duplication; that never removes inherited build/search cost.

Added work per family: at most3.0 process-CPU seconds AND250M declared units.
Complete work per family: at most10 seconds AND12B units. The smaller admission
always governs. Every executed mathematical kernel is inventoried; validation,
memory, IO/hash/PNG/JSON and variable exact-integer complexity have measured CPU
and byte/call metadata, not invented hardware-FLOP equality. Actual runtime
retains the original two-full-equivalent per-request declared cap; conservative
admission envelopes are not consumed padding charges. Preserve individual batch
kernel receipts and reconcile their actual units into each family total.
Each768-row offline model phase is pre-admitted at75000 units/row, with an
assertion that actual inventoried work stays below that envelope. Each64-request
runtime batch is pre-admitted at its unchanged two-full-equivalent request cap.
Only actual kernels are charged. Standard lazy PNG plugin initialization is
performed once in shared setup without rendering an image, and fully attributed
to both families; no initial dummy image is generated.

Any actual cap or parity/profile violation exits nonzero and preserves partial
costs/data and original errors. Pure launch defects before model results may
receive a recorded new technical identity and pre-run freeze; no score-based
rerun, relaxed cap, new threshold or alternative mapping is allowed. Final
lossless administrative receipt/descriptor writing and later saved-output
summaries are recorded separately, not training credits. No extra model fitting
or static-budget-reallocation experiment is performed here.

## Readiness and retention

Primary TRAIN decoding readiness requires log2-minus-KEEP positive mean CE AND
joint success for each frozen model family, per-seed greedy drop<=.02, and all
four caps/quality equivalences holding. Always report every seed and all three
thresholds, including wrong-agreement/both-wrong/marginal-correctness tradeoffs.
No positive CE/consistency alone or secondary threshold substitutes for primary.
No formal confidence/independent-source claim follows from these used TRAIN rows.

Retain original p/q/greedy pairs, original R tables/semantic mappings, all Q and
source-pair action maps, endpoint/greedy arrays, true initial/final sampled pairs,
RNG/call/profile/source identities, every actual PNG receipt, complete ledger
and costs. Source/protocol identity and CALLS must be committed/frozen before
the single run. Local hand checks must distinguish this support rule from the
dot rule, exact ties/subnormals, complete pushforward mass, requestwise CE both
helper branches, asymmetric semantic indexing, wrong-agreement partition,
original greedy versus joint/marginal MAP, aliases, budgets and one final render.
Formal data stays closed. No optimizer/model update or deployment is authorized.
