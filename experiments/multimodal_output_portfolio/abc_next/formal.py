"""Seal all policies and source identities before qualification and test access."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from ..abc_recovery.base_recovery import file_sha, write_json
from ..v6.neural import parameter_hash
from ..v7.data import VIEWS
from ..v7.snapshot import Snapshot
from ..v7.sources import load_roles
from .execute import POLICIES, execute_model
from .sensor_run import load_sensor
from .settings import (ARMS, CACHE, MANIFEST, OLD, REPO, RUNS, SEEDS, SENSOR, SOURCE_RANGES,
                       model_path, observers, resources, source_pins)
from .value import load_controller


def implementation_pins():
    result = source_pins()
    here = Path(__file__).parent
    paths = [here / (name + ".py") for name in ("execute", "formal", "analysis", "timing")]
    paths += [here.parent / "abc_recovery" / (name + ".py") for name in ("control", "statistics", "analysis")]
    for path in paths:
        result[str(path.relative_to(REPO))] = file_sha(path)
    return result


def controller_census(directory):
    result = json.loads((directory / "result.json").read_text())
    expected = {(seed, arm) for seed in SEEDS for arm in ARMS}
    actual = [(row["seed"], row["arm"]) for row in result["controllers"]]
    if result["status"] != "completed" or len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("All 15 frozen controllers are required before evaluation")
    for row in result["controllers"]:
        if file_sha(Path(row["controller_file"])) != row["controller_sha256"]:
            raise ValueError("A controller differs from its pre-evaluation identity")
    return result


def freeze(controllers, destination):
    from .timing import timing_registration
    fitted = controller_census(controllers)
    manifest = json.loads(MANIFEST.read_text())
    source_ids = {}
    for phase in ("qualification", "test"):
        interval = SOURCE_RANGES[phase]
        ids = manifest["roles"][interval["role"]]["source_ids"][2 * interval["start"]:2 * (interval["start"] + interval["count"])]
        if len(ids) != 2 * interval["count"] or len(set(ids)) != len(ids):
            raise ValueError("Incomplete or duplicated future source census")
        source_ids[phase] = {"count": len(ids), "sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}
    record = {"schema": "hepta.abc-next.formal-freeze.v1", "frozen_unix_ns": time.time_ns(),
        "controllers_directory": str(controllers), "controllers_result_sha256": file_sha(controllers / "result.json"),
        "resources": resources(), "source_sha256": implementation_pins(), "source_ranges": SOURCE_RANGES,
        "future_source_ids": source_ids, "seeds": SEEDS, "arms": ARMS, "policies": POLICIES,
        "architecture": fitted["architecture"], "views": VIEWS,
        "legacy_sha256": {f"{s}/{a}": file_sha(OLD / f"control-001/seed-{s}/{a}/policies/feedback.pt") for s in SEEDS for a in ARMS},
        "qualification_output": str(RUNS / "qualification-001"), "test_output": str(RUNS / "evaluation-001"),
        "primary_comparisons": ["output_ndu/fixed minus output_mean/fixed", "output_ndu/feedback minus output_ndu/development_selected_nonfeedback"],
        "primary_metric": "net_utility_joint_CE", "gamma": 2., "action_proxy_cost": .002,
        "primary_nominal_confidence": .975, "descriptive_confidence": .95,
        "bootstrap_replicates": 4000, "bootstrap_seed": 2026102507,
        "bootstrap_unit": "paired source-pair and training-seed axes; retain all within-source views/scenarios",
        "fixed_seed_source_bootstrap_also_reported": True,
        "qualification_can_select_or_refit": False, "negative_qualification_can_suppress_test": False,
        "formal_test_outcomes_opened": False, "large_raw_data_archival_required": False,
        "timing": timing_registration(controllers)}
    write_json(destination, record)
    print(json.dumps({"protocol": str(destination), "sha256": file_sha(destination),
                      "future_source_ids": source_ids, "controllers": len(fitted["controllers"])}), flush=True)


def verify(protocol):
    if protocol["schema"] != "hepta.abc-next.formal-freeze.v1":
        raise ValueError("Unknown formal registration")
    if protocol["source_ranges"] != SOURCE_RANGES or protocol["source_sha256"] != implementation_pins():
        raise ValueError("Frozen source allocations or implementation changed")
    if protocol["resources"] != resources():
        raise ValueError("Frozen generators, reader, observers or source manifest changed")
    controllers = Path(protocol["controllers_directory"])
    if file_sha(controllers / "result.json") != protocol["controllers_result_sha256"]:
        raise ValueError("Controller census or development choices changed")
    fitted = controller_census(controllers)
    for seed in SEEDS:
        for arm in ARMS:
            if file_sha(OLD / f"control-001/seed-{seed}/{arm}/policies/feedback.pt") != protocol["legacy_sha256"][f"{seed}/{arm}"]:
                raise ValueError("Historical controller changed")
    return fitted


def run(protocol_path, phase):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    protocol = json.loads(protocol_path.read_text())
    fitted = verify(protocol)
    output = Path(protocol[phase + "_output"])
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "registration.json", {"phase": phase, "unix_ns": time.time_ns(),
        "protocol_sha256": file_sha(protocol_path), "controllers_result_sha256": protocol["controllers_result_sha256"]})
    try:
        if phase == "test":
            prior = json.loads((Path(protocol["qualification_output"]) / "result.json").read_text())
            if prior["status"] != "completed" or prior["protocol_sha256"] != file_sha(protocol_path):
                raise ValueError("Once-only qualification has not completed under this same freeze")
        interval = SOURCE_RANGES[phase]
        # This is the first role materialization, after every identity check.
        corpus = load_roles(CACHE, MANIFEST, roles=(interval["role"],))
        sensor, judges = load_sensor(SENSOR), observers()
        before = {name: parameter_hash(judge) for name, judge in judges.items()}
        entries = []
        for row in fitted["controllers"]:
            seed, arm = row["seed"], row["arm"]
            snapshot = Snapshot.load(model_path(seed, arm), expected_file_sha256=protocol["resources"]["model_sha256"][f"{seed}/{arm}"])
            controller = load_controller(Path(row["controller_file"]))
            directory = output / f"seed-{seed}" / arm
            data = execute_model(snapshot, controller, sensor, corpus, judges, directory,
                **interval, training_seed=seed, arm=arm, static_index=row["selection"]["static_plan_index"], views=VIEWS)
            entries.append({"seed": seed, "arm": arm, "directory": str(directory),
                "data_sha256": file_sha(directory / "data.pt"), "summary_sha256": file_sha(directory / "summary.json")})
            print(json.dumps({"phase": phase, "seed": seed, "arm": arm,
                              "selected_policy_rows": data["paths"].numel()}), flush=True)
            del data
        if before != {name: parameter_hash(judge) for name, judge in judges.items()}:
            raise ValueError("An outcome observer changed during evaluation")
        verify(protocol)
        write_json(output / "result.json", {"schema": "hepta.abc-next.formal-execution-result.v1", "status": "completed",
            "phase": phase, "protocol_sha256": file_sha(protocol_path), "models": entries,
            "source_range": interval, "wall_ns": time.perf_counter_ns() - wall,
            "cpu_ns": time.process_time_ns() - cpu, "policies_refit_or_selected_here": False,
            "observer_parameters_unchanged": True})
    except BaseException as error:
        write_json(output / "failure.json", {"error": repr(error), "unix_ns": time.time_ns(),
            "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "qualification", "test"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--controllers", type=Path, default=RUNS / "controllers-001")
    args = parser.parse_args()
    torch.set_num_threads(2)
    freeze(args.controllers, args.protocol) if args.phase == "freeze" else run(args.protocol, args.phase)


if __name__ == "__main__":
    main()
