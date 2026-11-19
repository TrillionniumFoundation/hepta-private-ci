#!/usr/bin/env python3
"""Build a reviewable, create-only ai395 preparation bundle; submit nothing."""

import argparse
import ast
import base64
import copy
import gzip
import io
import json
from pathlib import Path
import tarfile

from evaluate_b import read, record, require, sha, unpack, verify_runtime_roots, write


def encoded(value):
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()


def evaluation_design(collector, cloud, phase_seconds):
    require(
        {k: v for k, v in collector["controller"].items() if k != "memory_mode"}
        == cloud["controller"],
        "Cloud controller does not preserve the collected control profile",
    )
    groups = {
        name: collector["source_selection"][name]
        for name in (
            "training_groups",
            "tuning_groups",
            "pilot_new_groups",
            "pilot_retention_groups",
        )
    }
    require(
        groups
        == {
            "training_groups": 2,
            "tuning_groups": 1,
            "pilot_new_groups": 2,
            "pilot_retention_groups": 2,
        },
        "Wrong reviewed case inventory",
    )
    require(
        len(cloud["training_seeds"]) == 2
        and cloud["training"]["head_learning_rates"] == [0.003]
        and len(cloud["fixed_schedule_candidates"]) == 1,
        "Wrong reviewed training/tuning opportunity",
    )
    design = {
        "schema": "ndu.real.pilot-design.v1",
        "study_id": collector["study_id"],
        "purpose": "Prospectively fixed real deployment evaluation of the two-seed matched-memory engineering pilot; no retraining or confirmation.",
        "scope": "Five constructed receipt workflows; two train source groups, one disjoint train-role tuning group, two development groups and two retention-validation groups.",
        "source_repository": collector["source_repository"],
        "source_revision": collector["source_revision"],
        "source_selection": {
            **groups,
            "order": "Unchanged collector study_id and SHA256 ordering; selected-sources bytes must match the collector plan.",
            "confirmation_release": "DENIED; confirmation and retention_test are outside this execution.",
        },
        **{
            key: copy.deepcopy(cloud[key])
            for key in (
                "estimand",
                "memory_modes",
                "training_seeds",
                "regimes",
                "controller",
                "arms",
                "training",
                "fixed_schedule_candidates",
            )
        },
        "behavior_collector_seed": collector["behavior_collector_seed"],
        "independent_fit_unit": "Training seed; cores, controllers, memory modes, regimes and episodes are paired conditions, not extra training repeats.",
        "budgets": {
            **cloud["budgets"],
            "max_workers": 4,
            "torch_threads_per_worker": 1,
            "maximum_actions": 8,
            "aggregate_job_cpu_quota_percent": 400,
            "aggregate_job_memory_bytes": 4 * 1024**3,
            "phase_wall_seconds": phase_seconds,
            "maximum_drain_seconds": 360,
            "automatic_performance_retries": 0,
            "phase_budget_semantics": "Existing scheduler stops new admissions with a 90-second reserve and retains every pending/not-started identity; external native execution owns the hard job bound.",
        },
        "objective": {
            "gross": "Independently pinned actual receipt delivery rubric in [0,1].",
            "net": "gross_quality - 0.01 * observed_deployment_wall_seconds",
            "failed_deployment_decision_utility": "-1 - 0.01 * observed wall seconds; unavailable gross score stays null.",
            "retention_scope": "Two retention-validation source groups for the current matched arms; no separate initial-checkpoint incumbent is included.",
        },
        "tuning": {
            "criterion": "Existing matrix.tune: mean observed net utility, equally weighted source groups and task families.",
            "trials_per_active_profile": 1,
            "tie_break": "Lowest trial index",
            "fixed_schedule_candidates": 1,
            "strongest_comparator": "Select among fixed/VOI/MPC on either core separately within each seed/regime/memory mode; six comparator profiles per memory mode.",
        },
        "statistics": {
            "confirmatory_use": False,
            "independent_training_seeds": 2,
            "episodes_are_independent_training_replicates": False,
            "scientific_admission": "HOLD",
            "analysis": "Retain the full paired observations and failures for the separate causal analysis; this runner does not apply the old 24-contrast inference protocol.",
            "budget_stop_analysis_policy": {
                "original_terminal_status": "Preserve BudgetStop and the original paired rows.",
                "analysis_only_mapping": "Map BudgetStop to statistical Completed only when an actual evaluator/rubric-bound finite score and an observed finite nonnegative deployment_wall_seconds are both present; otherwise use Unresolved.",
                "meaning": "Resolved statistical observation only; no claim of original execution success or acceptable quality.",
                "required_cost_scope": "Measured deployment wall cost used by the frozen utility; energy and provider prices need not be known for this mapping.",
                "energy_or_provider_unknown_blocks_mapping": False,
                "full_improvement_budget_gate": False,
                "audit": "Retain original and statistical status counts and every BudgetStop adaptation separately.",
            },
        },
        "expected_inventory": {
            "training_jobs": 56,
            "content_pretraining_jobs": 8,
            "frozen_shared_fit_jobs": 8,
            "joint_fit_jobs": 40,
            "profiles": 80,
            "tuning_cases": 5,
            "development_cases": 10,
            "retention_validation_cases": 2,
            "tuning_episodes": 400,
            "pilot_episodes": 960,
            "separate_initial_incumbents": 0,
        },
        "research_accounting": {
            "phases": [
                "source_and_model_transfer",
                "parameter_replay",
                "tuning",
                "deployment_evaluation",
            ],
            "upstream_collection_and_training": "Original receipts remain separately charged; do not double count nested model/evaluation work.",
            "energy_joules": None,
            "provider_charges": None,
        },
        "permitted_outcome": "Engineering observations only; Inconclusive or Failed, no adoption or RSI claim.",
    }
    return design


