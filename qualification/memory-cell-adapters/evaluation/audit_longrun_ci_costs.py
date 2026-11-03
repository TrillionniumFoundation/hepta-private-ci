"""Read-only CI artifact, tensor-byte, source-use and cost-scope audit.

This supplement never imports Torch or an experiment/model module. It hashes
saved float32 tensor bytes, inspects saved reader rows, and derives descriptive
cost statistics. It executes no training, inference, or held queries.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_longrun_ci import EvidencePaths
from audit_longrun_resume import canonical, identity, load, sha


def distribution(values):
    ordered = sorted(values)
    return {"count": len(ordered), "min": ordered[0], "median": statistics.median(ordered),
            "p95_nearest_rank": ordered[math.ceil(0.95 * len(ordered)) - 1],
            "max": ordered[-1], "sum": sum(ordered)}


def audit(args):
    paths = EvidencePaths(args.bundle_root, args.checkout_root, args.initial_study)
    run, download = paths.run, args.download_root.resolve(strict=True)
    main_audit = load(args.main_audit)
    checks, failed = 0, []

    def check(label, condition):
        nonlocal checks
        checks += 1
        if not condition:
            failed.append(label)

    check("main_audit_passed", main_audit["passed"] and not main_audit["failed_checks"])
    for name, expected in main_audit["final_artifact_identities"].items():
        check("main_audit_evidence:" + name, identity(run / name) == expected)
    restore = load(download / "RESTORE_VERIFICATION.json")
    origin = load(download / "ARTIFACT_ORIGIN.json")
    packaging = load(download / "memory-adapter-longrun-packaging.json")
    check("download_zip_identity", identity(download / "artifact.zip") == restore["zip"] == origin["zip"])
    check("download_archive_identity", identity(download / packaging["archive"])
          == {key: packaging[key] for key in ("bytes", "sha256")} == restore["tar"])
    check("download_inventory_identity", identity(download / "RESTORED_INVENTORY.jsonl") == restore["inventory"])
    check("packaging_identity", identity(download / "memory-adapter-longrun-packaging.json") == restore["packaging"])
    check("github_origin_binding", origin["conclusion"] == "success"
          and origin["run_id"] == 40681620656 and origin["job_id"] == 122793476485
          and origin["source_commit"] == main_audit["ci_wrapper_audit"]["source_commit"]
          == origin["artifact"]["workflow_run"]["head_sha"]
          and origin["artifact"]["digest"] == "sha256:" + restore["zip"]["sha256"])
    restored_rows = []
    with (download / "RESTORED_INVENTORY.jsonl").open() as source:
        for line in source:
            row = json.loads(line)
            relative = Path(row["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unbounded restored inventory path")
            physical = (paths.bundle.parent / relative).resolve(strict=True)
            if not physical.is_relative_to(paths.bundle):
                raise ValueError("Restored inventory escapes the bundle")
            check("restored_file_unchanged:" + row["path"], identity(physical)
                  == {key: row[key] for key in ("bytes", "sha256")})
            restored_rows.append(row)
    actual_files = [path for path in paths.bundle.rglob("*") if path.is_file()]
    check("whole_restored_tree_inventory", len(actual_files) == len(restored_rows) == restore["regular_files"]
          and sum(row["bytes"] for row in restored_rows) == restore["uncompressed_regular_bytes"])

    checkpoints = sorted(list(run.glob("inputs/seed-*/manifest.json"))
                         + list(run.glob("seed-*/stage-*/*/checkpoint/manifest.json")))
    check("checkpoint_inventory", len(checkpoints) == 219)
    tensor_records = []
    for path in checkpoints:
        manifest, arrays = load(path), {}
        label = str(path.parent.relative_to(run))
        shape_contract = {"A": [4, 384], "B": [384, 4], "head.bias": [12], "head.weight": [12, 384]}
        check("tensor_set:" + label, set(manifest["tensors"]) == set(shape_contract))
        hasher = hashlib.sha256()
        for name, spec in sorted(manifest["tensors"].items()):
            check("tensor_shape:" + label + ":" + name, spec["shape"] == shape_contract[name])
            pieces = []
            for number, part in enumerate(spec["parts"]):
                if part["file"] != f"{name}.{number:04d}.npz":
                    raise ValueError("Unexpected tensor chunk filename")
                file = path.parent / part["file"]
                check("tensor_file_identity:" + label + ":" + name,
                      identity(file) == {key: part[key] for key in ("bytes", "sha256")} and part["bytes"] <= 512000)
                with zipfile.ZipFile(file) as archive:
                    if archive.namelist() != ["values.npy"] or archive.infolist()[0].file_size > 1048576:
                        raise ValueError("Unexpected tensor archive")
                with np.load(file, allow_pickle=False) as archive:
                    piece = archive["values"].copy()
                if piece.dtype != np.dtype("<f4") or piece.ndim != 1 or not np.isfinite(piece).all():
                    raise ValueError("Invalid float32 tensor data")
                pieces.append(piece)
            array = np.concatenate(pieces).reshape(spec["shape"])
            arrays[name] = array
            hasher.update(canonical([name, spec["shape"], "float32"]))
            hasher.update(array.astype("<f4", copy=False).tobytes())
        digest = hasher.hexdigest()
        check("independent_tensor_parameter_digest:" + label, digest == manifest["parameter_sha256"])
        raw_bytes = sum(array.nbytes for array in arrays.values())
        check("parameter_payload_budget:" + label, raw_bytes == 7692 * 4)
        tensor_records.append({"checkpoint": label, "parameter_sha256": digest, "float32_payload_bytes": raw_bytes,
                               "persistent_bytes": sum(file.stat().st_size for file in path.parent.iterdir())})

    sources = [row for row in load(run / "inputs/sources.json") if row["kind"] == "semantic"]
    canonical_file = run / "inputs/canonical.npz"
    canonical_identity = identity(canonical_file)
    with np.load(canonical_file, allow_pickle=False) as data:
        feature_digests = {name: sha(data[name].astype("<f4").tobytes()) for name in ("semantic", "skill")}
    encoder_sha = load(run / "inputs/development-encoder.json")["base_encoder_sha"]
    readers, fits = [], []
    read_source_rows = 0
    for file in sorted(run.rglob("*.process.json")):
        process = load(file)
        if process.get("script") not in ("fit_worker.py", "owner_read.py"):
            continue
        stem = file.name.removesuffix(".process.json")
        request_file = file.with_name(stem + ".request.json")
        request = load(request_file)
        report = load(file.with_name(stem + ".stdout"))
        label = str(file.relative_to(run))
        check("response_request_and_pid_binding:" + label,
              report["request_sha256"] == identity(request_file)["sha256"]
              and report["pid"] == process["pid"] and request["encoder_sha"] == encoder_sha
              and paths.resolve(request["canonical_features_path"]) == canonical_file)
        check("response_canonical_feature_binding:" + label,
              {key: report["canonical_features"][key] for key in ("bytes", "sha256")} == canonical_identity
              and report["canonical_features"]["f32_sha256"] == feature_digests)
        entry = {"process": process, "report": report}
        if process["script"] == "fit_worker.py":
            fits.append(entry)
            continue
        readers.append(entry)
        is_initial = stem == "initial-read"
        expected_database = file.parent / ("owner.sqlite" if is_initial else "sources.sqlite")
        check("reader_database_path:" + label, paths.resolve(request["database"]) == expected_database)
        state = [{**row, "active": True} for row in sources] if is_initial else load(file.parent / "source-state.json")
        for arm in report["arms"]:
            check("reader_row_inventory:" + label + ":" + arm["arm"],
                  len(arm["rows"]) == 8 and {row["entity"] for row in arm["rows"]} == set(range(8)))
            for row in arm["rows"]:
                source = state[row["entity"]]
                active = source["active"]
                read_source_rows += 1
                expected_reads = {"events": 0, "exceptions": 0, "explicit_values": int(active and arm["arm"] == "exact_sql"),
                                  "model": int(active and arm["arm"] == "parameter"), "source_status": 1}
                check("reader_source_identity_and_access:" + label + ":" + arm["arm"] + ":" + str(row["entity"]),
                      row["result"]["sources"] == ([source["source_id"]] if active else [])
                      and row["reads"] == expected_reads)
    check("fit_reader_inventory", len(fits) == 216 and len(readers) == 219 and read_source_rows == 3504)

    timing = {}
    for name, rows in (("fit", fits), ("reader", readers)):
        timing[name + "_process_wall_ns"] = distribution([row["process"]["wall_ns"] for row in rows])
        timing[name + "_process_cpu_seconds"] = distribution([row["process"]["cpu_seconds"] for row in rows])
        timing[name + "_body_wall_ns"] = distribution([row["report"]["wall_ns"] for row in rows])
        timing[name + "_body_cpu_ns"] = distribution([row["report"]["cpu_ns"] for row in rows])
    timing["checkpoint_load_wall_ns"] = distribution([row["report"]["model_load_wall_ns"] for row in readers])
    for name in ("parameter", "exact_sql"):
        timing[name + "_eight_address_loop_ns"] = distribution([
            next(arm["read_wall_ns"] for arm in row["report"]["arms"] if arm["arm"] == name) for row in readers])
    timing["measured_model_calls_wall_ns"] = distribution([row["report"]["model_reads"]["wall_ns"] for row in readers])
    timing["fit_method_wall_seconds"] = distribution([row["report"]["training"]["wall_seconds"] for row in fits])
    timing["fit_method_cpu_seconds"] = distribution([row["report"]["training"]["cpu_seconds"] for row in fits])

    resource = load(run / "resource.json")
    wrapper = load(paths.bundle / "CI_RESULT.json")
    hardware = load(paths.bundle / "HARDWARE.json")
    preparation = load(paths.bundle / "PREPARATION.json")
    process_errors, storage_errors = Counter(), Counter()
    for line in (run / "resource-samples.jsonl").open():
        row = json.loads(line)
        process_errors.update(error["error"] for error in row["process_errors"])
        storage_errors.update(error["error"] for error in row["storage"].get("errors", []))
    check("resource_error_classification", sum(process_errors.values()) + sum(storage_errors.values()) == resource["sample_error_count"])
    observation_ns = resource["wall_ns_through_observation_close"]
    coverage = {name: {"observed_ns": value["observed_interval_ns"], "unknown_ns": value["unobserved_interval_ns"],
                       "observed_fraction": value["observed_interval_ns"] / observation_ns,
                       "sampled_byte_ns_estimate": value["sampled_byte_ns_estimate"],
                       "observed_peak_bytes": resource["peaks_of_sequential_sample_sums"][name]}
                for name, value in resource["integrals"].items()}
    outer_cpu = main_audit["ci_wrapper_audit"]["wrapper_total_observed_cpu_seconds_without_double_counting_children"]
    manager_cpu = sum(resource["child_exit_rusage"][key] for key in ("ru_utime", "ru_stime"))
    launcher = wrapper["lifecycle_launcher"]
    check("cpu_inclusion_order", launcher["completed_child_cpu_seconds"] >= manager_cpu
          >= timing["fit_process_cpu_seconds"]["sum"] + timing["reader_process_cpu_seconds"]["sum"])
    prior_audit = load(args.prior_audit)
    check("prior_chain_audit_passed", prior_audit["passed"] and not prior_audit["failed_checks"])
    prior_completed_cpu = prior_audit["cost_boundary"]["completed_children_including_initial_reads_cpu_seconds"]
    cpu_scopes = {
        "preparation_wall_ns": preparation["wall_ns"],
        "preparation_children_cpu_seconds": preparation["completed_children_cpu_seconds"],
        "manager_and_waited_descendants_kernel_cpu_seconds": manager_cpu,
        "monitor_launcher_cpu_seconds_including_manager_tree": launcher["completed_child_cpu_seconds"],
        "monitor_launcher_wall_ns": launcher["wall_ns"],
        "monitor_process_cpu_seconds_difference": launcher["completed_child_cpu_seconds"] - manager_cpu,
        "wrapper_and_children_cpu_seconds_without_double_counting": outer_cpu,
        "wrapper_wall_ns": wrapper["wrapper_wall_ns"],
        "packaging_cpu_ns": packaging["packaging_cpu_ns"], "packaging_wall_ns": packaging["packaging_wall_ns"],
        "ci_wrapper_plus_packaging_cpu_seconds": outer_cpu + packaging["packaging_cpu_ns"] / 1e9,
        "job_pre_wrapper_wall_ns": hardware["job_pre_wrapper_wall_ns"],
        "checkout_python_setup_cpu_seconds": None, "upload_cpu_seconds": None,
        "post_observation_monitor_serialization_and_launcher_tail_wall_ns":
            launcher["exited_monotonic_ns"] - resource["observations_ended_monotonic_ns"],
        "observed_research_cpu_lower_bound_seconds": prior_completed_cpu + outer_cpu + packaging["packaging_cpu_ns"] / 1e9,
        "research_lower_bound_scope": "Original longrun 435 completed children plus disjoint CI longrun wrapper/children and CI packaging only; omits original driver/monitor, original interrupted work, preparation not recorded here, checkout/setup, upload, earlier formal studies, native CI and local acquisition/auditing.",
    }
    report = {
        "schema": "hepta.memory.ci-longrun-independent-cost-supplement.v1",
        "passed": not failed, "check_count": checks, "failed_checks": failed,
        "read_only_evidence": True, "torch_or_model_module_imported": False,
        "training_or_inference_executed": False,
        "main_audit": identity(args.main_audit), "prior_chain_audit": identity(args.prior_audit),
        "artifact_origin": origin, "restore_receipt": identity(download / "RESTORE_VERIFICATION.json"),
        "read_only_path_mapping": paths.report(), "restored_files_reverified": len(restored_rows),
        "restored_regular_bytes_reverified": sum(row["bytes"] for row in restored_rows),
        "checkpoint_float32_digest_count": len(tensor_records), "checkpoints": tensor_records,
        "reader_source_identity_and_access_rows": read_source_rows, "timing": timing,
        "cpu_and_wall_scopes": cpu_scopes, "resource_window_ns": observation_ns,
        "resource_coverage": coverage, "resource_error_classification": {"process": dict(process_errors), "storage": dict(storage_errors)},
        "storage": {"bundle_regular_bytes": restore["uncompressed_regular_bytes"],
                    "tar_bytes": packaging["bytes"], "zip_bytes": restore["zip"]["bytes"],
                    "checkpoint_persistent_bytes": distribution([row["persistent_bytes"] for row in tensor_records]),
                    "per_model_float32_parameter_bytes": 7692 * 4,
                    "restored_prior_evidence_bytes_outside_lifecycle_roots": preparation["restored_evidence_bytes"],
                    "lifecycle_cost_inventory": main_audit["cost"]},
        "interpretation": [
            "No training or prediction was executed: saved float32 arrays were decoded solely to independently recompute parameter hashes.",
            "The 219 new Python reader processes each run both arms in fixed parameter-then-SQL order. Whole-process timings include interpreter/import/startup/exit and both arms; they are not isolated deployment latencies.",
            "Checkpoint load timing excludes Python/Torch imports and process startup. Neither this measurement nor fresh process identity establishes an uncached filesystem or storage cold start.",
            "Eight-address loop slices exclude checkpoint loading, connection setup and shared preparation. Their comparison is descriptive, not a randomized standalone service benchmark.",
            "Fit-method timing includes validation, optimizer construction, diagnostic forwards and hashing as well as 600 gradient updates; full worker cost also includes startup/imports and checkpoint I/O.",
            "Kernel manager usage, completed child sums and the enclosing monitor launcher overlap. Only disjoint outer wrapper CPU plus packaging is added in the CI accounting.",
            "The monitor records one uninterrupted lifecycle window, but process exit races and journal-file scan races leave explicit unknown sample intervals. Continuous resource integrals are not exact.",
            "Monitor storage roots contain lifecycle output and historical evidence, not installed dependencies, restored formal evidence, repository content, remote storage, or the referenced shared encoder asset.",
            "Shared encoder reference bytes are 127536988, but this CI replication reuses saved canonical features and does not execute or restore the encoder weights.",
            "The additional clean run does not fill in the CPU or memory history of the original interrupted attempt. Research totals retain that unknown and charge both observed executions.",
            "Repeated addresses, fixed source schedule and the same three seeds are correlated observations, not independent generalization samples. Exact SQL matched correctness without parametric fitting.",
        ],
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle-root", "checkout-root", "initial-study", "download-root", "main-audit", "prior-audit", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.download_root.resolve()):
        raise ValueError("Write derived audit outside downloaded evidence")
    report = audit(args)
    raw = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) >= 400000:
        raise ValueError("Supplement exceeds individual blob limit")
    args.output.write_bytes(raw)
    print(json.dumps({key: report[key] for key in ("passed", "check_count", "failed_checks", "checkpoint_float32_digest_count", "reader_source_identity_and_access_rows")}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
