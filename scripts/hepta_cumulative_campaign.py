#!/usr/bin/env python3
"""Add two cumulative control lineages to an immutable completed six-arm run."""

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_cumulative_controls as controls
import hepta_cumulative_source as source


def scores(predictions, plan):
    result = {}
    for partition in ("calibration", "evaluation"):
        groups = {}
        for row in plan["tasks"]:
            if row["partition"] == partition:
                groups.setdefault(row["source_group"], []).append(
                    int(predictions[row["id"]] == row["target_output_sha256"])
                )
        value = sum(
            (Fraction(sum(values), len(values)) for values in groups.values()),
            Fraction(),
        ) / len(groups)
        result[partition] = [value.numerator, value.denominator]
    return result


def run(args):
    runtime, plan = controls.checked_runtime(args.chain)
    controls.verify_runtime_snapshot()
    pin_raw = args.source_pin.read_bytes()
    pin = json.loads(pin_raw)
    retained = json.loads((args.source / "source-retention.json").read_bytes())
    controls.require(
        retained["source_pin_sha256"] == hashlib.sha256(pin_raw).hexdigest()
        and retained["all_extracted_members_match_original_index"] is True
        and retained["source_sha"] == pin["source_sha"]
        and retained["run_id"] == pin["run_id"],
        "original retained source",
    )
    original = args.source / "original"
    controls.require(
        source.digest(original / "evidence-index.json") == pin["evidence_index_sha256"],
        "original evidence index pin",
    )
    index = json.loads((original / "evidence-index.json").read_bytes())
    controls.require(
        index["source"] == pin["source_sha"] and index["chain"] == controls.CHAIN_SHA,
        "actual original source identity",
    )

    def file(name):
        return source.pinned_member(original, index, name)

    def read(name):
        return runtime.read_json(file(name))

    original_campaign = read("descendant-diagnostics/campaign.json")
    controls.require(
        original_campaign["completed_rounds"] == 3
        and original_campaign["status"] == "diagnostic-completed-installation-blocked"
        and original_campaign["installed_children"] == 0,
        "three actual source candidate descendants are required",
    )
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    plan_path = args.output / "experiment-plan.json"
    original_plan = file("genesis/experiment-plan.json")
    controls.require(
        source.digest(original_plan) == controls.PLAN_SHA, "same original plan bytes"
    )
    plan_path.write_bytes(original_plan.read_bytes())
    contract_path = file("genesis/target-contract.json")
    initial_parent = read("genesis/parent-material.json")
    previous_candidate, candidate_total = (
        initial_parent["adapter"],
        dict.fromkeys(controls.COUNT_FIELDS, 0),
    )
    parents, rounds = {}, []
    result = dict(
        schema="hepta-cumulative-control-campaign-v1",
        status="running",
        source_pin_sha256=hashlib.sha256(pin_raw).hexdigest(),
        source_run_id=pin["run_id"],
        source_sha=pin["source_sha"],
        chain_sha=controls.CHAIN_SHA,
        runner_sha256=runtime.file_sha(__file__),
        helper_sha256=runtime.file_sha(controls.__file__),
        original_six_arms_preserved=True,
        source_candidate_training_reexecuted=False,
        comparison_scope="public repeated tasks; independent runs with exact frozen runtime/data recipe",
        original_plan_unchanged=True,
        rounds=rounds,
        installed_children=0,
        authority=controls.NO_AUTHORITY,
        total_resource_cost_matched=False,
        independent_future_quality=False,
        budget_matched_gain_proven=False,
    )
    runtime.save(args.output / "campaign.json", result)
    try:
        for number in (1, 2, 3):
            prefix = f"descendant-diagnostics/round-{number}/"
            assessment = read(prefix + "assessment.json")
            candidate = read(prefix + "candidate-parent-material.json")
            trained = read(prefix + "train-candidate/execution/actual-receipt.json")
            controls.require(
                assessment["schema"]
                == "hepta-controlled-six-arm-descendant-assessment-v2"
                and assessment["round"] == number
                and assessment["experiment"] == runtime.identity(plan)
                and trained["outcome"] == "success"
                and trained["parent_readback"] == previous_candidate
                and trained["candidate"]
                == {name: candidate[name] for name in ("adapter", "file_sha256")},
                "actual original candidate lineage",
            )
            candidate_directory = original / (prefix + "candidate-evaluation-input")
            import llm_parent_material as parent_material

            for name in (
                "target-contract.json",
                "wrapped-adapter.json",
                "artifact.safetensors",
            ):
                file(prefix + "candidate-evaluation-input/" + name)
            parent_material.verify_parent(
                candidate_directory / "target-contract.json",
                candidate_directory / "wrapped-adapter.json",
                candidate_directory / "artifact.safetensors",
                expected_contract=controls.CONTRACT,
                expected_adapter=candidate["adapter"],
                expected_file_sha256=candidate["file_sha256"],
            )
            for name in controls.COUNT_FIELDS:
                count = trained["training"][name]
                controls.require(
                    type(count) is int and count > 0, "actual candidate training count"
                )
                candidate_total[name] += count
            controls.require(
                trained["training"]["steps"] == plan["training_steps"],
                "original candidate steps",
            )
            previous_candidate = candidate["adapter"]
            candidate_predictions = runtime.verify_predictions(
                read(prefix + "evaluate-candidate/predictions.json"),
                plan,
                "candidate",
                candidate["adapter"],
                controls.CONTRACT,
            )
            candidate_scores = scores(candidate_predictions, plan)
            controls.require(
                candidate_scores == assessment["scores"]["candidate"],
                "original score recomputation",
            )
            row = dict(
                round=number,
                source_assessment_sha256=source.digest(
                    file(prefix + "assessment.json")
                ),
                candidate=dict(
                    artifact=candidate["adapter"],
                    file_sha256=candidate["file_sha256"],
                    actual_parent_readback=trained["parent_readback"],
                    per_round=trained["training"],
                    cumulative_campaign=dict(candidate_total),
                    scores=candidate_scores,
                    receipt_sha256=source.digest(
                        file(prefix + "train-candidate/execution/actual-receipt.json")
                    ),
                ),
                original_six_arm_scores=assessment["scores"],
                cumulative_controls={},
            )
            for role, label in controls.ROLES.items():
                if number == 1:
                    directory = original / (prefix + "train-" + role)
                    for name in (
                        "artifact.json",
                        "actual-receipt.json",
                        "artifact.safetensors",
                    ):
                        file(prefix + "train-" + role + "/" + name)
                    if role == "fresh-budget-matched-lora":
                        file(prefix + "train-" + role + "/wrapped-adapter.json")
                    parent = controls.parent_descriptor(
                        directory, contract_path, role, 1, [], runtime
                    )
                    controls.check_parent(parent, role, 1, runtime, plan)
                    predictions = runtime.verify_predictions(
                        read(prefix + "evaluate-" + role + "/predictions.json"),
                        plan,
                        role,
                        parent["artifact"],
                        controls.CONTRACT,
                    )
                    controls.require(
                        scores(predictions, plan) == assessment["scores"][role],
                        "original control score recomputation",
                    )
                    row["cumulative_controls"][label] = dict(
                        origin="original-actual-round-one-control",
                        parent=parent,
                        scores=scores(predictions, plan),
                        reexecuted=False,
                    )
                else:
                    parent = parents[role]
                    controls.check_parent(parent, role, number - 1, runtime, plan)
                    directory = args.output / f"round-{number}-train-{label}"
                    request_path = args.output / f"round-{number}-{label}-input.json"
                    child_path = Path(__file__).with_name(
                        "hepta_cumulative_control_child.py"
                    )
                    request = dict(
                        schema="hepta-cumulative-control-input-v1",
                        chain=str(args.chain),
                        materials=str(args.materials),
                        plan=plan,
                        role=role,
                        round=number,
                        parent=parent,
                        output=str(directory),
                        authority=controls.NO_AUTHORITY,
                        child_source_sha256=runtime.file_sha(child_path),
                        helper_source_sha256=runtime.file_sha(controls.__file__),
                    )
                    runtime.save(request_path, request)
                    controls.verify_runtime_snapshot()
                    supervised = runtime.supervise(
                        [
                            sys.executable,
                            "-I",
                            "-B",
                            str(child_path),
                            "--input",
                            str(request_path),
                            "--input-sha256",
                            runtime.file_sha(request_path),
                        ],
                        directory,
                        plan["training_budget"],
                        exit_observation=plan.get("exit_observation"),
                    )
                    controls.require(
                        supervised["outcome"] == "success",
                        "cumulative training supervisor",
                    )
                    receipt = runtime.read_json(directory / "actual-receipt.json")
                    controls.require(
                        receipt["outcome"] == "success"
                        and receipt["actual_parent_readback"] == parent["artifact"],
                        "actual control parent",
                    )
                    parent = controls.parent_descriptor(
                        directory,
                        directory / "target-contract.json",
                        role,
                        number,
                        parent["history"],
                        runtime,
                    )
                    controls.check_parent(parent, role, number, runtime, plan)
                    evaluation = args.output / f"round-{number}-evaluate-{label}"
                    controls.verify_runtime_snapshot()
                    evaluated = runtime.supervise(
                        [
                            sys.executable,
                            "-I",
                            "-B",
                            str(args.chain / "scripts/llm_runtime_pilot.py"),
                            "_child",
                            "--materials",
                            str(args.materials),
                            "--plan",
                            str(plan_path),
                            "--output",
                            str(evaluation),
                            "--phase",
                            "evaluate",
                            "--role",
                            role,
                            "--artifact",
                            str(directory),
                        ],
                        evaluation,
                        plan["inference_budget"],
                        exit_observation=plan.get("exit_observation"),
                    )
                    controls.require(
                        evaluated["outcome"] == "success",
                        "cumulative evaluation supervisor",
                    )
                    evaluated_receipt = runtime.read_json(
                        evaluation / "actual-receipt.json"
                    )
                    controls.require(
                        evaluated_receipt["outcome"] == "success"
                        and evaluated_receipt["forward_executed"] is True
                        and evaluated_receipt["artifact"] == parent["artifact"],
                        "real control reload and forwards",
                    )
                    predictions = runtime.verify_predictions(
                        runtime.read_json(evaluation / "predictions.json"),
                        plan,
                        role,
                        parent["artifact"],
                        controls.CONTRACT,
                    )
                    row["cumulative_controls"][label] = dict(
                        origin="actual-cumulative-continuation",
                        parent=parent,
                        scores=scores(predictions, plan),
                        training_supervisor=supervised,
                        evaluation_supervisor=evaluated,
                        receipt_sha256=runtime.file_sha(
                            directory / "actual-receipt.json"
                        ),
                        token_schedule_sha256=runtime.file_sha(
                            directory / "token-schedule.json"
                        ),
                        evaluation_receipt_sha256=runtime.file_sha(
                            evaluation / "actual-receipt.json"
                        ),
                    )
                    controls.verify_runtime_snapshot()
                    controls.check_parent(parent, role, number, runtime, plan)
                parents[role] = parent
                controls.require(
                    parent["cumulative_campaign"] == candidate_total,
                    "candidate and cumulative control measured step/token schedules differ",
                )
            if number > 1:
                controls.require(
                    len(
                        {
                            entry["token_schedule_sha256"]
                            for entry in row["cumulative_controls"].values()
                        }
                    )
                    == 1,
                    "cumulative controls use different actual token schedules",
                )
            strongest = max(
                Fraction(*entry["scores"]["evaluation"])
                for entry in row["cumulative_controls"].values()
            )
            gain = Fraction(*candidate_scores["evaluation"]) - strongest
            row.update(
                cumulative_post_genesis_step_token_schedule_matched=True,
                gain_vs_cumulative_controls=[gain.numerator, gain.denominator],
                gain_scope="descriptive public-task scores; not equal-time/FLOPs or product quality",
                total_resource_cost_matched=False,
                blockers=[
                    "MissingSystemLongitudinalEvidence",
                    "TotalResourceCostUnmatched",
                ],
            )
            rounds.append(row)
            runtime.save(args.output / "campaign.json", result)
        result.update(status="completed-diagnostic-no-installation", completed_rounds=3)
        runtime.save(args.output / "campaign.json", result)
    except BaseException as error:
        result.update(
            status="execution-failed",
            error_type=type(error).__name__,
            reason=str(error)[:512],
        )
        runtime.save(args.output / "campaign.json", result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("chain", "materials", "source", "source-pin", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    controls.require(
        all(path.is_absolute() for path in vars(args).values()),
        "absolute campaign paths",
    )
    run(args)


if __name__ == "__main__":
    main()
