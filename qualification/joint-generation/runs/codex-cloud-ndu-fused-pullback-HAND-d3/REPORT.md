# Hand-only fused CV probe: numerical fallback works on the panel, CPU gain absent

Completed once, exit0, after source `b557620174` and freeze/smoke `cc154115b7`.
Physical process CPU after terminal write **3.637093396s**, declared useful-kernel
work5,383,032,477 units, about5.94MiB retained. No TRAIN/task-data construction,
trained weight load, generation request or new training run. NativeAdam was
called only for actual one-step hand-model update checks; each such model had
at most one update. Timing itself was read-only and all model digests remained.
Original CV TRAIN failure and all12 negative cells remain unchanged.

The new source lives in `ndu_training/fused_pullback`; source/plan/bounds were
frozen BEFORE any cloud numerical result. No tolerance or guard was changed
after inspection. All gradient vectors, raw failures,128 timing blocks and four
Williams waves remain. No repeat or subset selection followed.

## Numerical result and preserved FAIL

All24 ordinary objective/state/sampler/view cases passed the fixed gradient
checks. Maximum ordinary gradient error was7.8063e−18; maximum hybrid one-step
parameter error2.6021e−15. Actual Adam tests included empty/clock3 moments and
clip fixtures. Observed steps preserve original raw/corrected six-group norms
using the OLD full CV path; they do not get a free current encoder gradient.

Unconditional raw fusion **FAILS** the declared parameter tolerance in the hand
mean-cancellation/empty-moments fixture:6 coordinates fail, max2.4980018e−11,
despite gradient error8.3266727e−17 passing its1e−12/1e−10 bound. The hidden-
cancellation fixture's raw parameter error6.9916e−12 passed this cloud bound;
that does not overwrite dot's different fixed-fixture FAIL2.701e−11.

The predeclared hybrid chose empty-moment, hidden-cancellation or mean-
cancellation fallback as applicable. Those adversarial update differences were
zero against the old path on this panel. This is conditional panel evidence,
not a global numerical equivalence or bitwise claim. For unclipped first Adam
with empty moments, update is LR*g/(|g|+eps); its maximum sensitivity is LR/eps.
Here actual LR=.003 and eps1e−8 give300000, explaining why8.33e−17 gradient
reordering can create2.50e−11 parameter change. A strict numerical FAIL alone
does not establish that engineering use is impossible.

## Real work saved, regular and observed separately

The head hidden states differ, so both head GEMMs remain. Only the redundant
dense reference encoder GEMM `[202,64]@[64,32]` is removed on eligible regular
steps:413,696 MACs. Bias merges the already tanh-pulled and weighted dH sums;
all.2 full-reference means remain BEFORE unchanged norm clip5/Adam clocks.

| Weighted N,32 low rows | Declared gradient units, no Adam |
|---|---:|
| Regular plain, same common implementation | 1,516,176 |
| Regular old CV-d2 | 2,493,032 |
| Regular unconditional raw fusion, including new identity checks | 1,674,344 |
| Regular hybrid, including all guards/checks | 1,745,107 |
| Observed old CV-d2, two preclip norms | 2,522,190 |
| Observed hybrid, old path plus identity checks | 2,535,310 |

Algebra-only CV overhead976856→145048 saves831808 per regular step, matching
dot's static inventory. New identity checks cost13120 and hybrid guards70763
units, so actual declared regular hybrid saving is747925; observed hybrid costs
13120 MORE, with no encoder-GEMM saving. Thus128 updates (125 regular/3 observed)
save93,451,265 units/model under no extra cancellation fallbacks, rather than
128 times a regular-step saving. Late cancellation fallback also pays the fused
encoder work already executed before recomputing the old two pullbacks.

All16 regular hybrid timing blocks actually fused; all16 observed hybrid blocks
used the old path. The reported negative speed result is not caused by hidden
regular fallback frequency in this hand panel.

## CPU measurement and complete-budget opportunity

Exactly2048 timed read-only gradient calls,128 blocks, four Williams waves,32
one-call warmups. Every case remains. Means below average both samplers/four
waves, milliseconds/call; no independence or formal inference is asserted.

| Arm/step | Equally implemented plain | Old CV-d2 | Raw fusion | Paid hybrid |
|---|---:|---:|---:|---:|
| A regular65 | .4708 | .7510 | .7491 | .9085 |
| N regular65 | .8788 | 1.0729 | 1.1983 | 1.3311 |
| A observed64 | .5672 | .7760 | .8394 | 1.0038 |
| N observed64 | .7027 | 1.0467 | 1.2577 | 1.0569 |

Saved declared operators did not yield CPU improvement. Raw A's near-zero
average saving is not replicated by N; hybrid is slower on both means. Dispatch,
allocation, checks and host drift remain possible contributors, not an isolated
causal finding. Do not remove guards/norm observations or pick a faster wave to
rescue the candidate. Hybrid/plain regular CPU ratios are1.93(A)/1.51(N).

Conditional forecasts retain full4.025s/4.546B base history, CV-only.895s/1.437B
reference history, actual.052s reference loading, old service/export/common
costs and add three new bindings(.01168s/5,367,144 units). Use the SAME old actual
adaptation envelope and account for observed steps. This is a projection from
hand kernels into old full-step costs, not a new training result:

| Arm | Old CV updates/candidate | Mean-time projected hybrid | Least-favorable-wave projection | Retained plain |
|---|---:|---:|---:|---:|
| A | 187 | 170 | 144 | 368 |
| N | 180 | 157 | 133 | 375 |

Operator-only projections would allow472/470, but the unchanged10s CPU cap
binds first under measured timing. Real guard frequency, optimizer transfer and
host behavior remain unmeasured. Old CV-file hash leakage is NOT retroactively
credited to plain. This NumPy hybrid therefore **does not justify another TRAIN
candidate now**. Numerical admissibility and operator savings are useful findings;
they do not establish full-budget speed or generation improvement.

The partitioned verifier's fake-file test confirms that CV-only hash calls now
have only A-CV/N-CV recipients; no real cache was rehashed by that test. It is a
future integration helper, not a claim that a new TRAIN runner has executed.
The separate d2 erratum preserves its exact BEFORE-receipt9.922830434s boundary.
No formal confirmation/alpha was opened or reset. No permission/resource blocker;
the present implementation's performance is the limiting evidence.
