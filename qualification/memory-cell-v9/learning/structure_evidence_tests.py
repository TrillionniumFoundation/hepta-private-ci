"""Raw evidence checks on development models and a real short resource process."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve()
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT.parents[2] / "memory-cell-v7"))

from evidence import canonical, decode, digest, read_json
from evidence_tests import development_export
from population_training import train_populations
from resource_evidence import verify_resources
from structure_evidence import population


class StructureEvidenceTests(unittest.TestCase):
    def test_variable_width_population_bits_and_route_corruption(self):
        export = development_export(9)
        config = {"shard_count": 3, "seed": 91317, "steps": 600, "dimension": 48, "total_hidden": 64, "threshold": 0.5}
        frame = {"schema": "hepta.memory.prospective-population-fit.v1", "export": export,
                 "configuration": config, "routing_mode": "fixed", "routing_trace": None}
        request = canonical(frame).decode()
        result = train_populations(export, config)
        result["request_digest"] = digest(request.encode())
        code = {"digest": digest(b"synthetic-development-audit"), "files": {}}
        with tempfile.TemporaryDirectory(prefix="hepta-v9-population-audit-") as temporary:
            root = Path(temporary)
            (root / "FIT_REQUEST.json").write_bytes(canonical({"request_json": request, "request_sha256": digest(request.encode()), "code_identity": code}))
            def save_response(value):
                raw = canonical(value).decode() + "\n"
                (root / "FIT_RESPONSE.json").write_bytes(canonical({"response_json": raw, "response_bytes": len(raw.encode()),
                    "request_bytes": len(request.encode()), "exit_code": 0, "stderr": "", "stderr_bytes": 0,
                    "whole_worker_wall_ns": 1, "code_identity": code}))
            save_response(result)
            checked, _ = population(root, code, export, 3)
            self.assertEqual(len(checked["semantic"]["shards"]), 3)
            corrupt = deepcopy(result)
            model = decode(corrupt["artifacts"]["semantic"]["native"])
            address = next(iter(model["routes"]))
            model["routes"][address] = (model["routes"][address] + 1) % 3
            corrupt["artifacts"]["semantic"]["native"] = canonical(model).decode()
            save_response(corrupt)
            with self.assertRaisesRegex(ValueError, "route/count"):
                population(root, code, export, 3)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux resource monitor")
    def test_resource_scorer_recomputes_real_samples_and_rejects_changed_integral(self):
        with tempfile.TemporaryDirectory(prefix="hepta-v9-resource-audit-") as temporary:
            root = Path(temporary)
            stock = root / "stock"
            stock.mkdir()
            command = [sys.executable, "-I", "-B", str(ROOT.parent / "resource_monitor.py")]
            for name, suffix in (("output", ".json"), ("samples", ".jsonl"), ("stdout", ".log"), ("stderr", ".log")):
                command.extend(["--" + name, str(root / (name + suffix))])
            command.extend(["--root", str(stock), "--interval-ms", "10", "--timeout-seconds", "5", "--", sys.executable,
                            "-I", "-B", "-c", "import time; values=bytearray(1048576); time.sleep(.08)"])
            began = time.perf_counter_ns()
            completed = subprocess.run(command, capture_output=True, timeout=10, check=False)
            wall = time.perf_counter_ns() - began
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            receipt = read_json(root / "output.json")
            checked = verify_resources(root, receipt, receipt["child_pid"], wall)
            self.assertTrue(checked["observation_wall_coverage_verified"])
            corrupt = deepcopy(receipt)
            corrupt["integrals"]["tree_rss_bytes"]["unobserved_interval_ns"] += 1
            with self.assertRaisesRegex(ValueError, "integral mismatch"):
                verify_resources(root, corrupt, receipt["child_pid"], wall)
            # Preserve the summed gap and every integral while misplacing the
            # unknown interval. Raw endpoints must still reject this receipt.
            corrupt = deepcopy(receipt)
            corrupt["sampling_gaps"]["before_first_sample_ns"] -= 1
            corrupt["sampling_gaps"]["after_last_sample_ns"] += 1
            with self.assertRaisesRegex(ValueError, "sampling gaps"):
                verify_resources(root, corrupt, receipt["child_pid"], wall)
            corrupt = deepcopy(receipt)
            corrupt["wall_ns_through_observation_close"] += 1
            with self.assertRaisesRegex(ValueError, "observation endpoints"):
                verify_resources(root, corrupt, receipt["child_pid"], wall)
            corrupt = deepcopy(receipt)
            corrupt["observations_ended_monotonic_ns"] += 1
            corrupt["wall_ns_through_observation_close"] += 1
            with self.assertRaisesRegex(ValueError, "sampling gaps"):
                verify_resources(root, corrupt, receipt["child_pid"], wall)
            sample_path = root / "samples.jsonl"
            original_samples = sample_path.read_bytes()
            samples = [decode(line) for line in original_samples.splitlines()]
            samples[0]["elapsed_ns"] += 1
            changed = b"".join(canonical(sample) + b"\n" for sample in samples)
            sample_path.write_bytes(changed)
            corrupt = deepcopy(receipt)
            corrupt["samples"].update(bytes=len(changed), sha256=digest(changed))
            with self.assertRaisesRegex(ValueError, "sample elapsed time"):
                verify_resources(root, corrupt, receipt["child_pid"], wall)


if __name__ == "__main__":
    unittest.main()
