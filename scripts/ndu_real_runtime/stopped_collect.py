"""Collect original train-only stopped episodes through the existing isolated host.

Original v2 transitions keep their action-only durations. Deployment, evaluator
and outer-process costs remain separate. Calibration and diagnostic exports
remain separate; this collector establishes neither coverage nor net benefit.
"""

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from ndu_real_materials.common import read_bound, strict_json
from .controllers import ControlPlan
from .metering import atomic_json, canonical_sha, file_sha
from .subprocess_supervisor import run_logged, supervision_policy
from .trajectory import V2_SCHEMA
from .stopped_collect_contract import (
    SCHEMA,
    PREPARATION_FILES,
    read_original,
    verify_selection,
    verify_frozen,
    readback_attempt,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def freeze(preparation, output, expected_pins):
    preparation, output = Path(preparation).resolve(), Path(output).resolve()
    if set(expected_pins) != set(PREPARATION_FILES):
        raise ValueError("Four externally pinned preparation files are required")
    inputs, pins = {}, []
    for name in PREPARATION_FILES:
        raw, pin = read_original(preparation / name, expected_pins[name])
        inputs[name] = strict_json(raw)
        pins.append(pin)
    selection, selected = inputs[PREPARATION_FILES[0]], inputs[PREPARATION_FILES[1]]
    config, control = inputs[PREPARATION_FILES[2]], inputs[PREPARATION_FILES[3]]
    code = Path(config["repository_root"]).resolve()
    if (
        code != Path(__file__).resolve().parents[2]
        or str(code) != selection["native_source_root"]
    ):
        raise ValueError("Collector is not executing the declared new source snapshot")
    if (
        Path(config["scripts_root"]).resolve() != code / "scripts"
        or str(code) not in config["runtime_roots"]
    ):
        raise ValueError("Actor source root differs from the declared snapshot")
    control_profile = ControlPlan(**control["control"])
    if (
        control_profile.memory_mode != "reset"
        or config["episode_wall_seconds"] != 60
        or control["episode_wall_seconds"] != 60
        or selection["episode_wall_seconds"] != 60
        or control_profile.latency_weight != config["latency_weight"]
    ):
        raise ValueError("Original per-episode limit/reset objective differs")
    for path, digest in selection["original_pins"].items():
        pins.append(read_original(path, digest)[1])
    previous_paths = [
        p for p in selection["original_pins"] if Path(p).name == "selected-sources.json"
    ]
    if len(previous_paths) != 1:
        raise ValueError("Original pilot roster needs one pinned path")
    previous = strict_json(
        read_original(previous_paths[0], selection["original_pins"][previous_paths[0]])[
            0
        ]
    )
    original_train = Path(previous_paths[0]).with_name("training-content.jsonl")
    fit_raw, fit_pin = read_original(
        original_train, selection["generator_fit_records_sha256"]
    )
    pins.append(fit_pin)
    fit_records = [strict_json(line) for line in fit_raw.splitlines()]
    if any(row["split"] != "train" for row in fit_records) or {
        row["source_group"] for row in fit_records
    } != set(selection["original_fit_groups"]):
        raise ValueError(
            "Actual generator fit records differ from the excluded source set"
        )
    material = Path(config["material_root"])
    catalog_raw, pin = read_original(
        material / "pilot-catalog.json", selection["catalog_sha256"]
    )
    pins.append(pin)
    exposure_raw, pin = read_original(
        config["source_exposure_ledger_path"], selection["exposure_sha256"]
    )
    pins.append(pin)
    groups = verify_selection(
        selection,
        selected,
        strict_json(catalog_raw)["cases"],
        previous,
        strict_json(exposure_raw)["quarantined_source_groups"],
    )
    registration_path = material / "registration-final.json"
    registration = strict_json(
        read_original(
            registration_path, selection["original_pins"][str(registration_path)]
        )[0]
    )
    for key in ("reference_index_sha256", "rubric_sha256", "registry_sha256"):
        if (
            registration[key] != selection[key]
            or key in config
            and config[key] != selection[key]
        ):
            raise ValueError("Registered material/evaluator identity differs")
    pins.append(
        read_original(
            material / "private/reference-index.v2.json",
            config["reference_index_sha256"],
        )[1]
    )
    for entry in selected:
        packet = strict_json(read_bound(material, entry["case"]["packet"]))
        actions = entry["exploration"]
        if (
            packet["case_id"] != entry["case"]["id"]
            or "WRITE_TEXT" in actions
            and packet["initial_delivery"]["text"] is not None
            or "RENDER_IMAGE" in actions
            and (
                not packet["requirements"]["image"]
                or packet["initial_delivery"]["image"] is not None
            )
        ):
            raise ValueError("Public legality would silently change the frozen macro")
    source_files = [
        *[
            p
            for folder in ("ndu_real_runtime", "ndu_real_materials")
            for p in (code / "scripts" / folder).glob("*.py")
            if not p.name.startswith("test_")
        ],
        code / "scripts/ndu_real_runtime/finite_entropic_golden.json",
        code
        / "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
    ]
    source_pins = [read_original(path)[1] for path in sorted(source_files)]
    config = dict(
        config,
        evaluator_sha256=file_sha(code / "scripts/ndu_real_materials/evaluator.py"),
    )
    output.mkdir(parents=True, exist_ok=False)
    for name in ("requests", "attempts", "episodes"):
        (output / name).mkdir()
    atomic_json(output / "execution-config.json", config)
    requests = []
    for entry in selected:
        case = entry["case"]
        operation = (
            "stopped-"
            + canonical_sha([str(output), case["id"], entry["exploration"]])[:32]
        )
        profile = {
            "study_id": output.name,
            "fit_id": "frozen-original-behavior-collector",
            "training_seed": 271828,
            "fit_run_id": "common-collector-not-independent-fit",
            "regime": "frozen",
            "arm": "stopped_macro_collection",
            "core": "ordinary",
            "controller": "tuned_fixed",
            "weights": selection["weights"],
            "model_sha256": selection["weights_sha256"],
            "training_receipt_sha256": selection["training_receipt_sha256"],
            "control_plan": str(preparation / "control-plan.json"),
            "control_plan_sha256": expected_pins["control-plan.json"],
            "policy_sha256": canonical_sha(entry["exploration"]),
            "episode_seed": 0,
            "retry_of": None,
            "original_operation_id": operation,
        }
        request = {
            "config": config,
            "case": case,
            "profile": profile,
            "output": str(output / "episodes" / operation),
            "training": True,
            "exploration": entry["exploration"],
        }
        path = output / "requests" / (operation + ".json")
        requests.append(
            {
                "path": str(path),
                "sha256": atomic_json(path, request),
                "phase": entry["phase"],
                "operation": operation,
            }
        )
    requests.sort(key=lambda entry: canonical_sha([entry["phase"], entry["operation"]]))
    frozen = {
        "schema": SCHEMA,
        "frozen_at": now(),
        "groups": groups,
        "requests": requests,
        "original_pins": pins,
        "source_pins": source_pins,
        "execution_config": config,
        "execution_config_sha256": file_sha(output / "execution-config.json"),
        "evaluator_template_sha256": inputs[PREPARATION_FILES[2]]["evaluator_sha256"],
        "effective_evaluator_sha256": config["evaluator_sha256"],
        "isolator_sha256": file_sha(code / "scripts/ndu_real_materials/isolate.py"),
        "budget": {
            "collection_wall_seconds": 600,
            "attempt_wall_seconds": 90,
            "finalization_reserve_seconds": 5,
            "maximum_workers": 4,
            "maximum_episodes": 60,
        },
        "supervision": supervision_policy(),
        "confirmation_access": False,
        "request_order": "preexecution_sha256_phase_operation_interleaving",
        "original_transition_duration_scope": "action_only_unchanged",
        "full_episode_cost_scope": "deployment_meter; external_evaluation_and_outer_supervision_separate",
        "model_training_performed": False,
        "scientific_admission": "HOLD",
    }
    digest = atomic_json(output / "COLLECTION_PLAN.json", frozen)
    return {
        "plan": str(output / "COLLECTION_PLAN.json"),
        "sha256": digest,
        "planned": len(requests),
    }


def execute_request(entry, plan, root):
    request = strict_json(read_original(entry["path"], entry["sha256"])[0])
    directory = Path(root) / "attempts" / entry["operation"]
    directory.mkdir(exist_ok=False)
    if Path(request["output"]).exists():
        raise ValueError("Original episode exists; no implicit execution retry")
    config = request["config"]
    roots = [config["pillow_path"], config["scripts_root"], config["repository_root"]]
    command = [
        config["python"],
        "-c",
        "import sys;sys.path[:0]="
        + repr(roots)
        + ";from ndu_real_runtime.episode import main;raise SystemExit(main())",
        "--request",
        entry["path"],
    ]
    environment = dict(
        os.environ,
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    admission = {
        "schema": "ndu.real.stopped-attempt.v1",
        "operation": entry["operation"],
        "request_sha256": entry["sha256"],
        "started_at": now(),
        "timeout_seconds": plan["budget"]["attempt_wall_seconds"],
        "retry_of": None,
    }
    atomic_json(directory / "admission.json", admission)
    started = time.monotonic()
    with (
        (directory / "stdout.log").open("xb", buffering=0) as stdout,
        (directory / "stderr.log").open("xb", buffering=0) as stderr,
    ):
        supervision = run_logged(
            command,
            stdout=stdout,
            stderr=stderr,
            timeout=admission["timeout_seconds"],
            env=environment,
        )
    receipt = {
        **admission,
        "finished_at": now(),
        "supervision": supervision,
        "outer_wall_seconds": time.monotonic() - started,
        "stdout_sha256": file_sha(directory / "stdout.log"),
        "stderr_sha256": file_sha(directory / "stderr.log"),
        "provider_charges": None,
        "energy_joules": None,
        "native_owner_authentication": "SEPARATE_REQUIRED",
    }
    atomic_json(directory / "attempt.json", receipt)
    return receipt


def readback(root, expected_sha256, *, export=False):
    root = Path(root)
    plan = verify_frozen(root, expected_sha256)
    items, exports = [], {"calibration": [], "diagnostic": []}
    for entry in plan["requests"]:
        item, raw = readback_attempt(entry, plan, root)
        items.append(item)
        if raw:
            exports[entry["phase"]].append(raw)
    result = {
        "schema": "ndu.real.stopped-collection-result.v1",
        "plan_sha256": expected_sha256,
        "observed_at": now(),
        "planned": len(items),
        "statuses": dict(Counter(i["status"] for i in items)),
        "attempts": items,
        "training_rows": sum(i["training_rows"] for i in items),
        "raw_transition_schema": V2_SCHEMA,
        "action_only_durations_relabelled": False,
        "diagnostic_rows_must_not_fit_calibration": True,
        "confirmation_access": False,
        "native_owner_authentication": "SEPARATE_REQUIRED",
        "scientific_admission": "HOLD",
    }
    if export:
        result["exports"] = {}
        for phase, chunks in exports.items():
            path = root / (phase + "-training-rows.jsonl")
            with path.open("xb") as stream:
                for raw in chunks:
                    stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            result["exports"][phase] = read_original(path)[1]
    return result


def run(root, expected_sha256):
    root = Path(root)
    started = time.monotonic()
    plan = verify_frozen(root, expected_sha256)
    atomic_json(
        root / "execution-started.json",
        {"plan_sha256": expected_sha256, "started_at": now(), "implicit_retry": False},
    )
    budget, cursor, pending = plan["budget"], 0, {}
    blocked = False
    with (
        ThreadPoolExecutor(max_workers=budget["maximum_workers"]) as pool,
        (root / "events.jsonl").open("x", buffering=1) as ledger,
    ):
        while pending or cursor < len(plan["requests"]):
            while (
                not blocked
                and len(pending) < budget["maximum_workers"]
                and cursor < len(plan["requests"])
            ):
                remaining = budget["collection_wall_seconds"] - (
                    time.monotonic() - started
                )
                if (
                    remaining
                    < budget["attempt_wall_seconds"]
                    + budget["finalization_reserve_seconds"]
                ):
                    blocked = True
                    break
                entry = plan["requests"][cursor]
                cursor += 1
                ledger.write(
                    json.dumps(
                        {
                            "event": "admitted",
                            "operation": entry["operation"],
                            "at": now(),
                        }
                    )
                    + "\n"
                )
                ledger.flush()
                os.fsync(ledger.fileno())
                pending[pool.submit(execute_request, entry, plan, root)] = entry
            if not pending:
                break
            finished, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
            for future in finished:
                entry = pending.pop(future)
                try:
                    receipt = future.result()
                    blocked |= not receipt["supervision"]["cleanup_complete"]
                    event = {
                        "event": "attempt_returned",
                        "operation": entry["operation"],
                        "returncode": receipt["supervision"]["returncode"],
                    }
                except BaseException as error:
                    blocked = True
                    event = {
                        "event": "attempt_unresolved",
                        "operation": entry["operation"],
                        "error": str(error),
                    }
                ledger.write(json.dumps(dict(event, at=now()), allow_nan=False) + "\n")
                ledger.flush()
                os.fsync(ledger.fileno())
                print(json.dumps(event), flush=True)
    result = readback(root, expected_sha256, export=True)
    result.update(
        elapsed_wall_seconds=time.monotonic() - started,
        wall_limit_seconds=budget["collection_wall_seconds"],
        dispatched=cursor,
        wall_limit_observed=time.monotonic() - started
        <= budget["collection_wall_seconds"],
        hard_real_time_guarantee=False,
    )
    atomic_json(root / "collection-result.json", result)
    return {
        key: result[key]
        for key in (
            "planned",
            "statuses",
            "training_rows",
            "elapsed_wall_seconds",
            "wall_limit_observed",
        )
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run", "readback"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--preparation", type=Path)
    parser.add_argument("--expected-preparation-pins", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze(
            args.preparation,
            args.root,
            strict_json(args.expected_preparation_pins.read_bytes()),
        )
    else:
        if not args.expected_plan_sha256:
            parser.error("run/readback require an external plan digest")
        result = (
            run(args.root, args.expected_plan_sha256)
            if args.command == "run"
            else readback(args.root, args.expected_plan_sha256)
        )
    print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
