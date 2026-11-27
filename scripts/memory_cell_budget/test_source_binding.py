"""Independent source pins must match actual imports before any model worker."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cohort_contract
from cohort_contract import file_sha
from model_budget import ledger_for, model_call
from prepare_budget_study import common_budget
import run_budget_models as runner


def inputs(root):
    implementation = root / "implementation"
    paths = (
        "scripts/memory_cell/parametric_model.py",
        "scripts/memory_cell/parametric_worker.py",
        "scripts/memory_cell_population/population_transfer.py",
        "scripts/memory_cell_network/model_process.py",
    )
    for name in paths:
        path = implementation / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('raise RuntimeError("fixture source must not execute")\n')
    controller = Path(cohort_contract.__file__).resolve().parent
    code = list(implementation.rglob("*.py")) + [
        p for p in controller.glob("*.py") if not p.name.startswith("test_")
    ]
    study = root / "study"
    study.mkdir()
    protocol = {"implementation_base": "4" * 40, "common_budget": common_budget()}
    (study / "protocol.json").write_text(json.dumps(protocol))
    seal = {
        "files": {"protocol.json": file_sha(study / "protocol.json")},
        "code": {str(p.resolve()): file_sha(p) for p in code},
        "external_inputs": {},
    }
    (study / "seal.json").write_text(json.dumps(seal))
    return study, implementation


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.study, self.implementation = inputs(self.root)

    def test_correct_independent_source_pin_preserves_admission_without_import(self):
        forms = (
            (self.implementation, self.study),
            (
                Path(os.path.relpath(self.implementation)),
                Path(os.path.relpath(self.study)),
            ),
        )
        for index, (implementation, study) in enumerate(forms):
            with self.subTest(relative=index == 1):
                result = cohort_contract.bind_implementation(study, implementation)
                self.assertEqual(
                    {
                        key: result[key]
                        for key in ("implementation", "study", "seal_sha256")
                    },
                    {
                        "implementation": str(self.implementation),
                        "study": str(self.study),
                        "seal_sha256": file_sha(self.study / "seal.json"),
                    },
                )
                self.assertEqual(len(result["source_set_sha256"]), 64)
                calls = []

                def child(script, argv, **kwargs):
                    request = json.loads(kwargs["input_text"])
                    calls.append((argv, request, kwargs["cwd"]))
                    receipt = self.root / ("synthetic-receipt-" + str(index) + ".json")
                    receipt.write_text("{}")
                    output = {
                        "source_binding": request["source_binding"],
                        "receipts": [],
                        "worker_process_io_before_stdout": {"rchar": 0, "wchar": 0},
                    }
                    return {"stdout": json.dumps(output), "receipt_path": str(receipt)}

                module = SimpleNamespace(
                    __file__=str(
                        self.implementation
                        / "scripts/memory_cell_network/model_process.py"
                    ),
                    ChildFailure=ValueError,
                    run_child=child,
                )
                ledger = ledger_for(
                    self.root / ("positive-" + str(index) + ".sqlite3"),
                    "test",
                    {"common_budget": common_budget()},
                    "0" * 64,
                )
                destination = self.root / ("worker-" + str(index))
                with patch.dict(sys.modules, {"model_process": module}):
                    measured = model_call(
                        ledger,
                        "synthetic",
                        {"phase": "parent", "study": str(study)},
                        implementation=implementation,
                        study=study,
                        directory=destination,
                    )
                self.assertEqual(len(calls), 1)
                argv, request, cwd = calls[0]
                self.assertEqual(
                    argv[argv.index("--implementation") + 1], str(self.implementation)
                )
                self.assertEqual(argv[argv.index("--study") + 1], str(self.study))
                self.assertEqual(request["study"], str(self.study))
                self.assertEqual(cwd, destination)
                self.assertEqual(measured["source_binding"], result)

    def test_other_checkout_at_same_head_is_rejected_before_worker_dispatch(self):
        other = self.root / "other"
        shutil.copytree(self.implementation, other)
        args = SimpleNamespace(
            study=self.study,
            implementation=other,
            model=self.root / "model",
            output=self.root / "output",
            runtime_component=None,
            model_lane_authorized=True,
        )
        with (
            patch.object(runner.subprocess, "check_output", return_value="4" * 40),
            patch.object(
                runner, "model_call", side_effect=RuntimeError("child boundary")
            ) as child,
        ):
            with self.assertRaisesRegex(ValueError, "independently pinned"):
                runner.run(args)
        child.assert_not_called()
        self.assertFalse(args.output.exists())

    def test_changed_model_source_is_rejected_without_resealing_history(self):
        before = (self.study / "seal.json").read_bytes()
        (self.implementation / "scripts/memory_cell/parametric_model.py").write_text(
            "changed = True\n"
        )
        with self.assertRaises(ValueError):
            cohort_contract.bind_implementation(self.study, self.implementation)
        self.assertEqual((self.study / "seal.json").read_bytes(), before)

    def test_new_unsealed_source_is_rejected(self):
        (self.implementation / "scripts/memory_cell/unregistered.py").write_text(
            "pass\n"
        )
        with self.assertRaisesRegex(ValueError, "independently pinned"):
            cohort_contract.bind_implementation(self.study, self.implementation)

    def test_foreign_cached_import_is_rejected_before_model_runtime(self):
        foreign = self.root / "foreign.py"
        foreign.write_text("pass\n")
        with patch.dict(
            sys.modules, {"parametric_model": SimpleNamespace(__file__=str(foreign))}
        ):
            with self.assertRaisesRegex(ValueError, "loaded implementation module"):
                cohort_contract.bind_implementation(self.study, self.implementation)

    def test_package_shadowing_pinned_python_file_is_rejected(self):
        package = self.implementation / "scripts/memory_cell/parametric_model"
        package.mkdir()
        (package / "__init__.py").write_text("pass\n")
        with self.assertRaisesRegex(ValueError, "import resolution"):
            cohort_contract.bind_implementation(self.study, self.implementation)

    def test_model_call_rejects_wrong_root_before_creating_worker_evidence(self):
        other = self.root / "other"
        shutil.copytree(self.implementation, other)
        wrong_study = self.root / "other-study"
        wrong_study.mkdir()
        for index, (implementation, request_study) in enumerate(
            ((other, self.study), (self.implementation, wrong_study))
        ):
            with self.subTest(wrong_implementation=index == 0):
                ledger = ledger_for(
                    self.root / ("budget-" + str(index) + ".sqlite3"),
                    "test",
                    {"common_budget": common_budget()},
                    "0" * 64,
                )
                destination = self.root / ("worker-" + str(index))
                with self.assertRaisesRegex(ValueError, "independently pinned"):
                    model_call(
                        ledger,
                        "no-worker",
                        {"phase": "parent", "study": str(request_study)},
                        implementation=implementation,
                        study=self.study,
                        directory=destination,
                    )
                self.assertEqual(ledger.snapshot()["events"], [])
                self.assertFalse(destination.exists())

    def test_direct_worker_rejects_wrong_root_before_importing_model(self):
        other = self.root / "other"
        shutil.copytree(self.implementation, other)
        wrong_study = self.root / "other-study"
        wrong_study.mkdir()
        binding = cohort_contract.bind_implementation(self.study, self.implementation)
        for index, (implementation, request_study) in enumerate(
            ((other, self.study), (self.implementation, wrong_study))
        ):
            with self.subTest(wrong_implementation=index == 0):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(
                            Path(cohort_contract.__file__).with_name(
                                "budget_model_worker.py"
                            )
                        ),
                        "--implementation",
                        str(implementation),
                        "--study",
                        str(self.study),
                        "--seal-sha256",
                        file_sha(self.study / "seal.json"),
                    ],
                    input=json.dumps(
                        {
                            "phase": "parent",
                            "study": str(request_study),
                            "source_binding": binding,
                        }
                    ),
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("independently pinned", result.stderr)
                self.assertNotIn("fixture source must not execute", result.stderr)


if __name__ == "__main__":
    unittest.main()
