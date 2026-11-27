# Fixed-width Q24 Cell capacity feasibility: negative preflight

**Status:** RESEARCH ONLY / `DENY_ALL` / no model selection or production writes.

## Exact source and original observation

This is a read-only mathematical tensor-census preflight based on original
`matched_train.py` blob `0f0c4f595639c077459120785d2daeeec2ce6eda`.
It does not change the training runner, Rust Q24 kernel, model identity, A0
signed deployment owner or NDU decision executor.

Existing [physical shadow run 38667249963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38667249963)
produced 20 named file positions from four mechanisms and five nominal ceiling
labels. The independently reviewed physical artifact's ZIP SHA-256 is
`9c871918e306f6f0fa0c6f3864bd75ff9271df3829ce8b58108618fc99e93995`.
Those 20 slots had only **five different weight hashes**, not 20 independently
realized model capacities. The report [PR #2163](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2163)
retains the actual physical provenance; this preflight adds the fixed-width
mathematical explanation and a lightweight executable **stop-before-training**
check, not a replacement physical-receipt evaluator.

## Why five equal physical tiers cannot exist in the current trainer

For a fixed registered Q24 feature width `w`, the original training
`structure.projection` saves `w` scalar weights and the existing binary
private `head.weight+bias` saves `w+1`. Its exact private counts are:

| Arm | Private scalars, including projection and Head |
| --- | --- |
| V2 | `2*w + 1` |
| V3 | `5*w + 1` |
| Diagonal SSM | `4*w + 1` |
| Low-rank minGRU | `4*w*rank + 4*w + 1` |

The current trainer varies minGRU rank as
`min(w, (cap - (w+1) - w - 2*w) // (4*w))`, but holds `w` fixed
for every candidate. V2/V3/SSM **never increase their trainable tensor
count** when the cap rises. Moreover, for every positive common `w`,
`2*w+1`, `5*w+1`, and `4*w+1` cannot all be equal.
Therefore the claimed *four-arm, five-tier, equal-realized-parameter* study
is **mathematically impossible under this exact original geometry**.
This is not a limitation on all future model architectures.

Example with the original 32D trace:

| Nominal max private parameters | V2 | V3 | SSM | minGRU |
| ---: | ---: | ---: | ---: | ---: |
| 2,048 | 65 | 161 | 129 | 1,921 |
| 8,192 | 65 | 161 | 129 | 4,225 |
| 16,384 | 65 | 161 | 129 | 4,225 |
| 65,536 | 65 | 161 | 129 | 4,225 |
| 262,144 | 65 | 161 | 129 | 4,225 |

Thus 20 slots collapse to **5 distinct parameter geometries**.
Independent weight SHA, original training source, fresh execution and equal
data/computational exposure are **separate** qualifications, not proven by
parameter arithmetic.

## Executable controls and evidence limitations

```sh
python -m unittest discover -s qualification/neuron-gated-sparse-v3 -p 'test_capacity_feasibility.py' -v
python -O -m unittest discover -s qualification/neuron-gated-sparse-v3 -p 'test_capacity_feasibility.py' -v
python qualification/neuron-gated-sparse-v3/capacity_feasibility.py --width 32 --trainer-source qualification/neuron-gated-sparse-v3/matched_train.py --output /new/write-once-geometry-review.json
```

The preflight script can run without `--trainer-source`, but labels the
result as **not source-blob-verified**. Passing the original source requires
its exact Git blob and refuses missing, symlinked, modified or too-large input.
The output always denies production promotion and NDU eligibility.
The repository's existing `hepta-neuron-gated-v3-shadow.yml` workflow
discovers the new test file under its A0 negative-tests stage; no second
model loader, trainer or CI acceptance owner is introduced.

The separate local Python 3.13 execution of 11 focused tests passed in
normal and optimized mode. Exact local Git blobs match uploaded files:
`c58885529cabfd9cbd265bed289219ba4ec36085` (implementation) and
`b685bdfdbd40fd8c3dc1a2f92d51e92a7a817cce` (tests).
**These local tests do not physically load pretrained models or reproduce
production A0**, and hosted exact-commit checks remain separately required.

## Scientifically useful next action

Keep original V1 as the frozen baseline. Either (a) redesign each arm's
**actual** hidden-state/adapter capacity and its native Q24-compatible
projection so physically materialized same-budget weights are possible,
accounting for projection and memory overhead, or (b) abandon misleading
five-tier head-to-head claims and compare **different-size models along a
measured quality-vs-whole-lifecycle-cost Pareto frontier**. Require actual
independent tensor SHA, original data/control fidelity, future utility, and
target-host resource receipts. Never promote an architecture for possessing
a larger named ceiling.

**DRAFT / DENY_ALL / NO_MAIN_MERGE / NO_CELL_SPLIT / NO_CNS_CUTOVER.**
