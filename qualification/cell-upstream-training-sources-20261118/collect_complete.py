"""Archive exact upstream originals and native replay receipts without new execution."""

import gzip, hashlib, io, json, os, pathlib, tarfile, time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, data):
    raw = (
        data
        if isinstance(data, bytes)
        else json.dumps(data, sort_keys=True, indent=2).encode() + b"\n"
    )
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return raw


def main(payload):
    started = time.perf_counter()
    root = pathlib.Path(payload["root"]).resolve(strict=True)
    output = root / "export-complete-1"
    output.mkdir(exist_ok=False)
    raw_result = (root / "replay-1/RESULT.json").read_bytes()
    assert (
        sha(raw_result)
        == "41388e7d6a7afd5e9a9c7b288dd428bc393a09d2e208228253bd7ef61b398240"
    )
    raw_sources = (root / "SOURCES.json").read_bytes()
    assert (
        sha(raw_sources)
        == "686f1d77e274486034044ead9ec1b5db25c98c87b530264e1128766da785d0fa"
    )
    result, sources = json.loads(raw_result), json.loads(raw_sources)
    plan = json.loads(
        (root / "material-entry-1/SOURCE_GROWTH_PROTOCOL.json").read_bytes()
    )
    materials = [
        json.loads(line)
        for line in (root / "material-entry-1/MATERIALS.jsonl").read_text().splitlines()
    ]
    assert len(materials) == len(sources["sources"]) == 4
    runtime = root / "runtime-evidence"
    runtime.mkdir(exist_ok=False)
    for name, text in payload["runtime"].items():
        write(runtime / name, text.encode())
    write(root / "collect_complete.py", payload["source"].encode())
    write(
        root / "COLLECTOR_SOURCE.json",
        {
            "source_commit": payload["source_commit"],
            "source_sha256": sha(payload["source"].encode()),
        },
    )
    summaries = []
    for source in sources["sources"]:
        before, after = [
            row for row in result["stages"] if row["project_id"] == source["project_id"]
        ]
        assert (
            before["tests"] == after["tests"]
            and before["failures"] > 0
            and after["passed"] == after["tests"]
        )
        summaries.append(
            {
                "source_id": source["source_id"],
                "project_id": source["project_id"],
                "repository_id": source["repository_id"],
                "owner": source["owner"],
                "request_url": source["request_url"],
                "before_commit": source["before_commit"],
                "after_commit": source["after_commit"],
                "original_merged_at": source["merged_at"],
                "license": source["license"],
                "original_test_path": source["selected_tests"]["path"],
                "original_test_functions": source["selected_tests"]["names"],
                "cases_each_revision": before["tests"],
                "before_passed": before["passed"],
                "before_failed": before["failures"],
                "after_passed": after["passed"],
                "after_failed": after["failures"],
                "case_timeouts_before": sum(
                    "Timeout" in (case["failure_type"] or "")
                    for case in before["cases"]
                ),
                "before_exit": before["wait_returncode"],
                "after_exit": after["wait_returncode"],
                "collection_errors": before["errors"] + after["errors"],
                "outer_child_timeouts": int(before["timed_out"])
                + int(after["timed_out"]),
                "original_regression_demonstrated": True,
            }
        )
    acquisition = json.loads((root / "ACQUISITION.json").read_bytes())
    readout = {
        "schema": "hepta.upstream-training-sources-readout.v1",
        "status": "FOUR_ORIGINAL_UPSTREAM_FIXES_REPLAYED",
        "intent_commit": "04eea36b2ffe52a9e5105d0701880a0dedca9717",
        "acquisition_source_commit": "5e78427a7e0bf2623177c10ab1ad9ab03932b80b",
        "replay_source_commit": "b8568658762bb3a54c94253811d563b0f39dac3e",
        "material_entry_source_commit": "c80a4cfdb49a49ed72cbdae18c0e4de68883c1d0",
        "collector_source_commit": payload["source_commit"],
        "source_inventory_sha256": sha(raw_sources),
        "native_replay_sha256": sha(raw_result),
        "material_jsonl_sha256": sha(
            (root / "material-entry-1/MATERIALS.jsonl").read_bytes()
        ),
        "source_growth_protocol_sha256": sha(
            (root / "material-entry-1/SOURCE_GROWTH_PROTOCOL.json").read_bytes()
        ),
        "sources": summaries,
        "deduplication": {
            "frozen_new_pool_project_count": 4,
            "github_organization_identity_count": 4,
            "repair_lineage_count": 4,
            "unique_observation_count": 4,
            "distinct_git_blobs": acquisition["distinct_git_blobs"],
            "downloaded_unique_blob_bytes": acquisition["downloaded_blob_bytes"],
            "test_parameters_are_new_sources": False,
            "repeated_model_calls_are_new_sources": False,
            "authenticated_human_users": 0,
            "statistical_source_independence_established": False,
        },
        "evidence_boundaries": {
            "historical_maintainer_code_and_tests": True,
            "actual_native_before_after_execution": True,
            "original_historical_agent_trajectory": False,
            "new_student_trajectory_collected": False,
            "new_model_calls": 0,
            "new_training_updates": 0,
            "full_repository_test_suite": False,
            "future_unexposed_evaluation": False,
            "pretraining_overlap_known": False,
            "coding_learning_gain_established": False,
            "user_growth_established": False,
            "native_adoption": False,
        },
        "replay_cost": {
            "actual_owned_test_children": result["actual_owned_children"],
            "actual_test_case_executions": sum(
                row["tests"] for row in result["stages"]
            ),
            "before_failures": sum(row["before_failed"] for row in summaries),
            "after_passes": sum(row["after_passed"] for row in summaries),
            "before_case_timeouts": sum(
                row["case_timeouts_before"] for row in summaries
            ),
            "outer_child_timeouts": 0,
            "collection_errors": 0,
            "owner_wall_seconds": result["owner_wall_seconds"],
            "completed_child_cpu_seconds": result["completed_child_cpu_seconds"],
            "per_case_timeout_seconds": 3,
            "cold_setup_acquisition_wall_seconds_separate": acquisition["wall_seconds"],
            "acquisition_includes_dependency_setup": True,
            "per_child_wall_and_cpu_receipts": "replay-1/RESULT.json",
            "energy_joules": None,
            "monetary_cost": None,
            "full_system_cost_known": False,
            "overlap_note": "Acquisition and native replay are disjoint; nested setup, test child and download timings must not be added again.",
        },
        "packaging_adaptations": [
            "Exact upstream package and test bytes preserved; selected after-fix original tests executed on both revisions.",
            "Only selected original function parameter sets run; repository-wide conftest/plugins disabled via isolated pytest configuration.",
            "platformdirs.version and humanize._version generated packaging metadata supplied as explicitly logged ModuleType stubs; no behavior function replaced.",
            "Rich original unbounded loops are observed case failures under the same 3-second timeout before and after.",
            "A fresh isolated venv uses pinned, retained dependency wheels; no shared training environment or service changed.",
        ],
        "e5_continuation": {
            "source_sizes": plan["source_sizes"],
            "budget_regimes": plan["budget_regimes"],
            "one_source_selection": next(
                row["source_ids"]
                for row in plan["points"]
                if row.get("requested_sources") == 1 and row["regime"] == "fixed_total"
            ),
            "one_source_selection_reason": plan["selection_rule"],
            "fixed_total_planned_updates_for_1_and_4": [32, 32],
            "fixed_per_source_planned_updates_for_1_and_4": [32, 128],
            "actual_training_updates": 0,
            "sixteen_source_missing": 12,
            "sixty_four_source_missing": 60,
            "numeric_head_accuracy_is_coding_gain": False,
            "remaining_requirements": plan["remaining_execution_requirements"],
        },
        "historical_context": {
            "old_v3_six_file_groups_one_hepta_project_authenticated_users_zero": True,
            "new_pool_does_not_relabel_old_B_or_B2": True,
            "evaluation_repositories_excluded": json.loads(
                (root / "INTENT.json").read_bytes()
            )["excluded_evaluation_repositories"],
            "new_upstream_projects_selected_by_root_before_inspection": True,
        },
    }
    write(output / "READOUT.json", readout)
    write(output / "RESULTS.md", payload["results_md"].encode())
    root_files = [
        path for path in root.iterdir() if path.is_file() and not path.is_symlink()
    ]
    folders = [
        "upstream-api",
        "git-blobs",
        "repositories",
        "environment",
        "owned-setup-1",
        "replay-1",
        "material-entry-1",
        "runtime-evidence",
        "wheels",
    ]
    files = [(str(path.relative_to(root)), path) for path in root_files]
    for folder in folders:
        for path in sorted((root / folder).rglob("*")):
            if path.is_file():
                assert not path.is_symlink()
                files.append((str(path.relative_to(root)), path))
    files.extend(
        [
            ("READOUT.json", output / "READOUT.json"),
            ("RESULTS.md", output / "RESULTS.md"),
        ]
    )
    assert len(files) == len({name for name, _ in files})
    index = {
        "schema": "hepta.complete-original-evidence-index.v1",
        "scope": "all acquired upstream metadata, 83 Git blobs, both source/test/license snapshots, pinned dependency wheels, eight original pytest runs, source material entry and runtime statuses",
        "omitted_reconstructible_directories": ["venv", "pip-cache"],
        "omission_reason": "Installed/cache copies are redundant with retained exact wheels, pip-freeze and setup receipts. No model weights or model calls exist in this intake.",
        "files": [
            {
                "path": name,
                "bytes": path.stat().st_size,
                "sha256": sha(path.read_bytes()),
            }
            for name, path in sorted(files)
        ],
    }
    index_raw = write(output / "EVIDENCE_INDEX.json", index)
    archive = output / "complete-originals.tar.gz"
    with archive.open("xb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6
        ) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as tar:
                for name, path in sorted(files) + [
                    ("EVIDENCE_INDEX.json", output / "EVIDENCE_INDEX.json")
                ]:
                    data = path.read_bytes()
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime, info.uid, info.gid = (
                        len(data),
                        0o600,
                        0,
                        0,
                        0,
                    )
                    tar.addfile(info, io.BytesIO(data))
    archive_raw = archive.read_bytes()
    manifest = {
        "schema": "hepta.complete-original-evidence-archive.v1",
        "path": str(archive),
        "bytes": len(archive_raw),
        "sha256": sha(archive_raw),
        "index_sha256": sha(index_raw),
        "indexed_original_files": len(files),
        "archive_members_including_index": len(files) + 1,
        "readout_sha256": sha((output / "READOUT.json").read_bytes()),
        "result_sha256": sha(raw_result),
        "sources_sha256": sha(raw_sources),
        "actual_model_calls": 0,
        "actual_training_updates": 0,
    }
    write(output / "ARCHIVE_MANIFEST.json", manifest)
    write(
        output / "COLLECTOR_EXIT.json",
        {
            "status": "COMPLETE",
            "wall_seconds": time.perf_counter() - started,
            "archive_sha256": manifest["sha256"],
            "new_model_calls": 0,
            "new_native_test_executions": 0,
            "new_training_updates": 0,
        },
    )
    print(json.dumps(manifest, sort_keys=True), flush=True)


if __name__ == "__main__":
    import sys

    main(json.load(sys.stdin))
