"""Read saved arrays and verify frozen unit-test identity; no experiment data."""

import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / "runs/codex-cloud-ndu-training-train-d1"
PARAMETERS = ("encoder", "bias", "text", "text_bias", "image", "image_bias")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    started = time.process_time()
    result = json.loads((RUN / "result.json").read_text())
    frozen = json.loads((ROOT / "ndu_training/frozen-train-d1.json").read_text())
    for name, digest in frozen["sources"].items():
        assert sha(ROOT / name) == digest, name
    report = {
        "scope": "read-only saved-array audit and handmade unit tests; no TRAIN reconstruction, inference or fitting",
        "result_sha256": sha(RUN / "result.json"),
        "frozen_test_sha256": sha(ROOT / "ndu_training/test_estimators.py"),
        "frozen_source_files_all_match": True,
        "delta_tolerance_fixed_before_execution": {"relative": 1e-12, "absolute": 1e-12},
        "delta_method": "sqrt(math.fsum(float(end-start)**2 for every saved content scalar)); does not trust recorded delta",
        "recomputed": [],
    }
    for arm, system in result["systems"].items():
        for key, row in system["candidates"].items():
            seed = int(key.split("-")[1])
            base_path = RUN / f"base-{seed}.npz"
            final_path = RUN / f"final-{arm}-{key}.npz"
            with np.load(base_path, allow_pickle=False) as base, np.load(final_path, allow_pickle=False) as final:
                for name in PARAMETERS:
                    assert base[name].shape == final[name].shape
                    differences = (final[name] - base[name]).ravel()
                    actual = math.sqrt(math.fsum(float(value) ** 2 for value in differences))
                    recorded = row["parameter_delta_l2"][name]
                    assert actual > 0 and math.isfinite(actual)
                    assert math.isclose(actual, recorded, rel_tol=1e-12, abs_tol=1e-12)
                    report["recomputed"].append({"arm": arm, "candidate": key, "parameter": name,
                        "actual_l2": actual, "recorded_l2": recorded, "absolute_error": abs(actual-recorded),
                        "base_sha256": sha(base_path), "final_sha256": sha(final_path)})
                for name in ("decoder", "decoder_bias"):
                    np.testing.assert_array_equal(base[name], final[name])
    report["endpointwise_best_A_greedy_deltas"] = {}
    for seed in (11, 23, 47):
        n = result["systems"]["N"]["candidates"][f"stratified-{seed}"]["train"]["greedy_joint_success"]
        best_a = max(result["systems"]["A"]["candidates"][f"{kind}-{seed}"]["train"]["greedy_joint_success"]
                     for kind in ("iid", "stratified"))
        report["endpointwise_best_A_greedy_deltas"][str(seed)] = n - best_a
    argv = [sys.executable, "-W", "error", "-m", "unittest", "ndu_training.test_estimators",
            "independent.test_learning", "independent.test_accounting", "-v"]
    header = {"argv": argv, "cwd": str(ROOT), "git_head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), "freeze_source_commit": frozen["source_commit"],
        "test_sha256": report["frozen_test_sha256"], "all_frozen_sources_match": True,
        "identity_note": "new execution of exact frozen source; original precommit logs remain unchanged and are not relabelled"}
    environment = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    completed = subprocess.run(argv, cwd=ROOT, env=environment, capture_output=True, text=True)
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (HERE / "frozen-source-tests.txt").open("x") as stream:
        stream.write(json.dumps(header, indent=2) + "\n" + completed.stdout + completed.stderr)
        stream.write(f"\nexit_code={completed.returncode}\n")
    report.update(test_exit_code=completed.returncode,
        audit_parent_cpu_seconds=time.process_time()-started,
        test_child_cpu_seconds=child_after.ru_utime+child_after.ru_stime-child_before.ru_utime-child_before.ru_stime)
    assert completed.returncode == 0, completed.stderr
    for name, digest in frozen["sources"].items():
        assert sha(ROOT / name) == digest, name
    with (HERE / "saved-array-audit.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"recomputed_parameter_deltas": len(report["recomputed"]),
                      "maximum_absolute_error": max(x["absolute_error"] for x in report["recomputed"]),
                      "frozen_tests_exit": completed.returncode,
                      "greedy_vs_best_A": report["endpointwise_best_A_greedy_deltas"]}))
