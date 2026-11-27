# H1: saved TRAIN decision headroom and unidentifiable complete-cost terms

**Administrative descriptive analysis completed, exit 0. No model/data execution.**
This uses all three T11 NC models' already saved Q1 TRAIN utility arrays and
existing T11 TRAIN paired-service/build receipts. It neither reruns CORE nor
constructs r2 or any new test. It is not qualification, a benchmark, a new fit,
a new critic selection, or evidence of unseen-source content generalization.
The user-required goal, dynamic over effective best static NDU under equal
complete budgets, remains unconfirmed.

The key result is conditional: label-known oracle decision headroom over
same-weight always-continue averages **0.002967465**
raw-utility-price units under the historical fixed TRAIN price proxy. It is
positive in every seed, but mandatory low/critic service overhead and the
TRAIN content opportunity gap versus selected static NDU are not identifiable
from the saved permitted receipts. Therefore these data establish neither that
a better critic can win nor that winning is impossible. No missing term is
filled from validation, formal results, base calibration or a new codec price.

## Frozen scope and equations

Q1 saved 3072 TRAIN rows per seed: 192 physical sources, each with all sixteen
instruction/sensor rows. All sources/rows/seeds are retained and weighted equally
by physical source. Because every group has sixteen rows, the source-equal mean
also equals the row mean here. The content encoder already saw all TRAIN, and
T11 checkpoints were validation-selected. Q1 holds sources out of critic fitting
only; no new folds or fits were created for H1.

For each saved row let `g = U_NC_full - U_NC_low`. Let `c` be the already frozen
TRAIN decision price, `0.02 * max(0, median(continue-stop CPU/row)) / R`, where
`R = 73435.296875 ns` is T11's common TRAIN reference. This is the old
`rowwise-png-v1` profile. Three paired aggregates estimate one price per seed;
there is no measured request-specific continuation-cost function.

With the common stop-path costs temporarily omitted, define:

- `V_stop = E[U_low]`;
- `V_continue = E[U_full] - c`;
- `V_oracle = E[U_low + max(g-c, 0)]`;
- `H_continue = E[max(c-g, 0)]`;
- `H_stop = E[max(g-c, 0)]`.

Oracle advantage over the better same-weight constant action is
`min(H_continue, H_stop)` **within each seed**, before averaging seeds. All
three seeds prefer always-continue as their best constant action. The oracle
knows outcome labels and both potential generated utilities, unavailable to
serving. These are conditional proxy-policy ceilings, **not a certified upper
bound on actual complete CPU-net utility**: median timing, zero-clamping and
additive constant-cost assumptions need not describe row-dependent execution.
A paired negative increment does not establish free physical computation.

## All-seed conditional information headroom

| Seed | Existing c | Rows where stop is oracle-better | H vs always-continue | H vs always-stop | H vs best same-weight constant |
| --- | ---: | ---: | ---: | ---: | ---: |
| 11 | 0.002948767 | 2269 / 3072 | 0.003234492 | 0.050306469 | 0.003234492 |
| 23 | 0.000000000 | 1100 / 3072 | 0.000876023 | 0.050712750 | 0.000876023 |
| 47 | 0.005897535 | 2382 / 3072 | 0.004791881 | 0.050538325 | 0.004791881 |

The mean full-minus-low raw utility is about 0.05 in every seed; this does not
mean continuation helps every request. Many small or negative individual gains
cross the fixed price, while some large gains require continuation. A classifier
that always continues can therefore be the best **constant** decision without
being an implementation failure, even though the label-known oracle has
additional conditional headroom. No learned policy is assumed able to observe
that oracle information.

All original paired marginal CPU values are retained, including negative and
high values; no warmup, trimming or timing repetition was added:

| Seed | Three original continue−stop CPU/row values, ns | Signed median, ns | Original zero-clamped median, ns |
| --- | --- | ---: | ---: |
| 11 | -15114.486 / 22066.722 / 10827.181 | 10827.181 | 10827.181 |
| 23 | -13337.444 / -40238.236 / 310.417 | -13337.444 | 0.000 |
| 47 | 21654.361 / 35486.958 / 4325.264 | 21654.361 | 21654.361 |

