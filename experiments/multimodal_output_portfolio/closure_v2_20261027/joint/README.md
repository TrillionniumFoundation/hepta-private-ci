# Direct actual-output gradient: implemented, audited, not promoted

The stochastic generator and its actual PNG/UTF-8 reward gradient are operational.
The one frozen new-source qualification **did not establish a generator gain,
retention noninferiority, or risk-specific advantage**. All four acceptance gates
remain false. The prior selected `joint_uniform` checkpoints remain the deployment
baseline. A correct gradient estimator is not evidence of useful generalization.

## What changed

Each of the three fixed seeds starts from its previously selected strong
`joint_uniform` model. The encoder, two selected transitions, decoder, gate and
reward recognizer are frozen. A 19,068-parameter public-state MLP learns the mean
of a 12-dimensional Gaussian residual in a fixed PCA basis of terminal states.
The sampled residual changes the state passed to the real neural decoder.
Deployment samples that same Gaussian, rather than substituting its mean.

For an actual serialized and reopened output bundle with utility `U`, the two
matched training objectives are `-U` and `(exp(-2U)-1)/2`. Both use the same data,
noise draws, source schedule, optimizer, complete candidate grid, clean Gaussian
KL coefficient and validation budget. The antithetic estimator is

\[
\widehat{\nabla_\mu E[c]}=
\frac{1}{2K\sigma}\sum_{k=1}^{K}
\left[c(\mu+\sigma\epsilon_k)-c(\mu-\sigma\epsilon_k)\right]\epsilon_k.
\]

It differentiates the Gaussian expectation of actual delivered outcome cost.
There is no reward-CNN derivative or straight-through PNG quantizer. It is
unbiased conditional on the current training batch/condition before clipping.
It is not an unbiased derivative of the log certainty equivalent itself, and
Adam/clipping are not unbiased updates. Training deterministically cycles four
conditions with balanced exposure; the original protocol's wording “equal
probability” is corrected explicitly in the qualification contract. The clean
KL compares the shifted Gaussian with its zero-mean counterpart at the same
sigma, not with the deterministic original decoder.

The data remain constructed MNIST image/text tasks. This is a latent generator
update, not a demonstrated end-to-end update of a natural multimodal foundation
model or of the original decoder weights.

## Frozen development and source boundary

After a separately retained 100-step pilot, both objectives completed both
predeclared development sigmas, 0.15 and 0.05: 600 steps per run, 1,200 steps per
objective per seed, seeds 17/29/43. Every step uses 16 examples and eight paired
directions, hence 256 actual PNG/UTF-8 outcomes. The two full grids contain
1,843,200 training deliveries; the pilot adds 51,200. Individual training PNGs
were scored after actual codec roundtrips but were not all retained. Checkpoints,
optimizer states, output-stream hashes, paired cost/gradient arrays, sources and
RNG contracts are retained. Do not call those hashes a full original media archive.

There are 30,720 full-grid validation deliveries. PCA is physically computed
once per seed per sigma on 512 historical examples and shared by the two arms;
counting it twice would overstate work. Training CPU/wall were measured. Original
PCA/validation timings were not separately measured, so a complete study CPU total
is not asserted. Inference actor calls are recorded as zero or one per output;
equal training budgets do not imply identical measured inference CPU.

Selection maximizes historical validation CE among retention-eligible candidates.
It uses the unchanged original model when no candidate improves validation.
The risk arm for seed 29 selected that explicit fallback. Consequently the
predeclared all-seed strictly-positive gate could not pass; this was documented
before qualification and the gate was not relaxed.

Qualification uses 512 new source pairs across four conditions and 256 disjoint
clean retention pairs. Official label/image hashes, cardinality, duplicate pixels,
source identities, cross-study disjointness, sigma, basis, actor configuration,
candidate/aggregate equality and training-checkpoint hashes are checked before
prediction. Its corruption and generation RNG namespaces differ from validation.
The seal includes both complete training runs, their executed source hashes,
selection hashes, budget hash and the actual 1,200-step total.

## New qualification result

All intervals below are paired 97.5% source-pair bootstrap intervals, conditional
on the three fixed training/noise seeds. The estimand averages the three seed CEs;
it does not pool their exponential moments into a different risk functional.

| Contrast | Test CE difference | Paired interval | Clean retention CE difference | Retention interval |
|---|---:|---|---:|---|
| Direct risk minus original | -0.004180 | [-0.010147, +0.001739] | -0.006429 | [-0.033094, +0.019835] |
| Direct risk minus zero-actor control | -0.000444 | [-0.006155, +0.005418] | -0.009964 | [-0.034001, +0.008003] |
| Direct risk minus matched direct mean | +0.001563 | [-0.006675, +0.009560] | +0.010798 | [-0.003885, +0.025721] |
| Direct mean minus original | -0.005743 | [-0.015163, +0.003651] | -0.017227 | [-0.051472, +0.013911] |

The retention margin remains -0.01. The risk-vs-mean retention interval clears
that margin, but its quality and all-seed gain requirements fail. No candidate is
promoted from these results. No new test result was used to select weights, sigma,
checkpoints, conditions, intervals or another qualification cohort.

Machine-readable evidence: [qualification result](results/QUALIFICATION_RESULT.json),
[seal](results/QUALIFICATION_SEAL.json), [grid](results/GRID_COMPLETED.json),
[selected models](results/GRID_SELECTIONS.json), and
[complete budget accounting](results/BUDGET_ACCOUNTING.json).

## Verification

Three behavior tests validate a discontinuous-output Gaussian derivative against
an independently integrated analytic oracle, reject private targets at the public
generation boundary, and reject unpaired cost grids. The actual-file preflight
rejected seven mutations: changed density/basis, source reuse, repeated sources
despite an updated manifest digest, changed official labels, an unsealed candidate
report and an altered scored checkpoint. Original development bytes remained intact.

A separate reviewer reconstructed 18 saved-state training probes: 4,608 actual
PNG/UTF-8 bundles, 9,216 media members. Maximum cost error was 3.06e-8 and coefficient
gradient error 1.89e-7. Because saved checkpoints are 200-step multiples, these are
clean-condition steps 1/201/401, not a verification of every unretained training image.

The qualification audit reopened all **27,648 actual bundles / 55,296 members**
from 864 closed ZIP containers, independently parsed official source pixels and
labels, reconstructed task swaps, rebuilt both frozen observer networks and
recomputed semantic/pixel utility without importing the experiment scorer.
Maximum score error was 1.34e-8; independent interval error was 6.18e-16.
All 2,304 declared fallback outputs were byte-identical to the original model.
No generator prediction or parameter update was performed by that readback audit;
it did run the two frozen metric recognizers on the archived media.

See [preflight](results/PREFLIGHT.json), [gradient probes](results/GRADIENT_PROBE_SUMMARY.json)
and [full readback audit](results/INDEPENDENT_AUDIT.json). The fitted recognizers are
imperfect task metrics, not human semantic certification. Neither writer-population
nor training-seed-population inference, nor global portfolio optimality, is claimed.
