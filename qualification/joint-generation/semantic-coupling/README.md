# Semantic coupling improves consistency without changing marginal content

An explicit maximal-agreement joint serving law passed all four fixed content-control
comparisons. **The original NDU-versus-additive gate still failed under both serving
laws.** This is a structural dependence change, not newly learned capability.

## Target-free operator

After existing explicit-word semantic transport, place min(p_s,q_s) on each pair
whose actual observed decoded semantics match. Couple remaining disjoint semantic
residuals by their normalized product. This attains the maximum possible agreement
given the two marginals. No target, reward, source image or new decoder is accepted.
Every marginal distribution, including unspecified attributes, is preserved
mathematically. Original independent serving remains unchanged and available.

The new profile has distinct schema/mode/identity and explicit model-bound loading.
The scalar sampler consumes a supplied uniform variate over the joint table CDF.
Raw and CDF-normalized marginal errors are separately checked against1e-12; invalid
mass rejects rather than receiving an epsilon repair. This is numerical preservation,
not bitwise identity. An arbitrary standalone sampler table has no external marginal
guarantee. Marginal greedy scores and joint MAP scores are reported separately.

## Actual paired results

Four original aligned A/J models,seeds11/23,were reconstructed and exactly matched
their predeclared digests. All four finals preceded validation. Each model was then
evaluated under BOTH services, with no coupling-specific training or decoder change.

For the original joint-NDU models on partial commands,macro(full,low):

| Metric | Seed11 independent → coupled | Seed23 independent → coupled |
|---|---:|---:|
| Cross-modal consistency | 95.33% → 99.54% | 95.47% → 99.38% |
| Joint success | 94.14% → 96.25% | 94.43% → 96.38% |
| Original joint CE | 0.919843 → 0.946710 | 0.920915 → 0.947328 |
| Text marginal and greedy score | unchanged | unchanged |
| Pixel MSE | unchanged to roundoff | unchanged to roundoff |

Both additive-model comparisons also passed the preregistered control gate. Maximum
CDF-normalized marginal error was8.12e-16. Joint success and agreement gains are
structural consequences of coupling, not evidence of improved learned representations.

NDU−A under coupling still improved joint CE by+.009833/+.011853, but seed23 retained
its **−1/624 greedy-text regression**. Therefore both independent and coupled NDU
two-seed gates remain false. A successful control feature cannot erase that failure.

Scores enumerate the full actual12x12 joint law using observed decoded strings and
learned pixels. The original exponential utility is evaluated on that law, not on
the product of its marginals. These are finite-law expectations, not Monte Carlo
sample estimates;36 fixed sampler draws check support only.

## Qualification and cost

`coupling.py` contains the opt-in profile and supplied-uniform sampler.
`test_coupling.py` has eight tests covering equal/disjoint/overlapping support,
permuted decoder semantics,all36commands,distinct identity/roundtrip,positive CDF
intervals and invalid inputs,including the near-normalized mass counterexample.

```sh
PYTHONPATH=../explicit-semantic-transport python -B -m unittest -v test_coupling
```

Whole waited child: **3.698424 CPU seconds**,3.714473 wall seconds,48748KiB RSS.
Includes tests,2restores,4clones/1200updates,3612forward batches/236592rows,
2decoder observations/24images,6192joint tables/891648entries,12384raw plus12384
normalized marginal checks,6192agreement checks,6roundtrips and36draws. No extra
decoder calls were needed for coupling. Limits20CPU/90wall/512MiB,one pinned thread,
under the existing new synthetic-only shared lock; complete wait4 retained.

Across6192requests, scalar coupling/transport/binding/table paths cost **1.175713 CPU
seconds**, versus **0.004174** for vectorized independent table formation. These are
different implementation paths,not matched kernels. The extra work is not free;
same paired model and common caps are not equality of actual total spend. Historical
base preparation,source/review and supervisor tail remain additional,not zero.

`PLAN.md` is the pre-execution plan;`SUMMARY.json` retains all models,laws,channels,
populations,contrasts and costs. Reused finite-RGB validation is exploratory,not fresh
held-out confirmation,natural-image capability or original digit-study recovery.
No TEST data,private inputs,model payloads or per-request outputs are published.