The complete stop/continue service, preparation, native/output/remaining
components and original order/sample seeds for all nine pairs are retained in
`analysis.json`. Stop native/input/ledger components are observations of the
whole stopped native path, not an isolated critic timer or the incremental
mandatory overhead over a direct static full path. Common input/validation work
may overlap that direct path, so subtracting the whole stop component as exact
extra overhead would be unjustified.

## Existing observable-feature OOF policies, with no refit

These rows reuse Q1's saved 42-hidden/instruction MSE and fixed regret-weighted
binary actions. First three rows are MSE, next three weighted binary. Neither
method, lambda, threshold, features nor calibration price was selected anew.

| Seed | Continue fraction | Proxy-net gain vs own always-continue | Regret to label oracle | Raw gain vs own direct full |
| --- | ---: | ---: | ---: | ---: |
| 11 | 0.6419 | +0.001256188 | 0.001978304 | +0.000200314 |
| 23 | 0.6680 | -0.000020926 | 0.000896949 | -0.000020926 |
| 47 | 0.5833 | +0.002485658 | 0.002306223 | +0.000028351 |
| 11 | 0.3464 | +0.001975640 | 0.001258852 | +0.000048190 |
| 23 | 0.7666 | +0.000242356 | 0.000633667 | +0.000242356 |
| 47 | 0.3464 | +0.003733111 | 0.001058770 | -0.000121788 |

MSE captures an average 0.001240306
proxy-net gain; weighted binary captures
0.001983702.
The weighted method's raw utility gain is negative for seed 47. Its better
proxy regret does not establish complete-system benefit or justify switching
controllers without a prospectively fixed contract and full costs. Existing
Q1 regret values were cross-checked numerically; all matched within 1e-14.

All 576 seed/source rows in `analysis.json` retain headroom, signed-gain counts,
OOF decision fractions, regrets and both costly false-stop and false-continue
losses. Per-row utility/decision values remain in the original hash-bound Q1 NPZ
alongside input hashes; they are not duplicated. The NPZ does not contain input
pixels. Reconstructing pixels would require the frozen TRAIN profile/source;
that reconstruction was not performed. For the oracle's stop opportunity:

| Seed | Row 99th percentile | Maximum row value | Top-one physical-source share | Top-five share |
| --- | ---: | ---: | ---: | ---: |
| 11 | 0.017015817 | 0.904572965 | 10.10% | 26.14% |
| 23 | 0.010365511 | 0.750086656 | 28.09% | 47.91% |
| 47 | 0.013921688 | 0.463104547 | 3.92% | 8.95% |

These high-loss tails and source concentrations remain in the result. No seed,
source, sensor variant or unfavorable decision was removed. These are
fixed descriptive summaries, with no new confidence interval or significance
claim.

## Direct full and best static NDU: missing terms matter

Let `K` mean utility-priced complete CPU cost, with the same service, runtime
preparation/H and complete build/(3H) boundary. Then, conditionally on the fixed
marginal proxy:

`J_oracle - J_NC_directfull = H_continue - (K_NC_alwayscontinue - K_NC_directfull)`.

Always-continue performs the mandatory low encoder/critic and then full. Direct
static full does not. Forced continuation's native timer combines both forwards;
it does not identify direct-full cost for this same NC model. The missing
incremental mandatory overhead cannot be set to zero, read from the base model,
or inferred by subtracting the stop path wholesale. Runtime preparation
amortization is also needed on a comparable direct path.

Against NDU/full, define `D = U_NDU_full_TRAIN - U_NC_full_TRAIN`. Then:

`J_oracle - J_NDU_full = H_continue - D - (K_NC_alwayscontinue - K_NDU_full)`.

This keeps the **content opportunity gap** separate from routing and costs.
The selected static NDU TRAIN utility rows were not saved in these permitted
artifacts; mean training loss is not decoded raw utility. Static NDU validation
contrasts cannot fill D. Comparable selected-static TRAIN service/preparation
receipts are likewise missing. No stronger claim against a best static menu
can be established by first failing to identify even this direct-full
comparison. A future static menu and complete selection cost must be genuinely
effective and fixed on TRAIN/validation, not chosen to make dynamic win.

