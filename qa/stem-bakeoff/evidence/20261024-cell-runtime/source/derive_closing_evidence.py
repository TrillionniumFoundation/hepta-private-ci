"""Freeze the completed recovery receipts and their separate closing cost cutoff."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def derive(phase, index_path):
    phase = Path(phase)
    names = ["tests/combined-final-before-recovery.json", "recovery-helper-pin.json",
        "costs/ledger-v1.json", "costs/verification-v1.json", "costs/notes-v1.json",
        "audit/actual-queue-review.json", "audit/actual-queue-review-attempt-1.json",
        "audit/packager-applicability-review.json", "publication/published-13.json",
        "publication/published-14.json"]
    closing = ["facts-derivation", "cost-derivation-outer-1", "plot-generation", "commit-13", "commit-14",
        "source-fetch-13", "source-fetch-14", "source-alignment-13", "source-alignment-14",
        "archive-build-1", "recovery-outer-1", "archive-preflight", "archive-roots"]
    names += ["closing/"+name+".json" for name in closing]
    names += [path.relative_to(phase).as_posix() for path in sorted((phase/"closing/recovery-1").glob("*.json"))
              if path.name != "runtime-facts-rederived.json"]
    paths = {name: phase/name for name in names}
    paths["archive-index"] = Path(index_path)
    pins = {name: {"sha256": digest(path), "bytes": path.stat().st_size} for name, path in paths.items()}
    documents = {name: json.loads(path.read_bytes()) for name, path in paths.items()}
    recovery = documents["closing/recovery-1/recovery-summary.json"]
    gate = documents["tests/combined-final-before-recovery.json"]
    if (not recovery["passed"] or recovery["fresh_child_commands"] != 13
            or recovery["total_parameter_states_verified"] != 4032
            or gate["exit_code"] != 0 or "Ran 44 tests" not in gate["stderr"]):
        raise ValueError("required focused gate or relocated recovery is incomplete")
    index = documents["archive-index"]
    if (recovery["index_sha256"] != pins["archive-index"]["sha256"]
            or recovery["archive_sha256"] != index["archive_sha256"]
            or recovery["before"] != recovery["after"]
            or recovery["before"]["ordinary_files"] != index["file_count"]):
        raise ValueError("archive/recovery binding differs")
    activities = []

    def add(name, source, wall, cpu, scope):
        if any(value is not None and (type(value) is not int or value < 0) for value in (wall, cpu)):
            raise ValueError("measured integer ns or explicit unknown required")
        activities.append({"id": name, "source": source, "wall_ns": wall, "cpu_ns": cpu, "scope": scope})

    for name in ("facts-derivation", "cost-derivation-outer-1", "plot-generation", "commit-13", "commit-14",
                 "source-alignment-13", "source-alignment-14", "archive-build-1", "recovery-outer-1"):
        source = "closing/"+name+".json"
        item = documents[source]
        if item.get("exit_code", 0) != 0:
            raise ValueError("closing command failed: " + name)
        add(name, source, item["wall_ns"], item["parent_cpu_ns"]+item["child_cpu_ns"],
            "Complete recorded outer process tree only; nested child/component costs are not added.")
    for name in ("source-fetch-13", "source-fetch-14"):
        source = "closing/"+name+".json"
        item = documents[source]
        add(name, source, item["wall_ns"], item["cpu_ns"], item["scope"])
    for name in ("actual-queue-review", "packager-applicability-review"):
        source = "audit/"+name+".json"
        item = documents[source]
        add(name, source, item["wall_ns_before_serialization"], item["parent_cpu_ns_before_serialization"]+item["child_cpu_ns"],
            "One read-only audit, before its own receipt serialization; no model calls.")
    source = "audit/actual-queue-review.json"
    correction = documents[source]["metadata_correction"]
    add("queue-audit-metadata-correction", source, correction["wall_ns_before_reserialization"],
        correction["parent_cpu_ns_before_reserialization"], "Small metadata-only correction; original audit interval charged once.")
    source = "publication/published-13.json"
    add("publication-13", source, documents[source]["wall_ns"], None,
        "Recorded API orchestration interval including stage payload read; CPU unavailable.")
    source = "publication/published-14.json"
    item = documents[source]
    for name, field in (("publication-14-tree-commit-ref", "api_tree_commit_ref_wall_ns"),
                        ("publication-14-figure-blob", "api_blob_wall_ns"),
                        ("publication-14-failed-git-push", "failed_git_push_wall_ns")):
        add(name, source, item[field], None, "Disjoint recorded tool/API wall interval; CPU unavailable; failed work retained.")
    add("other-closing-work", None, None, None,
        "Unmetered preflight, image chunk reads, inspections, review/editing and orchestration not covered by recorded intervals; not zero.")
    totals = {unit: {"sum_measured": sum(item[unit] for item in activities if item[unit] is not None),
                     "unmeasured_components": [item["id"] for item in activities if item[unit] is None]}
              for unit in ("wall_ns", "cpu_ns")}
    main = documents["costs/ledger-v1.json"]["measured_work_totals"]
    if main != documents["costs/verification-v1.json"]["independent_raw_source_totals"]:
        raise ValueError("primary cost cutoff differs")
    if any(digest(paths[name]) != pin["sha256"] for name, pin in pins.items()):
        raise ValueError("closing source changed during derivation")
    return {"schema": "hepta.runtime-770-closing-evidence.v1", "source_pins": pins,
        "receipts": documents, "recovery": recovery, "unique_focused_tests": 44,
        "main_measured_work_totals": main, "closing_activities": activities,
        "closing_measured_work_totals": totals,
        "combined_known_wall_ns": main["wall_ns"]["sum_measured"]+totals["wall_ns"]["sum_measured"],
        "combined_known_cpu_ns": main["cpu_ns"]["sum_measured"]+totals["cpu_ns"]["sum_measured"],
        "cost_scope": "Known disjoint work only. Wall sums are work, not concurrent elapsed; unknowns are not zero. Controller includes all13 child processes and inventories.",
        "excluded_terminal_work": ["this derivation process and self-serialization", "report source commits15 and later",
                                   "final formatting", "later source publication and alignment", "terminal delivery receipt"],
        "archive_scope": "Archive frozen before build/recovery; closing receipts are preserved here without recursively rebuilding raw data.",
        "local_engineering_gates_passed": True, "native_production_integrated": False,
        "new_quality_evidence": False, "remote_ci_consulted": False,
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "quality_qualified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("phase", "archive-index", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    result = derive(args.phase, args.archive_index)
    with Path(args.output).open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("closing_measured_work_totals", "combined_known_wall_ns", "combined_known_cpu_ns")}))
