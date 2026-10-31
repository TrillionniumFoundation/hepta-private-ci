"""One narrow synthetic test of the actual CLI main scope serialization order.

The CLI source is unchanged. Model, Torch, asset, corpus, context and train
execution are stubbed; all old-input files are synthetic temporary JSON.
"""
import argparse
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from ..field_bridge_v4_20261027 import training_run as cli

HERE = Path(__file__).resolve().parent


class CliScopeContract(unittest.TestCase):
    def test_actual_main_preserves_complete_scope_in_all_three_receipts(self):
        with tempfile.TemporaryDirectory(prefix="training-cli-scope-synthetic-", dir=HERE) as temporary:
            folder = Path(temporary)
            root, old_root = folder / "run", folder / "synthetic-old"
            protocol = {"study_id": "hepta.field-bridge.v4.synthetic-cli-scope",
                        "source_allocation_sha256": "a" * 64, "source_manifest_sha256": "b" * 64}
            protocol_path, freeze_path = folder / "PROTOCOL.json", folder / "FREEZE.json"
            protocol_path.write_text(json.dumps(protocol))
            freeze_path.write_text(json.dumps({"synthetic_fixture_only": True}))
            inputs = {"bank_sha256": old_root / "bank/17/BANK.json",
                      "controller_file_sha256": old_root / "fit/17/CONTROLLERS.json",
                      "reference_file_sha256": old_root / "reference/17/REFERENCE.json"}
            for key, path in inputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"synthetic_fixture_only": True, "seed": 17, "kind": key}))
            pins = {key: cli.file_hash(path) for key, path in inputs.items()}
            required, calls = {"synthetic_dependency.py": "c" * 64}, []
            freeze = {"registered_commit": "d" * 40}
            objects = {"original": object(), "reward": object()}
            expected_scope = cli.run_scope(protocol_path, freeze_path, protocol, freeze, required)
            expected_scope.update(pins)

            def verify(freeze_arg, protocol_arg, phase, out, old):
                self.assertEqual(Path(freeze_arg), freeze_path)
                self.assertEqual(Path(protocol_arg), protocol_path)
                self.assertEqual((phase, Path(out), Path(old)), ("train", root, old_root))
                calls.append("verify")
                return protocol, freeze, required

            def policies(fitted, bank, received_protocol, scope):
                self.assertEqual(received_protocol, protocol)
                self.assertEqual(scope, expected_scope)
                self.assertFalse((root / "train/17/START.json").exists())
                calls.append("policies-before-start")
                return []

            def assets(asset_root, seeds, observers):
                self.assertEqual((seeds, observers), ([17], ["reward"]))
                start = json.loads((root / "train/17/START.json").read_text())
                self.assertEqual(start["scope"], expected_scope)
                calls.append("stub-assets-after-start")
                return {17: objects["original"]}, {"reward": objects["reward"]}, {"synthetic_fixture_only": True}

            def corpus(asset_root, roles, manifest_path=None, phase="adaptation"):
                self.assertEqual(roles, list(cli.ADAPTATION_ROLES))
                self.assertEqual(phase, "adaptation")
                calls.append("stub-corpus")
                return SimpleNamespace(manifest={"manifest_sha256": protocol["source_manifest_sha256"]},
                                       splits=dict.fromkeys(roles))

            def context(original, loaded_corpus, observers, seed, group, received_protocol):
                self.assertIs(original, objects["original"])
                self.assertIs(observers["reward"], objects["reward"])
                self.assertEqual((seed, group, received_protocol), (17, "qualification", protocol))
                calls.append("stub-context")
                return SimpleNamespace(seed=17, protocol=protocol)

            def train(context, fitted, bank, scope, destination):
                start = json.loads((destination / "START.json").read_text())
                self.assertEqual(scope, start["scope"])
                self.assertEqual(scope, expected_scope)
                calls.append("stub-train")
                result = {"schema": cli.SCHEMA + ".trained-seed.1", "study_id": protocol["study_id"],
                          "seed": 17, "scope": deepcopy(scope), "synthetic_fixture_only": True}
                cli.write_json(destination / "COMPLETE.json", result)
                return result

            torch_stub = ModuleType("torch")
            torch_calls = []
            torch_stub.set_num_threads = lambda value: torch_calls.append(("threads", value))
            torch_stub.set_num_interop_threads = lambda value: torch_calls.append(("interop", value))
            torch_stub.use_deterministic_algorithms = lambda value: torch_calls.append(("deterministic", value))
            assets_stub = ModuleType("synthetic_assets"); assets_stub.load_assets = assets
            source_stub = ModuleType("synthetic_sources"); source_stub.load_corpus_roles = corpus
            learning_stub = ModuleType("synthetic_learning"); learning_stub.make_context = context
            modules = {"torch": torch_stub,
                "experiments.multimodal_output_portfolio.field_bridge_v3_20261027.assets": assets_stub,
                "experiments.multimodal_output_portfolio.field_bridge_v3_20261027.learning": learning_stub,
                "experiments.multimodal_output_portfolio.field_bridge_v4_20261027.source_roles": source_stub}
            argv = ["training_run", "train", "--seed", "17", "--assets", str(folder / "unused-assets"),
                    "--out", str(root), "--v3-run-root", str(old_root), "--protocol", str(protocol_path),
                    "--freeze", str(freeze_path)]
            with mock.patch.dict(sys.modules, modules), mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(cli, "verify_freeze", side_effect=verify), \
                 mock.patch.object(cli, "policies", side_effect=policies), \
                 mock.patch.object(cli, "source_files", return_value=required), \
                 mock.patch.object(cli, "train_seed", side_effect=train), redirect_stdout(io.StringIO()):
                cli.main()

            start = json.loads((root / "train/17/START.json").read_text())
            complete = json.loads((root / "train/17/COMPLETE.json").read_text())
            phase = json.loads((root / "PHASE_RECEIPTS/train-17.json").read_text())
            self.assertEqual(start["scope"], complete["scope"])
            self.assertEqual(complete["scope"], phase["scope"])
            self.assertEqual(phase["scope"], expected_scope)
            self.assertTrue(all(phase["scope"][key] == value for key, value in pins.items()))
            self.assertEqual(phase["complete_sha256"], cli.file_hash(root / "train/17/COMPLETE.json"))
            self.assertEqual(calls, ["verify", "policies-before-start", "stub-assets-after-start",
                                     "stub-corpus", "stub-context", "stub-train", "verify"])
            self.assertEqual(torch_calls, [("threads", 2), ("interop", 1), ("deterministic", True)])
            self.assertFalse((root / "train/17/FAILED.json").exists())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite an existing receipt")
    started = time.perf_counter_ns()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CliScopeContract))
    files = [Path(__file__), Path(cli.__file__)]
    receipt = {"schema": cli.SCHEMA + ".cli-scope-serialization-contract.1", "passed": result.wasSuccessful(),
        "tests_run": result.testsRun, "errors": len(result.errors), "failures": len(result.failures),
        "verification_scope": "Actual main orchestration with synthetic old inputs and stubbed execution; existing pre-START pin enrichment verified",
        "cli_source_changed": False, "new_bug_fix_claimed": False,
        "original_model_observer_corpus_or_frozen_fit_data_loaded": False,
        "model_calls": 0, "optimizer_steps": 0,
        "wall_ns": time.perf_counter_ns() - started,
        "source_files": {str(path.relative_to(HERE.parent)): cli.file_hash(path) for path in files}}
    cli.write_json(args.output, receipt)
    raise SystemExit(0 if result.wasSuccessful() else 1)
