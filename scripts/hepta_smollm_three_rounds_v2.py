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
    observed_head = subprocess.check_output(
        ["git", "-C", str(args.chain), "rev-parse", "HEAD"], text=True
    ).strip()
    require(
        observed_head == CHAIN_COMMIT,
        "training source must be the exact public V2 commit",
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
    plan_raw = (PROFILES / "smollm2-public-initial-v2.plan.json").read_bytes()
    plan = runtime.validate_plan(json.loads(plan_raw))
    manifest, _ = runtime.verify_materials(args.materials)
    require(plan == runtime.experiment_plan(manifest), "frozen same-budget public plan")
    output = args.output
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    plan_path = output / "experiment-plan.json"
    plan_path.write_bytes(plan_raw)
    freeze = dict(
        schema="hepta-controlled-real-round-freeze-v2",
        round=args.round,
        parent=parent,
        actual_current_incumbent=incumbent,
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
        result = runtime.supervise(
            command,
            path,
            plan["training_budget" if stage == "train" else "inference_budget"],
            exit_observation=plan.get("exit_observation"),
        )
        phases.append(dict(name=path.name, **result))
        runtime.save(output / "phase-outcomes.json", phases)
        require(result["outcome"] == "success", "required phase failed: " + path.name)
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
                initial_setup_profile=parent_step.PROFILE if initial_setup else None,
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
            )
        )
        completion = runtime.read_json(
            candidate_output
            / (
                "parent-step-result-v2.json"
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
        for role in runtime.CONTROLS:
            receipt = phase("train", role)
            require(
                receipt["contract"] == parent["contract"], "control target contract"
            )
            artifacts[role] = receipt["artifact"]
            training[role] = receipt["training"]
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