## Known build cost, without double counting

T11 complete NC build CPU was 8.537556029 s versus
8.307966292 s for static NDU; difference
0.229589737 s. Under the unchanged three-seed
100000-request horizon and historical reference, this difference costs
**0.000208428** utility units. Gross NC critic/helper CPU was
0.269756872 s, amortized
0.000244893. The gross helper
cost is already inside NC's complete build and is **not added again** to the
NC-minus-N build difference.

Gross selected-controller work was 202857987 target units + 37042218 fit units
+ 23751864 calibration units = **263652069 declared units** (2.20% of the 12B
cap); serialization CPU remained real despite zero declared export arithmetic.
These costs help explain less useful content training but do not quantify D.
T11 NC reached 488 updates per seed versus NDU 513/514/514; an update-count
ratio cannot be converted into a utility deficit without nonformal TRAIN data.

A sensitivity ceiling after subtracting **only** the known complete build
difference is shown below. It assumes D and all other direct-full cost
contrasts are zero solely to expose the remaining unpriced allowance. It is
not an estimate of those missing terms, an actual speed saving, or sufficient
evidence for feasibility:

| Seed | Initial H_continue | H minus known build-cost difference | Equivalent remaining service CPU allowance, ns/row |
| --- | ---: | ---: | ---: |
| 11 | 0.003234492 | 0.003026064 | 11111.0 |
| 23 | 0.000876023 | 0.000667595 | 2451.3 |
| 47 | 0.004791881 | 0.004583453 | 16829.4 |

Any mandatory route service/preparation overhead and unfavorable content/static
cost gap must fit jointly inside the remaining allowance under the same
historical proxy. An oracle itself failing that inequality would rule out
learned routing only **within the specified cost model**; H1 cannot evaluate
that inequality with the missing terms. Conversely, positive conditional
allowance never proves a realizable router can win.

## Next permitted evidence and profile boundary

Before changing the critic, a separately fixed TRAIN-only collection would need
same-selected-model direct NC/full and best-static NDU utility/service/preparation
receipts, with all rows/groups and complete cost attribution, to identify D and
mandatory route overhead. Full and low output gains plus request-level or
predeclared aggregate timing need consistent scopes. Any prospective critic
comparison must use available low-view information and keep all learning,
paired-label, selection and content opportunity costs. This report authorizes
none of those new executions.

Codec D1 remains a separate pending on/off complete-allocation diagnostic. Q1
and T11 use the old rowwise twelve-code output profile and previously selected
models. New cached-profile prices, headroom, extra updates, stability or
qualification cannot be derived from these old prices. Do not normalize across
profiles or use already opened CORE information to select a new design. No
result here promises that dynamic superiority is scientifically attainable.

## Administrative provenance and cost

The direct T11 selection file had been removed after verified lossless archival;
the initial inspection raised FileNotFoundError. H1 read only its existing
`selection.json` archive member, verified against original size/hash; no raw
model was restored or executed. `ADMIN.json` records SHA256/size for every input
file, the exact member, full analysis source, argv, UTC and worker cost boundary.
All read-file hashes were verified unchanged after analysis. `execution.json`
records complete worker CPU **1.576028 s**, launcher
own CPU 0.001205131 s before final
receipt, and wall 1.577499266 s. These are
administrative R&D costs, without benchmarking or a build credit. Waited-child
CPU is not added twice. Outer startup/final receipt boundaries are explicit.

Earlier schema-inspection tool calls read the same existing files but were
outside the timed numeric worker; their CPU was not separately captured and is
not included in the 1.576028 s worker figure. No cumulative all-session CPU
claim is made.

Only this H1 directory was added; original archives, NPZ, plans, sources and
markers were not edited. No dataset construction, inference, model fit,
training, bootstrap, held-out access, merge, deployment or permission change.
All retained H1 payloads are bounded below 2 MiB and the raw Q1 arrays are
referenced by their existing hash rather than duplicated.
