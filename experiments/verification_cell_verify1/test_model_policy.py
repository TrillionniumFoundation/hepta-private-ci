import importlib.util
import sys
import json
from pathlib import Path
import tempfile
import unittest

from .model_protocol import Journal, cases, digest, frozen_plan
from .model_policy import Pilot


def dependencies():
    root = Path(__file__).resolve().parents[3]
    candidates = [root / "phase1-dependency/experiments/verification_cell_verify1", root / "source/experiments/verification_cell_verify1", Path(__file__).resolve().parent]
    source = next(path for path in candidates if (path / "runtime.py").is_file())
    result = {}
    for name in ("runtime", "contracts"):
        key = "verify1_policy_test_" + name
        spec = importlib.util.spec_from_file_location(key, source / (name + ".py"))
        result[name] = importlib.util.module_from_spec(spec)
        sys.modules[key] = result[name]
        spec.loader.exec_module(result[name])
    return result


class UnitOnlyScore:
    """Policy test input only. The runnable pilot always constructs MLXBackend."""
    identities = {"qwen": {"base_sha256": "a" * 64}, "smol": {"base_sha256": "b" * 64}}

    def __init__(self, value=0.0, fail=False):
        self.value, self.fail, self.calls = value, fail, []

    def score(self, key, role, view, context):
        if self.fail:
            raise RuntimeError("unit-injected inference failure")
        self.calls.append(view)
        return {"score": self.value, "operation_id": "unit-only", "base_sha256": self.identities[key]["base_sha256"],
                "adapter_sha256": None, "prompt_sha256": digest(view), "evidence_sha256": digest(view)}


class PolicyTests(unittest.TestCase):
    def test_intervention_changes_actual_host_check_frontier(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = frozen_plan()
            journal = Journal(Path(temporary) / "pilot", plan)
            model = UnitOnlyScore(0.4)
            pilot = Pilot(journal, dependencies(), model, plan)
            case = next(case for case in cases("confirmation") if case["fault"] == "semantic_error")
            rows = {setting["name"]: pilot.trajectory(case, "single", setting) for setting in plan["interventions"]}
            self.assertEqual([rows[name]["detected_step"] for name in ("risk_low", "risk_high", "cost_low", "cost_high")], [4, 2, 2, 4])
            self.assertEqual(len({digest(view) for view in model.calls}), 1)
            decisions = [json.loads(line) for line in (journal.directory / "decisions.jsonl").read_text().splitlines()]
            self.assertEqual(len({row["matched_evidence_parent_sha256"] for row in decisions}), 1)
            self.assertTrue(all(row["outcome_error"] and not row["accepted"] for row in rows.values()))

    def test_missing_ack_is_reconciled_not_labeled_value_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = frozen_plan()
            journal = Journal(Path(temporary) / "pilot", plan)
            pilot = Pilot(journal, dependencies(), UnitOnlyScore(), plan)
            case = next(case for case in cases("confirmation") if case["fault"] == "missing_receipt")
            row = pilot.trajectory(case, "single")
            self.assertEqual((row["accepted"], row["outcome_error"], row["detected_step"]), (True, False, 4))
            operations = [json.loads(line) for line in (journal.directory / "operations.jsonl").read_text().splitlines()]
            self.assertEqual(len([row for row in operations if row["kind"] == "host_effect"]), 3)
            self.assertEqual(len([row for row in operations if row["kind"] == "host_reconcile_without_replay"]), 1)


if __name__ == "__main__":
    unittest.main()
