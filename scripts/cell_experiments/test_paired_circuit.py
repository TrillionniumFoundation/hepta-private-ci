"""Exercise the public paired intake and cold execution with real fitted Cell weights."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from . import coding_sft, data, paired_cold, paired_freeze
from .online_v4.test_circuit_bundle import setup_fixture


def evaluate_fixture(root, request):
    spec = {
        key: request[key]
        for key in ("parent", "candidate", "retention", "timeout_seconds")
    }
    coding_sft.write_new(root / "spec.json", spec)
    freeze = paired_freeze.freeze(root / "spec.json", root, root / "FROZEN.json")
    coding_sft.write_new(root / "future.json", request["future"])
    path = root / "paired.json"
    bound = paired_freeze.assemble(
        root / "FROZEN.json", freeze, root / "future.json", path
    )
    if bound != data.digest(request):
        raise ValueError("assembled fixture differs from the registered request")
    out = root / "evaluation"
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "cell_experiments.paired_cold",
            str(path),
            bound,
            str(root),
            str(out),
        ],
        env=env,
        check=True,
    )
    return json.loads((out / "RESULT.json").read_bytes())


class RoutedPairTests(unittest.TestCase):
    def test_two_phase_fitted_circuits_and_exposure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "materials"
            request = setup_fixture(root)
            result = evaluate_fixture(root, request)
            self.assertTrue(result["circuit_loaded"])
            self.assertEqual(
                result["paired_circuit_changes"]["changed_cell_weights"], ["source"]
            )
            self.assertEqual(result["counts"]["future"]["candidate_only"], 1)
            self.assertEqual(result["counts"]["retention"]["both"], 1)
            self.assertEqual(len({r["pid"] for r in result["cold_receipts"]}), 2)
            for arm in paired_cold.ARMS:
                work = result["measured_circuit_work"][arm]
                self.assertEqual(work["model_calls"], 4)
                for index, panel in enumerate(paired_cold.PANELS):
                    row = json.loads(
                        (root / "evaluation" / arm / f"{index:04d}.json").read_bytes()
                    )
                    self.assertEqual(row["panel"], panel)
                    nodes = row["prediction"]["circuit_trace"]["nodes"]
                    self.assertEqual(
                        row["input_ids_sha256"], nodes[0]["output"]["input_ids_sha256"]
                    )
            duplicate = copy.deepcopy(request)
            duplicate["future"][0]["task"]["input"] = "train"
            with self.assertRaisesRegex(ValueError, "router training input"):
                paired_cold.token_inputs(duplicate, request["candidate"], root)
            child = copy.deepcopy(request["candidate"])
            child["models"]["source"]["parent"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "wrong changed Cell parent"):
                paired_cold.checked_models(request["parent"], child)
            child = copy.deepcopy(request["candidate"])
            child["budget"]["max_relay_bytes"] += 1
            with self.assertRaisesRegex(ValueError, "budget changed"):
                paired_cold.checked_models(request["parent"], child)
            old_cell = request["parent"]["models"]["source"]
            extra = copy.deepcopy(old_cell)
            extra["files"].append(
                {"path": "unused.safetensors", "role": "adapter", "sha256": "a" * 64}
            )
            self.assertFalse(paired_cold.cell_weights_changed(old_cell, extra))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        # PEFT records this name in adapter_config.json. Preserve a supplied relative path.
        destination = Path(sys.argv[2])
        print(
            json.dumps(
                evaluate_fixture(destination, setup_fixture(destination)), indent=2
            )
        )
    else:
        unittest.main()
