# Color × joint-spatial source prior: qualification only

**17 literal tests passed; no scientific benefit evaluated.** The unique new3×4
partition separates color from the JOINT(shape,position) variable, instead of
forcing all three attributes independent. The renderer builds a spatial mask from
shape/position before choosing a color channel; this motivates a hypothesis, not
proof that posterior color/spatial uncertainty is independent or that correlation
loss caused any previous failure. No alternative partitions were swept.

Raw12-class logits,202→32 encoder, both heads, command mask and learned decoder
have exactly the old parameter inventory. The new policy is

    q(color,spatial) = marginal_color(color)*marginal_spatial(spatial)

Both normalizations and the two-factor bounded-p/m pullback follow the qualified
full-factor chain. Strict support, finite inputs, near-zero-sum virtual-logit
gradients, marginal closure and canonical integer tuple types are required;
underflow rejects without epsilon/floor/fallback. The explicit mode/profile and
digest differ from full-factor/direct modes; clone resets moments, checkpoints
are disabled. Same-rho utility and ordinary anchor remain upstream, unchanged.

This adds a known structural prior, not new FIT labels or parameters. The function
class changes; pointwise output freedom is5 versus full-factor4 and direct11. It preserves the four-state spatial joint but
discards color–spatial correlation. Equal tensors do not imply equal initial
predictions. Canonical training indices are not a decoded-semantic guarantee;
actual learned-decoder observation, transport, coupling and FIT calibration remain
required, with a canonical observed-map guard in the prospective science.

## Exact same-policy theorem and finite tests

For the SAME raw policy, setting shape OR position makes transported CS and full-
factor policies coincide, since the remaining spatial marginal is shared. Color-
only requests can retain different spatial joint dependence; allkeep can differ too.
Separately trained models generally have different raw policies, so their other
request strata need not agree. A color-only empirical pattern is descriptive,
not proof of a causal explanation.

The literal correlated witness uses color(.2,.3,.5) and spatial(.4,.1,.1,.4): CS
preserves its joint law while full factorization does not. The36-command grid
checks the equality condition on its32 shape/position-set commands for two fixed
raw policies, plus a color-only inequality witness. Other cases cover marginals,
idempotence, explicit identity/underflow refusals, same tensors/mask/decoder,
cloning, exact raw-forward work and no checkpoint I/O.

Eleven old source/full-factor tests are byte-identical; six new tests pass. New
finite differences cover48 raw-logit coordinates(max1.00e-10), eight both-head
A+ordinary-anchor coordinates(max4.92e-11), seven supervised model parameters
(max2.28e-10) and seven A+anchor model parameters(max4.04e-11), below fixed3e-8
head and2e-7 model bounds. V1 remained unexecuted; v2 completed the prospective
transport fixtures before the first run. No general floating-point proof follows.

Fully waited cost: **0.347780 CPU seconds**,0.371704 wall seconds,30540KiB RSS,
under5CPU/30wall/512MiB/4MiB, CPU0, one numerical thread and the existing synthetic
lock. Fourteen literal toy initializations and real toy updates are included.
Zero restored models, scientific models or scientific data rows; no renderer run.
Source/review, historical work and unknown supervisor tails are additional, not zero.

The planned three-arm A comparison retains direct and full-factor controls,
matched auxiliary work and original quality gates. It is not an NDU-success claim;
old failed studies and gates remain unchanged.

## Portable tests

```sh
PYTHONPATH=../factorized-source:../source-scene-decomposition:../explicit-semantic-transport:../transport-aligned-training:.. python -B -m unittest -v test_color_spatial_source
```

Only portable source/tests, the executed plan and aggregates are public. No weights,
private inputs, runtime paths, per-request predictions or unrestricted runner;
no default change, merge or deployment.
