"""Adapt actual frozen content on admitted train trajectories for a macro 2x2.

Every native training row is reconstructed from its retained actor observations,
registered train reference and independently bound scores before fitting. The
calibration and evaluation sources never enter this optimizer. Historical
exposure of the starting checkpoint is not erased by this new separation.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import ctrl_macro_study as study


def export_train(root, frozen, context, modules, output):
    from ndu_real_materials import common
    from ndu_real_runtime.content_identity import verify_evaluation
    from ndu_real_runtime.episode import EpisodeHost
    from ndu_real_runtime.metacontrol_macro_contract import SEQUENCES, read_pin
    from ndu_real_runtime.objective import utility_profile

    report = study.read(root / "EXPORT.json")
    regenerated = modules["macro_training_pairs"].export(
        root / "collection",
        expected_plan_sha256=frozen["collection_plan_bytes_sha256"],
        context=context,
        expected_source_sha256=frozen["converter_sha256"],
    )
    if regenerated != report:
        raise ValueError(
            "Retained training export differs from original artifact readback"
        )
    modules["macro_training_pairs"].fit_rows(
        report,
        "train",
        context=context,
        expected_export_sha256=study.read(root / "EXPORT_PIN.json")["canonical_sha256"],
    )
    plan = frozen["collection_plan"]
    if any(
        item["evidence_kind"] != "native_module_execution" for item in report["planned"]
    ):
        raise ValueError("Content adaptation requires original native collection")
    control = modules["ControlPlan"](
        **json.loads(
            read_pin(
                {
                    "path": plan["profile"]["control_plan"],
                    "sha256": plan["profile"]["control_plan_sha256"],
                }
            )
        )["control"]
    )
    config = plan["config"]
    chunks, pins, sources = [], [], set()
    for pair in plan["pairs"]:
        if pair["split"] != "train":
            continue
        case = pair["case"]
        if (
            case["role"] != "train"
            or case["source_id"] not in plan["source_splits"]["train"]
        ):
            raise ValueError("Content optimizer may use only registered fit sources")
        reference = common.strict_json(
            common.read_bound(config["material_root"], case["reference"])
        )
        packet = common.strict_json(
            common.read_bound(config["material_root"], case["packet"])
        )
        sources.add(case["source_id"])
        for macro, actions in SEQUENCES.items():
            branch = root / "collection" / (pair["pair_id"] + "-" + macro)
            native = study.read(branch / "result.json")
            steps = study.read(branch / "trajectory.json")["steps"]
            if native["terminal_status"] != "Completed" or native["actions"] != actions:
                raise ValueError("Only completed original branches supply content rows")
            scores = []
            for index in range(len(steps) + 1):
                delivery = branch / f"delivery-{index:02d}"
                score_raw = (delivery / "evaluation.json").read_bytes()
                score = common.strict_json(score_raw)
                verify_evaluation(
                    score,
                    (delivery / "delivery.json").read_bytes(),
                    case_id=case["id"],
                    evaluator_sha256=config["evaluator_sha256"],
                    rubric_sha256=config["rubric_sha256"],
                )
                if (
                    score["reference_sha256"] != case["reference"]["sha256"]
                    or score["role"] != "train"
                ):
                    raise ValueError("Original score/reference identity differs")
                scores.append(score)
                pins.append(
                    {
                        "path": str(delivery / "evaluation.json"),
                        "sha256": study.sha(score_raw),
                    }
                )
            check = output / (pair["pair_id"] + "-" + macro)
            check.mkdir()
            receiver = SimpleNamespace(
                steps=steps,
                operation_id=native["original_operation_id"],
                case=case,
                reference=reference,
                source_size=(
                    packet["source_size"]["width"],
                    packet["source_size"]["height"],
                ),
                control=control,
                utility_profile_sha256=modules["digest"](utility_profile(control)),
                control_profile_sha256=modules["digest"](asdict(control)),
                config=config,
                profile=plan["profile"],
                output=check,
            )
            EpisodeHost.training_rows(receiver, scores)
            original = common.read_relative(
                branch, "training-rows.jsonl", limit=32 * 1024 * 1024
            )
            reconstructed = (check / "training-rows.jsonl").read_bytes()
            if [common.strict_json(line) for line in original.splitlines()] != [
                common.strict_json(line) for line in reconstructed.splitlines()
            ]:
                raise ValueError(
                    "Training rows differ from reconstructed original observations"
                )
            chunks.append(original)
            pins.append(
                {
                    "path": str(branch / "training-rows.jsonl"),
                    "sha256": study.sha(original),
                }
            )
    if sources != set(plan["source_splits"]["train"]):
        raise ValueError("Incomplete content training source inventory")
    data = b"".join(chunks)
    with (output / "records.jsonl").open("xb") as stream:
        stream.write(data)
    return {
        "sha256": study.sha(data),
        "sources": sorted(sources),
        "original_pins": pins,
    }


def adapt(args):
    modules = study.modules(args.repository)
    root, frozen, context = study.thaw(args, modules)
    plan, profile = frozen["collection_plan"], frozen["collection_plan"]["profile"]
    from ndu_real_runtime.metacontrol_macro_contract import read_pin
    from ndu_real_runtime.training import FitConfig

    config = FitConfig(
        content_epochs=args.epochs,
        content_lr=args.learning_rate,
        latency_weight=plan["config"]["latency_weight"],
        max_wall_seconds=600,
    )
    output = Path(args.output).resolve()
    if any(
        output == Path(p).resolve() or Path(p).resolve() in output.parents
        for p in plan["config"]["runtime_roots"]
    ):
        raise ValueError("Training output must remain outside actor read roots")
    output.mkdir(parents=True, exist_ok=False)
    started = {
        "schema": "ctrl.content-adaptation-plan.v1",
        "freeze_sha256": args.freeze_sha256,
        "seed": args.seed,
        "config": asdict(config),
        "base_weights_sha256": profile["model_sha256"],
        "driver_sha256": study.sha(Path(__file__).read_bytes()),
        "time_ns": time.time_ns(),
    }
    study.write(output / "PLAN.json", started)
    try:
        records = export_train(root, frozen, context, modules, output)
        study.write(output / "DATASET.json", records)
        read_pin({"path": profile["weights"], "sha256": profile["model_sha256"]})
        import torch
        from ndu_real_runtime.neural import ReceiptPortfolioModel
        from ndu_real_runtime.training import load_records, parameter_sha, _save_weights
        from ndu_real_runtime.fit_loop import train_epochs
        from ndu_real_runtime.metering import Meter
        from ndu_real_runtime.objective import utility_profile

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(args.seed)
        model = ReceiptPortfolioModel("ordinary").float()
        model.load_state_dict(
            torch.load(profile["weights"], map_location="cpu", weights_only=True),
            strict=True,
        )
        before = parameter_sha(model, content_only=True)
        content_ids = {id(p) for p in model.content_parameters()}
        for parameter in model.parameters():
            parameter.requires_grad_(id(parameter) in content_ids)
        rows, dataset = load_records(output / "records.jsonl")
        if dataset["sha256"] != records["sha256"]:
            raise ValueError("Content dataset changed before fitting")
        control = modules["ControlPlan"](
            **study.read(profile["control_plan"])["control"]
        )
        meter = Meter(
            "ctrl-content-adapt", journal_path=output / "training.meter.jsonl"
        )
        began = time.perf_counter()
        audit = train_epochs(
            model,
            rows,
            config,
            phase="content",
            seed=args.seed,
            regime="joint",
            controller="tuned_fixed",
            meter=meter,
            output=output,
            deadline=began + config.max_wall_seconds,
            plan=control,
        )
        after = parameter_sha(model, content_only=True)
        if before == after or audit["optimizer_steps"] <= 0:
            raise ValueError("Content learning changed no actual parameters")
        weights = _save_weights(model, output / "weights.pt")
        parameter_pin = parameter_sha(model)
        cold = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys,torch; sys.path[:0]=[sys.argv[3]+'/scripts',sys.argv[3]]; from ndu_real_runtime.neural import ReceiptPortfolioModel; from ndu_real_runtime.training import parameter_sha; m=ReceiptPortfolioModel('ordinary').float(); m.load_state_dict(torch.load(sys.argv[1],map_location='cpu',weights_only=True),strict=True); pin=parameter_sha(m); print(pin); sys.exit(0 if pin==sys.argv[2] else 1)",
                str(output / "weights.pt"),
                parameter_pin,
                args.repository,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if cold.stdout.strip() != parameter_pin:
            raise ValueError("Fresh-process content parameter readback differs")
        deployment = {
            "schema": "ndu.real.deployment-profile.v1",
            "weights_sha256": weights,
            "core": "ordinary",
            "memory_mode": "reset",
            "utility_profile_sha256": modules["digest"](utility_profile(control)),
            "rubric_sha256": plan["config"]["rubric_sha256"],
            "recursive_policy_trained": False,
            "control_profile_sha256": modules["digest"](asdict(control)),
        }
        deployment_pin = study.write(output / "deployment-profile.json", deployment)
        for pin in records["original_pins"]:
            read_pin(pin)
        for path, pin in (
            (profile["weights"], profile["model_sha256"]),
            (profile["control_plan"], profile["control_plan_sha256"]),
            (output / "records.jsonl", records["sha256"]),
        ):
            read_pin({"path": str(path), "sha256": pin}, limit=512 * 1024 * 1024)
        study.thaw(args, modules)
        if study.sha(Path(__file__).read_bytes()) != started["driver_sha256"]:
            raise ValueError("Content adaptation source changed during fitting")
        receipt = {
            **started,
            "schema": "ctrl.content-adaptation.v1",
            "status": "COMPLETED",
            "dataset_sha256": records["sha256"],
            "fit_sources": records["sources"],
            "initial_content_sha256": before,
            "final_content_sha256": after,
            "weights_sha256": weights,
            "parameter_sha256": parameter_pin,
            "deployment_profile_sha256": deployment_pin,
            "training": audit,
            "elapsed_seconds": time.perf_counter() - began,
            "cold_load_parameter_sha256": cold.stdout.strip(),
            "meter": meter.finish(),
            "prior_checkpoint_exposure_cleared": False,
            "full_cost_observed": False,
            "production_admission": False,
        }
        study.write(output / "receipt.json", receipt)
        print(
            json.dumps(
                {
                    k: receipt[k]
                    for k in (
                        "status",
                        "weights_sha256",
                        "initial_content_sha256",
                        "final_content_sha256",
                        "elapsed_seconds",
                    )
                }
            ),
            flush=True,
        )
    except Exception as error:
        study.write(
            output / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "time_ns": time.time_ns(),
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=314159)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--learning-rate", type=float, default=0.0003)
    args = parser.parse_args()
    if not 0 <= args.seed < 2**32:
        parser.error("Training seed must be an unsigned 32-bit integer")
    adapt(args)


if __name__ == "__main__":
    main()
