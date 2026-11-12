#!/usr/bin/env python3
"""Fresh CTRL research stages; existing actor outputs are never replayed.

INPUT_PREPARED.json supplies collection_plan and development evaluation_cases.
freeze writes a new immutable input, source inventory and six-policy protocol;
later stages require its independently retained raw SHA256. No fixture option,
sealed-role release, measured failure imputation or physical full-cost claim.
"""

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return sha(raw)


def modules(repository):
    sys.path[:0] = [
        str(Path(repository).resolve() / "scripts"),
        str(Path(repository).resolve()),
    ]
    from ndu_real_runtime import macro_actor, macro_execution
    from ndu_real_runtime import macro_execution_plan, macro_policy, macro_realization
    from ndu_real_runtime import macro_training_pairs, metacontrol_native_pairs
    from ndu_real_runtime.controllers import ControlPlan
    from ndu_real_runtime.critic_context import CriticContext, context_digest
    from ndu_real_runtime.metacontrol_macro_contract import digest, validate_plan
    from ndu_real_runtime.objective import utility_profile

    return {
        "macro_actor": macro_actor,
        "macro_execution": macro_execution,
        "macro_execution_plan": macro_execution_plan,
        "macro_policy": macro_policy,
        "macro_realization": macro_realization,
        "macro_training_pairs": macro_training_pairs,
        "metacontrol_native_pairs": metacontrol_native_pairs,
        "ControlPlan": ControlPlan,
        "CriticContext": CriticContext,
        "context_digest": context_digest,
        "digest": digest,
        "validate_plan": validate_plan,
        "utility_profile": utility_profile,
    }


def context_for(plan, m):
    profile, config = plan["profile"], plan["config"]
    control = m["ControlPlan"](**read(profile["control_plan"])["control"])
    runtime = Path(config["scripts_root"]) / "ndu_real_runtime"
    return m["CriticContext"](
        encoder_sha256=profile["model_sha256"],
        answer_sha256=profile["model_sha256"],
        generator_sha256=sha((runtime / "ocr.py").read_bytes()),
        public_state_sha256=m["macro_actor"].codec_sha256(),
        action_sha256=m["macro_policy"].ACTION_SHA256,
        **m["macro_actor"].host_context(
            config, m["digest"](m["utility_profile"](control))
        ),
    )


