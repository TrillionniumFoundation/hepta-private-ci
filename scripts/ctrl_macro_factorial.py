"""Freeze and execute real content variants with separately fitted macro critics.

The four named cells are frozen/adapted content crossed with the identical STOP
finalizer or a conditional complete-macro control. This is a finite macro study;
it is not qualification of a general recursive or slow-timescale NDU controller.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import ctrl_macro_study as study
from ndu_real_runtime.macro_cohort import _sha
from ndu_real_runtime.macro_policy import METHODS

MODES = ("frozen", "adapted")


def inputs(repository, registrations):
    modules = study.modules(repository)
    loaded = {}
    for mode in MODES:
        entry = registrations[mode]
        args = SimpleNamespace(
            repository=repository,
            run_dir=entry["directory"],
            freeze_sha256=entry["freeze_sha256"],
        )
        root, frozen, context = study.thaw(args, modules)
        checkpoint = (root / "CHECKPOINT.json").read_bytes()
        pin = study.read(root / "CHECKPOINT_PIN.json")["sha256"]
        model = modules["macro_policy"].load(checkpoint, pin, context=context)
        cold = study.read(root / "COLD_LOAD.json")
        if (
            cold.get("checkpoint_sha256") != pin
            or cold.get("context_sha256") != modules["context_digest"](context)
            or cold.get("fresh_process") is not True
        ):
            raise ValueError(
                "Both content-specific critics require fresh-process readback"
            )
        loaded[mode] = (root, frozen, model)
    return loaded, modules


def validate_pair(loaded, receipt):
    off, on = (loaded[mode][1] for mode in MODES)
    a, b = (f["collection_plan"] for f in (off, on))
    profile_variants = {
        "weights",
        "model_sha256",
        "training_receipt_sha256",
        "study_id",
        "original_operation_id",
        "fit_id",
        "fit_run_id",
        "arm",
    }
    if (
        off["evaluation_cases"] != on["evaluation_cases"]
        or off["methods"] != list(METHODS)
        or a["source_splits"] != b["source_splits"]
        or a["pairs"] != b["pairs"]
        or a["config"] != b["config"]
        or a["action_budget_seconds"] != b["action_budget_seconds"]
        or any(
            off[k] != on[k]
            for k in (
                "methods",
                "read_seconds_bound",
                "finalizer_seconds_reserve",
                "alpha",
                "ridge",
            )
        )
        or {k: v for k, v in a["profile"].items() if k not in profile_variants}
        != {k: v for k, v in b["profile"].items() if k not in profile_variants}
        or a["profile"]["core"] != "ordinary"
        or a["profile"]["memory_mode"] != "reset"
    ):
        raise ValueError(
            "Content variants changed cases, information frontier, controls, budgets or prices"
        )
    old, new = a["profile"]["model_sha256"], b["profile"]["model_sha256"]
    steps = receipt.get("training", {}).get("optimizer_steps")
    if (
        old == new
        or receipt.get("schema") != "ctrl.content-adaptation.v1"
        or receipt.get("status") != "COMPLETED"
        or receipt.get("base_weights_sha256") != old
        or receipt.get("weights_sha256") != new
        or receipt.get("initial_content_sha256") == receipt.get("final_content_sha256")
        or any(
            not _sha(receipt.get(k))
            for k in (
                "initial_content_sha256",
                "final_content_sha256",
                "parameter_sha256",
                "cold_load_parameter_sha256",
                "base_weights_sha256",
                "weights_sha256",
            )
        )
        or type(steps) is not int
        or steps <= 0
        or receipt.get("cold_load_parameter_sha256") != receipt.get("parameter_sha256")
        or receipt.get("fit_sources") != sorted(a["source_splits"]["train"])
    ):
        raise ValueError(
            "Two content labels require distinct trained parameter artifacts and train-only provenance"
        )
    train, calibration = (
        set(a["source_splits"][split]) for split in ("train", "calibration")
    )
    evaluation = {r["source_id"] for r in off["evaluation_cases"]}
    if train & calibration or (train | calibration) & evaluation:
        raise ValueError("Content, calibration and evaluation sources must be disjoint")
    for mode, (_, frozen, model) in loaded.items():
        plan = frozen["collection_plan"]
        if (
            model.data["fit_sources"] != sorted(plan["source_splits"]["train"])
            or model.data["calibration_sources"]
            != sorted(plan["source_splits"]["calibration"])
            or model.data["context"]["answer_sha256"] != plan["profile"]["model_sha256"]
            or model.data["context"]["encoder_sha256"]
            != plan["profile"]["model_sha256"]
            or any(
                item["case"]["source_sha256"] in model.data["source_bindings"].values()
                for item in frozen["evaluation_cases"]
            )
        ):
            raise ValueError(
                f"{mode} critic was not fitted for its actual content and independent partition"
            )


def freeze(args):
    registrations = {
        mode: {
            "directory": str(Path(getattr(args, mode + "_dir")).resolve()),
            "freeze_sha256": getattr(args, mode + "_freeze"),
        }
        for mode in MODES
    }
    loaded, _ = inputs(args.repository, registrations)
    receipt_path = Path(args.adaptation_receipt).resolve()
    receipt_raw = receipt_path.read_bytes()
    if study.sha(receipt_raw) != args.adaptation_sha256:
        raise ValueError("Adaptation receipt differs from external pin")
    receipt = json.loads(receipt_raw)
    validate_pair(loaded, receipt)
    if receipt["freeze_sha256"] != registrations["frozen"]["freeze_sha256"]:
        raise ValueError("Learned content did not use the registered frozen study")
    adapted_profile = loaded["adapted"][1]["collection_plan"]["profile"]
    if (
        adapted_profile.get("training_receipt_sha256") != args.adaptation_sha256
        or Path(adapted_profile["weights"]).resolve().with_name("receipt.json")
        != receipt_path
    ):
        raise ValueError(
            "Actual adapted deployment does not bind its original training receipt"
        )
    for root, _, model in loaded.values():
        if any(
            (root / n).exists()
            for n in (
                "EVALUATE_START.json",
                "EVALUATION_REPORT.json",
                "evaluation",
                "deployments",
            )
        ):
            raise ValueError("Factorial must be frozen before either evaluation begins")
    for mode, (root, _, model) in loaded.items():
        registrations[mode]["checkpoint_sha256"] = model.sha256
    protocol = {
        "schema": "ctrl.content-control-factorial.v1",
        "studies": registrations,
        "repository": str(Path(args.repository).resolve()),
        "driver_sha256": study.sha(Path(__file__).read_bytes()),
        "adaptation_receipt": {
            "path": str(receipt_path),
            "sha256": args.adaptation_sha256,
        },
        "factorial": {
            "off_off": "frozen/STOP",
            "off_on": "frozen/conditional",
            "on_off": "adapted/STOP",
            "on_on": "adapted/conditional",
        },
        "time_ns": time.time_ns(),
        "fixed_control": "identical complete WRITE_TEXT then STOP finalizer",
        "adaptive_control": "content-specific calibrated conditional complete-macro policy",
        "scope": "exposed development material; no recursive-NDU or new-source qualification",
    }
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    pin = study.write(root / "FROZEN.json", protocol)
    print(
        json.dumps(
            {
                "factorial_sha256": pin,
                "planned_executions": len(loaded["frozen"][1]["evaluation_cases"]) * 12,
            }
        ),
        flush=True,
    )


def thaw(args):
    root = Path(args.output)
    raw = (root / "FROZEN.json").read_bytes()
    if study.sha(raw) != args.factorial_sha256:
        raise ValueError("Factorial differs from its external freeze")
    frozen = json.loads(raw)
    if frozen["repository"] != str(Path(args.repository).resolve()) or frozen[
        "driver_sha256"
    ] != study.sha(Path(__file__).read_bytes()):
        raise ValueError("Factorial driver or repository changed")
    loaded, modules = inputs(args.repository, frozen["studies"])
    from ndu_real_runtime.metacontrol_macro_contract import read_pin

    receipt = json.loads(read_pin(frozen["adaptation_receipt"]))
    validate_pair(loaded, receipt)
    if any(
        model.sha256 != frozen["studies"][mode]["checkpoint_sha256"]
        for mode, (_, _, model) in loaded.items()
    ):
        raise ValueError("Critic changed after factorial freeze")
    return root, frozen, loaded, modules


def reconcile(args):
    root, frozen, loaded, modules = thaw(args)
    combined, rows, frontiers, actions = None, [], {}, {}
    for mode, (directory, registered, model) in loaded.items():
        execution = study.read(directory / "EXECUTION_PLAN.json")
        pin = study.read(directory / "EXECUTION_PIN.json")["canonical_sha256"]
        if (
            modules["digest"](execution) != pin
            or study.read(directory / "evaluation/PLAN.json") != execution
        ):
            raise ValueError("Execution plan differs from its pin or original roster")
        plan = registered["collection_plan"]
        cohort = execution["cohort"]
        if (
            execution["registered_cases"] != registered["evaluation_cases"]
            or any(
                execution[k] != plan[k]
                for k in (
                    "config",
                    "action_budget_seconds",
                    "source_pins",
                )
            )
            or execution["observer_sha256"] != registered["observer_sha256"]
            or [arm["arm_id"] for arm in cohort["arms"]] != list(METHODS)
            or set(execution["profiles"]) != set(METHODS)
        ):
            raise ValueError("Execution departed from frozen factorial cases or inputs")
        modules["macro_execution_plan"].validate_plan(execution, pin)
        modules["macro_execution_plan"].check_inputs(
            execution, directory / "evaluation"
        )
        from ndu_real_runtime.metacontrol_macro_contract import read_pin

        for arm in cohort["arms"]:
            profile = execution["profiles"][arm["arm_id"]]
            deployment = json.loads(read_pin(profile["macro_policy"]))
            if (
                {k: v for k, v in profile.items() if k != "macro_policy"}
                != plan["profile"]
                or arm["policy"] != arm["arm_id"]
                or arm["content_mode"] != "off"
                or arm["control_mode"]
                != (
                    "on"
                    if arm["policy"] in {"point", "unconditional", "conditional"}
                    else "off"
                )
                or deployment["checkpoint_sha256"] != model.sha256
                or deployment["checkpoint_utf8"] != model.to_bytes().decode()
                or deployment["read_seconds_bound"] != registered["read_seconds_bound"]
                or deployment["finalizer_seconds_reserve"]
                != registered["finalizer_seconds_reserve"]
            ):
                raise ValueError(
                    "Executed content or policy differs from factorial freeze"
                )
        report = modules["macro_execution"].reconcile(
            directory / "evaluation",
            expected_plan_sha256=pin,
        )
        if combined is None:
            combined = deepcopy(cohort)
            combined.update(arms=[], one_off_costs={}, factorial=frozen["factorial"])
        if any(combined[k] != cohort[k] for k in ("contexts", "partitions", "shared")):
            raise ValueError(
                "Executed cohorts differ from the common experimental frontier"
            )
        for arm in cohort["arms"]:
            name = mode + "/" + arm["arm_id"]
            combined["arms"].append(
                {
                    **arm,
                    "arm_id": name,
                    "content_mode": "off" if mode == "frozen" else "on",
                }
            )
            combined["one_off_costs"][name] = cohort["one_off_costs"][arm["arm_id"]]
        for row in report["rows"]:
            rows.append({**row, "arm_id": mode + "/" + row["arm_id"]})
            if row["status"] != "COMPLETED":
                continue
            branch = directory / "evaluation" / row["execution_id"]
            realization = study.read(branch / "REALIZATION.json")
            identity = realization["comparison_binding"]
            key = (row["source_id"], row["case_id"], row["seed"])
            frontier = {
                k: identity[k]
                for k in (
                    "initial_packet_sha256",
                    "source_sha256",
                    "evaluator_sha256",
                    "rubric_sha256",
                    "latency_tariff",
                )
            }
            if (
                any(v is None for v in frontier.values())
                or frontiers.get(key, frontier) != frontier
            ):
                raise ValueError(
                    "Executed arms did not observe the same initial physical frontier"
                )
            frontiers[key] = frontier
            initial = study.read(branch / "native/trajectory.json")["steps"][0]
            control = initial["controller"]
            name = mode + "/" + row["arm_id"]
            actions.setdefault(name, []).append(
                {
                    "source_id": row["source_id"],
                    "case_id": row["case_id"],
                    "macro": realization["macro"],
                    "controller": control,
                    "read_attribution": realization["read_attribution"],
                }
            )
    result = {
        "schema": "ctrl.content-control-factorial-report.v1",
        "factorial_sha256": args.factorial_sha256,
        "cohort": modules["macro_execution"].macro_cohort.evaluate(
            combined, rows, expected_plan_sha256=modules["digest"](combined)
        ),
        "plan": combined,
        "rows": rows,
        "observed_actions": actions,
        "matched_initial_physical_frontiers": len(frontiers),
        "full_cost_observed": False,
        "recursive_ndu_qualified": False,
        "new_source_confirmation": False,
        "production_admission": False,
        "decision": "NoUpdate",
    }
    study.write(root / "REPORT.json", result)
    print(
        json.dumps(
            {
                "planned_executions": result["cohort"]["planned_executions"],
                "factorial": result["cohort"]["factorial"],
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "evaluate", "reconcile"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True)
    for mode in MODES:
        parser.add_argument("--" + mode + "-dir")
        parser.add_argument("--" + mode + "-freeze")
    parser.add_argument("--adaptation-receipt")
    parser.add_argument("--adaptation-sha256")
    parser.add_argument("--factorial-sha256")
    args = parser.parse_args()
    if args.stage == "freeze":
        freeze(args)
    elif args.stage == "reconcile":
        reconcile(args)
    else:
        root, frozen, _, _ = thaw(args)
        study.write(
            root / "EVALUATE_START.json",
            {"time_ns": time.time_ns(), "factorial_sha256": args.factorial_sha256},
        )
        try:
            for mode in MODES:
                entry = frozen["studies"][mode]
                subprocess.run(
                    [
                        sys.executable,
                        str(Path(args.repository) / "scripts/ctrl_macro_study.py"),
                        "evaluate",
                        "--repository",
                        args.repository,
                        "--run-dir",
                        entry["directory"],
                        "--freeze-sha256",
                        entry["freeze_sha256"],
                    ],
                    check=True,
                )
            reconcile(args)
            study.write(root / "EVALUATE_COMPLETED.json", {"time_ns": time.time_ns()})
        except Exception as error:
            study.write(
                root / "EVALUATE_FAILED.json",
                {
                    "time_ns": time.time_ns(),
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            raise


if __name__ == "__main__":
    main()
