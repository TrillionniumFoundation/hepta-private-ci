"""Verify published-source/model/seal/cost metadata without executing model code."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import tarfile

from audit_metadata_core import ARMS, SEEDS, STAGES, Metadata, audit_generation, digest, require, unique


PACKET_SHA = "7a52402940d92489f4625bac035160d0eee3cf51c872422f5184445af6319735"
PROTOCOL_SHA = "a3531af321d47e82d98d31d2bb5db0cb9eb87809ac30a470468a7b7cde5c1e46"
PUBLISHED = "ee7609048da0c12d542765e29422c0d3c647e0a5"
ALGORITHM = "689c45e1903a6b28dcff6d05c7b732a07511f512"
RAW_SHA = "ce836866d54bf5ea3a6d4d43cbde5f34c31017fcfffcadb60e6068055e23b62c"


def identity(path):
    require(path.is_file() and not path.is_symlink(), "ordinary file required")
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": digest(raw)}


def json_file(path):
    require(path.suffix == ".json" and path.stat().st_size < 64 << 20, "bounded metadata JSON required")
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def file_map(rows):
    result = {}
    for row in rows:
        name = row["path"]
        require(not Path(name).is_absolute() and ".." not in Path(name).parts and name not in result,
                "unsafe or duplicate manifest path")
        result[name] = {"bytes": row["size"], "sha256": row["sha256"]}
    return result


def dump(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main(packet, output):
    packet, target = Path(packet), Path(output)
    root = packet / "unpacked"
    archive = packet / "reporting-metadata.tar.gz"
    require(identity(archive) == {"bytes": 3761485, "sha256": PACKET_SHA}, "metadata packet identity changed")
    transferred = {}
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        require(len(members) == 74 and len({m.name for m in members}) == 74, "metadata member census differs")
        for member in members:
            require(member.isfile() and not Path(member.name).is_absolute() and ".." not in Path(member.name).parts,
                    "metadata archive has unsafe member")
            path = root / member.name
            require(member.name.endswith((".json", ".log")), "metadata packet contains nonmetadata payload")
            raw = stream.extractfile(member).read()
            require(raw == path.read_bytes(), "unpacked original differs")
            transferred[member.name] = {"bytes": len(raw), "sha256": digest(raw)}
    owner_manifest = json_file(root / "owner-manifest.json")
    raw_members = json_file(root / "raw-archive-members.json")
    verification = json_file(root / "archive-verification.json")
    owner_files, full_archive_files = file_map(owner_manifest["files"]), file_map(raw_members["files"])
    require(len(owner_files) == owner_manifest["file_count"] == 4409, "original owner census differs")
    require(sum(x["bytes"] for x in owner_files.values()) == owner_manifest["total_bytes"] == 96326039,
            "original owner bytes differ")
    require(len(full_archive_files) == verification["archive_members_verified"] == 4417, "raw archive member count differs")
    require(verification["raw_archive"] == {"name": "raw-evidence.tar.gz", "size": 82855926, "sha256": RAW_SHA},
            "raw archive identity differs")
    require(verification["owner_manifest_sha256"] == transferred["owner-manifest.json"]["sha256"]
            and verification["archive_members_manifest_sha256"] == transferred["raw-archive-members.json"]["sha256"],
            "main archive byte verification references other manifests")
    for name, value in owner_files.items():
        require(full_archive_files["owner/" + name] == value, "owner/raw archive member identity differs")
    for name, value in transferred.items():
        if name in full_archive_files:
            require(value == full_archive_files[name], "transported metadata differs from raw archive original")
    require(set(full_archive_files) - {"owner/" + x for x in owner_files} ==
            {x for x in transferred if x.startswith(("execution/", "publication/")) or x == "protocol.json"},
            "raw archive has unaccounted external member")

    plan = json_file(root / "protocol.json")
    require(transferred["protocol.json"] == {"bytes": 48276, "sha256": PROTOCOL_SHA}, "published protocol file differs")
    require(plan["algorithm_commit"] == ALGORITHM and plan["source_freshness_scope"] == "audited_known_v6_sources_only",
            "algorithm/exposure scope differs")
    require(plan["unknown_source_exposure_gaps"] == [], "resolved protocol contains known unresolved source gaps")
    require(owner_manifest["source_commit"] == PUBLISHED and owner_manifest["protocol_sha256"] == PROTOCOL_SHA
            and owner_manifest["owner"] == plan["source_owner_directory"], "original owner binding differs")
    published = json_file(root / "execution/publication-verification.json")
    require(published["verified"] is True and published["head"] == PUBLISHED
            and published["protocol_sha256"] == PROTOCOL_SHA and published["checked_protocol_bytes"] == 48276
            and published["verified_before_dataset_cache_preparation"] is True, "publication receipt differs")
    blob_id = hashlib.sha1(b"blob " + str(48276).encode() + b"\0" + (root / "protocol.json").read_bytes()).hexdigest()
    require(blob_id == published["github_blob_sha"], "Git protocol blob identity differs")
    cache = json_file(root / "execution/cache-setup.json")
    require(cache["after_publication"] is True and cache["published_head"] == PUBLISHED
            and cache["network_downloads"] == 0 and cache["new_cohort_prepared_by_setup"] is False, "cache setup boundary differs")
    expected_cache = {x["name"]: x for x in plan["source_files"]}
    require(len(cache["files"]) == 4, "cache file census differs")
    for item in cache["files"]:
        expected = expected_cache[Path(item["cache_file"]).name]
        require(all(item[k] == expected[k] for k in ("bytes", "sha256", "md5")), "registered compressed input differs")

    metadata = Metadata(root / "owner", owner_files)
    generation = audit_generation(metadata, plan, PUBLISHED)
    cases, trained, environment = generation["cases"], generation["training"], generation["environment"]
    require(environment["python"].startswith("3.12.") and environment["packages"] == plan["environment"]["packages"]
            and environment["torch_threads"] == environment["torch_interop_threads"] == 2
            and environment["deterministic_algorithms"] is True and environment["cuda_build"] is None,
            "actual numerical environment differs")
    start, harness = metadata.read("harness-start.json"), metadata.read("harness-summary.json")
    execution = json_file(root / "execution/result.json")
    require(start["source_commit"] == execution["published_head"] == PUBLISHED
            and start["protocol_file_sha256"] == execution["protocol_sha256"] == PROTOCOL_SHA
            and execution["owner"] == plan["source_owner_directory"] and execution["exit"] == 0
            and execution["automatic_retries"] == harness["automatic_retries"] == 0
            and start["no_resumes_or_retries"] is True and start["budget"] == plan["resource_budget"], "execution/source/budget differs")
    require(harness["complete"] is True and harness["model_generation_sealed"] is True and harness["final_cohort_consumed"] is True,
            "registered execution incomplete")
    require([x["stage"] for x in harness["stages"]] == list(STAGES), "process stages differ")
    for row in harness["stages"]:
        require(metadata.read(row["stage"] + "-process.json") == row, "process receipt and summary differ")
        require(row["failure"] is None and row["returncode"] == 0 and row["automatic_retries"] == 0,
                "failed or retried stage")
        metadata.bound(row["stage"] + ".log", {"sha256": row["log_sha256"]})
        require(row["command"][row["command"].index("--source-commit") + 1] == PUBLISHED, "stage source argv differs")
    require(sum(x["cpu_ns_including_import_and_exit"] for x in harness["stages"]) == harness["total_stage_cpu_ns"], "CPU total differs")
    require(harness["total_wall_ns"] < plan["resource_budget"]["total_compute_seconds"] * 10**9,
            "run exceeded registered compute budget")
    require(all(row[field] <= plan["resource_budget"]["maximum_child_rss_bytes"]
                for row in harness["stages"] for field in ("maximum_sampled_child_rss_bytes", "cumulative_completed_child_peak_rss_bytes"))
            and all(row["maximum_sampled_evidence_bytes"] <= plan["resource_budget"]["maximum_new_evidence_bytes"] for row in harness["stages"])
            and harness["new_evidence_bytes"] <= plan["resource_budget"]["maximum_new_evidence_bytes"],
            "recorded resource measurement exceeds registered bound")
    require(harness["new_evidence_bytes"] + owner_files["harness-summary.json"]["bytes"] == owner_manifest["total_bytes"],
            "pre-summary and archived owner bytes do not reconcile")

    output_paths = {f"outputs/seed{seed}-{arm}/{case['case_id']}/{name}"
                    for seed in SEEDS for arm in ARMS for case in cases for name in ("image.png", "caption.txt")}
    runs, run_rows, seals = {}, {}, {}
    for stage in ("inference", "replay"):
        required = {"source-freeze.json", "run.json", "rows.json", "states.npz"} | output_paths
        if stage == "replay":
            required.add("replay.json")
        seals[stage] = metadata.seal(stage, "run-seal.json", required)
        result = metadata.read(stage + "/run.json")
        rows = metadata.read(stage + "/rows.json")["rows"]
        require(result["stage"] == stage and result["environment"] == environment and result["completed_rows"] == 1080
                and len(rows) == 1080 and result["final_targets_opened"] is False
                and result["protocol_canonical_sha256"] == digest(plan)
                and result["training_canonical_sha256"] == digest(trained), "run binding differs")
        for field, filename in (("data_receipt_sha256", "data/data-receipt.json"),
                                ("training_seal_sha256", "training/training-seal.json"), ("model_seal_sha256", "model-seal.json")):
            require(result[field] == owner_files[filename]["sha256"], "run predecessor seal differs")
        require(result["total_calls"] == {key: value * 1080 for key, value in plan["common_inference_calls"].items()},
                "registered structural calls differ")
        for row in rows:
            for kind, relative in row["paths"].items():
                metadata.bound(stage + "/" + relative, {"sha256": row["output_sha256"][kind]})
        runs[stage], run_rows[stage] = result, rows
    require(seals["inference"]["files"]["states.npz"] == seals["replay"]["files"]["states.npz"],
            "replayed state archive identity differs")
    for relative in output_paths:
        require(seals["inference"]["files"][relative] == seals["replay"]["files"][relative], "replayed output identity differs")
    replay = metadata.read("replay/replay.json")
    require(replay["all_output_bytes_equal"] is True and replay["all_state_tensors_equal"] is True
            and replay["rows_replayed"] == 1080 and replay["new_final_targets_opened"] is False
            and replay["original_run_seal_sha256"] == owner_files["inference/run-seal.json"]["sha256"], "replay assertion differs")
    evaluation_seal = metadata.seal("evaluation", "evaluation-seal.json",
                                     {"source-freeze.json", "summary.json", "scored-rows.json", "final-access.json"})
    final_access = metadata.read("data/final-access-ndu-fresh-factorial.json")
    require(metadata.read("evaluation/final-access.json") == final_access, "final claim copies differ")
    require(final_access["single_access_consumed"] is True and final_access["failure_consumes_sources"] is True
            and final_access["source_owner_directory"] == plan["source_owner_directory"]
            and final_access["source_commit"] == PUBLISHED and final_access["source_case_count"] == 90
            and final_access["rows_ready"] == 1080, "final claim boundary differs")
    for field, filename in (("data_receipt_sha256", "data/data-receipt.json"),
                            ("training_seal_sha256", "training/training-seal.json"), ("model_seal_sha256", "model-seal.json"),
                            ("run_seal_sha256", "inference/run-seal.json"), ("replay_seal_sha256", "replay/run-seal.json")):
        require(final_access[field] == owner_files[filename]["sha256"], "final claim predecessor differs")
    require(final_access["expected_target_identity"] == owner_files["data/final-targets.npz"], "opaque target identity differs")
    summary = metadata.read("evaluation/summary.json")
    require(summary["environment"] == environment and summary["protocol_canonical_sha256"] == digest(plan)
            and summary["final_access_ledger_sha256"] == owner_files["data/final-access-ndu-fresh-factorial.json"]["sha256"]
            and summary["final_targets_opened_once"] is True and summary["outcome_dependent_model_selection"] is False
            and summary["arithmetic_audit"]["rows_checked"] == 1080
            and summary["arithmetic_audit"]["maximum_absolute_difference"] <= 1e-7
            and summary["total_audit_crop_predictions"] == 2160, "final scoring audit differs")
    require(all(final_access[key] == value for key, value in summary["binding"].items()), "summary final binding differs")
    times = [start["at_utc"], generation["model_seal"]["at_utc"], seals["inference"]["at_utc"],
             seals["replay"]["at_utc"], final_access["at_utc"], evaluation_seal["at_utc"]]
    require(list(map(datetime.fromisoformat, times)) == sorted(map(datetime.fromisoformat, times)), "recorded seal/claim order differs")
    expected_root = {"harness-start.json", "harness-summary.json", "model-seal.json"}
    expected_root |= {stage + suffix for stage in STAGES for suffix in (".log", "-process.json")}
    require({x for x in owner_files if "/" not in x} == expected_root, "unexpected owner root file")
    require({x for x in owner_files if x.startswith("data/")} == {"data/" + x for x in generation["data"]["files"]} |
            {"data/data-receipt.json", "data/final-access-ndu-fresh-factorial.json"}, "data owner contains extra or missing file")
    suffix_counts = Counter(Path(name).suffix for name in owner_files)
    require(suffix_counts == {".json": 57, ".log": 6, ".npz": 6, ".pt": 20, ".png": 2160, ".txt": 2160}, "owner suffix census differs")

    result = {"schema": "hepta.ndu-fresh.original-metadata-review.v1", "status": "passed",
        "analysis_environment": {"python": platform.python_version()}, "metadata_packet": identity(archive),
        "transferred_originals_verified": transferred, "original_owner_files": len(owner_files),
        "original_owner_bytes": owner_manifest["total_bytes"], "raw_archive_verification_receipt": transferred["archive-verification.json"],
        "raw_archive": verification["raw_archive"], "raw_archive_location_verified": "main host, per original byte-verification receipt",
        "source_commit": PUBLISHED, "algorithm_commit": ALGORITHM, "protocol_identity": transferred["protocol.json"],
        "protocol_canonical_sha256": digest(plan), "original_github_protocol_blob_sha": blob_id,
        "source_files_bound": len(plan["algorithm_source_files"]), "source_scope": generation["source_scope"],
        "source_freshness_scope": plan["source_freshness_scope"], "detailed_exposure_reviewed_scope": plan["exposure_reviewed_scope"],
        "explicit_prior_pixel_exclusions": 520, "new_distinct_source_pixels": 180,
        "source_reserve_pixel_counts": generation["data"]["reserved_source_pixels"],
        "model_files": 20, "bootstrap_required_files_excluding_seal": 20, "training_required_files_excluding_seal": 26,
        "base_reports_verified": 6, "gate_reports_verified": 12, "paired_base_controls": 3, "paired_gate_utility_controls": 6,
        "optimizer_updates": {"observers": 600, "bases": 12000, "gates": 1440},
        "all_twelve_reported_gate_parameter_hashes_changed": all(x["initial_gate_sha256"] != x["final_gate_sha256"] for x in generation["gate_reports"].values()),
        "all_twelve_reported_gate_gradients_positive": all(x["gate_gradient_abs_sum_max"] > 0 for x in generation["gate_reports"].values()),
        "replay_output_file_bindings": 2160, "matching_state_archive_identity": seals["inference"]["files"]["states.npz"],
        "all_six_process_receipts_zero_exit_no_retry": True, "recorded_seal_and_final_claim_times": times,
        "final_access_consumed": True, "reported_original_metric_arithmetic_audit": summary["arithmetic_audit"],
        "owner_suffix_counts": dict(suffix_counts), "actual_run_environment": environment,
        "scope_limits": ["local review opens JSON/log metadata only; no .pt/.npz/PNG payload",
            "raw archive payload bytes were verified on main, not downloaded/rehashed in this review",
            "matching state/output identities bind the original replay; no new inference or OCR execution",
            "independent 1080-row statistical review is a separate receipt",
            "publication ordering is checked against the original publication/execution receipts, not a new GitHub query"],
        "new_model_executed": False, "new_corpus_prepared": False, "final_target_payload_opened": False}
    costs = {"schema": "hepta.ndu-fresh.cost-breakdown.v1", "source_scope": "nested recorded timers; do not add across levels",
        "outer_harness": {key: harness[key] for key in ("total_wall_ns", "total_stage_cpu_ns", "new_evidence_bytes", "harness_peak_rss_bytes")},
        "outer_stages": harness["stages"], "cache_setup_wall_seconds": cache["wall_seconds"],
        "inner_stage_costs": {"prepare": generation["data"]["cost"], "bootstrap": generation["bootstrap"]["cost"],
            "gates": trained["cost"], "inference": runs["inference"]["cost"], "replay": runs["replay"]["cost"], "evaluate": summary["cost"]},
        "observer_fits": {name: {key: row[key] for key in ("cost", "wall_ns", "calibration_accuracy", "train_sources", "calibration_sources", "steps")} for name, row in generation["observers"].items()},
        "base_fits": [{"seed": seed, "profile": profile, "elapsed_seconds": row["elapsed_seconds"]} for (seed, profile), row in generation["base_reports"].items()],
        "base_paired_costs_once_per_seed": {str(seed): generation["base_reports"][seed, "supervised"]["paired_execution_cost"] for seed in SEEDS},
        "gate_fits": [{"seed": seed, "arm": arm, "factorial_cost": row["factorial_cost"], "costs": row["costs"]} for (seed, arm), row in generation["gate_reports"].items()],
        "inference_row_costs": {stage: {"wall_ns": sum(x["cost"]["wall_ns"] for x in rows), "cpu_ns": sum(x["cost"]["cpu_ns"] for x in rows), "rows": len(rows)} for stage, rows in run_rows.items()},
        "model_file_bytes": sum(x["bytes"] for x in generation["model_seal"]["model_files"].values()),
        "owner_bytes_after_summary": owner_manifest["total_bytes"], "recorded_raw_archiving_wall_seconds": verification["wall_seconds_before_metadata"]}
    target.mkdir(parents=True, exist_ok=False)
    dump(target / "metadata-review.json", result)
    dump(target / "cost-breakdown.json", costs)
    print(json.dumps({"status": "passed", "metadata_files": len(transferred), "owner_files": len(owner_files),
        "models": 20, "registered_optimizer_updates": 14040, "no_model_or_target_payload_opened": True, "output": str(target)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--output", required=True)
    main(**vars(parser.parse_args()))
