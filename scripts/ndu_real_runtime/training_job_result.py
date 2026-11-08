"""Bind actual trainer results; read-only reconciliation is not native authority."""

import argparse
from dataclasses import asdict, fields
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from ndu_real_materials.common import strict_json
from .controllers import ControlPlan
from .metering import canonical_sha
from .objective import utility_profile
from .span_meter import verify_record
from .subprocess_supervisor import supervision_policy
from .training import FitConfig, SCHEMA, _source_pins, parse_args, validate_record
from .trajectory import (
    V2_SCHEMA,
    episode_groups,
    memory_replay_metadata,
    validate_chains,
)

OUTER_SECONDS = 660
FIT_SECONDS = 600
JSON_LIMIT = 2 * 1024 * 1024
# The line bound is not the receipt bound: the original meter admits 65,536
# events plus stage rows. Keep whole receipts/journals finite without imposing
# the per-training-record 2 MiB limit on an otherwise admitted original fit.
ARTIFACT_LIMIT = 256 * 1024 * 1024
DATA_LIMIT = 512 * 1024 * 1024
AUTHORITY = "SEPARATE_REQUIRED"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bounded(path, limit=JSON_LIMIT, *, content=False):
    """No symlink leaf, bounded stable regular bytes; no checkpoint deserialization."""
    path = Path(path)
    with os.fdopen(
        os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        ),
        "rb",
    ) as stream:
        before = os.fstat(stream.fileno())
        require(
            not path.is_symlink()
            and stat.S_ISREG(before.st_mode)
            and before.st_size <= limit,
            "Nonregular or oversized artifact",
        )
        digest, blocks, size = hashlib.sha256(), [], 0
        while block := stream.read(1024 * 1024):
            size += len(block)
            require(size <= limit, "Artifact grew beyond its bound")
            digest.update(block)
            if content:
                blocks.append(block)
        after = os.fstat(stream.fileno())
    require(
        (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        and size == after.st_size,
        "Artifact changed while reading",
    )
    return (b"".join(blocks) if content else None), {
        "sha256": digest.hexdigest(),
        "bytes": size,
    }


def document(path, limit=JSON_LIMIT):
    raw, pin = bounded(path, limit, content=True)
    return strict_json(raw), pin


def admit(job, config, started_at):
    command = [job["command"]["executable"], *job["command"]["args"]]
    require(
        command[:3] == [config["python"], "-m", "ndu_real_runtime.training"],
        "Unexpected trainer command",
    )
    flags = [part.split("=", 1)[0] for part in command[3:] if part.startswith("--")]
    require(
        len(command) <= 64 and len(flags) == len(set(flags)) and "--help" not in flags,
        "Duplicate/oversized trainer arguments",
    )
    try:
        args = parse_args(command[3:])
    except SystemExit as error:
        raise ValueError("Trainer arguments rejected") from error
    fit = FitConfig(
        **{field.name: getattr(args, field.name) for field in fields(FitConfig)}
    )
    require(
        fit.max_wall_seconds <= FIT_SECONDS,
        "Child fit exceeds existing 600s allowance inside 660s supervisor",
    )
    require(
        args.run_id == job["job_id"]
        and str(args.output) == job["output"]
        and args.output.is_absolute(),
        "Original operation/output differs",
    )
    root = Path(__file__).resolve().parents[2]
    require(
        Path(config["scripts_root"]).resolve() == root / "scripts"
        and Path(config["repository_root"]).resolve() == root,
        "Child import roots differ from admitted source",
    )
    require(
        not any(
            (Path(config["pillow_path"]) / name).exists()
            for name in ("ndu_real_runtime", "ndu_real_materials")
        ),
        "Pillow path shadows trainer packages",
    )
    require(
        job.get("runtime_job_id") in (None, args.runtime_job_id),
        "Self-reported runtime job identity differs",
    )
    stage = "bootstrap" if args.bootstrap else "content" if args.content_only else "fit"
    indexed = {
        "seed": args.seed,
        "core": args.core,
        "phase": stage,
        "regime": args.regime,
        "controller": args.controller,
        "lr": args.lr,
    }
    require(
        all(job[k] == v for k, v in indexed.items() if k in job),
        "Indexed job identity differs from executed command",
    )
    expected = {
        "schema": "ndu.real.training-receipt.v1",
        "run_id": args.run_id,
        "runtime_job_id": args.runtime_job_id,
        "stage": stage,
        "core": args.core,
        "regime": args.regime,
        "controller": args.controller,
        "seed": args.seed,
        "config": asdict(fit),
        "source_pins": _source_pins(),
        "replicate_role": "collector" if stage == "bootstrap" else args.replicate_role,
        "training_replicate": stage == "fit" and args.replicate_role == "fit",
        "scientific_admission": "HOLD",
        "learning_disposition": "not_decided_by_trainer",
    }
    inputs = {
        str(root / name): bounded(root / name)[1] for name in expected["source_pins"]
    }
    require(
        all(
            inputs[str(root / name)]["sha256"] == sha
            for name, sha in expected["source_pins"].items()
        ),
        "Source changed during admission",
    )
    # Parent supervision changes must not invalidate trainer/model lineage.
    supervision_sources = {
        str(Path(__file__).with_name(name)): bounded(Path(__file__).with_name(name))[1]
        for name in (
            "pipeline.py",
            "subprocess_supervisor.py",
            "training_job_result.py",
        )
    }
    inputs.update(supervision_sources)
    if args.control_plan:
        require(args.control_plan.is_absolute(), "Control plan path must be absolute")
        control, inputs[str(args.control_plan)] = document(args.control_plan)
        plan = ControlPlan(**control["control"])
        expected["control_plan_sha256"] = inputs[str(args.control_plan)]["sha256"]
    else:
        plan = ControlPlan(
            latency_weight=fit.latency_weight, memory_mode=args.memory_mode or "reset"
        )
    require(
        plan.latency_weight == fit.latency_weight
        and args.memory_mode in (None, plan.memory_mode),
        "Training/control memory or utility differs",
    )
    expected.update(
        memory_mode=plan.memory_mode,
        control=asdict(plan),
        utility_profile=utility_profile(plan),
        utility_profile_sha256=canonical_sha(utility_profile(plan)),
        control_profile_sha256=canonical_sha(asdict(plan)),
    )
    started = {
        key: expected[key]
        for key in (
            "schema",
            "run_id",
            "runtime_job_id",
            "stage",
            "core",
            "regime",
            "controller",
            "seed",
            "config",
            "source_pins",
            "replicate_role",
            "training_replicate",
            "scientific_admission",
            "learning_disposition",
        )
    }
    records = None
    if stage != "bootstrap":
        require(
            args.expected_records_sha256 is not None and args.records.is_absolute(),
            "Actual records need a prospective digest and absolute path",
        )
        raw, pin = bounded(args.records, DATA_LIMIT, content=True)
        require(
            pin["sha256"] == args.expected_records_sha256,
            "Actual records differ from admitted digest",
        )
        rows = []
        for line in raw.splitlines():
            require(
                line.strip() and len(line) <= JSON_LIMIT and len(rows) < 10000,
                "Training record line/count bound exceeded",
            )
            rows.append(validate_record(strict_json(line)))
        require(rows, "No actual records")
        episode_groups(rows, plan.memory_mode)
        v2 = [row for row in rows if row["schema"] == V2_SCHEMA]
        require(
            all(
                row["utility_profile_sha256"] == expected["utility_profile_sha256"]
                for row in v2
            ),
            "Record utility profile differs",
        )
        rubrics = {row["rubric_sha256"] for row in v2}
        require(len(rubrics) <= 1, "Mixed rubric revisions")
        expected.update(memory_replay_metadata(rows, plan.memory_mode))
        expected.update(
            rubric_sha256=next(iter(rubrics), None),
            behavior_control_profile_sha256=sorted(
                {r["behavior_control_profile_sha256"] for r in v2}
            ),
        )
        records = dict(
            pin,
            rows=len(rows),
            legacy_v1_rows=sum(r["schema"] == SCHEMA for r in rows),
            complete_v2_chains=validate_chains(rows),
        )
        inputs[str(args.records)] = pin
    lineage = None
    if args.pretrained:
        require(args.pretrained.is_absolute(), "Pretrained path must be absolute")
        previous, receipt_pin = document(
            args.pretrained / "receipt.json", ARTIFACT_LIMIT
        )
        _, weights_pin = bounded(args.pretrained / "weights.pt", DATA_LIMIT)
        require(
            previous.get("status") == "CONTENT_PRETRAINED"
            and previous.get("stage") == "content"
            and previous.get("weights_sha256") == weights_pin["sha256"]
            and previous.get("records", {}).get("sha256") == records["sha256"]
            and all(
                previous.get(k) == expected[k]
                for k in (
                    "seed",
                    "core",
                    "source_pins",
                    "memory_mode",
                    "utility_profile_sha256",
                )
            )
            and all(
                previous["config"][k] == expected["config"][k]
                for k in ("content_epochs", "content_lr", "batch_size")
            ),
            "Pretrained lineage differs",
        )
        lineage = {
            "receipt_sha256": receipt_pin["sha256"],
            "run_id": previous["run_id"],
            "cost_in_original_receipt": True,
        }
        require(
            "depends_on" not in job or job["depends_on"] == [previous["run_id"]],
            "Admitted dependency differs from consumed predecessor",
        )
        inputs[str(args.pretrained / "receipt.json")] = receipt_pin
        inputs[str(args.pretrained / "weights.pt")] = weights_pin
    else:
        require(not job.get("depends_on"), "Declared dependency was not consumed")
    return {
        "schema": "ndu.real.training-job-admission.v2",
        "original_operation_id": job["job_id"],
        "started_at": started_at,
        "command": command,
        "output": str(args.output),
        "retry_of": None,
        "expected_receipt": expected,
        "expected_started": started,
        "records": records,
        "pretrained_lineage": lineage,
        "input_files": inputs,
        "supervision": {
            "policy": supervision_policy(),
            "source_files": supervision_sources,
        },
        "budget": {
            "child_fit_limit_seconds": fit.max_wall_seconds,
            "supervisor_limit_seconds": OUTER_SECONDS,
            "reserved_startup_and_io_seconds": OUTER_SECONDS - FIT_SECONDS,
            "scope": "existing wall envelope; actual child and supervisor costs retained, not full budget equivalence",
        },
        "native_owner_authentication": AUTHORITY,
    }


def validate_output(admission, *, exit_code, supervisor_wall_seconds):
    require(
        type(exit_code) is int and exit_code == 0,
        "Child terminal exit is not successful",
    )
    require(
        type(supervisor_wall_seconds) in (int, float)
        and math.isfinite(supervisor_wall_seconds)
        and 0
        <= supervisor_wall_seconds
        <= admission["budget"]["supervisor_limit_seconds"]
        <= OUTER_SECONDS,
        "Supervisor envelope exceeds admitted budget",
    )
    for name, expected in admission["input_files"].items():
        require(
            bounded(name, DATA_LIMIT)[1] == expected,
            "Admitted source/data/control/lineage changed: " + name,
        )
    output = Path(admission["output"])
    started, started_pin = document(output / "started.json")
    receipt, receipt_pin = document(output / "receipt.json", ARTIFACT_LIMIT)
    profile, profile_pin = document(output / "deployment-profile.json")
    _, weights_pin = bounded(output / "weights.pt", DATA_LIMIT)
    expected = admission["expected_receipt"]
    require(
        all(started.get(k) == v for k, v in admission["expected_started"].items())
        and started.get("status") == "STARTED",
        "Started identity differs",
    )
    require(
        all(receipt.get(k) == v for k, v in expected.items()),
        "Receipt source/config/control/memory/schema identity differs",
    )
    status = {
        "bootstrap": "BOOTSTRAP_READY_NOT_A_FIT",
        "content": "CONTENT_PRETRAINED",
        "fit": "FITTED_NOT_ADOPTED",
    }[expected["stage"]]
    require(
        receipt.get("status") == status
        and receipt.get("checkpoint_parameter_replay_exact") is True
        and receipt.get("weights_sha256") == weights_pin["sha256"]
        and receipt.get("deployment_profile_sha256") == profile_pin["sha256"],
        "Final artifact/status binding differs",
    )
    require(
        receipt.get("reused_content") == admission["pretrained_lineage"],
        "Pretrained receipt lineage differs",
    )
    if admission["records"] is not None:
        observed = receipt["records"]
        require(
            all(
                observed.get(k) == v
                for k, v in admission["records"].items()
                if k != "rows"
            )
            and observed["counts"]["rows"] == admission["records"]["rows"],
            "Actual record schema inventory differs",
        )
    else:
        require("records" not in receipt, "Bootstrap unexpectedly claims records")
    wanted_profile = {
        "schema": "ndu.real.deployment-profile.v1",
        "weights_sha256": weights_pin["sha256"],
        "core": expected["core"],
        "memory_mode": expected["memory_mode"],
        "utility_profile_sha256": expected["utility_profile_sha256"],
        "control_profile_sha256": expected["control_profile_sha256"],
        "rubric_sha256": expected.get("rubric_sha256"),
        "recursive_policy_trained": receipt.get("fit_training", {}).get(
            "recursive_objective_applied", False
        ),
    }
    require(
        profile == wanted_profile,
        "Deployment profile fields differ despite a matching weights digest",
    )
    meter = receipt["meter"]
    replay = verify_record(
        meter["raw_spans"], expected_sha256=meter["raw_spans_sha256"]
    )
    require(
        meter.get("schema") == "ndu-real-exclusive-meter-v2"
        and meter.get("operation_id") == expected["run_id"]
        and meter["raw_spans"]["header"]["operation_id"] == expected["run_id"]
        and replay["valid"]
        and replay["complete_record"]
        and replay["envelope"]["status"] == "SUCCEEDED",
        "Meter identity/terminal spans differ",
    )
    for key, ns_key in (
        ("wall_seconds", "inclusive_wall_ns"),
        ("cpu_seconds", "inclusive_process_cpu_ns"),
    ):
        require(
            meter[key] == replay["envelope"][ns_key] / 1e9,
            "Meter totals differ from raw spans",
        )
    require(
        meter["costs"]
        == {
            key: value["exclusive_wall_ns"] / 1e9
            for key, value in replay["categories"].items()
        }
        and meter["observed_unclassified_overhead_seconds"]
        == replay["uninstrumented"]["wall_ns"] / 1e9,
        "Meter category costs differ from raw spans",
    )
    require(
        meter["wall_seconds"] <= supervisor_wall_seconds,
        "Child meter exceeds parent envelope",
    )
    raw, meter_pin = bounded(
        output / "training.meter.jsonl", ARTIFACT_LIMIT, content=True
    )
    lines = [strict_json(line) for line in raw.splitlines()]
    require(
        lines
        == [{"header": meter["raw_spans"]["header"]}]
        + [{"event": e} for e in meter["raw_spans"]["events"]],
        "Persisted meter journal differs",
    )
    return {
        "state": "VALIDATED_UNAUTHENTICATED",
        "receipt_sha256": receipt_pin["sha256"],
        "weights_sha256": weights_pin["sha256"],
        "started_sha256": started_pin["sha256"],
        "deployment_profile_sha256": profile_pin["sha256"],
        "meter_journal_sha256": meter_pin["sha256"],
        "native_owner_authentication": AUTHORITY,
        "production_stage_completed": False,
        "adoption_authorized": False,
    }


def reconcile(directory, expected_admission_sha256):
    """Read retained admission/result only; no subprocess, repair, new ID or adoption."""
    directory = Path(directory)
    admission, pin = document(directory / "admission.json")
    require(
        pin["sha256"] == expected_admission_sha256,
        "Admission differs from caller's original digest",
    )
    if admission.get("schema") != "ndu.real.training-job-admission.v2":
        return {
            "state": "UNATTRIBUTED_HISTORICAL",
            "native_owner_authentication": AUTHORITY,
            "production_stage_completed": False,
        }
    if not (directory / "result.json").exists():
        return {
            "state": "UNRESOLVED",
            "reason": "original supervisor terminal result missing",
            "production_stage_completed": False,
        }
    result, result_pin = document(directory / "result.json")
    require(
        result.get("schema") == "ndu.real.training-job-result.v2"
        and result.get("admission_sha256") == expected_admission_sha256
        and all(
            result.get(k) == admission[k]
            for k in ("original_operation_id", "command", "output", "retry_of")
        )
        and result.get("native_owner_authentication") == AUTHORITY,
        "Original supervisor result binding differs",
    )
    log_limit = 16 * 1024 * 1024
    if "supervision" in admission:
        require(
            result.get("supervision") == admission["supervision"],
            "Supervisor admission binding differs",
        )
        log_limit = admission["supervision"]["policy"]["stream_limit_bytes"]
        require(
            type(log_limit) is int and 0 < log_limit <= 16 * 1024 * 1024,
            "Invalid retained log limit",
        )
    for name in ("stdout", "stderr"):
        require(
            bounded(directory / (name + ".log"), log_limit)[1]["sha256"]
            == result[name + "_sha256"],
            "Retained log differs",
        )
    if result.get("exit_code") is None or result.get("status") == "unresolved":
        return {
            "state": "UNRESOLVED",
            "result_sha256": result_pin["sha256"],
            "production_stage_completed": False,
        }
    if result.get("status") != "completed":
        return {
            "state": "FAILED_RETAINED",
            "result_sha256": result_pin["sha256"],
            "production_stage_completed": False,
        }
    require(
        result.get("error") is None,
        "Completed label conflicts with retained supervisor error",
    )
    if "supervision" in admission:
        report = result.get("process_supervision") or {}
        require(
            report.get("schema") == "ndu.real.subprocess-supervision.v1"
            and report.get("policy") == admission["supervision"]["policy"]
            and report.get("returncode") == result["exit_code"]
            and report.get("error") is None
            and not report.get("cleanup_errors")
            and report.get("cleanup_complete") is True
            and report.get("child_reaped") is True
            and report.get("logs_fsynced") is True
            and all(
                report.get("streams", {}).get(name, {}).get("eof") is True
                and report["streams"][name].get("truncated") is False
                and report["streams"][name].get("observed_bytes")
                == report["streams"][name].get("retained_bytes")
                == (directory / (name + ".log")).stat().st_size
                for name in ("stdout", "stderr")
            ),
            "Completed label conflicts with supervisor evidence",
        )
    observed = validate_output(
        admission,
        exit_code=result["exit_code"],
        supervisor_wall_seconds=result["wall_seconds"],
    )
    require(
        result.get("artifact_validation") == observed
        and result.get("receipt_sha256") == observed["receipt_sha256"]
        and result.get("weights_sha256") == observed["weights_sha256"],
        "Retained result artifact proof differs",
    )
    return dict(observed, result_sha256=result_pin["sha256"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-directory", type=Path, required=True)
    parser.add_argument("--expected-admission-sha256", required=True)
    args = parser.parse_args()
    try:
        result = reconcile(args.operation_directory, args.expected_admission_sha256)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {
            "state": "REJECTED",
            "error": str(error),
            "production_stage_completed": False,
        }
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["state"] == "VALIDATED_UNAUTHENTICATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
