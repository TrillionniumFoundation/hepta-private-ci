"""Prospective source/policy/code registration, before any new final outcomes."""

import argparse
import json
from pathlib import Path
import time

from ...abc_next.settings import MANIFEST, MANIFEST_SHA, REPO, RUNS, SEEDS, SENSOR, model_path, source_pins
from ...abc_recovery.base_recovery import file_sha, write_json
from ...v7.data import VIEWS
from ...v7.snapshot import Snapshot
from .analysis import BOOTSTRAP_SEED, PRICES
from .serial import POLICIES


def implementation_pins():
    paths = [Path(__file__).with_name(name + ".py") for name in
        ("features", "value", "allocation", "development", "serial", "analysis", "protocol", "core_tests", "identity_smoke")]
    paths += [Path(__file__).parents[1] / "process.py",
              Path(__file__).parents[2] / "abc_next/timing.py",
              Path(__file__).parents[2] / "abc_recovery/statistics.py",
              Path(__file__).parents[2] / "abc_recovery/control.py"]
    return {**source_pins(), **{str(path.relative_to(REPO)): file_sha(path) for path in paths}}


def freeze(development, output):
    data = json.loads((development / "result.json").read_text())
    if data["status"] != "completed" or [e["seed"] for e in data["controllers"]] != list(SEEDS):
        raise ValueError("The complete five-seed development census is required")
    entries = []
    for row in data["controllers"]:
        old_path = RUNS / f"controllers-001/seed-{row['seed']}/output_ndu/controller.pt"
        model_file = model_path(row["seed"], "output_ndu")
        model_file_sha = file_sha(model_file)
        snapshot = Snapshot.load(model_file, expected_file_sha256=model_file_sha)
        if snapshot.fingerprint != row["model_sha256"]:
            raise ValueError("Development snapshot semantics changed")
        entries.append({key: row[key] for key in ("seed", "compact_file", "compact_file_sha256", "old_controller_sha256")}
                       | {"model_file_sha256": model_file_sha, "model_snapshot_sha256": snapshot.fingerprint}
                       | {"old_controller_file": str(old_path)}
                       | {key: row["selection"][key] for key in ("selected_candidate", "selected_nonfeedback", "static_plan_index")})
    profile = {"source_role": "test", "pair_start": 512, "pair_count": 256, "views": list(VIEWS),
        "scenarios": 2, "training_seeds": list(SEEDS), "arm": "original_output_ndu", "policies": list(POLICIES),
        "requests": 81920, "threads": 1, "source_pairs_are_primary_resampling_unit": True,
        "within_source_replays_are_independent_n": False,
        "selected_feedback": "preselected per seed as cached or compact; references an actually executed policy row, no extra N",
        "request_endpoint": "actual selected generation, public policy, lossless NPZ, append+fsync, same-open-descriptor exact readback and hash verification",
        "request_excludes": ["resident model load", "source construction", "offline scoring", "analysis", "development training"],
        "decision_commit_scope": "Original runtime commits public action in process before future draws; this is not a crash-durable action journal",
        "excluded_costs_are_separately_recorded": True,
        "clock_scope": "shared Linux container; same-census paired cyclic policy order; no outlier removal or isolated-host claim"}
    inference = {"gamma": 2., "primary_observer": "primary", "replicates": 4000, "bootstrap_seed": BOOTSTRAP_SEED,
        "source_and_seed_crossed_bootstrap": True, "keep_all_views_and_scenarios": True,
        "primary_families": {"quality_vs_reference": "rawCE>0 AND success difference>=0, zero margin",
            "replacement_vs_old_feedback": "rawCE and success differences>=-.005 AND mean wall difference<0"},
        "primary_nominal_two_sided_confidence": .975,
        "component_intersection_rule": "Every inequality in a family must hold; family conclusions use the corresponding endpoints",
        "finite_five_seed_bootstrap_coverage_guaranteed": False,
        "actual_time_prices_utility_per_ms": list(PRICES),
        "economic_scope": "Sensitivity over predeclared prices, not calibrated user value; CE(U-lambda*measured cost), not CE(U)-lambda*mean cost",
        "price_bands": "nominal95 max-absolute-centered bootstrap over frozen finite grid; separate wall and CPU bands, no combined family claim",
        "failures": "retain attempts and costs, no dropped outliers; any unavailable quality or cache identity mismatch blocks quality inference",
        "development_amortization": "report entire new development wall/CPU separately; do not equate request-only prices to full lifetime economics"}
    write_json(output, {"schema": "hepta.abc4.control-final-protocol.v1", "frozen_unix_ns": time.time_ns(),
        "profile": profile, "inference": inference, "controllers": entries,
        "development_directory": str(development), "development_result_sha256": file_sha(development / "result.json"),
        "allocation_sha256": file_sha(Path(__file__).with_name("SOURCE_ALLOCATION.json")),
        "manifest_sha256": MANIFEST_SHA, "sensor_sha256": file_sha(SENSOR),
        "source_sha256": implementation_pins(), "new_final_outcomes_opened": False,
        "source_scope": "512 individual MNIST test images absent from earlier source roles/outcome executions; unknown writer clusters not certified",
        "model_identity_scope": "model_file_sha256 binds checkpoint bytes; model_snapshot_sha256 binds parameter plus configuration semantics; both checked independently"})
    print(json.dumps({"protocol": str(output), "sha256": file_sha(output)}))


def validate(path):
    spec = json.loads(path.read_text())
    if (spec["schema"] != "hepta.abc4.control-final-protocol.v1" or spec["source_sha256"] != implementation_pins()
            or file_sha(MANIFEST) != spec["manifest_sha256"] or file_sha(SENSOR) != spec["sensor_sha256"]
            or file_sha(Path(__file__).with_name("SOURCE_ALLOCATION.json")) != spec["allocation_sha256"]
            or file_sha(Path(spec["development_directory"]) / "result.json") != spec["development_result_sha256"]):
        raise ValueError("Frozen code, source or development result changed")
    if (spec["profile"]["pair_start"], spec["profile"]["pair_count"], spec["profile"]["scenarios"]) != (512, 256, 2):
        raise ValueError("Final source census changed")
    if (spec["profile"]["training_seeds"] != list(SEEDS) or spec["profile"]["views"] != list(VIEWS)
            or spec["profile"]["policies"] != list(POLICIES) or spec["profile"]["requests"] != 81920
            or [row["seed"] for row in spec["controllers"]] != list(SEEDS)):
        raise ValueError("Final model/view/policy census changed")
    developed = json.loads((Path(spec["development_directory"]) / "result.json").read_text())
    development_rows = {row["seed"]: row for row in developed["controllers"]}
    for row in spec["controllers"]:
        if (file_sha(Path(row["compact_file"])) != row["compact_file_sha256"]
                or file_sha(Path(row["old_controller_file"])) != row["old_controller_sha256"]):
            raise ValueError("Frozen controller changed")
        snapshot = Snapshot.load(model_path(row["seed"], "output_ndu"), expected_file_sha256=row["model_file_sha256"])
        if (snapshot.fingerprint != row["model_snapshot_sha256"]
                or snapshot.fingerprint != development_rows[row["seed"]]["model_sha256"]):
            raise ValueError("Frozen model snapshot semantics changed")
        if any(row[key] != development_rows[row["seed"]]["selection"][key]
               for key in ("selected_candidate", "selected_nonfeedback", "static_plan_index")):
            raise ValueError("Policy or reference differs from development choice")
    return spec


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); freeze(args.development, args.output)
