# R16 causal missing-content posterior

This small continuation depends on the complete addressed-flow source at
`a793d55c23a7742378b081b162252da428a9fdb2`. It preserves the old generator,
models, training, opened confirmation and failure records. Review
`INFERENCE_SCOPE.md` before interpreting the Selective missing-target subgroup.

Implementation stages are independently reviewable:

1. `posterior.py` and `audit.py`: exact ordinary observer,
   common calibration layer, independent latent enumeration and old-world replay.
2. `confirm.py`, `CONFIRMATION_PROTOCOL.json` and
   `SOURCE_MANIFEST.json`: prospective fixed-model confirmation and full evidence.

## Prepare existing frozen weights

From the repository root, reconstruct the already published archive and verify
its identity before extracting into `frozen_weights/`:

```python
from pathlib import Path
import hashlib, io, json, tarfile
root = Path(".")
folder = root / "experiments/hcsn_addressed_flow_20261101/artifacts"
manifest = json.loads((folder / "RETENTION_CANDIDATE_ARCHIVE.json").read_text())
parts = []
for item in manifest["parts"]:
    payload = (root / item["path"]).read_bytes()
    assert len(payload) == item["bytes"]
    assert hashlib.sha256(payload).hexdigest() == item["sha256"]
    parts.append(payload)
payload = b"".join(parts)
assert hashlib.sha256(payload).hexdigest() == manifest["archive_sha256"]
with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
    archive.extractall(root / "frozen_weights", filter="data")
```

The numerical runtime requires NumPy, SciPy and CPU PyTorch. The observed runtime
used Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0 and PyTorch 2.15.0+cpu. GPU execution
and energy are not tested. `PYTHONPATH=/tmp/hcsn-torch-runtime` was a session-local
runtime selector; it is not a required repository path.

## Reproduce opened development

```bash
python -m experiments.hcsn_missing_posterior_r16_20261101.audit --out /tmp/missing-dev-replay
```

The driver checks original checkpoint hashes and requires all 18 original
missing-condition accuracy results to reproduce. New raw inputs and outputs,
source hashes and measured nested costs are saved in the output directory.

## Execute fresh confirmation

Only after the source freeze is published and read back:

```bash
python -m experiments.hcsn_missing_posterior_r16_20261101.confirm --source-commit EXACT_REMOTE_SOURCE_SHA --out /tmp/missing-fresh-confirmation
```

Supply the actual 40-character source SHA. The driver rejects source or model
drift. Use a parent process meter to capture interpreter startup, all imports,
exit code, CPU, wall time and peak RSS in addition to its nested execution
timers. On failure retain the entire output directory and outer process receipt;
an absent or incomplete summary is not acceptance. No new result may be pooled
with the opened development stream.

## Independent confirmation audit

`audit_confirm_independent.py` reads the single completed `confirmation_01`,
reconstructs all 3,072 causal posteriors independently, recomputes proper-score
bounds and episode reliability from raw arrays, and checks the actual READ
successors. It imports no project inference or statistics helper. Run it from
the repository root with:

```bash
python -B -m experiments.hcsn_missing_posterior_r16_20261101.audit_confirm_independent
```

Its evidence and separate entire-process cost are retained in
`INDEPENDENT_CONFIRMATION_AUDIT.json` and `INDEPENDENT_AUDIT_PROCESS_RECEIPT.json`.
The source freeze, opened development and confirmation remain distinct.
