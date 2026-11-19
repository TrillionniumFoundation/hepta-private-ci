"""Prepare explicit, disjoint final bundle file lists after their owners finish.

This helper never starts sealing or training. It excludes live/recursive
outputs, checks final readiness, hashes files in bounded blocks, and removes
only byte-identical coverage already certified by a formal bundle manifest.
The resulting list is an input to one independent seal_bundle.py invocation.
"""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback

from .archive_closure import PACKAGE, file_hash, member_map, merge_members, read_json, require, write_new
from .archive_closure_final import ClosureAudit


NAMES = ("lif_supplement001_evidence", "content002_metadata", "v2_auxiliary_evidence")
ROOT_DIRECT_GIT = {"README.md", "final_report.py", "campaign_costs.py", "CAMPAIGN_COSTS.md",
                   "archive_closure.py", "ARCHIVE_CLOSURE.md", "archive_closure_final.py", "ARCHIVE_CLOSURE_FINAL.md"}
LIF_ROOT = {"LIF_SUPPLEMENT001_PROTOCOL.json", "LIF_COST_BINDINGS_TEMPLATE.json", "lif_supplement.py",
            "lif_supplement_analysis.py", "lif_cost_receipts.py"}
MAIN_ROOT = {"CONTENT002_PROTOCOL.json", "CONTENT.md", "model.py", "content_training.py", "content_study.py",
             "content_analysis.py", "content_checkpoint_archives.py", "CHECKPOINT_ARCHIVES.md",
             "CONTENT_SUPPLEMENT001_PROTOCOL.json", "content_supplemental_analysis.py"}


def exclusion(relative):
    parts = Path(relative).parts
    if not parts:
        return "empty path"
    if parts[0] == "artifacts":
        return "formal compressed bundles and closure are separate artifacts"
    if "work" in parts:
        return "internal staging work tree"
    if "__pycache__" in parts or relative.endswith(".pyc"):
        return "interpreter cache"
    if relative in ROOT_DIRECT_GIT:
        return "canonical root reporting/cost/closure source or README published directly in Git"
    if parts[-1] == "watcher.lock" or parts[-1].endswith(".tmp"):
        return "coordination lock or incomplete temporary output"
    if len(parts) > 1 and parts[0] == "results":
        if parts[1] == "final_bundle_plans":
            return "planner's own metadata is published outside payloads to avoid recursion"
        if re.fullmatch(r"(?:archive_closure|campaign_costs|campaign_costs_final|final_costs|final_report)[0-9]+(?:_execution)?(?:\..*)?", parts[1]):
            return "final closure/cost/report output or enclosing execution, published separately"
        if parts[1] == "evidence_sealing" and len(parts) > 2 and parts[2] == "v2_auxiliary_evidence":
            return "auxiliary bundle's own sealing receipts cannot be included recursively"
    if len(parts) > 1 and parts[0] == "reproduction_receipts" and parts[1].startswith("final_catalog"):
        return "catalog produced after final sealing, published separately"
    return None


def group(relative):
    parts = Path(relative).parts
    if relative in LIF_ROOT or (len(parts) > 1 and parts[0] == "results"
            and (parts[1].startswith("lif_") or parts[1] == "content_lif_review001.json")):
        return "lif_supplement001_evidence"
    if relative in MAIN_ROOT or (len(parts) > 1 and parts[0] == "results"
            and (parts[1] == "content002" or parts[1].startswith("content_analysis002")
                 or parts[1] in ("content_supplement001", "content_supplement_preflight001")
                 or parts[1].startswith("content_analysis_supplement001")
                 or parts[1] == "content_checkpoint_archives")):
        return "content002_metadata"
    return "v2_auxiliary_evidence"


def coverage(package):
    union, owners, manifests = {}, {}, []
    for path in sorted((package / "artifacts").rglob("*.json")):
        record = read_json(path)
        if record.get("schema") != "hcsn-evidence-bundle.v1":
            continue
        seal_path = path.with_name(record["name"] + "_EXECUTION.json")
        seal = read_json(seal_path)
        members = member_map(record["members"])
        require(seal["name"] == record["name"] and seal["archive_sha256"] == record["archive_sha256"]
                and seal["verified_restore"] == dict(archive_sha256=record["archive_sha256"],
                                                     restored_or_already_identical=len(members)),
                "Unverified formal bundle cannot determine existing coverage")
        merge_members(union, members, owners, record["name"])
        manifests.append(dict(name=record["name"], path=str(path.relative_to(package)), sha256=file_hash(path)))
    return union, manifests


def completed_support(package, relative):
    receipt = read_json(package / relative)
    require(receipt["schema"] == "hcsn-measured-support-execution.v1"
            and receipt["status"] == "completed" and receipt["returncode"] == 0,
            "Support process is not complete: " + relative)
    return dict(path=relative, sha256=file_hash(package / relative))