def build(args):
    require(
        args.phase_seconds in {900, 1200},
        "Review a 900 or 1200 second episode phase before execution",
    )
    capsule_bytes = read(args.cloud_build / "source-capsule.tar.gz", 2 * 1024**2)
    capsule = unpack(capsule_bytes)
    build_bytes = read(args.cloud_build / "build-receipt.json")
    cloud_build = json.loads(build_bytes)
    require(
        sha(capsule_bytes) == cloud_build["payload_sha256"]
        and sha(capsule["source-manifest.json"])
        == cloud_build["source_manifest_sha256"],
        "Cloud build/capsule binding differs",
    )
    manifest = json.loads(capsule["source-manifest.json"])
    cloud = json.loads(capsule["inputs/design.json"])
    collector_bytes = capsule["inputs/collector-design.json"]
    collector = json.loads(collector_bytes)
    collection_bytes = capsule["inputs/COLLECTION_RESULT.json"]
    collection = json.loads(collection_bytes)
    require(
        sha(capsule["inputs/training.jsonl"]) == collection["raw_sha256"],
        "Cloud input differs from the original collected training observations",
    )
    config_bytes = read(args.collector_config)
    config = json.loads(config_bytes)
    task = Path(config["repository_root"]).parent
    require(
        args.remote_root.is_absolute() and args.remote_root.parent == task,
        "Evaluation output must be a new child of the original task root",
    )
    require(
        args.training_output_root.is_absolute()
        and args.native_artifacts_root.is_absolute()
        and args.training_output_root.is_relative_to(args.native_artifacts_root.parent),
        "Original native training paths must be explicitly bound",
    )
    source = args.remote_root / "source"
    evaluation_config = {
        **config,
        "repository_root": str(source),
        "scripts_root": str(source / "scripts"),
        "runtime_roots": [
            str(source) if name == config["repository_root"] else name
            for name in config["runtime_roots"]
        ],
    }
    verify_runtime_roots(config, evaluation_config, source)
    source_files = {
        row["path"]: row["sha256"]
        for row in manifest["files"]
        if row["path"].startswith(("scripts/", "experiments/"))
    }
    require(
        source_files["scripts/ndu_real_materials/evaluator.py"]
        == config["evaluator_sha256"],
        "Independent evaluator code changed",
    )
    runner = read(Path(__file__).with_name("evaluate_b.py"))
    files = {
        "source-capsule.tar.gz": capsule_bytes,
        "source-build-receipt.json": build_bytes,
        "collector-config.json": config_bytes,
        "collector-design.json": collector_bytes,
        "collection-result.json": collection_bytes,
        "cloud-design.json": capsule["inputs/design.json"],
        "evaluation-config.json": encoded(evaluation_config),
        "evaluation-design.json": encoded(
            evaluation_design(collector, cloud, args.phase_seconds)
        ),
        "cloud-verifier.py": read(args.cloud_verifier),
    }
    spec = {
        "schema": "hepta.causal-b.evaluation-spec.v1",
        "task_root": str(task),
        "evaluation_root": str(args.remote_root),
        "runner_sha256": sha(runner),
        "request_id": cloud_build["request_id"],
        "source_payload_sha256": sha(capsule_bytes),
        "training_backend": "ai395_native",
        "training_output_root": str(args.training_output_root),
        "native_artifacts_root": str(args.native_artifacts_root),
        "source_manifest_sha256": sha(capsule["source-manifest.json"]),
        "source_files": source_files,
        "controller": cloud["controller"],
        "records_sha256": collection["raw_sha256"],
        "rubric_sha256": config["rubric_sha256"],
        "phase_wall_seconds": args.phase_seconds,
        "external_limits_required": {
            "cpu_quota_percent": 400,
            "aggregate_memory_bytes": 4 * 1024**3,
            "timeout_seconds": 2 * (args.phase_seconds + 360) + 180,
        },
        "collector_bindings": {
            "collector-config.json": sha(config_bytes),
            "collector-design.json": sha(collector_bytes),
            "COLLECTION_RESULT.json": sha(collection_bytes),
            "collection/PILOT_PLAN.json": collection["plan_sha256"],
            "collection/training-common.jsonl": collection["raw_sha256"],
        },
        "bundle_files": {name: sha(payload) for name, payload in files.items()},
    }
    files["spec.json"] = encoded(spec)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size, member.mode, member.mtime = len(data), 0o600, 0
            tar.addfile(member, io.BytesIO(data))
    payload = gzip.compress(archive.getvalue(), mtime=0)
    args.output.mkdir(parents=True, exist_ok=False)
    for name in ("spec.json", "evaluation-config.json", "evaluation-design.json"):
        write(args.output / name, files[name])
    write(args.output / "evaluation-inputs.tar.gz", payload)
    transfer = task / (args.remote_root.name + "-transfer")
    script = f"""import base64,hashlib,os,subprocess,sys
from pathlib import Path
root=Path({str(transfer)!r})
root.mkdir(mode=0o700,exist_ok=False)
runner=base64.b64decode({base64.b64encode(runner).decode()!r},validate=True)
bundle=base64.b64decode({base64.b64encode(payload).decode()!r},validate=True)
if hashlib.sha256(runner).hexdigest()!={sha(runner)!r}: raise SystemExit('runner digest differs')
if hashlib.sha256(bundle).hexdigest()!={sha(payload)!r}: raise SystemExit('bundle digest differs')
for name,data in [('evaluate_b.py',runner),('evaluation-inputs.tar.gz',bundle)]:
 with (root/name).open('xb') as output: output.write(data)
os.environ['PYTHONDONTWRITEBYTECODE']='1'
command=[{config["python"]!r},str(root/'evaluate_b.py'),'prepare','--root',{str(args.remote_root)!r},'--bundle',str(root/'evaluation-inputs.tar.gz'),'--bundle-sha256',{sha(payload)!r}]
raise SystemExit(subprocess.run(command,timeout=180,check=False).returncode)
"""
    ast.parse(script)
    require(
        len(script.encode()) <= 2 * 1024**2,
        "Preparation payload exceeds its reviewed 2 MiB transfer bound",
    )
    write(args.output / "prepare_payload.py", script.encode())
    receipt = {
        "schema": "hepta.causal-b.evaluation-build.v1",
        "submitted": False,
        "bundle_sha256": sha(payload),
        "bundle_bytes": len(payload),
        "runner_sha256": sha(runner),
        "payload_sha256": sha(script.encode()),
        "payload_bytes": len(script.encode()),
        "cloud_request_id": cloud_build["request_id"],
        "source_payload_sha256": sha(capsule_bytes),
        "evaluation_root": str(args.remote_root),
        "native_prepare_timeout_seconds": 240,
        "native_execute_limits": spec["external_limits_required"],
        "execute_argv_template": [
            config["python"],
            str(transfer / "evaluate_b.py"),
            "execute",
            "--root",
            str(args.remote_root),
            "--downloads",
            str(args.native_artifacts_root),
            "--prepare-receipt-sha256",
            "OBSERVED_PREPARE_RESULT_SHA256",
            "--artifact-manifest-sha256",
            "VERIFIED_ORIGINAL_ARTIFACT_MANIFEST_SHA256",
        ],
    }
    record(args.output / "build-receipt.json", receipt)
    print(json.dumps(receipt, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-build", type=Path, required=True)
    parser.add_argument("--cloud-verifier", type=Path, required=True)
    parser.add_argument("--collector-config", type=Path, required=True)
    parser.add_argument("--remote-root", type=Path, required=True)
    parser.add_argument("--training-output-root", type=Path, required=True)
    parser.add_argument("--native-artifacts-root", type=Path, required=True)
    parser.add_argument("--phase-seconds", type=int, default=1200)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
