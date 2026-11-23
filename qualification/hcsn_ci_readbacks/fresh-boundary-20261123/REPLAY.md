# Reproduce the 12-recording transfer study

Use the repository revision containing this directory. The short replay recomputes all 24 policies' outcomes and all source-level comparisons from sealed decisions and the released posteriors. The cold replay starts with the 12 published recordings, restores the original policy parameters, generates the 24 sets of decisions before opening the camera, and verifies the result against the public evidence.

## Short offline replay

From the repository root, use a fresh output directory and a Python environment containing NumPy.

```sh
study="$PWD/qualification/hcsn_ci_readbacks/fresh-boundary-20261123"
readback="$(mktemp -d)"
python -m zipfile -e "$study/independent-scores.zip" "$readback"
(
  cd "$readback" &&
  python score_published_actions.py input recomputed.json &&
  cmp recomputed.json scores.json &&
  python compare.py . official-result.json input
)
```

The independent verifier checks 670 quantities including 288 policy-by-source utilities. The released independent JSON has SHA-256 `6d40ca977191364f65bc84b919d92cd919d0f40d9ed325cdab1924febaad0eb5`.

## Cold replay environment

The original CPU execution used Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0, Pillow 13.0.0, PyTorch 2.15.0+cpu, torchvision 0.29.2+cpu and FFmpeg/FFprobe 7.1.5. FFmpeg and FFprobe must be on PATH. A Linux shell can prepare a Python 3.12 environment as follows.

```sh
repo="$(pwd -P)"
study="$repo/qualification/hcsn_ci_readbacks/fresh-boundary-20261123"
work="$(mktemp -d)"
python3.12 -m venv "$work/venv"
. "$work/venv/bin/activate"
python -m pip install numpy==2.3.5 scipy==1.17.0 Pillow==13.0.0
python -m pip install --index-url https://download.pytorch.org/whl/cpu \
  torch==2.15.0+cpu torchvision==0.29.2+cpu
ffmpeg -version | head -1
ffprobe -version | head -1
```

## Restore inputs

The helper verifies the study protocol, recorded source-code hashes and four historical archives. It writes the 25 original parameter and seal files in the layout consumed by `actions.py`. To fetch the twelve original works and the official checkpoint into the new work directory, run the following command. The recordings total 665,895,136 bytes. Their URLs, uploader and artist credits, licensing, publisher revisions, sizes, original SHA-1, acquired SHA-256 and four start times per recording are in [cohort.json](cohort.json).

```sh
python "$study/restore_frozen.py" --work "$work" --fetch
```

For an offline run with preexisting originals and checkpoint, use this command in its place. Each raw file should be named with its Commons page ID and original suffix, for example `37320740.ogv`. Supply one or more directories containing these files.

```sh
python "$study/restore_frozen.py" --work "$work" \
  --originals /path/to/commons-originals /path/to/other-originals \
  --weights /path/to/resnet18-f37072fd.pth
```

To inspect just the recoverable weights and their source bindings, use `python "$study/restore_frozen.py" --work "$work" --parameters-only`. The parameters come from these repository objects.

| Restored input | Historical repository source |
| --- | --- |
| Free acoustic frontend and gallery | [records-04.zip](../../hcsn_intervention_value/evidence/records-04.zip), member `primary/discovery/front_weights.json` |
| 18 original read-enabled parameter sets, scaler, teacher and selection seal | [records-07.zip](../../hcsn_intervention_value/evidence/records-07.zip), members under `primary/policies/` |
| Source SVD fit and bounded LP/gradient edit parameters | [locked_heads.zip](../../hcsn_blocker_followup/evidence/locked_heads.zip), members `fit.json` and `edit_seal.json`. The same bytes also occur under `outcomes/` in [paid-roster-04.zip](../../hcsn_blocker_followup/evidence/paid-roster-04.zip). |
| Six-coordinate TRAIN-only edit | [train_only_seal.json](../purchase-attainability-20261123/train_only_seal.json) |
| Disk-backed original RGB staging and input transforms | [source_replay.zip](../../hcsn_blocker_followup/media/source_replay.zip), members `pinned/rgb_disk.py` and `pinned/vision_disk.py` |

The ImageNet-1K V1 ResNet-18 checkpoint is 46,830,571 bytes and has SHA-256 `f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec`. The helper can fetch the file from [the official PyTorch model host](https://download.pytorch.org/models/resnet18-f37072fd.pth).

## Recompute the locked decisions, camera and scores

Work from the **new work directory**. The restoration helper creates a `trial` link there pointing to the checkout. The original archived RGB adapter resolves `trial/qualification/hcsn_intervention_value/media/vision.py` relative to the process working directory. The `PYTHONPATH` below gives the package imports and the archived adapter the same checkout.

```sh
cd "$work"
export PYTHONPATH="$repo"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python "$study/actions.py" --originals "$work/media-cache" \
  --discovery "$work/discovery" --policies "$work/policies" \
  --selector "$work/selector" --six "$work/selector/train_only_six.json" \
  --out "$work/evaluation"
action_sha="$(sha256sum "$work/evaluation/action-seal.json" | cut -d ' ' -f 1)"
python "$study/camera.py" --originals "$work/media-cache" \
  --weights "$work/resnet18.pth" --scratch "$work/scratch" \
  --out "$work/evaluation" --action-seal "$action_sha"
python "$study/score.py" "$work/evaluation"
```

Each run's action seal includes measured wall times, so pass its freshly computed SHA to the camera. The reference seal and the new seal each bind the roster, free posteriors, acoustic inputs, Q-values and all actions. The pre-purchase data had 48 rows and 24 action vectors. The published `actions.json` SHA-256 is `b76f924fef28528cefcab1bbe97f98e4a9e4627d841ed7c97f1668536496905a`. The camera posterior file SHA-256 is `c72730270654a850e5c5939e327d24eeae3d6d2a04eec3fda349f8f83f14e5fb`.

The `evaluation.zip` archive contains the original arrays, decisions, raw camera receipt and result. To compare the cold outputs, run the following in the same shell.

```sh
python -m zipfile -e "$study/evaluation.zip" "$work/reference"
(
  cd "$work/reference" && sha256sum -c SHA256SUMS
)
for artifact in roster.json audio.npz free.npz qvalues.npz actions.json camera.npz; do
  cmp "$work/evaluation/$artifact" "$work/reference/$artifact" || exit 1
done
python - "$work" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
old, new = [json.loads((root / name / 'result.json').read_text())
            for name in ('reference', 'evaluation')]
for field in ('primary', 'scores', 'opportunity', 'prior_audio_subgroup',
              'queries', 'sources', 'policies', 'all_original_evaluators_match'):
    if old[field] != new[field]:
        raise SystemExit(f'Result differs in {field}')
print('All 24 policy results, paired source tests, and opportunities match.')
PY
```

For independent reverse-order verification of the raw camera trace, use `python "$study/verify_camera.py" --weights "$work/resnet18.pth" --out "$work/evaluation" --output "$work/reversed-camera.json" --originals "$work/media-cache"`. It checks each transformed tensor, logits and posterior. A single published Ogg file contains a backwards pair of decoded timestamps just before its first registered window. The certified recovery for this window verifies that three physical decode starts produce the same six RGB frames, with original clock ticks 139, 151, 162, 174, 185 and 197 at 24 ticks/s. The trace covers 47 ordinary windows and this one recovered window. [Recovery code](recover_preroll.py) · [Published camera verification](camera-replay.json)
