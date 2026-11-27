# PRED-1 independent original-archive study: reproduction and execution

This delivery contains a training/development diagnostic, a portable input archive, the unchanged independent confirmation design, and a separately frozen execution supplement. The archived experiment belongs only to original PRED-1. Its results must not be counted as integrated-candidate model execution, owner adoption, real-task gains or complete physical-cost qualification. Historical PRED-1 HOLD stays historical.

## Files to carry to the native host

- `overlay/scripts/hepta_pred1/diagnose_training.py` and `test_diagnose_training.py`: current diagnostic implementation and 14 regression tests.
- `input-bundle-001/pred1-training-dev-inputs.tar.gz`: all required historical inputs in one binary archive.
- `input-bundle-001/ARCHIVE.sha256`, `MANIFEST.sha256` and `SOURCE_MAP.md`: archive checksum, relative payload checksums and unchanged-freeze path mapping.
- `execution-supplement-001/guarded_confirm.py`, `test_guarded_confirm.py`, `EXECUTION_SUPPLEMENT.json` and `EXECUTION_SUPPLEMENT.sha256`: separately pinned guard, 13 synthetic control tests and execution supplement.

Archive SHA-256: `3611e8f2032e28abe9ee2b77c7650d16d12aed20eb79d0c2987c0b2db4c91129`; 111,217 bytes. All 66 archive members are ordinary relative-path files. The 65 checksum entries cover 63 input/provenance payload files, `SOURCE_MAP.md`, and `MANIFEST.json`; the archive checksum also covers the checksum file. There are no confirmation results or checkpoint weights.

After extraction, the source package is exactly:

```text
source/hepta_pred1/__init__.py
source/hepta_pred1/contracts.py
source/hepta_pred1/evaluation.py
source/hepta_pred1/models.py
source/hepta_pred1/run.py
source/hepta_pred1/simulator.py
source/hepta_pred1/test_contracts.py
source/hepta_pred1/test_evaluation.py
source/hepta_pred1/test_models.py
source/hepta_pred1/test_run.py
source/hepta_pred1/test_simulator.py
```

Do not put the new diagnostic or wrapper into that frozen package. Do not format those 11 files. The guard and the original runner both bind the source inventory and exact file bytes. `source/run.py` is not a second copy: the diagnostic uses `source/hepta_pred1/run.py`.

The original 48 fit metadata files are under `training/`. Original diagnostic configuration is `config/original-registered-config.json`. The prospective 16-new-seed configuration is `provenance/independent-confirmation-002/registered_config.json`; these configurations have different purposes and must not be swapped.

## Environment

The archived implementation uses only the Python standard library and NumPy. Reference environment: **Python 3.12, NumPy exactly 2.3.5**. Python 3.12 patch version, OS, BLAS build and host identity must be recorded on the native host; no Python patch or BLAS build was pinned by the original freeze. The execution supplement requires Python major/minor 3.12 and NumPy 2.3.5.

Set `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, and `VECLIB_MAXIMUM_THREADS=1` before interpreter startup. This keeps the native backend at one compute thread across common BLAS implementations. No Torch, GPU, external model, network data or pytest is required. `uv` is only an optional environment launcher; an already provisioned Python 3.12 environment with NumPy 2.3.5 can run the same Python command directly.

## Extract and verify on the native host

Run from the copied delivery root containing `input-bundle-001/` and `execution-supplement-001/`. These commands do not generate samples.

```sh
PRED_DELIVERY="$PWD"
PRED_INPUTS="$PRED_DELIVERY/unpacked-inputs"
python3.12 - "$PRED_DELIVERY" "$PRED_INPUTS" <<'PY'
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import sys
import tarfile
root, target = map(Path, sys.argv[1:])
archive = root / 'input-bundle-001/pred1-training-dev-inputs.tar.gz'
supplement = json.loads((root / 'execution-supplement-001/EXECUTION_SUPPLEMENT.json').read_text())
assert sha256(archive.read_bytes()).hexdigest() == supplement['input_archive_sha256']
target.mkdir(parents=True, exist_ok=False)
with tarfile.open(archive, 'r:gz') as tar:
    names = []
    for member in tar.getmembers():
        path = PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and '..' not in path.parts
        names.append(member.name)
    assert len(names) == len(set(names)) == 66
    tar.extractall(target, filter='data')
for line in (target / 'MANIFEST.sha256').read_text().splitlines():
    expected, relative = line.split('  ', 1)
    assert sha256((target / relative).read_bytes()).hexdigest() == expected, relative
print('Verified 66 archive members and 65 relative checksums')
PY

python3.12 "$PRED_DELIVERY/execution-supplement-001/guarded_confirm.py" \
  --bundle "$PRED_INPUTS" \
  --supplement "$PRED_DELIVERY/execution-supplement-001/EXECUTION_SUPPLEMENT.json" \
  --check-only
```

The check-only mode does not import NumPy or the experiment package, run training, or generate samples. The expected runner `source_identity.sha256` is `a07f2eb7c06c5ddf98b632a205a1865e75a18cdc09c9e3085a88dd2f01a32583`. This differs intentionally from the original freeze's source metadata manifest SHA `dbf82bbd1f829c9281342add90b0bf5b968c10d40fa76cfa433a155875231ba4`: the former hashes the runner's filename→digest mapping, while the latter also includes byte sizes.

## Reproduce the diagnostic and controlled tests

```sh
python3.12 -m unittest discover \
  -s "$PRED_DELIVERY/overlay/scripts/hepta_pred1" \
  -p test_diagnose_training.py -v
