# Preserved original checkpoints

These are actual trained tensor checkpoints, not randomly initialized examples. Every `.pt` retains its original adjacent `.pt.manifest.json`. The files are copied byte-for-byte from the fixed Actions artifacts; do not rewrite their sidecars to make a changed model or source appear compatible.

**These are research candidates with failed or unestablished efficacy/semantic gates.** Read [the results report](../evidence/RESULTS.md) before interpreting their outputs.

| Directory / file | Source | Purpose |
| --- | --- | --- |
| `seed17-width32/hepta_dynamic_risk/MODEL.pt` | Full registered seed17/width32 study | Teacher generator/actor/critics; planner used at evaluation |
| `seed17-width32/distillation/STUDENT.pt` | Same study | Distilled actor; generator and critics exactly equal teacher |
| `seed17-width32/ordinary_dynamic_mean/MODEL.pt` | Same study | Parameter-matched ordinary control |
| `natural-diagnostic/dual/MODEL.pt` | Original eight-source natural diagnostic | Dual model; four-source internal evaluation only |
| `natural-diagnostic/ordinary/MODEL.pt` | Same natural diagnostic | Ordinary control |

The first seed and width were selected by registered order, not observed advantage. Width32 has 596,985 parameters. The native artifact's `TENSOR_CONTINUATION.pt` files are intermediate episode snapshots and must not be substituted for these canonical training candidates.

[MANIFEST.json](MANIFEST.json) records full SHA256, Git object SHA1, sizes, source commits, run/job/artifact IDs, original archive paths, and compressed-evidence mappings. Checkpoints contain only tensors and safe primitive containers and are read using `weights_only=True`. They are inference checkpoints; optimizer states and autograd graphs are not included.

## Loading weights for a new episode

Use the pinned Python/Torch versions in `.github/workflows/joint-hepta-generation.yml`. The candidate migration loader validates the whole file, sidecar, tensor identities and exact model/core/media source before returning a frozen model and its lineage:

```python
from pathlib import Path
from experiments.multimodal_output_portfolio.joint_hepta_20261029.deployment import load_candidate

root = Path("experiments/multimodal_output_portfolio/joint_hepta_20261029")
model, lineage = load_candidate(
    root / "checkpoints/seed17-width32/hepta_dynamic_risk/MODEL.pt",
    expected_arm="hepta_dynamic_risk",
)
```

This starts from the selected weights for a **new** episode. It does not resume the original clocks, trajectory, source input or RNG state. For exact original checkpoint continuation, use its source commit and the original profile/input; source binding is intentional. Do not weaken source checks after changing core/model/media code.

## Reconstructing the preserved study and source receipt

The following standard-library preparation writes only new temporary directories. Original compressed JSON bytes are restored exactly. The archived source receipt's adjacent GitHub API metadata and input manifest are preserved so the deployment CLI can verify the receipt without claiming a new API lookup.

```python
from pathlib import Path
import gzip
import shutil

root = Path("experiments/multimodal_output_portfolio/joint_hepta_20261029")
study = Path("/tmp/joint-hepta-preserved-study")
provenance = Path("/tmp/joint-hepta-preserved-provenance")
shutil.copytree(root / "checkpoints/seed17-width32", study)
(study / "RESULTS.json").write_bytes(
    gzip.decompress((root / "evidence/seed17_width32_results.json.gz").read_bytes())
)
shutil.copytree(root / "evidence/native/provenance", provenance)
(provenance / "STUDY_INPUT_MANIFEST.json").write_bytes(
    gzip.decompress((provenance / "STUDY_INPUT_MANIFEST.json.gz").read_bytes())
)
```

On the supported Linux native workflow, with the original pinned `a50c8974...` Git objects available locally and the exact required Rust dependencies accessible:

```bash
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.native_build \
  --repository "$PWD" --destination /tmp/joint-hepta-native-build
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.deployment \
  --study /tmp/joint-hepta-preserved-study \
  --source-receipt /tmp/joint-hepta-preserved-provenance/DEPLOYMENT_SOURCE.json \
  --binary /tmp/joint-hepta-native-build/target/debug/examples/owner_host \
  --output /tmp/joint-hepta-preserved-deployment
```

All destination directories must be new. Hardware-dependent CPU/wall cost will be measured anew; identical physical costs are not promised. This command repeats already-used synthetic sources and is not a fresh semantic qualification. The repository contains selected original result records and all-six-configuration compact evidence, not every raw media file from all six Actions artifacts.
