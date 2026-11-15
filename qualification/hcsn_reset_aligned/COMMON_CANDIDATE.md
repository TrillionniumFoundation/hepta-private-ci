# Common numerical, gradient and cold-state candidate

This research assembly puts the following implementations on one source tree:

| Input | Frozen source | Scope |
| --- | --- | --- |
| #6157 | `fb663f141f5763692a5fc05e09ae60e8d7da4bdf` | Bound conservative old-law migration and retained DDE flux history |
| #6170 | `4e0aa275988fe3919c5f802a3891b8337b30dc83` | Reset-aligned generator, variational DDE, first-order Torch law/physical gradients, shared-generator U and F |
| #6165 | `74f97ea0c9595735e103a00ea1f6fd7ae8267d81` | Independent negative review; its original operator source remains `f9345af3c74e32a2b6ab62f84e8998f37f0d2ac3` |

The extra Git parents retain the input histories. The complete #6170 operator
subtree is reused by Git tree identity. The common change strengthens
`state_io` to bind every local implementation in the concrete model and spatial
class inheritance chains. Otherwise changing the inherited graded generator
could leave a reset-aligned checkpoint apparently compatible. A new test changes
the actual inherited source in an isolated copy, then requires a fresh Python
process to reject the unchanged checkpoint. This is a state-version fix, not
automatic migration across source versions.

## One executable check

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B -m qualification.hcsn_reset_aligned.qualify_common \
  --output /path/to/new-empty-attempt
```

The Linux CPU runtime requires Python 3.12, NumPy 2.3.5, SciPy 1.17.0 and
PyTorch 2.8.0+cpu. The hosted workflow checks out the exact PR head and uses
pinned action identities. The runner requires all 45 declared unittest cases,
zero skips and identical before/after Python source hashes. Separate branches'
test totals are never accepted in place of executing this source.

The healthy diagnostic actually performs 120 Adam updates and retains all 121
loss/parameter/gradient observations. The fixed target is relative MSE below
`2e-4`, with reset moving from below to above the old `0.5` interpolation knot.
It estimates two scalar parameters from the same discrete model's synthetic
teacher. It does not establish task learning, class balance, sufficient training
of the old C2 model or benefit on an independent source.

The common integration fixture maps a real 25-component old law, including
signed content and an initial remaining-age distribution, onto a reset-aligned
32-interval mesh. It runs to model time `0.137`, saves actual Newton flux-history
coefficients, restores in a new Python process and continues to time `1.0`.
All seven probability/content/count/value state fields must agree with an
uninterrupted trajectory within absolute `4e-9`. The full regenerative dynamic
value identity is checked separately within `5e-9`. Changing the physical reset
or inherited operator source must reject the retained state.

Original test streams, source hashes, compressed before/after checkpoints and
fresh-process restoration streams are retained. `test_process_cost` measures
only the 45-test subprocess. The separately reported cold-restore process wall
time includes imports and one continuation. Model time `0.137` is not latency.
Neither measurement is an isolated kernel benchmark, a latency distribution,
a complete training campaign cost or measured device energy.

## Numerical and training boundaries

The old 14,336-position, unchanged 1% continuation gate remains bound to its
original #6144 fixed graded discretizations and retained arrays. It is not a
qualification of every moving-mesh geometry used by the Torch tests. The
common 32-interval integration fixture and 8-interval synthetic fit have
different declared geometries; their local successes do not transfer the
512-interval continuation bound to coarse training grids.

The retained independent review exhibits a first-hit probability error of
about +185.9% at T=0.1 on the equal-segment 8-interval mesh, falling to about
+3.27% at 64 intervals. At T=0.01 the coarse result is orders of magnitude too
large. With mu=-0.12 and sigma=0.08, those equal-segment meshes through 64
intervals have negative rates and are refused. A correct discrete gradient
does not remove these continuum/domain failures. The original review is
preserved under its old source binding; it is not relabeled as a new run.

The moving-nodal law is held fixed in the physical derivative. A fixed physical
prior additionally needs a differentiated migration map. In particular B and
Vr enter this fixed-weight generator through log(Vr)-B, so their reported
partials do not independently identify both quantities. Delay, phase supports,
query times, upper endpoint, grading and node topology remain fixed. The
Torch law has at most 64 nodal/phase rows, uses first-order CPU FP64 VJPs and
does not persist an autograd graph across a cold checkpoint.

The U readout uses remaining phase age and full history in its backward.
F is the killed first-hit distribution for an initially active nodal law;
its current API explicitly refuses initial phase packets. F is not the
regenerative event count M. See `STATE_CONTRACT.md` in `hcsn_joint_dde` for
C, F, G, U, J, M and the upper-boundary convention.

## Admission status

Status remains research HOLD. This candidate supplies no independent future
task, complete C2 training replay, production candidate publication, external
evaluation, adoption or owner-issued NoUpdate receipt. #6173's six real old
C2 checkpoint diagnostics are a separate model/source and cannot fill those
fields for this candidate.

Before mechanism claims, the same qualified task model still needs the
continuation-only/risk-only/both comparison; fixed/learned/optimal boundary
comparison; reset and content switches; and a function-identical neutral-name
control. The older content-by-boundary pilot cannot replace these controls.
Tuned GRU, actual SSM/CfC, appropriately sized Transformer and applicable SNN
gradient baselines still need common budget and target-quality comparisons,
full latency/memory/energy accounting and new independent data sources. Cell
admission and a newly consuming task must use that same candidate identity
before expansion to larger models or more complex boundaries.
