"""R10 adversarial audit tests on real outputs; originals are never mutated."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np


class TamperTests(unittest.TestCase):
    def attempt(self, kind, expected):
        source = Path(os.environ["NDU_R10_SOURCE"])
        runs = Path(os.environ["NDU_R10_RUNS"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / "runs"
            fake.mkdir()
            for name in ("PLAN.json", "COMPLETE.json", "LAWS.npz"):
                shutil.copy2(runs / name, fake / name)
            complete = json.loads((fake / "COMPLETE.json").read_text())
            first = complete["census"][0]["name"]
            for row in complete["census"]:
                if row["name"] == first:
                    shutil.copytree(runs / first, fake / first)
                else:
                    (fake / row["name"]).symlink_to(runs / row["name"], target_is_directory=True)
            folder = fake / first
            report_path = folder / "REPORT.json"
            report = json.loads(report_path.read_text())
            if kind == "census":
                complete["census"].pop()
            elif kind == "tensor":
                with np.load(folder / "WEIGHTS.npz", allow_pickle=False) as data:
                    theta = data["theta"].copy()
                theta[0] += 0.1
                np.savez_compressed(folder / "WEIGHTS.npz", theta=theta)
            elif kind == "terminal":
                report["fit"]["terminal_cc5"] += 0.1
                report["fit"]["final_qualification"] = not report["fit"]["final_qualification"]
                (folder / "FIT.json").write_text(json.dumps(report["fit"]))
                seal = json.loads((folder / "FIT_SEAL.json").read_text())
                seal["fit_sha256"] = hashlib.sha256((folder / "FIT.json").read_bytes()).hexdigest()
                (folder / "FIT_SEAL.json").write_text(json.dumps(seal))
            elif kind == "stage":
                report["fit"]["stages"][0]["name"] = "gl5" if report["case"]["schedule"] == "stage_gl3_gl5" else "gl3"
                (folder / "FIT.json").write_text(json.dumps(report["fit"]))
                seal = json.loads((folder / "FIT_SEAL.json").read_text())
                seal["fit_sha256"] = hashlib.sha256((folder / "FIT.json").read_bytes()).hexdigest()
                (folder / "FIT_SEAL.json").write_text(json.dumps(seal))
            elif kind == "monitor":
                # If first run is frequent, falsify a monitor; otherwise falsify zero-monitor semantics.
                report["fit"]["monitor_wall"] += 0.1
                (folder / "FIT.json").write_text(json.dumps(report["fit"]))
                seal = json.loads((folder / "FIT_SEAL.json").read_text())
                seal["fit_sha256"] = hashlib.sha256((folder / "FIT.json").read_bytes()).hexdigest()
                (folder / "FIT_SEAL.json").write_text(json.dumps(seal))
            elif kind == "law":
                with np.load(fake / "LAWS.npz", allow_pickle=False) as data:
                    laws = {key: data[key].copy() for key in data.files}
                laws["gl3_weights"][0] += 1e-5
                np.savez_compressed(fake / "LAWS.npz", **laws)
                plan = json.loads((fake / "PLAN.json").read_text())
                plan["law_sha256"] = hashlib.sha256((fake / "LAWS.npz").read_bytes()).hexdigest()
                (fake / "PLAN.json").write_text(json.dumps(plan))
                complete["plan_sha256"] = hashlib.sha256((fake / "PLAN.json").read_bytes()).hexdigest()
            elif kind == "metric":
                report["costs"]["cc17"] += 0.1
            if kind in ("terminal", "stage", "monitor", "metric"):
                report_path.write_text(json.dumps(report))
                complete["census"][0]["report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
            (fake / "COMPLETE.json").write_text(json.dumps(complete))
            command = [
                sys.executable,
                "-O",
                str(Path(__file__).with_name("verify.py")),
                "--source", str(source),
                "--runs", str(fake),
                "--out", str(root / "audit"),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stderr)
            self.assertFalse((root / "audit" / "AUDIT.json").exists())

    def test_missing_case(self): self.attempt("census", "incomplete census")
    def test_changed_tensor(self): self.attempt("tensor", "weight hash mismatch")
    def test_rehashed_terminal_gate(self): self.attempt("terminal", "terminal CC5 mismatch")
    def test_rehashed_stage(self): self.attempt("stage", "stage identity mismatch")
    def test_rehashed_monitor_time(self): self.attempt("monitor", "monitor wall mismatch")
    def test_rehashed_metric(self): self.attempt("metric", "cost mismatch")
    def test_rehashed_law(self): self.attempt("law", "Arrays are not equal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
