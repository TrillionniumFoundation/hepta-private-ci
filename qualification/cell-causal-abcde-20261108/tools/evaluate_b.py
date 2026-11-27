#!/usr/bin/env python3
"""Freeze and evaluate returned B checkpoints without training or wider actor roots."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import resource
import sys
import tarfile
import time
import traceback

MAX_BYTES = 64 * 1024**2


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path, limit=MAX_BYTES):
    path = Path(path)
    require(
        not path.is_symlink() and path.is_file() and path.stat().st_size <= limit,
        "Bounded regular file required: " + str(path),
    )
    data = path.read_bytes()
    require(len(data) <= limit, "Input grew beyond its bound")
    return data


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(data)


def record(path, value):
    return write(
        path,
        (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
    )


def cpu_usage():
    return sum(
        value.ru_utime + value.ru_stime
        for value in (
            resource.getrusage(resource.RUSAGE_SELF),
            resource.getrusage(resource.RUSAGE_CHILDREN),
        )
    )


def relative(name):
    path = PurePosixPath(name)
    require(
        not path.is_absolute()
        and name
        and all(p not in {"", ".", ".."} for p in name.split("/")),
        "Non-canonical archive path",
    )
    return path


def unpack(data):
    files, size = {}, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            name = str(relative(member.name))
            size += member.size
            require(
                member.isfile()
                and name not in files
                and 0 <= member.size <= MAX_BYTES
                and size <= MAX_BYTES
                and len(files) < 4096,
                "Unsafe or oversized archive",
            )
            payload = archive.extractfile(member).read()
            require(len(payload) == member.size, "Truncated archive member")
            files[name] = payload
    return files


def load_runtime(config):
    sys.dont_write_bytecode = True
    sys.path[:0] = [
        config["pillow_path"],
        config["scripts_root"],
        config["repository_root"],
    ]
    os.environ.update(
        PYTHONDONTWRITEBYTECODE="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
    )


def verify_source(root, spec):
    for name, digest in spec["source_files"].items():
        require(
            sha(read(root / "source" / relative(name))) == digest,
            "Frozen evaluation source changed: " + name,
        )


def verify_runtime_roots(old, new, source):
    expected = {
        **old,
        "repository_root": str(source),
        "scripts_root": str(source / "scripts"),
    }
    require(
        old["runtime_roots"].count(old["repository_root"]) == 1,
        "Old source must have one explicit runtime root",
    )
    expected["runtime_roots"] = [
        str(source) if value == old["repository_root"] else value
        for value in old["runtime_roots"]
    ]
    require(
        new == expected,
        "Evaluation config changed permissions or unrelated runtime fields",
    )


def prepare(args):
    raw = read(args.bundle, 2 * 1024**2)
    require(sha(raw) == args.bundle_sha256, "Preparation bundle digest differs")
    files = unpack(raw)
    spec = json.loads(files["spec.json"])
    require(
        set(files) == {"spec.json", *spec["bundle_files"]},
        "Unexpected preparation member",
    )
    require(
        all(
            sha(files[name]) == digest for name, digest in spec["bundle_files"].items()
        ),
        "Preparation member digest differs",
    )
    root, task = args.root, Path(spec["task_root"])
    require(
        root.is_absolute()
        and root == Path(spec["evaluation_root"])
        and root.parent == task
        and task.resolve() == task,
        "Output is not the new task-local evaluation root",
    )
    require(
        sha(read(__file__)) == spec["runner_sha256"],
        "Evaluation runner differs from reviewed bytes",
    )
    root.mkdir(mode=0o700, exist_ok=False)
    started, initial_cpu, stage = time.monotonic(), cpu_usage(), "admission"
    result = {
        "schema": "hepta.causal-b.evaluation-prepare.v1",
        "status": "started",
        "bundle_sha256": args.bundle_sha256,
    }
    record(
        root / "PREPARE_ADMISSION.json",
        {**result, "spec_sha256": sha(files["spec.json"]), "started_unix": time.time()},
    )
    try:
        for name, payload in files.items():
            write(root / "pins" / relative(name), payload)
        stage = "source-and-collector-bindings"
        capsule = unpack(files["source-capsule.tar.gz"])
        manifest = json.loads(capsule["source-manifest.json"])
        require(
            sha(capsule["source-manifest.json"]) == spec["source_manifest_sha256"],
            "Source manifest differs",
        )
        bound = {row["path"]: row for row in manifest["files"]}
        require(
            len(bound) == len(manifest["files"])
            and set(capsule) == {"source-manifest.json", *bound},
            "Duplicate or unbound capsule member",
        )
        for name, row in bound.items():
            require(
                len(capsule[name]) == row["bytes"]
                and sha(capsule[name]) == row["sha256"],
                "Capsule source/input binding differs",
            )
        for name, digest in spec["source_files"].items():
            require(
                name.startswith(("scripts/", "experiments/"))
                and sha(capsule[name]) == digest,
                "Actor source contains an unapproved input",
            )
            write(root / "source" / relative(name), capsule[name])
        require(
            not (root / "source/inputs").exists(),
            "Training inputs entered actor runtime source",
        )
        for name, digest in spec["collector_bindings"].items():
            require(
                sha(read(task / relative(name))) == digest,
                "Original collector evidence changed: " + name,
            )
        original_plan = json.loads(read(task / "collection/PILOT_PLAN.json"))
        config = json.loads(files["evaluation-config.json"])
        verify_runtime_roots(
            json.loads(files["collector-config.json"]), config, root / "source"
        )
        stage = "prospective-evaluation-freeze"
        load_runtime(config)
        from ndu_real_runtime.causal_b_contract import validate_design
        from ndu_real_runtime.study import freeze

        design = json.loads(files["evaluation-design.json"])
        validate_design(design)
        require(
            design["study_id"] == original_plan["design"]["study_id"],
            "Case-selection study identity changed",
        )
        plan = freeze(config, root / "pins/evaluation-design.json", root / "study")
        require(
            plan["selected_sources_sha256"] == original_plan["selected_sources_sha256"],
            "Evaluation cases differ from the collector-frozen cases",
        )
        selected = json.loads(read(root / "study/selected-sources.json"))
        allowed = {
            "training": "train",
            "tuning": "train",
            "pilot_new": "development",
            "pilot_retention": "retention_validation",
        }
        require(
            all(
                case["role"] == role
                for key, role in allowed.items()
                for case in selected["cases"][key]
            ),
            "Sealed or wrong-role source entered evaluation",
        )
        counts = {name: len(cases) for name, cases in selected["cases"].items()}
        require(
            counts
            == {"training": 10, "tuning": 5, "pilot_new": 10, "pilot_retention": 2},
            "Frozen case inventory differs from the reviewed engineering pilot",
        )
        result.update(
            status="ready_for_original_training_return",
            plan_sha256=sha(read(root / "study/PILOT_PLAN.json")),
            selected_sources_sha256=plan["selected_sources_sha256"],
            case_counts=counts,
        )
    except BaseException as error:
        result.update(
            status="failed",
            stage=stage,
            error={
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
    result.update(
        wall_seconds=time.monotonic() - started,
        cpu_seconds=cpu_usage() - initial_cpu,
        scientific_admission="HOLD",
        adoption_authorized=False,
        confirmation_access=False,
    )
    pin = record(root / "PREPARE_RESULT.json", result)
    print(json.dumps({**result, "receipt_sha256": pin}, sort_keys=True), flush=True)
    return 0 if result["status"] == "ready_for_original_training_return" else 1


def migrate_index(root, spec):
    """Rewrite directory only; every original cloud artifact remains immutable."""
    from ndu_real_runtime.controllers import ControlPlan
    from ndu_real_runtime.metering import canonical_sha
    from ndu_real_runtime.objective import utility_profile
    from ndu_real_runtime.training import _source_pins, parameter_sha
    from ndu_real_runtime.neural import ReceiptPortfolioModel
    from dataclasses import asdict
    import torch

    torch.set_num_threads(1)
    base = root / "cloud-return/results/b"
    index_bytes = read(base / "model-index.json")
    original, derived = json.loads(index_bytes), json.loads(index_bytes)
    fit_plan = json.loads(read(base / "fit-plan.json"))
    cloud_plan = json.loads(read(base / "CAUSAL_B_PLAN.json"))
    require(
        cloud_plan["design"] == json.loads(read(root / "pins/cloud-design.json")),
        "Returned training design differs from the frozen cloud design",
    )
    require(
        cloud_plan["records"]["sha256"] == spec["records_sha256"],
        "Returned training data pin differs",
    )
    prefix = PurePosixPath(spec["training_output_root"])
    require(
        fit_plan["intent"]["output_root"] == str(prefix),
        "Unexpected original cloud output root",
    )
    jobs = {job["output"]: job for job in fit_plan["jobs"]}
    entries = original["content"] + original["fits"]
    require(
        len(jobs) == 56
        and len(entries) == 56
        and {row["directory"] for row in entries} == set(jobs),
        "Returned fit/index denominator differs",
    )
    pins, mappings = _source_pins(), []
    for original_row, row in zip(entries, derived["content"] + derived["fits"]):
        old_path = PurePosixPath(row["directory"])
        suffix = old_path.relative_to(prefix)
        relative(str(suffix))
        target = base / "models/independent" / str(suffix)
        row["directory"] = str(target)
        job = jobs[str(old_path)]
        require(
            all(
                row[key] == job[key]
                for key in (
                    "seed",
                    "core",
                    "memory_mode",
                    "observation_policy",
                    "paired_memory_group",
                )
            ),
            "Index treatment metadata differs from its original job",
        )
        if job["phase"] == "fit":
            require(
                all(
                    row[key] == job[key]
                    for key in ("regime", "controller", "trial_index")
                ),
                "Fit index metadata differs",
            )
        evidence = {
            "old_directory": str(old_path),
            "new_directory": str(target),
            "status": row["status"],
        }
        if row["status"] == "completed":
            receipt_data = read(target / "receipt.json")
            receipt = json.loads(receipt_data)
            deployment_data = read(target / "deployment-profile.json")
            deployment = json.loads(deployment_data)
            require(
                sha(receipt_data) == row["receipt_sha256"]
                and sha(read(target / "weights.pt"))
                == row["weights_sha256"]
                == receipt["weights_sha256"],
                "Checkpoint or receipt changed during transfer",
            )
            require(
                sha(deployment_data) == receipt["deployment_profile_sha256"],
                "Deployment contract changed",
            )
            require(
                receipt["source_pins"] == pins == fit_plan["intent"]["source_pins"],
                "Cloud training and evaluation source bytes differ",
            )
            require(
                receipt["run_id"] == job["job_id"]
                and receipt["records"]["sha256"] == spec["records_sha256"],
                "Original fit identity/data differs",
            )
            require(
                receipt["stage"] == job["phase"]
                and receipt["status"]
                == (
                    "CONTENT_PRETRAINED"
                    if job["phase"] == "content"
                    else "FITTED_NOT_ADOPTED"
                ),
                "Original training status differs",
            )
            require(
                all(
                    receipt[key] == job[key]
                    for key in (
                        "seed",
                        "core",
                        "regime",
                        "controller",
                        "memory_mode",
                        "observation_policy",
                    )
                ),
                "Original fit treatment differs",
            )
            control = ControlPlan(
                **{**spec["controller"], "memory_mode": row["memory_mode"]}
            )
            require(
                receipt["control_profile_sha256"] == canonical_sha(asdict(control))
                and receipt["utility_profile_sha256"]
                == canonical_sha(utility_profile(control)),
                "Deployment control or utility differs",
            )
            require(
                deployment["weights_sha256"] == row["weights_sha256"]
                and deployment["core"] == row["core"]
                and deployment["memory_mode"] == row["memory_mode"]
                and deployment["rubric_sha256"] == spec["rubric_sha256"],
                "Deployment model/rubric binding differs",
            )
            model = ReceiptPortfolioModel(row["core"]).float()
            model.load_state_dict(
                torch.load(
                    target / "weights.pt", map_location="cpu", weights_only=True
                ),
                strict=True,
            )
            require(
                parameter_sha(model) == receipt["final_parameter_sha256"],
                "Transferred tensor parameters do not replay exactly",
            )
            evidence.update(
                weights_sha256=row["weights_sha256"],
                receipt_sha256=row["receipt_sha256"],
                deployment_profile_sha256=sha(deployment_data),
                parameter_replay_exact=True,
            )
            del model
        require(
            {k: v for k, v in original_row.items() if k != "directory"}
            == {k: v for k, v in row.items() if k != "directory"},
            "Migration changed a non-directory index field",
        )
        mappings.append(evidence)
    index_pin = record(root / "model-index.ai395.json", derived)
    record(
        root / "MODEL_MIGRATION_RECEIPT.json",
        {
            "schema": "hepta.causal-b.model-migration.v1",
            "original_index_sha256": sha(index_bytes),
            "derived_index_sha256": index_pin,
            "directory_is_only_changed_index_field": True,
            "original_training_plan_sha256": sha(read(base / "CAUSAL_B_PLAN.json")),
            "mappings": mappings,
            "models_retrained": False,
        },
    )
    return mappings


def retain_downloads(original, target, expected_manifest_sha256):
    """Copy exact bounded native artifacts without changing the original root."""
    raw = read(original / "artifact-manifest.json", 1024**2)
    require(sha(raw) == expected_manifest_sha256, "Original artifact manifest changed")
    manifest, names, total = json.loads(raw), set(), len(raw)
    require(1 <= len(manifest["files"]) <= 1024, "Artifact inventory exceeds its bound")
    target.mkdir(exist_ok=False)
    write(target / "artifact-manifest.json", raw)
    for row in manifest["files"]:
        name = str(relative(row["path"]))
        require(
            name not in names and name != "artifact-manifest.json",
            "Duplicate native artifact",
        )
        names.add(name)
        path = original / name
        require(
            path.resolve().is_relative_to(original.resolve()),
            "Native artifact escaped its original return directory",
        )
        payload = read(path, 32 * 1024**2)
        total += len(payload)
        require(
            total <= 32 * 1024**2
            and len(payload) == row["bytes"]
            and sha(payload) == row["sha256"],
            "Native artifact size/hash differs",
        )
        write(target / name, payload)
    return target


def execute(args):
    root = args.root
    spec = json.loads(read(root / "pins/spec.json"))
    require(
        root == Path(spec["evaluation_root"])
        and root.parent == Path(spec["task_root"])
        and root.resolve() == root,
        "Wrong evaluation root",
    )
    require(
        sha(read(root / "PREPARE_RESULT.json")) == args.prepare_receipt_sha256,
        "Preparation receipt differs",
    )
    prepared = json.loads(read(root / "PREPARE_RESULT.json"))
    require(
        prepared["status"] == "ready_for_original_training_return",
        "Evaluation preparation did not complete",
    )
    require(
        args.downloads.resolve().is_relative_to(root.parent)
        or args.downloads.resolve() == Path(spec["native_artifacts_root"]),
        "Return directory is outside the frozen native transfer scope",
    )
    require(
        sha(read(args.downloads / "artifact-manifest.json"))
        == args.artifact_manifest_sha256,
        "Original provider artifact manifest differs",
    )
    require(
        sha(read(__file__)) == spec["runner_sha256"],
        "Reviewed evaluation runner changed",
    )
    record(
        root / "EXECUTE_ADMISSION.json",
        {
            "started_unix": time.time(),
            "prepare_receipt_sha256": args.prepare_receipt_sha256,
            "artifact_manifest_sha256": args.artifact_manifest_sha256,
            "automatic_retry": False,
            "external_limits_required": spec["external_limits_required"],
        },
    )
    started, initial_cpu, stage = time.monotonic(), cpu_usage(), "source-verification"
    result = {
        "schema": "hepta.causal-b.evaluation-result.v1",
        "status": "started",
        "training_backend": "ai395_native",
        "expected_tuning_episodes": 400,
        "expected_pilot_episodes": 960,
        "phases": {},
    }
    try:
        verify_source(root, spec)
        require(
            sha(read(root / "study/PILOT_PLAN.json")) == prepared["plan_sha256"],
            "Prospective evaluation plan changed",
        )
        for name, digest in spec["bundle_files"].items():
            require(
                sha(read(root / "pins" / relative(name))) == digest,
                "Frozen evaluation input changed",
            )
        loader = importlib.util.spec_from_file_location(
            "cloud_verifier", root / "pins/cloud-verifier.py"
        )
        verifier = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(verifier)
        retained = retain_downloads(
            args.downloads, root / "provider-return", args.artifact_manifest_sha256
        )
        result["training_return"] = verifier.verify_download(
            retained,
            json.loads(read(root / "pins/source-build-receipt.json")),
            root / "cloud-return",
        )
        require(
            (root / "cloud-return/results/b/model-index.json").is_file(),
            "Original cloud model index is absent",
        )
        config = json.loads(read(root / "pins/evaluation-config.json"))
        load_runtime(config)
        stage = "model-migration-and-parameter-replay"
        mappings = migrate_index(root, spec)
        result["model_status_counts"] = {
            status: sum(row["status"] == status for row in mappings)
            for status in sorted({row["status"] for row in mappings})
        }
        from ndu_real_runtime.matrix import tune, pilot
        from ndu_real_runtime.metering import _usage
        from ndu_real_runtime.study import verify_plan

        verify_plan(root / "study")
        for stage, operation in (
            ("tune", lambda: tune(root / "study", root / "model-index.ai395.json")),
            ("pilot", lambda: pilot(root / "study")),
        ):
            phase_start, cpu = time.monotonic(), _usage()
            require(
                time.monotonic() - started + spec["phase_wall_seconds"] + 360
                <= spec["external_limits_required"]["timeout_seconds"],
                "Remaining native budget cannot cover another original phase",
            )
            completed = False
            try:
                with (
                    (root / (stage + ".stdout.log")).open("x") as stdout,
                    (root / (stage + ".stderr.log")).open("x") as stderr,
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    operation()
                completed = True
            finally:
                phase = {
                    "completed": completed,
                    "wall_seconds": time.monotonic() - phase_start,
                    "cpu_seconds": _usage() - cpu,
                    "nested_episode_costs_are_included": True,
                }
                result["phases"][stage] = phase
                record(root / (stage + ".envelope.json"), phase)
        verify_source(root, spec)
        lock = json.loads(read(root / "study/selection-lock.json"))
        pilot_result = json.loads(read(root / "study/pilot/phase-result.json"))
        result.update(
            status="evaluated",
            complete_tuning=lock["all_search_trials_complete"],
            expected_profiles=80,
            selected_profiles=len(lock["selected"]),
            pilot_planned=pilot_result["planned"],
            pilot_dispatched=pilot_result["dispatched"],
        )
    except BaseException as error:
        result.update(
            status="failed",
            stage=stage,
            error={
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
    result.update(
        wall_seconds=time.monotonic() - started,
        cpu_seconds=cpu_usage() - initial_cpu,
        phase_costs_overlap_total=True,
        native_outer_envelope_separately_required=True,
        max_self_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        energy_joules=None,
        provider_charges=None,
        scientific_admission="HOLD",
        adoption_authorized=False,
        confirmation_access=False,
        models_retrained=False,
    )
    pin = record(root / "EVALUATION_RESULT.json", result)
    print(json.dumps({**result, "receipt_sha256": pin}, sort_keys=True), flush=True)
    return 0 if result["status"] == "evaluated" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--root", type=Path, required=True)
    prep.add_argument("--bundle", type=Path, required=True)
    prep.add_argument("--bundle-sha256", required=True)
    run = commands.add_parser("execute")
    run.add_argument("--root", type=Path, required=True)
    run.add_argument("--downloads", type=Path, required=True)
    run.add_argument("--prepare-receipt-sha256", required=True)
    run.add_argument("--artifact-manifest-sha256", required=True)
    args = parser.parse_args()
    return prepare(args) if args.command == "prepare" else execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
