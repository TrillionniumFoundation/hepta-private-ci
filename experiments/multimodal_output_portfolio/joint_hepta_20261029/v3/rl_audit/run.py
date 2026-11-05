"""Execute the registered finite audits with pinned bytes and whole-process costs.

The supplied commit is a publication identifier, not local git HEAD (a partial
checkout may have unrelated local history). SOURCE_MANIFEST.json verifies bytes;
the accompanying GitHub readback receipt verifies their published tree identity.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import traceback

from experiments.multimodal_output_portfolio.joint_hepta_20261029.process_meter_v2 import (
    meter_command,
    write_new,
)


PACKAGE = "experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit"
DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[4]
PHASES = ("semantics", "structure", "tools")


def source_snapshot(root=ROOT, manifest_path=DIRECTORY / "SOURCE_MANIFEST.json"):
    root = Path(root).resolve()
    manifest_bytes = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != "ndu.rl-audit.source.v1" or not manifest.get("files"):
        raise ValueError("A nonempty registered source manifest is required")
    observed = {}
    for name, expected in manifest["files"].items():
        path = root / name
        if Path(name).is_absolute() or not path.resolve().is_relative_to(root):
            raise ValueError("Source path escapes the registered repository")
        data = path.read_bytes()
        identity = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "bytes": len(data),
        }
        if identity != expected:
            raise ValueError(f"Source changed since registration: {name}")
        observed[name] = identity
    return {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "base_commit": manifest["base_commit"],
        "files": observed,
    }


def child(phase, output):
    """Imports, execution and serialization are enclosed by the parent meter."""
    output.mkdir(parents=True, exist_ok=False)
    binding = source_snapshot()
    write_new(
        output / "START.json",
        {
            "phase": phase,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "runner_file": str(Path(__file__).resolve()),
            "source_binding": binding,
        },
    )
    try:
        registration = json.loads((DIRECTORY / "PROTOCOL.json").read_text())
        if phase == "semantics":
            from .semantics import audit

            result = audit()
        elif phase == "structure":
            from .structure import run_study

            result = run_study(seeds=registration["structure"]["seeds"])
        elif phase == "tools":
            from .tool_factorial import run_study

            result = run_study(seeds=registration["tools"]["seeds"])
        else:
            raise ValueError("Unknown registered phase")
        if phase == "structure":
            cases = result.pop("cases")
            result["case_files"] = []
            for index, case in enumerate(cases):
                filename = f"case_{index:03d}.json"
                payload = (json.dumps(case, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
                with (output / filename).open("xb") as stream:
                    stream.write(payload)
                result["case_files"].append(
                    {"path": filename, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
                )
        elif phase == "tools":
            records = result.pop("records")
            result["record_files"] = []
            for index in range(0, len(records), 18):
                filename = f"records_{index // 18:03d}.json"
                payload = (
                    json.dumps(records[index : index + 18], sort_keys=True, separators=(",", ":"), allow_nan=False)
                    + "\n"
                ).encode()
                with (output / filename).open("xb") as stream:
                    stream.write(payload)
                result["record_files"].append(
                    {"path": filename, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
                )
        if source_snapshot() != binding:
            raise ValueError("Source changed during child execution")
        write_new(output / "RESULT.json", {"phase": phase, "source_binding": binding, "data": result})
    except BaseException as error:
        write_new(
            output / "FAILURE.json",
            {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
                "failed_work_retained": True,
            },
        )
        raise


def validate_result(output, phase, binding, registration=None):
    output = Path(output)
    if (output / "FAILURE.json").exists():
        raise ValueError("Child retained a failure; exit zero cannot override it")
    start = json.loads((output / "START.json").read_text())
    result = json.loads((output / "RESULT.json").read_text())
    if (
        start.get("phase") != phase
        or result.get("phase") != phase
        or start.get("source_binding") != binding
        or result.get("source_binding") != binding
        or not isinstance(result.get("data"), dict)
    ):
        raise ValueError("Child phase, registered source or result schema mismatch")
    registered = json.loads((DIRECTORY / "PROTOCOL.json").read_text()) if registration is None else registration
    data = result["data"]
    if phase in ("structure", "tools") and data.get("protocol") != registered[phase]:
        raise ValueError("Result protocol differs from registration")
    cases, records, paths = [], [], set()
    for group in ("case_files", "record_files"):
        for entry in data.get(group, []):
            if entry["path"] in paths:
                raise ValueError("Duplicate result shard")
            paths.add(entry["path"])
            path = output / entry["path"]
            if Path(entry["path"]).is_absolute() or not path.resolve().is_relative_to(output.resolve()):
                raise ValueError("Result shard path escapes execution directory")
            payload = path.read_bytes()
            if len(payload) != entry["bytes"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                raise ValueError("Result shard is missing or changed")
            parsed = json.loads(payload)
            if group == "case_files":
                cases.append(parsed)
            else:
                records.extend(parsed)
    if phase == "structure":
        settings = registered[phase]
        panels = {p["name"]: p for p in settings["panels"]}
        expected = {(name, seed) for name in panels for seed in settings["seeds"]}
        observed = [(row["panel"]["name"], row["seed"]) for row in cases]
        arms = {(family, target) for family in settings["families"] for target in settings["targets"]}
        arms |= {("reference", "exact"), ("reference", "fixed_known_model"), ("action_ablation", "frozen")}
        if set(observed) != expected or len(observed) != len(expected):
            raise ValueError("Structure case roster is incomplete or duplicated")
        for row in cases:
            selected = [(r["family"], r["kind"]) for r in row["records"]]
            if row["panel"] != panels[row["panel"]["name"]] or set(selected) != arms or len(selected) != len(arms):
                raise ValueError("Structure panel or arm roster changed")
    elif phase == "tools":
        settings = registered[phase]
        expected = {
            (seed, method, inference, f"p{i}-b{n}")
            for seed in settings["seeds"]
            for method in settings["training"]
            for inference in settings["inference"]
            for i in range(len(settings["parameter_pairs"]))
            for n in settings["initial_counts"]
        }
        observed = [(r["seed"], r["training"], r["inference"], r["task"]["id"]) for r in records]
        trained = [(r["seed"], r["method"]) for r in data["training"]]
        expected_train = {(s, m) for s in settings["seeds"] for m in settings["training"]}
        if (
            set(observed) != expected
            or len(observed) != len(expected)
            or set(trained) != expected_train
            or len(trained) != len(expected_train)
        ):
            raise ValueError("Tool task or training roster is incomplete or duplicated")
    elif phase == "semantics":
        observed = [(p["eta"], p["rate"]) for p in data["panels"]]
        expected = {(eta, rate) for eta in (0.0, 0.2, 2.0) for rate in (0.0, 0.13)}
        if set(observed) != expected or len(observed) != len(expected):
            raise ValueError("Semantic panel roster changed")
    return True


def execute(output, source_commit, phases=PHASES):
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("An exact published commit SHA is required")
    if not phases or len(set(phases)) != len(phases) or any(p not in PHASES for p in phases):
        raise ValueError("Use a nonempty unique subset of registered phases")
    output = Path(output).resolve()
    before = source_snapshot()
    output.mkdir(parents=True, exist_ok=False)
    write_new(
        output / "REGISTRATION.json",
        {
            "schema": "ndu.rl-audit.execution.v1",
            "source_commit": source_commit,
            "source_binding": before,
            "protocol": json.loads((DIRECTORY / "PROTOCOL.json").read_text()),
            "phases": list(phases),
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "remote_commit_binding_requires_separate_readback_receipt": True,
            "production_qualification": False,
        },
    )
    receipts, results_valid = {}, {}
    environment = dict(os.environ)
    environment.update({"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    for phase in phases:
        command = [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('"
            + PACKAGE
            + ".run',run_name='__main__')",
            str(ROOT),
            "--child",
            phase,
            "--output",
            str(output / phase / "run"),
        ]
        try:
            receipts[phase] = meter_command(command, output / phase, timeout_seconds=1800, environment=environment)
            try:
                results_valid[phase] = validate_result(output / phase / "run", phase, before)
            except (ValueError, OSError, KeyError, TypeError) as error:
                results_valid[phase] = False
                write_new(output / (phase + "_RESULT_REJECTED.json"), {"error": str(error)})
        except BaseException as error:
            write_new(
                output / (phase + "_METER_FAILURE.json"),
                {
                    "type": type(error).__name__,
                    "message": str(error),
                    "traceback": traceback.format_exc(),
                    "complete_cost_known": False,
                },
            )
            raise
    try:
        unchanged = source_snapshot() == before
        after_error = None
    except (ValueError, OSError) as error:
        unchanged, after_error = False, str(error)
    write_new(
        output / "COMPLETION.json",
        {
            "source_commit": source_commit,
            "source_bytes_unchanged": unchanged,
            "source_error": after_error,
            "phase_exit_codes": {p: r["exit_code"] for p, r in receipts.items()},
            "phase_results_valid": results_valid,
            "requested_phases_completed": unchanged
            and all(results_valid.values())
            and all(r["exit_code"] == 0 and not r["timed_out"] for r in receipts.values()),
            "all_registered_phases_completed": set(phases) == set(PHASES)
            and unchanged
            and all(results_valid.values())
            and all(r["exit_code"] == 0 and not r["timed_out"] for r in receipts.values()),
            "scientific_superiority_established": False,
            "new_algorithm_established": False,
            "cost_scope": "Each phase's complete waited process; enclosed measurements are subtotals. Outer launcher, provisioning and publication remain separate.",
        },
    )
    return (
        0
        if unchanged
        and all(results_valid.values())
        and all(r["exit_code"] == 0 and not r["timed_out"] for r in receipts.values())
        else 1
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--phases", nargs="+", choices=PHASES, default=PHASES)
    parser.add_argument("--child", choices=PHASES)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.output)
        return 0
    if args.source_commit is None:
        parser.error("--source-commit is required for the metered parent")
    return execute(args.output, args.source_commit, tuple(args.phases))


if __name__ == "__main__":
    raise SystemExit(main())
