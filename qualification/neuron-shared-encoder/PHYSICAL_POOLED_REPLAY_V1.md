# E1/E2 — Actual pretrained pooled features → private trained Heads (shadow)

This additive experiment reuses exact **previously executed** mmBERT-small and
ModernBERT-base pooled feature artifacts from GitHub Actions public-pretrained
run [`38534349397`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38534349397).
Its original downloaded ZIP has SHA-256:

`1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2`

With this exact observed archive present locally, the offline runner checks the
ZIP pin, model ID/revision, original dataset and source manifest hashes, tensor
bytes and numerical digest, source-input row bindings, and original 64/32/32
public training/calibration/holdout partitions. Then it **actually trains** a
private pooled Cell Head for each of two Cell slots and each of three seeds,
saves safetensors, reloads the exact Head artifacts and evaluates all 32
retrospective holdout examples with scalar and packed numerical parity checks.

Run from `qualification/neuron-shared-encoder`:

```python
from pathlib import Path
from neuron_shared_encoder.physical_pooled_replay_v1 import (
    PUBLIC_ZIP_SHA256, run_pooled_trained_readback)

for arm in ('mmbert', 'modernbert'):
    report = run_pooled_trained_readback(
        Path('/approved/path/to/hepta-public-pretrained-38534349397.zip'),
        PUBLIC_ZIP_SHA256, Path('/new/private/results') / arm,
        arm=arm, steps=20, seeds=(11,23,47))
    assert report['production_admission'] == 'BLOCKED'
```

Output paths MUST NOT already exist. Run in a private approved workspace with
the original public dataset license and storage entitlement respected; this
harness cannot issue one. No model download or source data re-encoding occurs.

Two Cell Heads share the same real pretrained Encoder artifact per arm, but their
training parameters and safetensors are separate. The Head adapter sees the
**single pooled vector as one token**. A token-query attention capacity gain
cannot be measured from this input and is explicitly *not* claimed. Rank-16
384d and rank-8 768d Head variants each satisfy a 16,384-parameter cap, but
**actual independent parameters differ**. Encoder compute and pretraining
costs are not included in the measured Head training time.

The additional control is a never-trained **random initialization**, *not*
the selected deployed no-change baseline. Training-only rows are sampled by a
fixed seeded schedule; per-Cell random initialization and candidate are frozen
before retrospective calibration/holdout labels are consulted. Each holdout
report retains recovered and lost correct cases, not only average accuracy.
Those labels were historically published before this research run, so neither
code structure nor event-time naming makes the evaluation prospective.

The generated files have self-computed SHA digests and strict readback, but no
independent trusted issuer, signed Final-use, Artifact CAS, NDU, genuine future
window, or source-authorization proof. These are **physical CPU research
observations, not production promotion evidence**. The original archive
contains plain source text; do not copy it into PR artifacts. Only bounded
reports and trained lightweight Head checkpoints should be retained.

Tests produce deliberately synthetic local fixtures with
`allow_synthetic=True` and demonstrate refusal of those same fixtures in real
mode. Do not set `allow_synthetic=True` in any scientific/production run.
