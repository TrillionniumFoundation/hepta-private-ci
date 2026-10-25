"""Real historical-source identity preflight, without opening final outcomes."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import torch

from ...abc_next.sensor_run import load_sensor
from ...abc_next.settings import CACHE, MANIFEST, SENSOR, model_path
from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...v7.data import VIEWS, make_batch
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .protocol import validate
from .serial import POLICIES, request
from .value import load


def run(protocol, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    spec = validate(protocol)
    failures = []
    for field in ("model_file_sha256", "model_snapshot_sha256"):
        changed = deepcopy(spec)
        changed["controllers"][0][field] = "0" * 64
        path = output / (field + ".invalid.json")
        write_json(path, changed)
        try:
            validate(path)
        except (ValueError, RuntimeError) as error:
            failures.append({"field": field, "refused": True, "error_type": type(error).__name__})
        else:
            raise AssertionError("Altered model identity was accepted")
    corpus = load_roles(CACHE, MANIFEST, roles=("forecast_calibration",))
    batch = make_batch(corpus, "forecast_calibration", 1, 2026102519, view=VIEWS[0], offset=448)
    sensor = load_sensor(SENSOR)
    cases = []
    with (output / "historical-media.bin").open("x+b") as media:
        for entry in spec["controllers"]:
            seed = entry["seed"]
            snapshot = Snapshot.load(model_path(seed, "output_ndu"), expected_file_sha256=entry["model_file_sha256"])
            assert snapshot.fingerprint == entry["model_snapshot_sha256"]
            old, compact = load_controller(Path(entry["old_controller_file"])), load(Path(entry["compact_file"]))
            rows = {policy: request(snapshot._model, batch.observation, policy, old=old, compact=compact,
                sensor=sensor, reference=entry["selected_nonfeedback"], static_index=entry["static_plan_index"],
                seed=seed, case=448, view=VIEWS[0], scenario=0, media=media) for policy in POLICIES}
            assert all(row["status"] == "completed" for row in rows.values()), rows
            for field in ("decisions", "completed_path", "output_sha256", "runtime_ledger_sha256"):
                assert rows["old_feedback"][field] == rows["cached_feedback"][field], field
            snapshot.verify_integrity()
            cases.append({"seed": seed, "requests": len(rows), "all_completed": True,
                "exact_cache_identity": True, "model_file_sha256": entry["model_file_sha256"],
                "model_snapshot_sha256": snapshot.fingerprint})
    result = {"schema": "hepta.abc4.control-model-identity-smoke.v1", "status": "passed",
        "protocol_sha256": file_sha(protocol), "source_role": "historical_forecast_calibration",
        "pair_range": [448, 449], "independent_n_claim": False, "quality_evaluated": False,
        "new_test_loaded": False, "bad_identity_refusals": failures, "models": cases,
        "actual_requests": sum(case["requests"] for case in cases),
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "media_sha256": hashlib.sha256((output / "historical-media.bin").read_bytes()).hexdigest()}
    write_json(output / "result.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); run(args.protocol, args.output)
