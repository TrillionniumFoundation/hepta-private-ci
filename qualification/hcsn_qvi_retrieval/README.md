# Regenerative boundaries for priced audio/video retrieval

This opt-in qualification experiment combines the scalar regenerative control
problem in #6739 with the finite population operator in #6958. It measures
three physical boundaries (fixed, learned, frozen-interval QVI) and three
adaptation procedures (post-SVD KEEP, profiled BP and an agent-written edit).
The public preregistration is `protocol.json`. No live model is modified.

## Reproduce

From the repository root, use Python with NumPy, SciPy, CPU PyTorch, ffmpeg
and ffprobe. The empirical study uses CPU FP64 and one numerical thread per
cold process. Results bind interpreter, library and source identities.
Use separate empty output directories for each scientific run. Preserve the
original inputs and results when doing a reproduction.

```sh
pkg=qualification/hcsn_qvi_retrieval
python "$pkg/acquire_media.py" /tmp/qvi-raw
mkdir -p /tmp/qvi-input
for split in train dev retain test
do
  python "$pkg/media.py" /tmp/qvi-raw "/tmp/qvi-input/$split.npz" --split "$split"
done
python "$pkg/verify_media.py" /tmp/qvi-raw/recordings.json /tmp/qvi-input
PYTHONPATH="$pkg:${PYTHONPATH:-.}:." python -m unittest qualification.hcsn_qvi_retrieval.test_ndu qualification.hcsn_qvi_retrieval.test_media qualification.hcsn_qvi_retrieval.test_dynamics qualification.hcsn_qvi_retrieval.test_adapt
python -m qualification.hcsn_qvi_retrieval.run_study diagnose /tmp/qvi-input /tmp/qvi-study
python -m qualification.hcsn_qvi_retrieval.run_study fit /tmp/qvi-input /tmp/qvi-study
python -m qualification.hcsn_qvi_retrieval.run_study confirm /tmp/qvi-input /tmp/qvi-study
python -m qualification.hcsn_qvi_retrieval.verify /tmp/qvi-input /tmp/qvi-study
```

Running the saved agent program reproduces its edits. Its original discovery
included a separate TRAIN-only diagnostic disclosure and an agent-authoring
interval. Include that cost when comparing discovery with conventional training.

## Task and states

The shared causal frontend and reference gallery are fixed for all arms.
Each query has two recordings of the same actor and expression as candidates.
The correct one has the same statement and a different take. Actor splits are
disjoint and reciprocal queries within an actor are dependent. The RAVDESS
source and license are identified in `data_manifest.json`. The source corpus has
one byte-identical pair in the selected media. The original hashes and failure
are retained. Excluding the whole affected actor-expression stratum preserves
balanced targets and independent positive takes.

STOP retrieves from the audio-prefix scores. READ pays 0.30 to acquire video
for that prefix and retrieves once. WAIT advances one 0.48 second interval
and pays continuously at 0.40 per second. The discount rate is 0.20. The first
observed prefix is the common decision-time origin. Terminal WAIT is masked.
The training teacher uses realized trajectories to assign three action values.
The deployed controller sees the unpriced query channels. Paid features enter
the environment only after READ. Common TRAIN-only centered SVD ridge solves
the three action heads with an unpenalized intercept.

The physical QVI optimizes an affine internal retention objective in a Brownian
frozen-coefficient forecast using task prices. Absolute reset and the physical
clock are shared. The executed population has a spatial grid and Erlang delay.
The separate empirical Bellman policy uses the TRAIN distribution of public
score margins and the actual external retrieval utility. Perfect-future utility
is recorded as a privileged upper bound. Comparing QVI to this bound does not
make it an exact solution of the external partially observed task.

## Historical five-checkpoint geometry

`feasibility.py` takes the public frozen TRAIN geometry from
[`2d0120e`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2d0120e208ed81515837a7530c9f6943af03e87f/tools/hcsn/wsp_20261104/joint/fixtures/train_linear_geometry.npz).
It measures whether moving continuation rows, adding terminal rows, or changing
both can satisfy the original legal action rankings with a 0.001 margin. It
keeps the existing hidden representation and base Belief scores fixed. A
feasible TRAIN solution supplies a candidate for fresh independent utility
evaluation. The RAVDESS task and these checkpoints have different action sets.
