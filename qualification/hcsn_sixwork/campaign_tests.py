"""Independent stdlib toys: no model, campaign registration or formal data."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv

from .campaign import admitted_selection, child_process, exclusive, python_identity, remaining
from .integrity import ARMS, TASKS, ledger_check, sha, validate


def toy_cost(root, name, budget):
    tail, encoded = "0" * 64, []
    rows = [{"kind": "reserve", "operation": 0, "charge": {"forward_examples": 2}},
            {"kind": "settle", "operation": 0, "status": "completed", "cumulative_wall_seconds": 1.}]
    for row in rows:
        row.update(identity="toy", budget=budget, previous=tail)
        tail = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        row["hash"] = tail
        encoded.append(json.dumps(row))
    (root / "cost.jsonl").write_text("\n".join(encoded) + "\n")
    exclusive(root / (name + ".cost.json"), {"tail": tail, "pending": None,
        "wall_overrun_seconds": 0, "wall_seconds": 1.1, "forward_examples": 2})


class CampaignTests(unittest.TestCase):
    def test_single_use_reservation_and_cumulative_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "toy-reserve.json"
            exclusive(path, {"toy": True})
            with self.assertRaises(FileExistsError):
                exclusive(path, {"toy": True})
        self.assertEqual(remaining(180, 70), 110)
        with self.assertRaises(ValueError):
            remaining(90, 91)

    def test_complete_child_wall_failure_and_timeout_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = child_process([sys.executable, "-c", "print('toy'); raise SystemExit(3)"],
                                   root, root, "toy-failure", 2)
            self.assertEqual(failed["returncode"], 3)
            self.assertFalse(failed["timed_out"])
            self.assertIn("toy", (root / "toy-failure.stdout").read_text())
            timeout = child_process([sys.executable, "-c", "import time; time.sleep(2)"],
                                    root, root, "toy-timeout", .1)
            self.assertTrue(timeout["timed_out"])
            self.assertLess(timeout["wall_seconds"], 1)
            self.assertNotEqual(timeout["returncode"], 0)

    def test_pending_ledger_cannot_pass_as_zero_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "toy-ledger.jsonl"
            budget = {"wall_seconds": 180, "forward_examples": 10}
            reserve = {"kind": "reserve", "operation": 0, "name": "toy",
                       "charge": {"forward_examples": 2}, "identity": "toy", "budget": budget,
                       "previous": "0" * 64}
            digest = hashlib.sha256(json.dumps(reserve, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            reserve["hash"] = digest
            path.write_text(json.dumps(reserve) + "\n")
            with self.assertRaisesRegex(ValueError, "unsettled"):
                ledger_check(path, "toy", budget)

    def test_venv_child_keeps_lexical_interpreter_and_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = root / "toy-venv"
            venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
            invocation = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            with patch("sys.executable", str(invocation)):
                identity = python_identity()
            self.assertEqual(identity["python"], str(invocation))
            self.assertEqual(identity["python_realpath"], str(invocation.resolve()))
            process = child_process([identity["python"], "-c",
                "import json,sys; print(json.dumps([sys.prefix,sys.base_prefix]))"],
                root, root, "toy-venv", 5)
            self.assertEqual(process["returncode"], 0)
            prefix, base_prefix = json.loads((root / "toy-venv.stdout").read_text())
            self.assertEqual(Path(prefix), environment)
            self.assertNotEqual(prefix, base_prefix)

    def test_final_rejects_selection_changed_after_fit_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selection.json"
            exclusive(path, {"toy": "validated"})
            original = sha(path)
            previous = {"validated_selection_sha256": original,
                        "validation": {"receipt_sha256": original}}
            admitted_selection(previous, path, original)
            path.write_text('{"toy":"changed"}')
            for supplied in (original, sha(path)):
                with self.assertRaisesRegex(ValueError, "originally validated"):
                    admitted_selection(previous, path, supplied)

    def test_exit_zero_receipt_with_failed_cell_is_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = {"wall_seconds": 90, "forward_examples": 10}
            toy_cost(root, "selection", budget)
            arms = {name: {"status": "no_update", "candidate_dev_return": 0.,
                          "selected_probability": [0.] * 5}
                    for name in ("howard_qvi", "lookup_gate_bp", "never_reset")}
            receipt = {"manifest_sha256": "toy", "phase": "fit", "cases": {"1": {"methods": arms}}}
            exclusive(root/"selection.json", receipt)
            cfg = {"seeds": [1], "budget": budget}
            valid = validate(root, cfg, "boundary", "fit", "toy")
            self.assertTrue(valid["passed"])
            self.assertEqual(valid["receipt_sha256"], sha(root / "selection.json"))
            receipt["cases"]["2"] = receipt["cases"]["1"]
            (root/"selection.json").write_text(json.dumps(receipt))
            self.assertFalse(validate(root, cfg, "boundary", "fit", "toy")["integrity_ok"])
            del receipt["cases"]["2"]
            arms["unplanned"] = arms["never_reset"]
            (root/"selection.json").write_text(json.dumps(receipt))
            self.assertFalse(validate(root, cfg, "boundary", "fit", "toy")["integrity_ok"])
            del arms["unplanned"]
            arms["lookup_gate_bp"] = {"status": "failed", "error": "deliberate toy failure"}
            (root/"selection.json").write_text(json.dumps(receipt))
            self.assertFalse(validate(root, cfg, "boundary", "fit", "toy")["integrity_ok"])

    def test_success_row_without_split_cannot_count_as_both_final_regimes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = {"wall_seconds": 180, "forward_examples": 10}
            toy_cost(root, "final", budget)
            exclusive(root / "selection.json", {"toy": "independent artificial receipt"})
            selected = sha(root / "selection.json")
            (root / "FINAL_CONSUMED").write_text(selected)
            rows = [{"case": task + "/1", "method": method, "split": split,
                     "status": "selected", "sample_squared_errors": [1., 1.], "mse": 1.,
                     "prediction": [1., 2.], "target": [0., 1.], "ids": [task+split+"a", task+split+"b"],
                     "data_sha256": "independent-toy"}
                    for task in TASKS for method in ARMS["feature"]
                    for split in ("final_iid", "final_clock")]
            receipt = {"manifest_sha256": "toy", "phase": "final", "results": rows}
            exclusive(root / "final.json", receipt)
            cfg = {"seeds": [1], "budget": budget, "final": 2}
            self.assertTrue(validate(root, cfg, "feature", "final", "toy", selected)["passed"])
            del rows[0]["split"]
            del rows[1]
            (root / "final.json").write_text(json.dumps(receipt))
            invalid = validate(root, cfg, "feature", "final", "toy", selected)
            self.assertFalse(invalid["integrity_ok"])
            self.assertTrue(any("missing/duplicate final cell" in x for x in invalid["defects"]))


if __name__ == "__main__":
    unittest.main()

