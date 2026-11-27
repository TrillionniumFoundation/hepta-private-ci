# Parent-preserving split routing: executed increment

Parent: `6cae51e0a3a89292b9099e689f450f84c16b8dc0` (PR #1721).
Tested final code: `c028bf12297e2cfbbb6b2d145390d055af1439e3`.
Branch: `research/shared-stem-parent-preserving-split-20261013`.
Research-only candidates. No main merge, history rewrite, native topology
installation, selected-model mutation or production authorization.

## Routing repair and exact scope of preservation

The previous flat top-k clones can select both siblings of one parent and displace
another parent's contribution. The previous policy and its observed nonzero drift
remain available as `hepta.cell-growth-policy.v1`; old results are not relabeled.

`family_routing.py` implements opt-in policy V2. Select the top two parent groups
using the original 16 parent logits, then one child per selected group using a
binary sibling contrast. Group mass and parent-index accumulation order remain.
The existing 32-row gate contains 16 parent logits and 16 sibling selectors;
there are no added/dummy stored parameters relative to the matched direct-32 bank.
Only two Heads per request execute at inference. Parameter gathering and routing
still consume temporary memory/time; parameter equality is not equal total cost.

Let S(x) be the parent's selected groups, p_g(x) their softmax weights and f_g(x)
the original Head. At initialization, f_(g,0)=f_(g,1)=f_g. For any sibling selector
b_g(x) in {0,1}, with unchanged parent logits and tie ordering,

    sum_(g in S(x)) p_g(x) f_(g,b_g(x))(x)
      = sum_(g in S(x)) p_g(x) f_g(x).

This elementary substitution is an initialization identity in REAL arithmetic,
not a general floating-point guarantee or a guarantee after subsequent learning.
The router retains parent GEMM geometry; child sample subsets can nevertheless
change kernel rounding. A bounded numerical check therefore runs on all admitted
training probes (at most 4096, in chunks of 64) before post-split training:

    max |child-parent| / (atol + rtol*|parent|) <= 1.

The numerical tolerances are frozen before execution. Failed parity abandons the
candidate and records `transition_parity_failed`, expected tasks and actual work;
no successful prediction seal is emitted. Exported preservation claims include
the initialization-only scope, sample count, both tolerances, maximum error and
maximum tolerance ratio. They explicitly deny a global float-parity certificate.

## Sibling specialization is actually trained, with its extra work charged

Hard sibling selection has no ordinary pathwise derivative. It is not silently
called a differentiable gate. A training-only auxiliary classifier evaluates both
siblings for each selected group under no_grad, then learns which sibling has the
lower individual correct-label log loss. Pairs within a fixed 1e-6 loss margin
supply no preference target. Nonfinite counterfactual losses reject rather than
being silently treated as an uninformative tie. The ordinary task loss trains
selected Heads and parent mixture weights; the separate auxiliary loss trains
the sibling selector. No straight-through gradient is introduced.

This local target is not a joint-policy advantage, unbiased policy gradient, NDU
credit estimate or proof of improved future utility. It can still overfit or create
load imbalance. It uses only training rows; evaluation inputs/labels cannot choose
growth or supply sibling targets. Metadata/digests alone do not prove source or
observer authenticity, semantic nonleakage or OS isolation.

Two extra sibling calls per selected group mean four EXTRA Head/row evaluations
per training sample. Those calls are separately counted and use the existing live
ATen meter. They are not disguised as free work or folded into the inference
activation cap. Both split and grouped direct controls use the same auxiliary
rule, optimizer-reset boundary and bound protocol. Final counts still match;
initial capacity and learning curriculum still differ. Common lifecycle caps
include simultaneously live predecessor/successor model parameters, not gradients,
optimizer, activations or Encoder storage. No resource-efficiency gain is claimed.

## Use the existing bound pipeline, not another experiment wrapper

The existing matrix_growth/matrix_runtime paths construct FamilyCellBank only for
an explicit V2 growth policy. Configuration remains V4 with this separately
versioned nested policy, covered by the existing configuration/protocol hashes.
Old policy V1 keeps its algorithm. Supply the same policy to the corresponding
non-NDU split and sparse direct-32 controls; the 64M controls remain available.

```python
growth_policy = {
    "schema": "hepta.cell-growth-policy.v2",
    "decision_step": 8,
    "loss_threshold": 0.7,
    "minimum_source_groups": 16,
    "gate_noise_scale": 0.001,
    "sibling_loss_weight": 0.1,
    "transition_atol": 1e-6,
    "transition_rtol": 1e-5,
}
```

These values illustrate the format, not validated tuning defaults. Keep the
required measured configuration, even width_units, common lifecycle contract and
more training steps than decision_step. Use the existing freeze_config and
matrix_runtime/matrix_export/paired_execution entry points. Fixed-16, replicated
and NDU arms are not silently mapped to the new grouped profile. Paired exports
reject flat/family training-protocol mismatches. Safetensor reload tests explicitly
reconstruct the bound family geometry; generic same-shaped flat CellBank loading
is NOT a supported semantic conversion or native recovery qualification.

## Verification actually completed

The unchanged predecessor passed 142 tests. The routing-only staged source passed
157 tests. Final source passed 165 tests twice, zero failures/errors/skips: all
142 retained, 15 new routing/training and 8 new seal/export integration tests.
Tests exercise hostile sibling scores, parent ties, selected-subset execution,
independent tensors, actual selector gradients, post-split child divergence,
nonfinite counterfactuals, pre-allocation caps, transition failure fencing,
checkpoint roundtrip, protocol mismatch and complete paired-audit integration.
The synthetic pair stays blocked for non-pretrained execution and missing costs.
No arithmetic registry or CI gate was weakened; existing CI discovers new tests.

The independently rerun synthetic diagnostic compares flat and parent-group
split/direct controls with real tiny PyTorch training. Both split/direct final
banks contain 896 parameters; live model peaks are 1344 versus 896. In this single
small training fixture the flat split's initial maximum logit change is
0.3348206877708435 and the grouped split's is 0.0. An additional 27 seeded geometry
checks (747 inputs) all satisfy the numerical gate; maximum observed absolute
error is 1.7881393432617188e-7. These are NOT pretrained 421M experiments,
independent task outcomes, latency benchmarks or lifelong-learning evidence.

The three early strict-meter failures (to.dtype, slice_backward, select_backward)
are retained in the downloadable evidence. Boolean and indexed gather/scatter
paths removed those unnecessary overloads; the existing meter was not relaxed.
The separate installed-HF check was attempted and failed at import because
Transformers is absent: zero of its three checks executed. It is not included in
165 passes. Direct repository DNS also failed. No actual pretrained model,
project-cloud/GPU/native/full-repository/Rust/remote-CI result is claimed.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
```

Exact source IDs, log hashes and diagnostic summary are retained beside this file.
The downloadable package includes raw passing/failing logs and diagnostic source.
Remaining: real approved weights/data and independent observer costs/authenticity,
request memory/energy, future-task and old-task retention, selective multi-generation
split/merge/pruning, NDU/System2 and native owner integration, multimodal generation,
and native 1024/4096-Cell serving/recovery. Initial parity does not close these gates.
