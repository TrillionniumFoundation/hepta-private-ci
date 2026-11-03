"""Train, terminate, and qualify fresh Python readers on separate development data.

This orchestrator and its training subprocess may see source values. The read
subprocess never imports this file and receives no export, targets, or training
code path. It loads a single native-format artifact using the independent Python
mirror. Source-export provenance is recorded, not elevated into owner authority.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from fresh_reader import canonical, decode, digest, model, require


HERE = Path(__file__).resolve().parent
QUALIFICATION = HERE.parents[1]
SCRIPT = HERE / "fresh_reader.py"
KINDS = ("semantic", "procedure")


def save(path, value):
    data = value if isinstance(value, bytes) else canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return {"bytes": len(data), "sha256": digest(data)}


def load_training(v6_root):
    require((v6_root / "v6/cells.py").is_file(), "missing-v6-runtime-use-explicit-v6-root")
    sys.path[:0] = [str(QUALIFICATION / "memory-cell-v7"), str(HERE.parent), str(v6_root)]
    import training
    from learning import byte_model, paired
    return training, byte_model, paired


def code_identity(v6_root):
    files = [SCRIPT, Path(__file__), HERE / "byte_model.py", HERE / "paired.py",
             QUALIFICATION / "memory-cell-v7/training.py", QUALIFICATION / "memory-cell-v7/native_export.py"]
    files += [v6_root / "v6" / name for name in ("__init__.py", "cells.py", "values.py", "contracts.py")]
    return {str(path.resolve()): {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())} for path in files}


def development_export():
    """New deterministic development facts; no frozen held inputs are accessed."""
    records = []
    for index in range(4):
        values = {"semantic": {"factor": index + 2, "label": f"fresh-value-{index}"},
                  "procedure": {"opcode": ("affine", "add_bias", "multiply", "clamp")[index],
                                "bias": index - 2, "limit": 40 + index}}
        for kind, value in values.items():
            records.append({"source_id": digest(f"fresh-source-{kind}-{index}".encode()),
                "owner_memory_id": f"fresh-memory-{kind}-{index}", "revision": 1,
                "record": {"schema": "hepta.memory.cell-record.v1", "entity": f"entity:fresh-{index}",
                           "kind": kind, "effective_at": 1, "value": value}})
    return {"schema": "hepta.memory.owner-snapshot.v1", "owner_agent_id": "fresh:development",
            "scope": "fresh:scope", "owner_cut_digest": digest(canonical(records)),
            "observed_at_unix_seconds": 2, "records": records, "withdrawn_addresses": [],
            "current_source_ids": sorted(row["source_id"] for row in records)}


def train(frame, output, v6_root):
    require(isinstance(frame, dict) and set(frame) == {"schema", "export"}
            and frame["schema"] == "hepta.memory.fresh-training.v1", "training-request-fields")
    training, byte, paired = load_training(v6_root)
    code = code_identity(v6_root)
    rows = training.current_rows(frame["export"])
    require(all(rows[kind] for kind in KINDS), "both-types-require-written-sources")
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    manifests = []
    for kind in KINDS:
        selected = rows[kind]
        zero = paired.initialize(selected, kind, paired.CONFIG)
        trained = training.AssociativeCell.fit(
            [row["record"]["entity"] for row in selected],
            [row["record"]["value"] for row in selected], paired.CONFIG["seed"], kind=kind,
            support_ids=[[row["source_id"]] for row in selected],
            hidden=paired.CONFIG["hidden"], dimension=paired.CONFIG["dimension"], steps=paired.CONFIG["steps"])
        trained.threshold = paired.CONFIG["threshold"]
        require(trained.training_receipt["initial_parameters"] == zero.parameters_digest(), "catalog-initialization-mismatch")
        for variant, cell in (("zero", zero), ("trained", trained)):
            payload, report = paired.artifact(cell)
            name = f"catalog-{kind}-{variant}"
            save(output / "training" / f"{name}.original.json", payload["original"].encode())
            raw = payload["native"].encode()
            identity = save(output / "artifacts" / f"{name}.json", raw)
            manifests.append({"name": name, "representation": "catalog", "kind": kind,
                              "variant": variant, **identity, "report": report})
        meta = byte.metadata(selected, kind)
        zero_arrays = byte.initial_arrays()
        trained_arrays, trained_report = byte.fit(selected, kind)
        require(trained_report["initial_parameters"] == byte.parameter_digest(zero_arrays), "byte-initialization-mismatch")
        for variant, arrays, report in (("zero", zero_arrays, {"steps": 0, "kind": "zero-step-control"}),
                                       ("trained", trained_arrays, trained_report)):
            payload, detail = byte.artifact(meta, arrays, report)
            name = f"byte-{kind}-{variant}"
            identity = save(output / "artifacts" / f"{name}.json", payload["native"].encode())
            manifests.append({"name": name, "representation": "byte", "kind": kind,
                              "variant": variant, **identity, "report": detail})
    require(code_identity(v6_root) == code, "training-source-changed")
    return {"schema": "hepta.memory.fresh-training-result.v1", "pid": os.getpid(),
            "actual_fit_calls": 4, "optimization_steps_per_fit": 600, "artifacts": manifests,
            "source_cut_digest": frame["export"]["owner_cut_digest"], "code_identity": code,
            "wall_ns_before_response": time.monotonic_ns()-began,
            "cpu_ns_before_response": time.process_time_ns()-cpu, "numpy_version": training.np.__version__,
            "training_kind": "existing-v9-mlp-adam", "language_model_finetuning": False,
            "new_independent_held_inputs_used": False, "owner_authority_verified": False}


def process(mode, frame, directory, extra=()):
    directory.mkdir(parents=True, exist_ok=False)
    request = canonical(frame)
    request_identity = save(directory / "request.json", request)
    environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH") if key in os.environ}
    environment.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    command = [sys.executable, "-I", "-u", "-B", str(SCRIPT), mode, *map(str, extra)]
    began = time.monotonic_ns()
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=directory, env=environment, start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = child.communicate(request, timeout=60)
    except subprocess.TimeoutExpired:
        timed_out = True
        child.kill()
        stdout, stderr = child.communicate()
    reaped = time.monotonic_ns()
    stdout_identity = save(directory / "response.json", stdout)
    stderr_identity = save(directory / "stderr.log", stderr)
    receipt = {"pid": child.pid, "mode": mode, "command": command, "exit_code": child.returncode,
               "started_monotonic_ns": began, "reaped_monotonic_ns": reaped,
               "whole_process_wall_ns": reaped-began, "timed_out": timed_out,
               "request": request_identity, "response": stdout_identity, "stderr": stderr_identity}
    try:
        require(not timed_out and len(stdout) <= 1024*1024 and len(stderr) <= 65536, "worker-bound-exceeded")
        response = decode(stdout)
        require(isinstance(response, dict) and response.get("pid") == child.pid, "child-pid-binding")
        receipt["response_parsed"] = True
    except (ValueError, TypeError) as error:
        response = {"pid": child.pid, "response_error": str(error)}
        receipt.update(response_parsed=False, response_error=str(error))
    save(directory / "process.json", receipt)
    return response, receipt


def run_qualification(export, output, v6_root, source_kind):
    require(output.is_absolute() and not output.exists(), "new-absolute-output-directory-required")
    output.mkdir(parents=True)
    began = time.monotonic_ns()
    receipt = {"schema": "hepta.memory.fresh-python-qualification.v1", "passed": False,
               "source_kind": source_kind, "execution_path": "independent-python-f64-mirror",
               "native_runtime_executed": False, "language_model_finetuning": False,
               "held_quality_established": False, "compression_established": False,
               "owner_authority_verified": False, "reads": [], "comparisons": []}
    try:
        export_identity = save(output / "TRAINING_EXPORT.json", export)
        save(output / "PROTOCOL.json", {"schema": "hepta.memory.fresh-python-protocol.v1",
            "source_export": export_identity, "kinds": list(KINDS), "representations": ["catalog", "byte"],
            "interventions": ["zero", "trained", "catalog-removed-rejection"],
            "configuration": {"seed": 91317, "steps": 600, "dimension": 48, "hidden": 32},
            "qualification": "exact written-source recall and unchanged support; outside-support abstention; positive trained-minus-zero recall; catalog removal rejected",
            "scope": "separate development qualification; no selection on frozen held tasks"})
        trained, training_process = process("train", {"schema": "hepta.memory.fresh-training.v1", "export": export},
            output / "training-process", ("--output", output, "--v6-root", v6_root))
        receipt.update(training=trained, training_process=training_process)
        require(training_process["exit_code"] == 0 and training_process["response_parsed"], "training-process-failed")
        current = {row["source_id"]: row for row in export["records"] if row["source_id"] in export["current_source_ids"]}
        expected = {kind: {row["record"]["entity"]: (row["record"]["value"], [source]) for source, row in current.items()
                           if row["record"]["kind"] == kind} for kind in KINDS}
        evidence = {}
        for item in trained["artifacts"]:
            name, kind = item["name"], item["kind"]
            path = output / "artifacts" / f"{name}.json"
            raw = path.read_bytes()
            require({"bytes": len(raw), "sha256": digest(raw)} == {k: item[k] for k in ("bytes", "sha256")}, "saved-artifact-differs")
            wire, _ = model(raw)
            require(wire["training_receipt_sha256"] == digest(canonical(item["report"]["training"])), "training-receipt-differs")
            if item["representation"] == "catalog":
                original = (output / "training" / f"{name}.original.json").read_bytes()
                require(digest(original) == wire["original_artifact_sha256"], "original-artifact-differs")
            sources = {digest(key.encode()): value[1] for key, value in expected[kind].items()}
            require(wire["supports"] == sources, "source-support-differs")
            queries = [{"id": f"q-{i}", "key": key} for i, key in enumerate(sorted(expected[kind]))]
            absent = "entity:fresh-reader-unwritten"
            require(absent not in expected[kind], "unwritten-probe-collides")
            queries.append({"id": "unwritten", "key": absent})
            request = {"schema": "hepta.memory.fresh-python-read.v1", "artifact_path": str(path),
                       "artifact_sha256": digest(raw), "support_sha256": digest(canonical(sources)), "queries": queries}
            read, cost = process("read", request, output / "readers" / name)
            require(cost["exit_code"] == 0 and cost["response_parsed"] and read["artifact_admitted"]
                    and read["request_sha256"] == digest(canonical(request)), "fresh-reader-failed")
            require(cost["started_monotonic_ns"] >= training_process["reaped_monotonic_ns"]
                    and read["pid"] != trained["pid"] and not read["training_modules_loaded"]
                    and read["data_files_read"] == [str(path.resolve())], "fresh-reader-isolation-failed")
            correct = sum(row["abstain"] is None and (row["value"], row["support_ids"]) == expected[kind][row["key"]]
                          for row in read["readouts"] if row["id"] != "unwritten")
            require(len(read["readouts"]) == len(queries) and read["readouts"][-1]["abstain"] == "outside-written-support"
                    and not read["readouts"][-1]["support_ids"], "unwritten-source-accepted")
            evidence[name] = (wire, read, request, raw)
            receipt["reads"].append({"name": name, "known_queries": len(expected[kind]), "known_correct": correct,
                                     "read": read, "process": cost})
        for representation in ("catalog", "byte"):
            for kind in KINDS:
                stem = f"{representation}-{kind}"
                controls = {row["name"]: row for row in receipt["reads"]}
                zero, fitted = controls[stem+"-zero"], controls[stem+"-trained"]
                zero_model, trained_model = evidence[stem+"-zero"][0], evidence[stem+"-trained"][0]
                require(zero_model["supports"] == trained_model["supports"]
                        and zero_model["threshold"] == trained_model["threshold"]
                        and zero_model["parameter_sha256"] != trained_model["parameter_sha256"], "parameter-intervention-mismatch")
                if representation == "catalog":
                    require(zero_model["catalog"] == trained_model["catalog"], "intervention-catalog-mismatch")
                comparison = {"representation": representation, "kind": kind,
                    "known_queries": fitted["known_queries"], "zero_correct": zero["known_correct"],
                    "trained_correct": fitted["known_correct"],
                    "trained_minus_zero": fitted["known_correct"]-zero["known_correct"]}
                comparison["passed"] = (comparison["trained_correct"] == comparison["known_queries"]
                                         and comparison["trained_minus_zero"] > 0)
                receipt["comparisons"].append(comparison)
                if representation == "catalog":
                    stripped = {key: value for key, value in trained_model.items() if key != "catalog"}
                    path = output / "artifacts" / f"{stem}-catalog-removed.json"
                    saved = save(path, stripped)
                    request = {**evidence[stem+"-trained"][2], "artifact_path": str(path), "artifact_sha256": saved["sha256"]}
                    read, cost = process("read", request, output / "readers" / f"{stem}-catalog-removed")
                    require(cost["exit_code"] == 2 and read["rejection"] == "value-catalog-required"
                            and not read["readouts"] and not read["training_modules_loaded"], "catalog-removal-control-failed")
                    receipt["reads"].append({"name": stem+"-catalog-removed", "read": read, "process": cost})
        receipt["passed"] = all(row["passed"] for row in receipt["comparisons"])
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        receipt["failure"] = f"{type(error).__name__}: {error}"
    inventory = []
    for path in sorted(output.rglob("process.json")):
        raw = path.read_bytes()
        cost = decode(raw)
        inventory.append({"path": str(path.relative_to(output)), "sha256": digest(raw),
                          **{key: cost[key] for key in ("pid", "mode", "exit_code", "whole_process_wall_ns", "timed_out", "response_parsed")}})
    receipt.update(parent_wall_ns_before_receipt=time.monotonic_ns()-began, process_inventory=inventory,
        reader_processes=sum(row["mode"] == "read" for row in inventory),
        measured_child_wall_ns=sum(row["whole_process_wall_ns"] for row in inventory),
        resource_scope="child wall includes startup/import/shutdown; per-read compute excludes them; do not add nested durations; no RSS byte-time or complete system-cost claim")
    save(output / "receipt.json", receipt)
    return receipt


def main(mode, arguments):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--v6-root", type=Path, default=Path(os.environ.get(
        "MEMORY_CELL_FRESH_V6_ROOT", str(QUALIFICATION / "memory-cell-v6"))))
    if mode == "qualify":
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--demo", action="store_true")
        source.add_argument("--export", type=Path)
    args = parser.parse_args(arguments)
    output, v6_root = args.output.absolute(), args.v6_root.resolve()
    if mode == "train":
        raw = sys.stdin.buffer.read(16*1024*1024+1)
        require(0 < len(raw) <= 16*1024*1024, "training-input-bound")
        result = train(decode(raw), output, v6_root)
        sys.stdout.buffer.write(canonical(result) + b"\n")
        return 0
    export = development_export() if args.demo else decode(args.export.read_bytes())
    result = run_qualification(export, output, v6_root,
        "synthetic-development-new-to-this-qualification" if args.demo else "caller-supplied-export-unverified-owner")
    print(json.dumps({"receipt": str(output / "receipt.json"), "passed": result["passed"],
                      "reader_processes": result["reader_processes"], "native_runtime_executed": False}))
    return 0 if result["passed"] else 1
