# Frozen hand-only exact-fusion numerical and performance probe

No new TRAIN run, trained weights or task dataset is used. Fresh h32 parameters,
3072 deterministic hand inputs and a manually assigned12-code decoder supply
the same geometry. Only original native Adam's library and saved cost/result
JSON receipts are read. No formal data/marker is opened. The prior complete-cost
CV TRAIN failure and all12 negative cells remain. No timing result authorizes
another training run automatically.

## Algebra and numerical limits

Current logits/loss/utility and reference cache retain rho1.5 and CE.2.
Reference dt/di are .5*(p−onehot) before .2 or batch normalization. Both paths
use identical x, indices, view and request weights. Current and reference dH
have already passed their OWN tanh derivatives; reference dH is multiplied by
w/n (or1/n). Fuse ONLY the encoder pullback:

`x.T @ (dH_current − .2*dH_reference_weighted) + .2*H_CE_reference_encoder`.

Bias uses the sum of this combined dH plus its .2 mean. Head hidden_current and
hidden_reference differ, so BOTH head GEMMs remain and use their own hidden.
All mean terms are added before unchanged global norm clip5 and NativeAdam;
per-parameter moment clocks stay unchanged. The new plain control uses the SAME
common forward/objective/folded pullback implementation without CV extras.

This is exact in real arithmetic, not bitwise and not unconditional Adam numerical
equivalence. Before this cloud probe, dot reported a fixed-tolerance FAIL:
1676 checks passed/1 near-cancellation Adam comparison failed, gradient error
1.352e−16 and parameter error2.701e−11, reference SHA
2ca954c39fba6a1ac8580971e10314e28421d51f21841c91e162ad534a81ba68.
Those are parent-reported external evidence, not a locally downloaded artifact.
The original FAIL is preserved; it does not prove training unusable. Cloud bounds
are predeclared in plan.json (gradient atol1e−12/rtol1e−10, parameter
atol2e−11/rtol1e−10, moments atol2e−12/rtol1e−10) and are not loosened after tests.

## Paid hybrid, with regular/observed steps separated

Raw CV-fused is a diagnostic control and may fail numerical update comparisons.
The candidate is CV-hybrid with these fixed non-score predicates:

* Observed step1 or multiples64 uses OLD complete CV, including raw six-group
  preclip norm and corrected preclip norm. No free current encoder gradient.
* Any missing/zero content moment clock uses old CV. Empty-moment eps sensitivity
  is especially relevant; in this probe LR=.003 and eps=1e−8 imply LR/eps300000.
* A regular step with max|merged dH| <=1e−8*(max|current dH|+.2 max|reference dH|)
  falls back before fused GEMM; its guards and computed dH are still paid.
* After fused encoder/bias plus full mean, any nonzero summand scale with
  |total| <=1e−8*(|data term|+|mean term|) falls back. The already executed fused
  encoder/bias AND old two encoder pullbacks are paid. Worst late fallback can
  be slower than old CV.

These guards address declared failure classes; they are not a global rounding
error proof. Numerical tests cover24 ordinary A/N×sampler×view×state cases,
actual NativeAdam updates with empty/clock3 moments and clip-scale fixtures,
observed raw norms, plus hidden/mean cancellation controls. Every raw failure
is retained. All hybrid/legacy required comparisons must pass to proceed to timing.

Algebra-only weighted CV overhead is old976856 versus raw fused145048 units,
saving831808 per regular step. For128 updates, only125 are regular: ideal
saving103976000, not128 times the per-step saving. The implemented paths also
pay new x/y/index identity checks; hybrid pays clock/cancellation guards and
binding validation. `gradient_work`/`combine_work` declare their actual chosen
path. Three real finite scans on parameters/mean/output preserve the3E check
inventory in raw fusion; no fake operations are burned to equalize costs.
Observed steps retain the old current+reference GEMMs; only extra checks differ.

## Fixed timing and complete-budget projection

Eight cases are A/N × IID/stratified × observed64/regular65. Four modes are plain,
old CV-d2, unconditional raw fusion and paid hybrid. Four Williams waves,16 calls
per block, exactly128 blocks/2048 timed read-only gradient formations plus32
one-call warmups. No Adam update occurs in timing. Models/inputs remain unchanged;
last gradient hashes must match warmups. Old CV-d2 keeps the old trust-based
reference gather; new paths pay explicit identity checks. All raw/guard costs
are therefore included in their differences. Timing order/sample count is fixed;
retain all waves and every adverse result. Python/ledger/IO overhead outside block
timers is in whole-process CPU. Physical cap10s, declared kernel cap8B,16MiB archive.
RNG/input generation and bookkeeping are CPU costs, not hardware-FLOP claims.

Projection retains the FULL original4.025s/4.546B base receipt and FULL CV-only
.895s/1.437B reference receipt, plus old actual reference loading, service/export
and other fixed costs. New binding cost is added for all three bases. Subtract
measured gradient-only savings from old full-update CPU; report mean and the least
favorable wave, observed-step frequency, and the same OLD actually used adaptation
envelope. This transfer is conditional, including unmeasured real guard frequency
and host/optimizer effects. Compare to the equally implemented plain kernel AND
its retained368/375 update opportunities. Do not claim equivalent learning or
replace the old strongest A. No coefficient, utility or sampler selection.

## Provenance correction and terminal behavior

e9bc had a small CV-only hash-cost leak: cache.verify_inputs in common included
reference NPZ hashes, so plain paid that CPU too; it did not pay loading/pullback/
correction. New verify_partitioned moves actual CV-only hash calls to the two-CV
phase. A fake-file recipient test verifies this without reading real cache/model
arrays. Old costs are not retroactively corrected or rerun. Its committed max
delivery receipt9.922830434s is explicitly BEFORE receipt; later ≈9.926s was a
different stdout scope, not an exact closed value of that committed receipt.

Commit source/plan/bounds, freeze hashes, zero-result entry smoke, then one probe.
Keep all vectors, comparison failures, timings and receipts; mismatch/cap failure
seals the probe without relaxing tolerances or automatically retrying. No code
entry for new TRAIN exists in this package. Parent reviews actual benefit before
deciding whether a new training candidate is justified.
