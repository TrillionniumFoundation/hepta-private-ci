# Use the zero-friction-safe stationary operator

Import StablePublished from the repository package qualification.hcsn_query_intervention_20261127.resonance. The standard module call returns (equity, hit). The named channels method also returns the endogenous boundary and discounted first-hit mass. An existing he_xiong.Law object or the standalone StationaryLaw dataclass can initialize it.

```python
import torch
from qualification.hcsn_query_intervention_20261127.resonance import (
    StablePublished, StationaryLaw,
)

law = StablePublished(StationaryLaw(premium=0.0))
premium = torch.tensor(0.0, dtype=torch.float64, requires_grad=True)
principal = torch.tensor(61.68, dtype=torch.float64)
asset = torch.tensor(75.0, dtype=torch.float64)
boundary = law.boundary(principal, premium=premium)
margin = torch.log(asset / boundary)
channels = law.channels(margin, principal, premium=premium)
d_equity_d_premium, = torch.autograd.grad(channels.equity, premium)
```

A fixed construction premium precomputes tensor constants and the coefficients of the affine boundary in coupon and principal. Passing an explicit premium tensor selects the fully differentiable divided-difference evaluation. A tensor batch of premia broadcasts with the margin and principal. The caller specifies whether a derivative holds asset value or log margin fixed. All floating point valuation tensors use FP64. Move the module to the caller's device; casting its constants to reduced precision is outside the qualified configurations. The numerical and throughput qualification here used CPU.

For a **new copy** of a loaded positive-premium native cell, its usual forward entry and its trained neural weights can be retained.

```python
from copy import deepcopy
from qualification.hcsn_query_intervention_20261127.resonance import replace_published

candidate = replace_published(deepcopy(existing_cell))
output = candidate(input_frames)
```

replace_published updates only the selected copy's law attribute. It initializes the reference buffers from the stable law and preserves the original cell's neural parameters, operating mode, device and mask. The original qualification trials and model seals are immutable. The state dictionary of the new law accepts the native law's five legacy buffer names in strict mode; for a near-zero legacy checkpoint use the copy-and-replace path so inaccurate legacy reference values are regenerated.

## Domain, endpoint and gradients

The public interface checks finite, strictly positive risk-free rate r, payout rate δ, volatility σ, maturity m and principal P, nonnegative coupon C and incremental liquidity yield κ=q−r, recovery α between zero and one inclusive, and tax benefit in [0,1). The constructed reference free boundary must be positive. Log margin x can be any finite real and the stopping extension returns E=0, F=G=1 for x≤0. Finite-horizon passage and reset transport require a positive finite horizon. Runtime tensor validation can be disabled using validate_args=False when callers independently enforce the same domain; this is useful for inner loops and batched differentiation. A negative formal yield increment used to measure the analytic left derivative below is rejected by this physical interface.

The numerical qualification sampled κ from 0 to .5, maturities .1 to 5, volatilities .15 to .4 and interior log margins 1e−5 to .4, with the wider 81×12 standard table tested to x=1.3. The legacy regression also varies principal 50–78 and margins .001–.8. This scope is finite; no arbitrary-extreme FP64 overflow bound is implied.

| Quantity | At κ=0, fixed x=.1 | Physical right derivative | At κ=0, fixed V=75 | Physical right derivative |
|---|---:|---:|---:|---:|
|Boundary B|65.048403|+240.143374|65.048403|+240.143374|
|Equity E|4.084713|−21.343451|7.657932|−383.833106|
|Hit F|.621039|0|.487725|+10.802787|
|Discounted hit G|.607110|−.170761|.473327|+10.584473|

These reverse-mode derivatives agree with one-sided fourth-order finite differences of the independent Green reference on the physical κ≥0 side to max absolute 1.25e−9 in both coordinate conventions. Extending the equations to small negative κ while q stays positive gives the same mathematical derivative from the left; independent left checks differed by at most 2.32e−9 at fixed x and 9.73e−9 at fixed V. Only the right direction represents increasing liquidity friction from zero.

At the historical κ=.01, native and stable B/E/F agree to 6.4e−14/4.4e−13/1.2e−16 over the tested input vector. Native and stable equity gradients with respect to log margin and principal differed by at most 2.96e−12 and 9.05e−15. Running the original LiteralCell code on 15 frames and four samples with identical initialized weights gave max output difference 1.29e−14, input-gradient difference 2.11e−15 and maximum difference across all neural parameter gradients 2.99e−13. The same cell with zero premium produced finite outputs and gradients. The regression used seeded test weights rather than a new task-training result. The module also passed strict legacy buffer loading, a 3×4 trainable-premium/principal broadcast and construction under torch.inference_mode().

The derivative of the hit probability with respect to initial margin at contact remains one-sided. The removable singularity fixed here pertains to liquidity yield in the financial coefficients.

## Cost of switching the normal cell path

At κ=.01, for 32×12 FP64 values, the native path took 0.302 ms CPU / 0.327 ms wall, the fixed-law stable specialization 0.466 ms CPU / 0.498 ms wall, and the fully differentiable variable-yield path 2.316 ms CPU / 6.212 ms wall. For an actual 15-step, four-sample LiteralCell forward plus backward, native took 24.598 ms CPU / 85.926 ms wall and stable 29.660 ms CPU / 106.186 ms wall. The validation used single-thread CPU, warm-up, 21 operator replicates and seven cell replicates. Checkpoint weights were identical, whereas hardware scheduling was shared. The 283.6× improvement against scalar numerical quadrature in RESULTS.md must not be interpreted as a speedup over the already-analytic native positive-premium cell. Across the separate 80-case grid the cached fixed-law path differed from the Green equity integral by at most 1.76e−12.