python3.12 -m unittest discover \
  -s "$PRED_DELIVERY/execution-supplement-001" \
  -p test_guarded_confirm.py -v
python3.12 "$PRED_DELIVERY/overlay/scripts/hepta_pred1/diagnose_training.py" \
  --campaign "$PRED_INPUTS/training" \
  --config "$PRED_INPUTS/config/original-registered-config.json" \
  --source "$PRED_INPUTS/source/hepta_pred1/run.py" \
  --output "$PRED_DELIVERY/diagnostic-native-001"
```

Use a new output directory for every diagnostic. Relocation changes absolute input paths and their aggregate manifest hash; implementation formatting changes the diagnostic implementation hash. The 48 fit rows, model comparisons and cost values must remain identical to the frozen historical diagnostic. Compare input role/SHA/size tuples, not the aggregate absolute-path hash.

## Launch the separate independent confirmation study

The next command performs training and generates the new study's confirmation data. It has not been run by this delivery. Use an exclusive new output directory; keep all failed attempts and the supervisor's log/resource receipts.

```sh
PRED_RUN="$PRED_DELIVERY/runs/native-independent-002-001"
env PYTHONDONTWRITEBYTECODE=1 \
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  uv run --no-project --python 3.12 --with numpy==2.3.5 \
  python "$PRED_DELIVERY/execution-supplement-001/guarded_confirm.py" \
  --bundle "$PRED_INPUTS" \
  --supplement "$PRED_DELIVERY/execution-supplement-001/EXECUTION_SUPPLEMENT.json" \
  --output "$PRED_RUN"
```

With a provisioned Python 3.12 + NumPy 2.3.5 interpreter, replace the `uv run ... python` launcher with that interpreter. The wrapper supplies the isolated archived package path itself. No `PYTHONPATH` modification is needed.

The original runner accepts 2–16 evaluation training seeds; the frozen configuration uses exactly 16 and three original family-selection seeds. It produces all fits first, writes `family-selection.json` and `selection.json`, then calls `generate_dataset(..., 'confirm', ...)`. The guard intercepts that first confirmation call and requires the expected GRU, unchanged source/config identities, all 114 checkpoint pins and their matching training records. It checks actual checkpoint bytes before forwarding to the original generator. Failed validation raises and preserves the failed attempt. It never substitutes a family, parameter, seed or checkpoint.

The wrapper changes no archived source bytes. Its only runtime hook is a separately identified forwarding callable around `hepta_pred1.run.generate_dataset`. Training and development calls pass through unchanged; confirmation order/count/history length must match the frozen configuration. Boundary and launch receipts live beside the campaign output in `<output>.execution/`, separate from the original runner's source snapshot and metrics.

## Denominators and operational budget

| Quantity | Frozen amount |
|---|---:|
| Reused selector seeds / fits | 3 / 18 |
| New evaluation training seeds / fits | 16 / 96 |
| All fits | 114 |
| Epochs / optimizer steps per fit | 30 / 960 |
| Total optimizer steps | 109,440 |
| Total training sample presentations | 14,008,320 |
| Independent primary statistical units | 16 training seeds |
| Confirmation episodes per seed | 1,024 |
| Distinct confirmation episode units | 16,384 |
| Six-model confirmation episode evaluations | 98,304 |

The original 48 fits consumed 141.20478683098918 training-wall seconds. Linear scaling gives **335.36 seconds of training** for 114 fits on comparable hardware. A practical planning range is **7–12 minutes overall**, excluding installation and queueing; it is an estimate, not a performance qualification. The original runner computes five exact sign-flip summaries with up to `2^16` sign assignments each after confirmation.

Recommended native supervisor limits: **one compute CPU quota, 4 GiB memory limit, 1,800 seconds wall timeout, and 1,800 CPU-seconds total budget**. An executor may allocate two logical CPUs for housekeeping while retaining one BLAS/OMP thread; no benefit from extra model-search workers is assumed. The RAM limit is a conservative operational allowance, not measured peak RSS. Record actual peak RSS, total wall/CPU, log truncation, exit status, timeout/termination and any recovery cost. Do not stop early based on observed scientific outcomes.

`<output>.execution/END.json` records the wrapper-plus-campaign total and boundary-check time. Boundary time is a subset of original campaign/wrapper elapsed time, so do not add it again. Installation, queueing, an externally terminated process, failure repair and publication remain separate costs. Money and energy remain unknown unless actually measured.

## Remaining original-source limitations and freeze handling

The 11 archived source files predate the later storage repair. Their improving checkpoints use the same per-fit filename and `wb` during training. The original runner creates the campaign directory exclusively, and the new guard checks all selected bytes before confirmation. Use an exclusive private directory; do not describe this original writer as the later create-only-per-epoch implementation. The archive has no `recover.py` and no automatic resume. If execution fails, preserve it and record a separately identified exact-identity recovery before attempting any repair; do not silently restart or replace seeds.

Original FREEZE SHA stays `19e6d61565d7d8fadf695a9a5814819197ac98835c80ad19d162e61db846b724`. Initial execution supplement SHA is `2d5d197b4825de1951f0301c6c59bed5ec849eebe0fa1c2d167985580626d37d`; initial guard SHA is `099b6272c981e87a078c3962f138334539b6d76a4cbd93a156ffe87ec066b17c`. If native formatting changes the guard bytes, preserve this supplement and create a new supplement with the final guard SHA before launching; re-run the 13 synthetic guard tests and check-only validation. Never rewrite the original FREEZE, historical diagnostic or 11 archived source files.
