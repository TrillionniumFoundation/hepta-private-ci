"""Temporary-fixture tests of receipt validation; no scientific run is made."""

import hashlib
import json
from pathlib import Path
import runpy
import tempfile


ROOT = Path(__file__).resolve().parent
SCHEDULER = ROOT / "run_formal.py"
api = runpy.run_path(str(SCHEDULER))
validate = api["validate_completion"]
specification = {"id": "unit_fixture", "task": "fixture_only"}

with tempfile.TemporaryDirectory(prefix="hepta_scheduler_unit_") as temporary:
    output = Path(temporary)
    folder = output / "candidates" / "unit_fixture"
    folder.mkdir(parents=True)
    rows = [{"update": i, "training_cpu_seconds": i / 10} for i in range(1, 385)]
    (folder / "training_trace.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    checkpoints = {}
    for name, step in {"step0": 0, "cpu15": 150, "cpu30": 300, "update192": 192, "update384": 384}.items():
        path = folder / f"{name}.fixture"
        path.write_bytes(f"Synthetic receipt-validation fixture {name}".encode())
        checkpoints[name] = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "updates": step, "training_cpu_seconds": step / 10}
    diagnostics = folder / "final_train_diagnostics.npz"
    diagnostics.write_bytes(b"Synthetic diagnostic-digest fixture, not scientific model data")
    receipt = {"status": "complete", "specification": specification, "updates": 384,
               "training_cpu_seconds": 38.4, "checkpoints": checkpoints,
               "diagnostic_sha256": hashlib.sha256(diagnostics.read_bytes()).hexdigest()}
    completion = folder / "complete.json"
    completion.write_text(json.dumps(receipt))
    validate(output, specification)
    accepted_valid_budget_endpoint = True
    receipt["checkpoints"]["cpu30"]["updates"] = 301
    completion.write_text(json.dumps(receipt))
    rejected_overbudget_step = False
    try:
        validate(output, specification)
    except RuntimeError as error:
        rejected_overbudget_step = "last completed in-budget update" in str(error)
    if not rejected_overbudget_step:
        raise AssertionError("An over-budget checkpoint was accepted")
    receipt["checkpoints"]["cpu30"]["updates"] = 300
    completion.write_text(json.dumps(receipt))
    (folder / "update384.fixture").write_bytes(b"Altered retained checkpoint")
    rejected_checkpoint_mutation = False
    try:
        validate(output, specification)
    except RuntimeError as error:
        rejected_checkpoint_mutation = "Checkpoint digest mismatch" in str(error)
    if not rejected_checkpoint_mutation:
        raise AssertionError("A modified checkpoint was accepted")

result = {"status": "passed_temporary_fixture_tests_only", "formal_training_performed": False,
          "formal_validation_or_test_read": False,
          "scheduler_source_sha256": hashlib.sha256(SCHEDULER.read_bytes()).hexdigest(),
          "accepted_valid_budget_endpoint": accepted_valid_budget_endpoint,
          "rejected_overbudget_step": rejected_overbudget_step,
          "rejected_checkpoint_mutation": rejected_checkpoint_mutation}
with (ROOT / "scheduler_qualification.json").open("x") as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result, indent=2))
