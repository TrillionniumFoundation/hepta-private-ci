# Bounded delta memory and fixed function-family controls

This is a new mechanism experiment on top of exact baseline
`b1934022821f3fdafd509b43cf0c4d7d45852e6e`. It does not edit or rerun the old
48-run mass-ridge experiment, its negative retrieval gate, or its unexecuted
conditional confirmation. The new source/data/seed protocol is in
`protocol.json`; `freeze.json` binds the scientific source before new outcomes.
"New" here means a new memory mechanism in this repository branch; it is not
a claim to have invented delta-rule learning.

The completed results are in `RESULTS.md`. The new quality gate fails, and
the strict aggregate replay audit also fails: 11 inherited mass-ridge
conditions exceed the frozen 1e-4 absolute-logit threshold. All 135 accuracy
values and label arrays agree exactly; the delta arms and fixed-ridge arm
pass the strict replay threshold. The audit deliberately returns exit1.
`replay_diagnosis.json` diagnoses one worst mass-ridge case at higher
precision without relaxing that failed gate or changing any checkpoint.

## Mechanism and scope

The learned input, key/value, content, boundary coordinate, fast/slow state and
readout parameter graph comes from `next/ridge` and `third/memory`. The new
memory changes the write/read mechanism only. There is no task-name switch,
label, manually decoded marker, query-key ID or answer routing in the model.
The final token reads prefix memory without writing, exactly as the earlier
sequence-to-one contract. The runtime boundary is a learned neural coordinate;
the nine financial parameters and their compiled table remain fixed.

Let each memory column be in the Euclidean ball of radius R=8, let ||k||≤1,
let v have coordinates in [-1,1], and let the ordinary learned write gate w
be in [0,1]. The update is

\[
\widetilde M=M+\frac{w}{10^{-4}+\|k\|^2}k(v-k^TM),\qquad
M^+=\Pi_{\mathrm{columns},R}(\widetilde M).
\]

The query read is qᵀM, followed by the same tanh/content/readout as before.
No Gram inverse, cumulative normalization mass, new learned parameter or
matrix solve is used by the delta candidate. The old fixed/mass ridge arms
call the unchanged baseline implementation, including its FP64 solve.

For fixed k,v,w, the linear part of the unprojected map is

\[
I-\frac{w}{10^{-4}+\|k\|^2}kk^T.
\]

Its eigenvalues are one in the orthogonal subspace and
1-w||k||²/(10⁻⁴+||k||²) in the key direction, all in [0,1]. Euclidean ball
projection is nonexpansive, so this fixed-input memory map is nonexpansive.
The column norm invariant gives |qᵀM_j|≤8 for ||q||≤1. These properties do
not bound gradients through learned keys, neural dynamics, parameter updates
or arbitrarily long coupled networks.

A zero write leaves every reachable memory state unchanged: initialization
is zero and every preceding update projects into the radius8 balls. An
arbitrary externally supplied state outside those balls can still change
under a zero write because the projection is applied.

Without an active projection, a write orthogonal to an existing query leaves
that query's memory read unchanged. A repeated key changes the old residual
toward the new value rather than averaging every historical conflict. General
keys are not orthogonal; cross-talk remains. Projection can also change an
orthogonal read if another write activates the global column constraint.
The projection seam is not differentiable everywhere. We report local AD
checks on its interior and active branch, not a globally C1 memory theorem.

## Paired comparison

Thirty runs are frozen: five variants × two tasks × three new seeds. Each
receives 600 Adam updates, batch32 and the same 8/16/32 length curriculum,
data, initialization and minibatch random stream within a task/seed.

| Variant | Memory | Fixed function family |
| --- | --- | --- |
| full_delta | Projected normalized delta | Complete compiled HX Call and modified C1 first-hit risk |
| sigmoid_delta | Same delta | Identical HX Call; risk sigmoid(2z) |
| c1_delta | Same delta | Two ordinary nonfinancial C1 functions |
| full_fixed | Original normalized statistics, fixed ridge | Same complete compiled HX pair |
| full_mass | Original normalized statistics, inverse-mass ridge | Same complete compiled HX pair |

All use the identical learned boundary scale/coordinate z. This is not a
slope-matched comparison: measured q′(0) is zero for FullHX and ordinary C1,
and 0.5 for sigmoid(2z). No function scale was chosen from test outcomes.
All five parameter trees and initial values match exactly; state sizes, table
bytes and compute differ and are reported separately. Equal updates are not
equal training cost or equal memory capacity.
The table-byte field counts the operator dependency of each arm, not measured
process residency: the shared inherited Python module eagerly loads the table
even when the C1 arm does not use it. Its logical zero table bytes therefore
do not demonstrate a resident-memory saving in this mixed-arm runner.