def freeze(args, m):
    raw = Path(args.prepared_plan).read_bytes()
    if sha(raw) != args.expected_input_sha256:
        raise ValueError("Prepared input differs from the external raw-byte pin")
    prepared = json.loads(raw)
    allowed = {
        "schema",
        "collection_plan",
        "evaluation_cases",
        "read_seconds_bound",
        "finalizer_seconds_reserve",
        "alpha",
        "ridge",
    }
    if (
        set(prepared) - allowed
        or prepared.get("schema") != "ctrl.fresh-experiment-input.v1"
    ):
        raise ValueError("Unexpected prepared-input schema")
    plan, evaluation = (
        deepcopy(prepared["collection_plan"]),
        prepared["evaluation_cases"],
    )
    repository = str(Path(args.repository).resolve())
    config = plan["config"]
    if config["repository_root"] != repository or config["scripts_root"] != str(
        Path(repository) / "scripts"
    ):
        raise ValueError("Prepared actor roots must select this exact checkout")
    root = Path(args.run_dir).resolve()
    read_roots = [Path(p).resolve() for p in config["runtime_roots"]]
    if any(root == p or p in root.parents or root in p.parents for p in read_roots):
        raise ValueError("Research output must be outside every actor runtime root")
    material_source = Path(config["scripts_root"]) / "ndu_real_materials"
    adaptations = {}
    for key, path in (
        ("evaluator_sha256", material_source / "evaluator.py"),
        ("isolator_sha256", material_source / "isolate.py"),
    ):
        actual = sha(path.read_bytes())
        adaptations[key] = {"prepared": config.get(key), "frozen": actual}
        config[key] = actual
    plan["source_pins"] = m["macro_execution_plan"].source_inventory(config)
    for name in ("deployment-profile.json", "receipt.json"):
        path = Path(plan["profile"]["weights"]).resolve().with_name(name)
        if path.exists():
            plan["source_pins"].append(
                {"path": str(path), "sha256": sha(path.read_bytes())}
            )
    m["validate_plan"](plan)
    from ndu_real_runtime.metacontrol_macro_contract import read_pin

    for path_key, pin_key in (
        ("weights", "model_sha256"),
        ("control_plan", "control_plan_sha256"),
    ):
        read_pin(
            {"path": plan["profile"][path_key], "sha256": plan["profile"][pin_key]}
        )
    if any(p["read_condition"] != "original" for p in plan["pairs"]):
        raise ValueError("Only original READ is fitted in this prospective protocol")
    train = set(plan["source_splits"]["train"])
    cal = set(plan["source_splits"]["calibration"])
    if plan["source_splits"]["future"]:
        raise ValueError("No sealed/future source release is provided")
    seen, physical = {}, {}
    for item in [*plan["pairs"], *evaluation]:
        case = item["case"]
        if case["role"] not in {"train", "development", "retention_validation"}:
            raise PermissionError("Sealed case is forbidden")
        source, pin = case["source_id"], case["source_sha256"]
        if seen.get(source, pin) != pin or physical.get(pin, source) != source:
            raise ValueError("Physical source aliases or mixed images in one source")
        seen[source], physical[pin] = pin, source
    eval_ids = {r["source_id"] for r in evaluation}
    if not evaluation or eval_ids & (train | cal):
        raise ValueError("Independent, nonempty evaluation sources required")
    if any(r["case"]["role"] != "development" for r in evaluation):
        raise PermissionError("This driver preregisters unsealed development only")
    context = context_for(plan, m)
    frozen = {
        "schema": "ctrl.fresh-experiment-freeze.v1",
        "prepared_input_sha256": sha(raw),
        "driver_sha256": sha(Path(__file__).read_bytes()),
        "repository": repository,
        "collection_plan": plan,
        "collection_plan_bytes_sha256": sha(
            (
                json.dumps(plan, sort_keys=True, indent=2, allow_nan=False) + "\n"
            ).encode()
        ),
        "evaluation_cases": evaluation,
        "context": context.to_wire(),
        "converter_sha256": m["macro_training_pairs"].source_sha256(),
        "fitter_sha256": m["macro_policy"].source_sha256(),
        "observer_sha256": m["digest"](m["macro_realization"].source_manifest()),
        "methods": list(m["macro_policy"].METHODS),
        "alpha": prepared.get("alpha", 0.1),
        "ridge": prepared.get("ridge", 0.001),
        "read_seconds_bound": prepared["read_seconds_bound"],
        "finalizer_seconds_reserve": prepared["finalizer_seconds_reserve"],
        "source_adaptations": adaptations,
        "full_cost_observed": False,
        "factorial_status": "NOT_REGISTERED_REQUIRES_SEPARATE_LEARNED_CONTENT_AND_CRITICS",
    }
    for field in ("read_seconds_bound", "finalizer_seconds_reserve"):
        if (
            type(frozen[field]) not in (int, float)
            or not 0 < frozen[field] < plan["action_budget_seconds"]
        ):
            raise ValueError(
                "Positive completion bounds within registered budget required"
            )
    root.mkdir(parents=True, exist_ok=False)
    with (root / "PREPARED_INPUT.json").open("xb") as stream:
        stream.write(raw)
    write(root / "COLLECTION_PLAN.json", plan)
    pin = write(root / "FROZEN.json", frozen)
    print(
        json.dumps(
            {
                "freeze_sha256": pin,
                "planned_pairs": len(plan["pairs"]),
                "planned_evaluation_actors": len(evaluation) * 6,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def thaw(args, m):
    root = Path(args.run_dir).resolve()
    raw = (root / "FROZEN.json").read_bytes()
    if sha(raw) != args.freeze_sha256:
        raise ValueError("Frozen protocol differs from the external raw-byte pin")
    frozen = json.loads(raw)
    if frozen["driver_sha256"] != sha(Path(__file__).read_bytes()) or frozen[
        "repository"
    ] != str(Path(args.repository).resolve()):
        raise ValueError("Executing driver or repository differs from freeze")
    if (
        frozen["converter_sha256"] != m["macro_training_pairs"].source_sha256()
        or frozen["fitter_sha256"] != m["macro_policy"].source_sha256()
        or frozen["observer_sha256"]
        != m["digest"](m["macro_realization"].source_manifest())
    ):
        raise ValueError("Codec, converter, fitter or observer source changed")
    from ndu_real_runtime.metacontrol_macro_contract import read_pin

    for pin in frozen["collection_plan"]["source_pins"]:
        read_pin(pin)
    if (
        sha((root / "COLLECTION_PLAN.json").read_bytes())
        != frozen["collection_plan_bytes_sha256"]
        or read(root / "COLLECTION_PLAN.json") != frozen["collection_plan"]
    ):
        raise ValueError("Retained collection plan changed")
    return root, frozen, m["CriticContext"].from_wire(frozen["context"])


def run_stage(args, m):
    root, frozen, context = thaw(args, m)
    plan = frozen["collection_plan"]
    if args.stage == "collect":
        summary = m["metacontrol_native_pairs"].collect(plan, root / "collection")
        write(root / "COLLECT_STAGE.json", summary)
    elif args.stage == "export":
        report = m["macro_training_pairs"].export(
            root / "collection",
            expected_plan_sha256=frozen["collection_plan_bytes_sha256"],
            context=context,
            expected_source_sha256=frozen["converter_sha256"],
        )
        write(root / "EXPORT.json", report)
        write(root / "EXPORT_PIN.json", {"canonical_sha256": m["digest"](report)})
        print(
            json.dumps(
                {
                    "planned_pairs": report["planned_pairs"],
                    "exported_pairs": report["exported_pairs"],
                    "unknown_pairs": report["unknown_pairs"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    elif args.stage == "fit":
        report = read(root / "EXPORT.json")
        pin = read(root / "EXPORT_PIN.json")["canonical_sha256"]
        rows = [
            m["macro_training_pairs"].fit_rows(
                report, split, expected_export_sha256=pin, context=context
            )
            for split in ("train", "calibration")
        ]
        began = time.perf_counter()
        model = m["macro_policy"].fit(
            *rows,
            context=context,
            expected_source_sha256=frozen["fitter_sha256"],
            alpha=frozen["alpha"],
            ridge=frozen["ridge"],
        )
        with (root / "CHECKPOINT.json").open("xb") as stream:
            stream.write(model.to_bytes())
        write(root / "CHECKPOINT_PIN.json", {"sha256": model.sha256})
        write(
            root / "FIT_STAGE.json",
            {
                "elapsed_seconds": time.perf_counter() - began,
                "fit_rows": len(rows[0]),
                "calibration_rows": len(rows[1]),
                "calibration": model.data["calibration"],
                "full_cost_observed": False,
            },
        )
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "cold-load",
                "--repository",
                args.repository,
                "--run-dir",
                args.run_dir,
                "--freeze-sha256",
                args.freeze_sha256,
            ],
            check=True,
        )
    elif args.stage == "cold-load":
        raw = (root / "CHECKPOINT.json").read_bytes()
        pin = read(root / "CHECKPOINT_PIN.json")["sha256"]
        model = m["macro_policy"].load(raw, pin, context=context)
        write(
            root / "COLD_LOAD.json",
            {
                "checkpoint_sha256": model.sha256,
                "context_sha256": m["context_digest"](context),
                "python": sys.executable,
                "fresh_process": True,
            },
        )
    elif args.stage == "evaluate":
        checkpoint = (root / "CHECKPOINT.json").read_bytes()
        pin = read(root / "CHECKPOINT_PIN.json")["sha256"]
        if read(root / "COLD_LOAD.json")["checkpoint_sha256"] != pin:
            raise ValueError("Fresh-process checkpoint admission is missing")
        model = m["macro_policy"].load(checkpoint, pin, context=context)
        directory = root / "deployments"
        directory.mkdir(exist_ok=False)
        control = m["ControlPlan"](**read(plan["profile"]["control_plan"])["control"])
        profiles, arms = {}, []
        for policy in frozen["methods"]:
            deployment = {
                "schema": "ndu.real.macro-deployment.v1",
                "policy": policy,
                "context": context.to_wire(),
                "weights_sha256": plan["profile"]["model_sha256"],
                "control_sha256": m["digest"](asdict(control)),
                "checkpoint_utf8": checkpoint.decode(),
                "checkpoint_sha256": pin,
                "read_seconds_bound": frozen["read_seconds_bound"],
                "finalizer_seconds_reserve": frozen["finalizer_seconds_reserve"],
            }
            path = directory / (policy + ".json")
            deployment_pin = write(path, deployment)
            profiles[policy] = {
                **plan["profile"],
                "macro_policy": {"path": str(path), "sha256": deployment_pin},
            }
            arms.append(
                {
                    "arm_id": policy,
                    "content_mode": "off",
                    "control_mode": "on"
                    if policy in {"point", "unconditional", "conditional"}
                    else "off",
                    "policy": policy,
                    "content_sha256": plan["profile"]["model_sha256"],
                    "critic_context_sha256": m["context_digest"](context),
                }
            )
        cases = frozen["evaluation_cases"]
        cohort = {
            "schema": "ndu.real.macro-cohort.v1",
            "contexts": [
                {k: r[k] for k in ("source_id", "case_id", "seed")} for r in cases
            ],
            "arms": arms,
            "partitions": {
                "fit": model.data["fit_sources"],
                "calibration": model.data["calibration_sources"],
                "evaluation": sorted({r["source_id"] for r in cases}),
            },
            "shared": m["macro_execution_plan"].shared_context(plan["config"], control),
            "one_off_costs": {
                name: {k: None for k in ("fit", "calibration", "tuning")}
                for name in profiles
            },
            "factorial": None,
        }
        execution = {
            "schema": "ndu.real.macro-execution-plan.v1",
            "cohort": cohort,
            "cohort_sha256": m["digest"](cohort),
            "config": plan["config"],
            "registered_cases": cases,
            "profiles": profiles,
            "action_budget_seconds": plan["action_budget_seconds"],
            "source_pins": plan["source_pins"],
            "observer_sha256": frozen["observer_sha256"],
        }
        execution_pin = m["digest"](execution)
        m["macro_execution_plan"].validate_plan(execution, execution_pin)
        m["macro_execution_plan"].check_inputs(execution, root / "evaluation")
        write(root / "EXECUTION_PLAN.json", execution)
        write(root / "EXECUTION_PIN.json", {"canonical_sha256": execution_pin})
        report = m["macro_execution"].execute(
            execution, root / "evaluation", expected_plan_sha256=execution_pin
        )
        write(root / "EVALUATION_REPORT.json", report)
    elif args.stage == "reconcile":
        pin = read(root / "EXECUTION_PIN.json")["canonical_sha256"]
        print(
            json.dumps(
                m["macro_execution"].reconcile(
                    root / "evaluation", expected_plan_sha256=pin
                ),
                sort_keys=True,
                allow_nan=False,
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "freeze",
            "collect",
            "export",
            "fit",
            "cold-load",
            "evaluate",
            "reconcile",
        ),
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--prepared-plan")
    parser.add_argument("--expected-input-sha256")
    parser.add_argument("--freeze-sha256")
    args = parser.parse_args()
    m = modules(args.repository)
    if args.stage == "freeze":
        if not args.prepared_plan or not args.expected_input_sha256:
            parser.error("freeze requires prepared-plan and its external raw SHA256")
        freeze(args, m)
    else:
        if not args.freeze_sha256:
            parser.error(
                "later stages require the independently retained freeze SHA256"
            )
        if args.stage == "reconcile":
            run_stage(args, m)
        else:
            stage_root, _, _ = thaw(args, m)
            start = {
                "stage": args.stage,
                "time_ns": time.time_ns(),
                "freeze_sha256": args.freeze_sha256,
                "argv": sys.argv,
                "driver_sha256": sha(Path(__file__).read_bytes()),
            }
            write(stage_root / (args.stage.upper() + "_START.json"), start)
            try:
                run_stage(args, m)
            except Exception as error:
                write(
                    stage_root / (args.stage.upper() + "_FAILED.json"),
                    {
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "time_ns": time.time_ns(),
                        "scope": "driver stage; original actor terminal states unchanged",
                    },
                )
                raise
            write(
                stage_root / (args.stage.upper() + "_COMPLETED.json"),
                {
                    "stage": args.stage,
                    "time_ns": time.time_ns(),
                    "freeze_sha256": args.freeze_sha256,
                },
            )


if __name__ == "__main__":
    main()
