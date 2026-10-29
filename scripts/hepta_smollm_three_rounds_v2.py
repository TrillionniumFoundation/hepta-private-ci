#!/usr/bin/env python3
"""One real matched training round, called between original Agentd reads.

The Rust loop owns CURRENT, selection, installation and actual ordinary reads.
This runner owns no product credential. Public smoke tasks and controlled owner
keys cannot qualify useful releases, future-task gains, or public rewards.
"""

import argparse
from fractions import Fraction
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

CHAIN_COMMIT = "c96022b897c1235fdbdbfcfa32764403511c6aab"
CONTRACT = "c9b06f9a029a3257801844f89acb59b5f59f6a39087335af323f274e9152992f"
PROFILES = (
    Path(__file__).resolve().parents[1] / "codex-rs/hepta-learning-artifacts/profiles"
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def evaluation_input(runtime, source, destination, material, plan, backbone):
    """Copy verified weights for the original evaluator, without admission."""
    destination.mkdir(mode=0o700)
    for name in (
        "artifact.safetensors",
        "wrapped-adapter.json",
        "target-contract.json",
    ):
        shutil.copyfile(source / name, destination / name)
    require(
        runtime.file_sha(destination / "artifact.safetensors")
        == material["file_sha256"],
        "evaluation copy differs from verified material",
    )
    runtime.save(
        destination / "artifact.json",
        dict(
            role="candidate",
            artifact=material["adapter"],
            contract=material["contract"],
            kind="lora",
            source_model=runtime.WEIGHT_SHA,
            experiment=runtime.identity(plan),
            parent_backbone=backbone,
            resulting_backbone=backbone,
            file_sha256=material["file_sha256"],
            native_admission_accepted=False,
            scope="verified-material-for-controlled-evaluation-only",
        ),
    )


def descendant_blockers(parent, incumbent, gain, incumbent_gain):
    """Report missing admission evidence; this function grants no authority."""
    blockers = []
    if any(
        parent[key] != incumbent[key]
        for key in ("generation", "contract", "adapter", "file_sha256")
    ):
        blockers.append("ParentNotCurrent")
    if gain <= 0 or incumbent_gain <= 0:
        blockers.append("NoGain")
    blockers.append("MissingSystemLongitudinalEvidence")
    return blockers


def run(args):
    research = None
    research_context = None
    observation = None
    if getattr(args, "observation_profile", None) is not None:
        import hepta_smollm_observed_execution_v1 as observation

        observation.validate_request(args)
    if getattr(args, "research_profile", None) is not None:
        import hepta_smollm_answer_eos_research_v3 as research

        research_context = research.validate_request(args)
    observed_head = subprocess.check_output(
        ["git", "-C", str(args.chain), "rev-parse", "HEAD"], text=True
    ).strip()
    require(
        observed_head
        == (
            observation.CHAIN_COMMIT
            if observation
            else research.CHAIN_COMMIT
            if research
            else CHAIN_COMMIT
        ),
        "training source must be the exact selected execution profile commit",
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(args.chain),
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "scripts",
            "formal",
            "config",
        ],
        check=True,
    )
    snapshot = Path(os.environ["HEPTA_PUBLIC_INITIAL_RUNTIME_SNAPSHOT"])
    require(
        snapshot.is_absolute() and sys.flags.no_user_site == 1,
        "cold runtime snapshot and disabled user site required",
    )

    def verify_runtime():
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).with_name("hepta_smollm_runtime_snapshot.py")),
                "verify",
                "--snapshot",
                str(snapshot),
            ],
            check=True,
        )

    verify_runtime()
    sys.path.insert(0, str(args.chain / "scripts"))
    import llm_inherited_runtime as inherited
    import llm_runtime_parent_step as parent_step_v1
    import llm_runtime_parent_step_v2 as parent_step
    import llm_runtime_pilot as runtime

    parent_raw = args.parent.read_bytes()
    require(
        hashlib.sha256(parent_raw).hexdigest() == args.parent_sha256,
        "parent descriptor digest",
    )
    parent = inherited.validate_parent(json.loads(parent_raw))
    inherited.read_parent(parent)
    require(
        parent["generation"] == 1 and parent["contract"] == CONTRACT,
        "public V2 initial parent",
    )
    readback_raw = args.ordinary_readback.read_bytes()
    readback = json.loads(readback_raw)
    require(
        readback["schema"] == "hepta-controlled-ordinary-public-initial-session-v2"
        and readback["ordinary_context_reads"] > 0
        and readback["controlled_test_issuer"] is True
        and readback["training_rounds"] == 0
        and readback["product_qualification_issued"] is False,
        "actual ordinary readback scope",
    )
    actual_parent = readback["parent"]
    require(
        actual_parent["generation"] == parent["generation"]
        and actual_parent["parameter_sha256"] == parent["file_sha256"]
        and actual_parent["contract"] == parent["contract"]
        and actual_parent["adapter"] == parent["adapter"],
        "actual loaded parent identity",
    )
    incumbent = parent
    proposal_path = getattr(args, "proposal_parent", None)
    diagnostic = proposal_path is not None
    if diagnostic:
        require(proposal_path.is_absolute(), "absolute diagnostic parent path")
        proposal_raw = proposal_path.read_bytes()
        require(
            hashlib.sha256(proposal_raw).hexdigest() == args.proposal_parent_sha256,
            "diagnostic parent descriptor digest",
        )
        parent = inherited.validate_parent(json.loads(proposal_raw))
        inherited.read_parent(parent)
        require(
            parent["contract"] == incumbent["contract"], "same frozen target contract"
        )
    lineage = getattr(args, "proposal_training_lineage", [])
    count_fields = ("steps", "tokens", "supervised_tokens")
    inherited_counts = dict.fromkeys(count_fields, 0)
    previous = incumbent
    for entry in lineage:
        require(
            entry["parent"] == previous
            and entry["child"]["generation"] == previous["generation"] + 1,
            "training lineage skips its actual parent",
        )
        receipt_pin = entry["training_receipt"]
        require(
            runtime.file_sha(receipt_pin["path"]) == receipt_pin["sha256"],
            "ancestor training receipt changed",
        )
        ancestor = runtime.read_json(receipt_pin["path"])
        require(
            ancestor["outcome"] == "success"
            and ancestor["parent_readback"] == previous["adapter"]
            and ancestor["candidate"]
            == {key: entry["child"][key] for key in ("adapter", "file_sha256")},
            "ancestor receipt does not bind this actual candidate",
        )
        for key in count_fields:
            require(
                type(ancestor["training"][key]) is int
                and ancestor["training"][key] >= 0,
                "ancestor measured schedule",
            )
            inherited_counts[key] += ancestor["training"][key]
        previous = entry["child"]
    require(
        previous == parent and parent["generation"] == len(lineage) + 1,
        "complete measured post-genesis lineage required",
    )
    plan_raw = (PROFILES / "smollm2-public-initial-v2.plan.json").read_bytes()
    plan = runtime.validate_plan(json.loads(plan_raw))
    manifest, _ = runtime.verify_materials(args.materials)
    require(plan == runtime.experiment_plan(manifest), "frozen same-budget public plan")
    output = args.output
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    plan_path = output / "experiment-plan.json"
    plan_path.write_bytes(plan_raw)
    research_plan = None
    research_pin = None
    observation_value = None
    observation_context = None
    if observation:
        import llm_runtime_observed_execution_v1 as observer

        observation_value = observation.freeze_plan(
            args, runtime, parent_step, parent, plan_path
        )
        observation_context = observer.context(observation_value)
    if research:
        import llm_answer_eos_research_v3 as objective

        require(objective.PROFILE == research.PROFILE, "named research objective")
        research_plan = output / "research-plan-v3.json"
        runtime.save(
            research_plan,
            objective.plan_record(
                dict(
                    files=dict(plan=str(plan_path)),
                    parent={
                        key: parent[key]
                        for key in ("contract", "adapter", "file_sha256")
                    },
                    initial_setup=dict(
                        parent_material=dict(
                            path=str(args.parent), sha256=args.parent_sha256
                        )
                    ),
                )
            ),
        )
        research_pin = runtime.file_sha(research_plan)
    freeze = dict(
        schema="hepta-controlled-real-round-freeze-v2",
        round=args.round,
        parent=parent,
        actual_current_incumbent=incumbent,
        candidate_training_lineage=lineage,
        diagnostic_unadmitted_lineage=diagnostic,
        current_snapshot_only=True,
        actual_parent_readback=hashlib.sha256(readback_raw).hexdigest(),
        current=readback["current"],
        experiment=runtime.identity(plan),
        chain_commit=observed_head,
        runner_sha256=runtime.file_sha(__file__),
        runtime_snapshot_sha256=runtime.file_sha(snapshot),
        immutable_held_runtime_closure=False,
        public_tasks=True,
        independent_future_quality=False,
        environment={
            name: importlib.metadata.version(name)
            for name in (
                "torch",
                "transformers",
                "peft",
                "safetensors",
                "tokenizers",
                "numpy",
                "accelerate",
            )
        },
        python=sys.version,
        production_qualification=False,
        installation_authorized=False,
    )
    if research:
        freeze.update(
            schema="hepta-controlled-answer-eos-round-freeze-v3",
            research_context=research_context,
            research_plan_sha256=research_pin,
            candidate_recipe=objective.RECIPE,
            experiment_scope="unchanged-material-and-control-plan-not-v3-candidate-recipe",
        )
    if observation:
        freeze.update(
            schema="hepta-controlled-real-round-freeze-observed-v1",
            execution_profile=observation.PROFILE,
            observation_execution=observation_context,
            model_plan_profile="strict-v1",
            observation_scope="new-execution-policy-original-model-plan-and-target",
        )
    if observation:
        import hepta_smollm_live_control_v1 as live_control

        control_entry = live_control.manifest(args.chain, plan_path)
        control_manifest = output / "control-execution-entry-v1.json"
        live_control.save(control_manifest, control_entry)
        freeze["control_execution_entry"] = dict(
            path=str(control_manifest), sha256=runtime.file_sha(control_manifest)
        )
    runtime.save(output / "round-freeze.json", freeze)
    phases = []

    def phase(stage, role, artifact=None, label=None):
        verify_runtime()
        path = output / (stage + "-" + (label or role))
        command = [
            sys.executable,
            str(args.chain / "scripts/llm_runtime_pilot.py"),
            "_child",
            "--materials",
            str(args.materials),
            "--plan",
            str(plan_path),
            "--output",
            str(path),
            "--phase",
            stage,
            "--role",
            role,
        ]
        if artifact is not None:
            command += ["--artifact", str(artifact)]
        if observation:
            live_input = live_control.request(
                control_entry, stage, role, args.materials, path, artifact
            )
            live_path = output / (path.name + "-live-input.json")
            live_control.save(live_path, live_input)
            command = [
                sys.executable,
                "-I",
                "-B",
                str(Path(live_control.__file__).resolve()),
                "--input",
                str(live_path),
                "--input-sha256",
                runtime.file_sha(live_path),
            ]
        result = runtime.supervise(
            command,
            path,
            plan["training_budget" if stage == "train" else "inference_budget"],
            exit_observation=(
                observer.checked_plan(observation_value)["observer"]
                if observation
                else plan.get("exit_observation")
            ),
        )
        phases.append(dict(name=path.name, **result))
        runtime.save(output / "phase-outcomes.json", phases)
        require(result["outcome"] == "success", "required phase failed: " + path.name)
        if observation:
            require(
                result.get("exit_observation_profile")
                == observer.checked_plan(observation_value)["observer"]
                and result.get("terminal_reconciliation_profile")
                == "explicit-" + observer.OBSERVER
                and result["budget"]
                == plan["training_budget" if stage == "train" else "inference_budget"],
                "exact observation policy and original phase budget required",
            )
            phases[-1]["live_control_release"] = live_control.verify(live_input, result)
            runtime.save(output / "phase-outcomes.json", phases)
        verify_runtime()
        return runtime.read_json(path / "actual-receipt.json")

    try:
        directory = Path(parent["directory"])
        candidate_output = output / "train-candidate"
        initial_setup = (
            parent["generation"] == 1
            and parent["file_sha256"] == incumbent["file_sha256"]
        )
        trainer = parent_step if initial_setup else parent_step_v1
        trainer.run(
            SimpleNamespace(
                operation="train",
                initial_setup_profile=(
                    observer.PROFILE
                    if observation
                    else research.PROFILE
                    if research
                    else parent_step.PROFILE
                    if initial_setup
                    else None
                ),
                parent_material=str(args.parent) if initial_setup else None,
                parent_material_sha256=args.parent_sha256 if initial_setup else None,
                materials=str(args.materials),
                plan=str(plan_path),
                output=str(candidate_output),
                attempt_id=runtime.identity(freeze),
                expected_plan=runtime.identity(plan),
                parent_contract=str(directory / "target-contract.json"),
                parent_adapter=str(directory / "wrapped-adapter.json"),
                parent_artifact=str(directory / "artifact.safetensors"),
                expected_contract=parent["contract"],
                expected_parent_adapter=parent["adapter"],
                expected_parent_file_sha256=parent["file_sha256"],
                candidate_directory=None,
                expected_candidate_adapter=None,
                expected_candidate_file_sha256=None,
                expected_candidate_record_sha256=None,
                expected_candidate_result_sha256=None,
                research_plan=str(research_plan) if research else None,
                research_plan_sha256=research_pin,
                observation_plan=(
                    observation_value["initial_setup"]["observation_plan"]["path"]
                    if observation
                    else None
                ),
                observation_plan_sha256=(
                    observation_value["initial_setup"]["observation_plan"]["sha256"]
                    if observation
                    else None
                ),
            )
        )
        completion = runtime.read_json(
            candidate_output
            / (
                "parent-step-result-observed-v1.json"
                if observation
                else "parent-step-result-v3.json"
                if research
                else "parent-step-result-v2.json"
                if initial_setup
                else "parent-step-result.json"
            )
        )
        require(
            completion["outcome"] == "success"
            and completion["completion_verified"] is True,
            "original parent-step completion",
        )
        verify_runtime()
        phases.append(dict(name="train-candidate", **completion["supervisor"]))
        runtime.save(output / "phase-outcomes.json", phases)
        trained = runtime.read_json(candidate_output / "execution/actual-receipt.json")
        if observation:
            require(
                trained["schema"] == "llm-runtime-parent-step-actual-observed-v1"
                and trained["observation_execution"] == observation_context
                and completion["observation_execution"] == observation_context,
                "exact observed candidate namespace and execution context required",
            )
        if research:
            objective.verify_training(trained["training"])
            require(
                trained["schema"] == "llm-runtime-parent-step-actual-v3"
                and trained["research"]
                == dict(
                    plan_sha256=research_pin,
                    recipe=runtime.identity(objective.RECIPE),
                    profile=research.PROFILE,
                ),
                "source-bound V3 candidate objective and receipt required",
            )
        require(
            trained["parent_readback"] == parent["adapter"]
            and (
                trained["training_changed_from_setup"] is True
                if initial_setup
                else trained["unchanged_parent"] is False
            ),
            "actual parent consumption and training",
        )
        candidate = trained["candidate"]
        # Copy the original verifier's exact candidate into the pilot evaluator
        # without making it selected, installed, signed or product-qualified.
        evaluation_candidate = output / "candidate-evaluation-input"
        next_parent = dict(
            schema=inherited.PARENT_SCHEMA,
            generation=parent["generation"] + 1,
            operation_id=runtime.identity(freeze),
            directory=str(evaluation_candidate),
            contract=parent["contract"],
            **candidate,
        )
        evaluation_input(
            runtime,
            candidate_output / "execution",
            evaluation_candidate,
            next_parent,
            plan,
            actual_parent["backbone"],
        )
        inherited.read_parent(next_parent)
        runtime.save(output / "candidate-parent-material.json", next_parent)
        artifacts = {"candidate": candidate["adapter"]}
        training = {"candidate": trained["training"]}
        training_receipts = {
            "candidate": candidate_output / "execution/actual-receipt.json"
        }
        for role in runtime.CONTROLS:
            receipt = phase("train", role)
            require(
                receipt["contract"] == parent["contract"], "control target contract"
            )
            artifacts[role] = receipt["artifact"]
            training[role] = receipt["training"]
            training_receipts[role] = output / ("train-" + role) / "actual-receipt.json"
        trained_roles = [
            "candidate",
            "fresh-budget-matched-lora",
            "budget-matched-full-tune",
        ]
        require(len(set(artifacts.values())) == 5, "five distinct actual artifacts")
        require(
            all(training[r]["steps"] == plan["training_steps"] for r in trained_roles)
            and len(
                {
                    (training[r]["tokens"], training[r]["supervised_tokens"])
                    for r in trained_roles
                }
            )
            == 1
            and all(
                training[r]["steps"] == 0
                for r in ("current-backbone", "randomized-rank-matched-lora")
            ),
            "matched full training schedule",
        )
        if diagnostic:
            evaluation_incumbent = output / "actual-current-incumbent-input"
            evaluation_input(
                runtime,
                Path(incumbent["directory"]),
                evaluation_incumbent,
                incumbent,
                plan,
                actual_parent["backbone"],
            )
            artifacts["actual-current-incumbent"] = incumbent["adapter"]
        history = {}
        for role in artifacts:
            counts = {
                key: training[role][key] if role in training else 0
                for key in count_fields
            }
            prior = (
                inherited_counts
                if role == "candidate"
                else dict.fromkeys(count_fields, 0)
            )
            history[role] = dict(
                artifact=artifacts[role],
                per_round=counts,
                inherited_campaign=prior,
                cumulative_campaign={
                    key: prior[key] + counts[key] for key in count_fields
                },
                parameter_parent=parent
                if role == "candidate"
                else incumbent
                if role == "actual-current-incumbent"
                else dict(
                    source_weight_sha256=runtime.WEIGHT_SHA, campaign_adaptation_steps=0
                ),
                inherited_training_receipts=[
                    entry["training_receipt"] for entry in lineage
                ]
                if role == "candidate"
                else [],
            )
        cumulative_schedule_matched = (
            len(
                {
                    tuple(
                        history[role]["cumulative_campaign"][key]
                        for key in count_fields
                    )
                    for role in trained_roles
                }
            )
            == 1
        )
        training_receipts = {
            role: dict(path=str(path), sha256=runtime.file_sha(path))
            for role, path in training_receipts.items()
        }
        roster = dict(
            experiment=runtime.identity(plan),
            contract=parent["contract"],
            artifacts=artifacts,
            frozen_before_evaluation=True,
            independent_custody=False,
            evaluation_protocol_roles={"actual-current-incumbent": "candidate"}
            if diagnostic
            else {},
        )
        runtime.save(output / "evaluation-roster.json", roster)
        predictions = {}
        for role in runtime.PARTICIPANTS:
            artifact = (
                evaluation_candidate
                if role == "candidate"
                else output / ("train-" + role)
            )
            phase("evaluate", role, artifact)
            values = runtime.read_json(
                output / ("evaluate-" + role) / "predictions.json"
            )
            predictions[role] = runtime.verify_predictions(
                values, plan, role, artifacts[role], parent["contract"]
            )
        if diagnostic:
            receipt = phase(
                "evaluate",
                "candidate",
                evaluation_incumbent,
                "actual-current-incumbent",
            )
            require(
                receipt["artifact"] == incumbent["adapter"]
                and receipt["forward_executed"] is True,
                "actual incumbent reload and forwards required",
            )
            values = runtime.read_json(
                output / "evaluate-actual-current-incumbent/predictions.json"
            )
            predictions["actual-current-incumbent"] = runtime.verify_predictions(
                values, plan, "candidate", incumbent["adapter"], incumbent["contract"]
            )
        scores = {}
        for role in predictions:
            scores[role] = {}
            for partition in ("calibration", "evaluation"):
                groups = {}
                for row in plan["tasks"]:
                    if row["partition"] == partition:
                        groups.setdefault(row["source_group"], []).append(
                            int(
                                predictions[role][row["id"]]
                                == row["target_output_sha256"]
                            )
                        )
                score = sum(
                    (Fraction(sum(v), len(v)) for v in groups.values()), Fraction()
                ) / len(groups)
                scores[role][partition] = [score.numerator, score.denominator]
        strongest = max(Fraction(*scores[r]["evaluation"]) for r in runtime.CONTROLS)
        gain = Fraction(*scores["candidate"]["evaluation"]) - strongest
        selected = max(
            runtime.CONTROLS,
            key=lambda r: (
                Fraction(*scores[r]["calibration"]),
                -runtime.CONTROLS.index(r),
            ),
        )
        assessment = dict(
            schema="hepta-controlled-real-round-assessment-v2",
            round=args.round,
            parent=parent,
            candidate_parent_material=next_parent,
            current=readback["current"],
            experiment=runtime.identity(plan),
            scores=scores,
            gain_vs_strongest_evaluation_control=[gain.numerator, gain.denominator],
            calibration_selected_control=selected,
            all_required_controls_executed=True,
            training_budget_matched_by_steps_and_token_schedule=True,
            training_budget_match_horizon="per-round-only",
            cumulative_trainable_schedule_matched=cumulative_schedule_matched,
            cumulative_budget_matched=False,
            budget_matched_gain_proven=False,
            training_history=history,
            training_receipts=training_receipts,
            training_count_scope="post-genesis-campaign-gradient-steps-and-token-schedule-only",
            upstream_pretraining_cost="unknown-common-source-checkpoint",
            non_gradient_costs_excluded_from_schedule=True,
            actual_consumption_not_assumed_equal=True,
            candidate_actual_parent_readback=trained["parent_readback"],
            decision="hold-no-positive-gain"
            if gain <= 0
            else "blocked-positive-unqualified",
            installed_child=False,
            useful_release=False,
            product_qualification=False,
            independent_future_quality=False,
            public_reward_eligible=False,
            phases=phases,
        )
        if diagnostic:
            incumbent_gain = Fraction(*scores["candidate"]["evaluation"]) - Fraction(
                *scores["actual-current-incumbent"]["evaluation"]
            )
            assessment.update(
                schema="hepta-controlled-six-arm-descendant-assessment-v2",
                decision="diagnostic-completed-installation-blocked",
                blockers=descendant_blockers(parent, incumbent, gain, incumbent_gain),
                actual_current_incumbent=incumbent,
                actual_current_snapshot=readback["current"],
                gain_vs_actual_current_incumbent=[
                    incumbent_gain.numerator,
                    incumbent_gain.denominator,
                ],
                original_five_arms_preserved=True,
                incumbent_evaluation_has_gradient_steps=False,
                candidate_generation_is_registry_admitted=False,
                current_snapshot_only=True,
                control_gain_scope="descriptive-public-task-scores-not-cumulative-budget-evidence",
            )
            if not cumulative_schedule_matched:
                assessment["blockers"].append("CumulativeBudgetMismatch")
        if research:
            require(
                research.validate_request(args) == research_context,
                "original research gate/readback inputs changed during execution",
            )
            assessment.update(
                schema="hepta-controlled-answer-eos-six-arm-assessment-v3",
                research_context=research_context,
                research_plan_sha256=research_pin,
                candidate_recipe=objective.RECIPE,
                experiment_scope="unchanged-material-and-control-plan-not-v3-candidate-recipe",
            )
        if observation:
            require(
                observer.context(observation_value) == observation_context,
                "observation policy changed during execution",
            )
            assessment.update(
                schema=observation.ASSESSMENT,
                execution_profile=observation.PROFILE,
                observation_execution=observation_context,
                model_plan_profile="strict-v1",
                observation_scope="new-execution-policy-original-model-plan-and-target",
            )
        runtime.save(output / "assessment.json", assessment)
        if not diagnostic:
            require(
                gain <= 0,
                "positive experimental candidate requires original product qualification; no automatic install",
            )
        print(json.dumps(assessment, sort_keys=True), flush=True)
        return assessment
    except BaseException as error:
        runtime.save(
            output / "abort.json",
            dict(
                outcome="failed",
                type=type(error).__name__,
                reason=str(error)[:512],
                phases=phases,
                installation=False,
                reward=False,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["chain", "materials", "parent", "output", "ordinary-readback"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--parent-sha256", required=True)
    parser.add_argument("--round", type=int, choices=(1, 2, 3), required=True)
    args = parser.parse_args()
    require(
        all(
            getattr(args, n).is_absolute()
            for n in ["chain", "materials", "parent", "output", "ordinary_readback"]
        ),
        "absolute paths required",
    )
    run(args)


if __name__ == "__main__":
    main()
