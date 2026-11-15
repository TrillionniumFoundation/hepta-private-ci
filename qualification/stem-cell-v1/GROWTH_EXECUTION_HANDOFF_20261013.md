# Bound population growth: executed source and remaining acceptance

Parent: `8aa4a71664e11ff29916f1c8904fdf69f055cf3c` (PR #1718).
Tested code: `27a7b790affe81f19a0b39d3b31b71b066990f61`.
Branch: `research/shared-stem-adaptive-split-20261013`.
Research only. No main merge, production selection, topology installation or
modification of historical results.

## Actual training path

`matrix_growth.py` is called by the EXISTING bound runtime, not an isolated demo.
At one preregistered training step, inspect mean training cross-entropy and the
number of distinct supplied training source groups. Only a residual above the
fixed threshold with sufficient groups triggers a 16-to-32 population split.
The decision consumes no evaluation inputs or labels. Group IDs and timestamps
remain externally supplied lineage, not an independence or authorization proof.

The parent starts with the final child Head width and half the final parameter
count. Growth physically creates 32 independent Heads, clones each parent into
two children and perturbs only new gate rows before continued training. No unused
32-Cell slots are counted as a prior 16-Cell model. The final bank has the same
actual parameter count as its directly initialized 32-Cell control at the same
feature width/configuration. The 64M-budget variant doubles actual capacity.

This is one residual-triggered POPULATION generation, not selective per-Cell
lifelong topology optimization. Growth still changes the training curriculum and
initial capacity. There is no claim of a pure final-graph causal effect or of
independent future improvement from a training residual.

Both split and direct controls perform the same training-only probe and reset
the optimizer at the same fixed boundary. Two training stages use the same
minibatch seed schedule. Optimizer reset, steps, examples and optimizer tensor
bytes are explicit; equal steps do not establish equal physical work.

Initial allocation and simultaneous parent/successor parameter counts are
preflighted before allocating the corresponding bank. Parent tensor digests
remain unchanged by splitting. Model-weight bytes exclude gradients, optimizer
state, activations and the frozen Encoder; they are NOT full process memory.
The old parent remains live during candidate training and is counted accordingly.

Flat top-k clone routing is NOT function preserving: siblings can displace other
parents. The transition records parent/child lineage and the training-probe max
logit change instead of claiming zero-delta equivalence. Subsequent trained child
weights actually diverge in the tensor tests. A better transition and independent
retention tests remain necessary before any selected/native topology change.

## Versioned controls and integration

Contract V2 adds a common `max_peak_trainable_params` ceiling. Final actual
trainable counts still match, while unequal transition peaks must fit that SAME
preregistered ceiling. A no-split control need not allocate useless copies to
match a growth transient. Contract V1 keeps its original peak-equality semantics.

Pass an explicit growth policy to `freeze_config` to select config V4:

```python
growth_policy = {
    "schema": "hepta.cell-growth-policy.v1",
    "decision_step": 8,
    "loss_threshold": 0.7,
    "minimum_source_groups": 16,
    "gate_noise_scale": 0.001,
}
```

Those numbers are an illustrative configuration, not validated tuning defaults.
Freeze actual choices before a run. Supply more training steps than decision_step,
an even width_units >= 2, a real bound measurement policy and contract V2. The
existing local Encoder profile may also be supplied. Use the SAME growth policy
and training protocol for the matching sparse direct-32 control. The existing
matrix_runtime/matrix_export/paired_execution CLIs remain the entry points.

The two non-NDU split arms are now executable under V4; V1/V2/V3 still reject
split. NDU and replicated-Encoder arms remain unsupported by this executor.
Non-triggered growth emits GrowthNotAdmitted with its actual training diagnostic;
run_bound writes FAILED and the task inventory, not a completed 32-Cell seal.
Migration work is recorded by the existing live meter. Budget stops propagate;
there is no post-hoc replacement of actual work with a nominal estimate.

Execution V2 and paired export V2 preserve actual transition peaks, lineage and a
training-protocol digest covering snapshot, workload, seed, steps, batch, width,
context and measurement/reset policy. The exporter rejects inconsistent or
criterion-violating growth records. The pair audit rejects different protocols.
Content hashes do not authenticate observers or establish outcome independence.
Missing evaluation costs, energy and request-peak memory still block efficacy.

## Verification actually performed

The unchanged predecessor passed 120 tests. Final code passed 142 tests twice,
zero failures/errors/skips: all 120 retained, 13 new growth tests and 9 new
export/lifecycle tests. Imported predecessor TestCase classes are not rediscovered
under a second module, so the count does not include duplicated test methods.
All eight remote blob IDs match the exact tested source bytes. Compileall and
staged whitespace checks passed. No Rust/full-repository/merge-candidate run is
claimed; this is a CPU source slice, not the target project cloud workspace.

The first growth integration attempt was genuinely blocked by the existing strict
meter on fused cross_entropy in inference_mode. Changing the training probe to
no_grad retained the registered log-softmax/NLL dispatch without changing the
objective or relaxing the arithmetic registry. The first failed log is retained
with the final logs in the downloadable package, not rewritten as a pass.

Four additional synthetic-Encoder/real-PyTorch runs are retained in
GROWTH_FIXTURE_DIAGNOSTIC_20261013.json. Their clocks and input vectors are test
fixtures. The 32-Cell split and direct control both contain 896 final parameters;
peak live model parameters are 1344 versus 896. These are NOT 421M model runs,
independent future outcomes, latency benchmarks or evidence of capability gain.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
```

Local installation of pinned Transformers was attempted twice and returned no
matching distribution from the available installer environment. The separate HF
check still fails at import; zero of its three tests ran. That failure is separate
from the 142 passing tests. The predecessor hosted jobs were read and remained
queued; no hosted success is claimed. Existing CI already discovers new test_*.py
files, so no new workflow or weakening of existing checks was added.

Remaining: actual approved pretrained model/data execution; suitable independent
observer and resource measurements; parameter-sensitive/retention-tested growth
selection; per-Cell multi-generation specialization, consolidation and pruning;
NDU/System2/native owner integration; multimodal generation; native 1024/4096-Cell
serving/recovery. No efficiency, lifelong-learning or 10T/100T equivalence claim.
