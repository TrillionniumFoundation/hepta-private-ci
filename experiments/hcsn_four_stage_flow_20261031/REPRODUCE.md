# Reproduction and artifact identities

The training source commit is `8044dbfc3c41356eaf3f8ac69c7537e2091eda80`.
The operator source commit is `1349bb1bfec5c9fe5f165e1efcf2be4b479c945e`.
Subsequent commits add evidence and analysis without changing frozen training
files. `results/campaign002/REMOTE_SOURCE_VERIFICATION.json` records independent
GitHub API readback of the committed Git blobs and local SHA256 checks.

The execution checkout used a partial local object store. Remote commits were
created through the GitHub connector, so their objects need not be present in
that original local checkout. The readback receipt, rather than a misleading
local `git rev-parse HEAD`, identifies the executed published source.

## Environment

Run from the repository root with Python 3.12 and a CPU PyTorch environment.
The protocol records the exact observed Python, Torch and NumPy versions. The
numerical audit also requires SciPy; figures require Matplotlib; AV preparation
requires ffmpeg and ffprobe. Set OMP, OpenBLAS and MKL thread counts to one for
comparable CPU execution. This is not a frozen operating-system image or a
claim of bitwise equivalence across hardware.

## Data

`data/COHORT.json` is the original immutable cohort metadata, copied byte for
byte. Its hash is `b65adcd877528b7cb5b81962ff3662c59ee1e144c26034b8a4e1d5e6426cf37a`.
It pins CREMA-D commit `1658cd342dff90010aa843eaeebd53610a08b1dc`, 38 actors,
two sentences, six emotions and every required media checksum. Original media
are not duplicated here; preparation rejects any mismatched source file.

Use fresh output directories. Existing evidence is deliberately not silently
overwritten. The following commands show the logical execution sequence; replace
`MEDIA_ROOT`, `FRESH_DATA`, `FRESH_RUN` and `SOURCE_COMMIT` with explicit paths
and the source identity of the experiment being reproduced.

```bash
python3 -m experiments.hcsn_four_stage_flow_20261031.av_data \
  --media-root MEDIA_ROOT \
  --cohort-path experiments/hcsn_four_stage_flow_20261031/data/COHORT.json \
  --out FRESH_DATA --splits train validation

python3 -m experiments.hcsn_four_stage_flow_20261031.runner \
  --out FRESH_RUN --freeze --steps 600

python3 -m experiments.hcsn_four_stage_flow_20261031.runner \
  --out FRESH_RUN --phase train --av-data FRESH_DATA \
  --frozen-commit SOURCE_COMMIT
```

Training must finish all 75 fits successfully before the all-candidate manifest
is created. The manifest is
`FRESH_RUN/CHECKPOINT_FREEZE__dynamics_mqar_selective_binding_avt.json`.

```bash
python3 -m experiments.hcsn_four_stage_flow_20261031.av_data \
  --media-root MEDIA_ROOT \
  --cohort-path experiments/hcsn_four_stage_flow_20261031/data/COHORT.json \
  --out FRESH_DATA --splits test \
  --candidate-freeze FRESH_RUN/CHECKPOINT_FREEZE__dynamics_mqar_selective_binding_avt.json

python3 -m experiments.hcsn_four_stage_flow_20261031.runner \
  --out FRESH_RUN --phase evaluate --av-data FRESH_DATA \
  --frozen-commit SOURCE_COMMIT \
  --candidate-freeze FRESH_RUN/CHECKPOINT_FREEZE__dynamics_mqar_selective_binding_avt.json
```

For complete child-process accounting, wrap each command with:

```bash
python3 -m experiments.hcsn_four_stage_flow_20261031.meter \
  --out UNIQUE_RECEIPT_PREFIX -- python3 -m TARGET_MODULE ARGS
```

The meter saves stdout, stderr, complete child user/system CPU, wall time,
peak RSS and exit status. Its receipt includes the nested operations. Do not
add a nested fit timer to the enclosing meter's total.

## Evidence interpretation

`campaign001` was superseded before any formal training or confirmation. It
records the design change to checkpoint-first evaluation and stronger ordinary
baselines. Small development runs live under `dev`; they are not independent
confirmation replications. `campaign002` contains all fixed-budget trained
candidates and their confirmation records, including failures if any.

All-query correctness in the symbolic tasks means all four requested values
are correct in the same episode. In AV/text there is only one final query,
so the corresponding metric is unweighted episode accuracy; the primary
consistency metric uses the declared class-balancing weights.

No single synthetic task, tiny AV/text experiment or CPU benchmark establishes
foundation-model quality, deployed energy savings or superiority to optimized
large Transformer/SNN implementations.