def readiness(package, name):
    # This only checks immutable audit metadata and source identities. It does
    # not evaluate quality values, rebuild models, or start any analysis.
    auditor = ClosureAudit(package)
    _, _, _, proofs = auditor.prerequisites()
    proofs["normalizer_outer"] = completed_support(package, "results/lif_cost_normalization001/EXECUTION.json")
    if name in ("content002_metadata", "v2_auxiliary_evidence"):
        state = package / "results/content_checkpoint_archives"
        status = read_json(state / "STATUS.json")
        require(status["status"] == "completed" and status["covered"] == 176, "Checkpoint watcher is still active")
        receipt_path = state / "instances" / (status["instance"] + "_EXECUTION.json")
        execution = read_json(receipt_path)
        require(execution["status"] == "completed", "Checkpoint watcher has not written its final self receipt")
        proofs["checkpoint_watcher_final"] = dict(path=str(receipt_path.relative_to(package)), sha256=file_hash(receipt_path))
    if name == "v2_auxiliary_evidence":
        _, existing = coverage(package)
        require({"lif_supplement001_evidence", "content002_metadata"} <= {record["name"] for record in existing},
                "Auxiliary bundle must follow both main metadata and LIF evidence bundles")
        scaling = auditor.audit_scaling()
        proofs.update(scaling["proofs"])
        figures = package / "results/figures002"
        manifest = read_json(figures / "MANIFEST.json")
        require(manifest["schema"] == "hcsn-evidence-figures.v1" and manifest["outputs"], "Final figures are incomplete")
        require(manifest["source_sha256"] == file_hash(package / "evidence_figures.py"), "Final figure source changed")
        for filename, expected in manifest["outputs"].items():
            path = figures / filename
            require(path.parent == figures and path.is_file() and file_hash(path) == expected, "Final figure output hash mismatch")
        proofs["figures_manifest"] = dict(path="results/figures002/MANIFEST.json", sha256=file_hash(figures / "MANIFEST.json"))
        proofs["figures_outer"] = completed_support(package, "results/figures002_execution/EXECUTION.json")
    return proofs


def inventory(package):
    excluded = {}
    files = []
    for root, directories, names in os.walk(package):
        relative_root = Path(root).relative_to(package)
        keep = []
        for name in sorted(directories):
            path = Path(root) / name
            relative = str((relative_root / name))
            require(not path.is_symlink(), "Evidence directory is a symlink: " + relative)
            reason = exclusion(relative)
            if reason:
                excluded[relative + "/"] = reason
            else:
                keep.append(name)
        directories[:] = keep
        for name in sorted(names):
            path = Path(root) / name
            relative = str(path.relative_to(package))
            reason = exclusion(relative)
            if reason:
                excluded[relative] = reason
                continue
            require(path.is_file() and not path.is_symlink(), "Expected regular immutable evidence: " + relative)
            files.append((relative, path))
    return files, excluded


def prepare(name, package, output):
    package, output = Path(package).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    status, error = "failed", None
    try:
        require(name in NAMES, "Unknown final bundle")
        require(not (package / "artifacts" / (name + ".json")).exists(), "Final bundle is already sealed")
        proofs = readiness(package, name)
        covered, manifests = coverage(package)
        available, exclusions = inventory(package)
        selected, covered_count, skipped_other_groups = {}, 0, 0
        for relative, path in available:
            assigned = group(relative)
            if name != "v2_auxiliary_evidence" and assigned != name:
                skipped_other_groups += 1
                continue
            actual = dict(path=relative, bytes=path.stat().st_size, sha256=file_hash(path))
            if relative in covered:
                require(covered[relative] == actual, "Previously sealed file changed: " + relative)
                covered_count += 1
                continue
            require(not relative.startswith("results/content002/runs/")
                    and not relative.startswith("results/content002/process_logs/"),
                    "Main worker evidence is missing from completed checkpoint bundles: " + relative)
            if name == "v2_auxiliary_evidence":
                require(assigned not in ("lif_supplement001_evidence", "content002_metadata"),
                        "A prior final bundle omitted or acquired new evidence: " + relative)
            selected[relative] = actual
        require(bool(selected), "No uncovered files selected")
        includes = sorted(selected)
        estimated_argv_bytes = sum(len(path.encode()) + len("--include") + 2 for path in includes)
        arg_max = os.sysconf("SC_ARG_MAX")
        require(estimated_argv_bytes < arg_max // 2, "Explicit child include arguments exceed conservative system argv budget")
        write_new(output / "INCLUDES.json", includes)
        record = dict(schema="hcsn-final-bundle-plan.v1", status="ready", bundle_name=name,
            includes=includes, members=[selected[path] for path in includes],
            include_list_sha256=file_hash(output / "INCLUDES.json"), selected_files=len(includes),
            selected_bytes=sum(item["bytes"] for item in selected.values()), covered_files_skipped=covered_count,
            other_groups_skipped=skipped_other_groups, excluded=exclusions, prerequisite_proofs=proofs,
            existing_manifests=manifests, estimated_include_argv_bytes=estimated_argv_bytes, system_arg_max=arg_max,
            source_sha256=file_hash(__file__), selection_rule="All eligible uncovered immutable paths; no score or outcome filtering",
            sealing_command=[sys.executable, "-m", "experiments.hcsn_distributional_v2.seal_bundle", "--name", name,
                             "--include-file", str(output / "INCLUDES.json")])
        write_new(output / "PLAN.json", record)
        status = "ready"
        print(json.dumps({key: record[key] for key in ("status", "bundle_name", "selected_files", "selected_bytes", "include_list_sha256")}))
        return record
    except BaseException:
        error = traceback.format_exc()
        raise
    finally:
        write_new(output / "EXECUTION.json", dict(schema="hcsn-final-bundle-plan-execution.v1", status=status,
            own_cpu_seconds_through_receipt=time.process_time(), wall_seconds=time.perf_counter()-started,
            source_sha256=file_hash(__file__), error=error,
            scope="This read-only plan process only; no sealing children. Parent clock and later wrapper/archive clocks are separate scopes."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", choices=NAMES, required=True)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.bundle, args.package, args.output)
