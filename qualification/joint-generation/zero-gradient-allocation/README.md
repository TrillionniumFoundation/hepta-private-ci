# Zero-gradient work allocation: modest gains, strict NDU gate still fails

For the fixed-decoder semantic-transport service, fully specified commands have
parameter-independent final loss. Their current per-row gradient is zero, although
Adam can still move parameters through history. This experiment allocates training
rows by **request words only**, not targets, validation scores or favorable seeds.

It retains1086/1560 training rows with at least one keep axis. Each informative
batch gradient is multiplied by pi=1086/1560, preserving the original mean gradient
mathematically before roundoff/clipping/Adam. At fixed parameters and iid batchB,
the covariance reduction is pi(1-pi)E[g_active*g_active^T]/B, a positive-semidefinite
matrix. This does **not** make nonlinear Adam updates unbiased or guarantee accuracy.

## Actual result: retain the failed gate

full/informative sampling × A/N × seeds11/23,300 updates each,batch64,unchanged
lr.003/anchor.2/rho1.5/model/decoder/serving operator. Same full/low masks and
all arithmetic branches in every arm. Four full-sampling final digests exactly
reproduced the preceding aligned-training controls. All8 finals preceded validation.

| Partial-command full/low mean contrast | Seed11 | Seed23 |
|---|---:|---:|
| informative N − full N: CE gain | **+0.004787** | +0.006962 |
| informative N − full N: greedy-text change | **−2/624** | +6/624 |
| informative N − informative A: CE gain | +0.011184 | +0.017807 |
| informative N − informative A: greedy-text change | **−4/624** | +4/624 |

Seed23 passed both primary contrasts. Seed11 failed allocation's required CE gain
of.005 and greedy nonregression; its NDU increment also failed greedy nonregression.
Thus the unchanged two-seed/two-contrast primary gate remains **false**. The near
threshold is not rounded up, and a favorable seed cannot replace the other one.

Pixel MSE, correct-text probability and joint success improved in these comparisons.
The additive allocation contrast passed in both seeds, but it was a descriptive
control, not a substitute for the NDU claim. Discrete greedy outcomes continue to
trade off against mean probabilities; this study does not resolve that requirement.
Further sampling-seed,weight or threshold tuning is not justified by these results.

## Implementation and qualification

`sampling.py` accepts only the explicit command inventory and returns canonical
eligible indices plus the fixed population fraction. All-keep rows remain eligible;
an empty eligible stratum rejects. No dataset/model/target input is accepted.
`test_sampling.py` contains seven literal tests covering the36-command lattice,
mean-gradient identity,covariance identity and a nonlinear-update counterexample.
Run within this repository directory:

```sh
PYTHONPATH=../explicit-semantic-transport python -B -m unittest -v test_sampling
```

The exact previously qualified transport and aligned A/N gradients were reused
unchanged. `PLAN.md` is the pre-execution plan. `SUMMARY.json` includes every arm,
contrast,channel,population and measured cost, including all failed conditions.
No private paths,per-request data or model checkpoints are published.

## Measured cost and limits

Whole waited child: **4.530842 CPU seconds**,4.550707 wall seconds,47520KiB RSS.
Includes seven tests,imports,sampling,two restores,8clones,2400updates,7220forward
batches/471120rows,20 scalar/vector serving checks,metrics and exit. Bounds were
20CPU/90wall/512MiB,CPU0/one thread,under the same new synthetic-only shared lock.
Previous supervised-base preparation and upstream costs are not free; supervisor
tail and source/review cost remain unknown,not zero. Fixed matched work/common
caps are not equality of actual total spend.

These are exploratory reused-validation results on a finite RGB task, not new
held-out confirmation,natural-image capability or restoration of the original
unavailable digit study. No model selection,deployment or gate relaxation followed.