The old financial kernel, probability reinterpretation and derivative limits
remain those documented in `next/full_kernel`. This experiment does not
reinterpret the added risk patch as the original financial debt Put.

## Data and evaluation

New generator bases and seeds are fixed before outcomes. Exact input hashes
check the new evaluation cohorts against earlier constructed benchmark,
v3/v4/third-development cohorts, current matching-length training and other
new evaluations. The old conditional confirmation data is never instantiated.
Small finite-vocabulary training examples may naturally repeat.

The two tasks use the unchanged first-marked-symbol memory and four-key
associative retrieval definitions. Length128 and length512 are primary
diagnostics. The retrieval checkpoints additionally face eight associations
at length512, a later conflicting same-key write at length128, and increased
filler noise. The overwrite target is the latest marked value for that key.
Overwrite/capacity/interference are extrapolation challenges, not tasks seen
in training, not alternative model-selection criteria and not substitutes
for the frozen quality gate.

The deterministic probe set separately isolates normalization dilution,
zero writes, orthogonal fillers, same-key overwriting, correlated-key
interference and finite versus overcomplete capacity. Success of the
orthogonal case is not used to hide its deliberate interference failures.

## Evidence and execution

`validate.py` independently checks NumPy/JAX recurrence agreement, random
directional derivatives, projection branches and deterministic mechanisms.
The scientific source freeze must pass before `run.py` trains.

Every run preserves all 12 candidate checkpoints, the selected checkpoint,
every update's loss and gradient norm, validation history and every test's
logits/labels. Checkpoint selection uses only validation32 cross entropy.
`audit.py` independently replays all saved selected checkpoints in NumPy and
checks data, prediction and checkpoint hashes, candidate selection, paired
initialization and update counts. It does not select or repair model weights.

The published `raw_evidence.zip` is a lossless archive of every `runs/` file;
`raw_evidence_manifest.json` gives every file's SHA256 and size. Original
local run files remain intact. `archive_validation.json` records an actual
restore into a new empty directory and full independent file-hash checks.
Only this archived duplicate `runs/` directory is excluded from Git.
Restore the published evidence before auditing it:

```bash
python tools/hcsn/task_flow_20261030/memory/restore_evidence.py
python tools/hcsn/task_flow_20261030/memory/audit.py
```

The restore utility uses only the Python standard library and refuses to
overwrite differing evidence. `--dest PATH` restores into another directory;
`--verify-only` verifies an existing restore without changing it.

`summarize.py` reports the original conjunctive quality gate, and the eight
FullHX-minus-C1/sigmoid paired comparisons with one Bonferroni95 interval
family. Three paired seeds describe these tasks and budgets; they do not
prove general equivalence or superiority across tasks. All negative gates
and challenge failures remain in `summary.json`.

From the repository root, using the declared dependencies:

```bash
python tools/hcsn/task_flow_20261030/memory/freeze.py
python tools/hcsn/task_flow_20261030/memory/validate.py
python tools/hcsn/task_flow_20261030/memory/run.py
python tools/hcsn/task_flow_20261030/memory/audit.py
python tools/hcsn/task_flow_20261030/memory/summarize.py
```

Existing complete output is not silently overwritten by the training runner.
Reproduction requires an isolated fresh output copy while preserving the
published evidence. The first run used the frozen runner's conservative
memory admission. Shared compilation/cache pressure then held that runner
between runs. `operational.py` continued the unchanged scientific runner
after a disclosed operational amendment, reserving 1.5GB headroom under a
more permissive estimate of reclaimable cache/slab. It does not change data,
model, optimizer, initialization, checkpoint selection or quality gates.
The handoff and source hashes are in `operational_handoff.json` and
`operational_amendment.json`. It never kills other jobs. Compilation,
optimizer, validation, completed-run and replay costs are separate nested or
additional scopes. `cost_ledger.json` keeps unmeasured campaign components
null; the sum of completed-run costs is not the entire campaign cost.
`diagnose.py` is explicitly exploratory and uses already declared test512
data after the full matrix; it never changes training or selection.

All models execute dense CPU code. No GPU, event-chip
energy, all-modal pretraining, general continuous-time semigroup or task-level
optimal free-boundary claim is made by this package.
