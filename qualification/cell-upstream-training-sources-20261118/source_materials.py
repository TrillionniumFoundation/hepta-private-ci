"""Load four pinned upstream repair materials and emit the original E5 source schedule.

This module does not create model trajectories, features, class labels, or training
updates. Its inputs are exact upstream files and actual native regression receipts.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

SIZES = (1, 4, 16, 64)
MODES = ("fixed_total", "fixed_per_source")
SOURCES_SHA256 = "686f1d77e274486034044ead9ec1b5db25c98c87b530264e1128766da785d0fa"
REPLAY_SHA256 = "41388e7d6a7afd5e9a9c7b288dd428bc393a09d2e208228253bd7ef61b398240"
EXPECTED_PROJECTS = (
    "python-attrs/attrs",
    "Textualize/rich",
    "tox-dev/platformdirs",
    "python-humanize/humanize",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_bound(root, path, expected):
    path = Path(path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("relative material path required")
    target = root / path
    if target.is_symlink() or not target.resolve(strict=True).is_relative_to(root):
        raise ValueError("material path leaves its root")
    raw = target.read_bytes()
    if sha(raw) != expected:
        raise ValueError("material digest differs: " + str(path))
    return raw


def reference(root, path):
    raw = (root / path).read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def load_materials(directory):
    """Return real repair transitions; these are not prepared-v3 model tasks."""
    root = Path(directory).resolve(strict=True)
    catalog = json.loads(read_bound(root, "SOURCES.json", SOURCES_SHA256))
    replay = json.loads(read_bound(root, "replay-1/RESULT.json", REPLAY_SHA256))
    if tuple(row["project_id"] for row in catalog["sources"]) != EXPECTED_PROJECTS:
        raise ValueError("frozen project panel differs")
    identities, organizations, observations, materials = set(), set(), set(), []
    for source in catalog["sources"]:
        project, source_id = source["project_id"], source["source_id"]
        if source_id in identities:
            raise ValueError("duplicate upstream lineage")
        identities.add(source_id)
        organizations.add(source["owner"]["id"])
        if source["license"]["spdx_id"] != "MIT" or not source["authorization"]["training_allowed"]:
            raise ValueError("missing frozen source authorization")
        if source["authenticated_user_count"] != 0 or source["original_model_trajectory_available"]:
            raise ValueError("upstream material relabeled as authenticated user trajectory")
        short = project.split("/")[-1]
        prefix = Path("repositories") / short
        bound_files, patches = [], []
        for item in source["source_files"]:
            contents = {}
            for variant in ("before", "after"):
                path = prefix / variant / item["path"]
                raw = read_bound(root, path, item[variant]["sha256"])
                if len(raw) != item[variant]["bytes"]:
                    raise ValueError("upstream file size differs")
                blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                if blob != item[variant]["git_blob_sha1"]:
                    raise ValueError("upstream Git blob identity differs")
                contents[variant] = raw
            bound_files.append({"path": item["path"], "before": item["before"], "after": item["after"]})
            if item["path"].endswith(".py") and not item["path"].startswith("tests/") and contents["before"] != contents["after"]:
                patch = "".join(difflib.unified_diff(
                    contents["before"].decode().splitlines(keepends=True),
                    contents["after"].decode().splitlines(keepends=True),
                    fromfile="a/" + item["path"], tofile="b/" + item["path"], n=3))
                patches.append({"path": item["path"], "unified_diff": patch,
                    "sha256": sha(patch.encode()), "construction": "deterministic diff of exact before/after Git blobs"})
        read_bound(root, prefix / "after" / source["license"]["path"], source["license"]["sha256"])
        rows = [row for row in replay["stages"] if row["project_id"] == project]
        if len(rows) != 2 or [row["variant"] for row in rows] != ["before", "after"]:
            raise ValueError("one actual prior/fixed replay pair required")
        prior, fixed = rows
        if not (prior["wait_returncode"] == 1 and prior["failures"] > 0 and prior["errors"] == 0
                and fixed["wait_returncode"] == 0 and fixed["failures"] == fixed["errors"] == 0
                and prior["tests"] == fixed["tests"] and not prior["timed_out"] and not fixed["timed_out"]):
            raise ValueError("original regression difference not established")
        if [row["name"] for row in prior["cases"]] != [row["name"] for row in fixed["cases"]]:
            raise ValueError("before/after original case sets differ")
        receipts = {}
        for row in rows:
            variant = row["variant"]
            folder = Path("replay-1") / (short + "-" + variant)
            for name, key in (("STDOUT.txt", "stdout_sha256"), ("STDERR.txt", "stderr_sha256"), ("junit.xml", "junit_sha256")):
                read_bound(root, folder / name, row[key])
            exit_receipt = reference(root, folder / "EXIT.json")
            if json.loads((root / exit_receipt["path"]).read_bytes()) != row:
                raise ValueError("owner result and original exit receipt differ")
            receipts[variant] = {
                "exit": exit_receipt,
                "pytest_intent": reference(root, folder / "PYTEST_INTENT.json"),
                "pytest_return": reference(root, folder / "PYTEST_RETURN.json"),
                "stdout": reference(root, folder / "STDOUT.txt"),
                "stderr": reference(root, folder / "STDERR.txt"),
                "junit": reference(root, folder / "junit.xml"),
                "passed": row["passed"], "failed": row["failures"],
                "case_timeouts": sum("Timeout" in (case["failure_type"] or "") for case in row["cases"]),
                "failed_case_names": [case["name"] for case in row["cases"] if case["failure_type"]],
                "actual_child_wait_returncode": row["wait_returncode"],
            }
        observation = sha(canonical({"before_commit": source["before_commit"],
            "selected_tests": source["selected_tests"], "files": bound_files}))
        if observation in observations:
            raise ValueError("same observation relabeled as another source")
        observations.add(observation)
        materials.append({
            "schema": "hepta.upstream-repair-material.v1",
            "source_id": source_id, "project_id": project, "lineage_id": source["lineage_id"],
            "repository_id": source["repository_id"], "owner": source["owner"],
            "original_author_account": source["original_author_account"],
            "request_url": source["request_url"],
            "original_created_at": source["created_at"], "original_merged_at": source["merged_at"],
            "before_commit": source["before_commit"], "after_commit": source["after_commit"],
            "observed_replay_at_ns": json.loads((root / "replay-1/FREEZE.json").read_bytes())["started_at_ns"],
            "observation_digest": observation, "source_kind": source["source_kind"],
            "split": "train", "exposure": "development", "future_task": False,
            "authenticated_user_count": 0, "original_model_trajectory_available": False,
            "pretraining_overlap_known": False, "authorization": source["authorization"],
            "license": source["license"], "package_import_root": source["package_import_root"],
            "package_prefix": str(prefix), "source_files": bound_files,
            "original_regression": source["selected_tests"],
            "repair_patches": patches, "actual_native_receipts": receipts,
            "declared_generated_packaging_metadata": {
                variant: json.loads((root / receipts[variant]["pytest_return"]["path"]).read_bytes())["generated_packaging_metadata_only"]
                for variant in ("before", "after")},
            "material_scope": "historical maintainer fix with newly observed native before/after execution; no historical agent reasoning/actions asserted",
        })
    if len(organizations) != 4 or len(observations) != 4:
        raise ValueError("four distinct project/organization observations required")
    return materials


def growth_schedule(materials, units_per_source=32):
    """Use composition.py's sizes, regimes and lexical prefix source selection."""
    if type(units_per_source) is not int or units_per_source < 4 or units_per_source % 4:
        raise ValueError("positive budget divisible by four required")
    ordered = sorted(materials, key=lambda row: row["source_id"])
    points = []
    for mode in MODES:
        for size in SIZES:
            point = {"regime": mode, "requested_sources": size, "available_sources": len(ordered),
                     "authenticated_user_count": 0, "actual_training_updates": 0}
            if size > len(ordered):
                point.update(status="BLOCKED_SOURCE_COUNT", missing_sources=size - len(ordered))
            else:
                selected = ordered[:size]
                count = units_per_source * (size if mode == "fixed_per_source" else 1)
                point.update(status="SOURCE_MATERIAL_READY_TRAINING_NOT_EXECUTED",
                    source_ids=[row["source_id"] for row in selected],
                    unique_repair_lineages=size,
                    planned_update_units=count,
                    planned_update_units_per_source=count // size,
                    schedule=[selected[index % size]["source_id"] for index in range(count)],
                    composition_numeric_passes=count // size,
                    composition_numeric_max_examples=count,
                    repeated_exposures_are_new_sources=False,
                    actual_compute_match_established=False,
                    token_mac_and_verifier_budgets_frozen=False)
            points.append(point)
    return points


def materialize(directory, output):
    root, output = Path(directory).resolve(strict=True), Path(output)
    materials = load_materials(root)
    schedule = growth_schedule(materials)
    output.mkdir(exist_ok=False)
    raw = b"".join(canonical(row) + b"\n" for row in materials)
    (output / "MATERIALS.jsonl").write_bytes(raw)
    plan = {
        "schema": "hepta.upstream-source-growth-entry.v1",
        "material_sha256": sha(raw), "material_records": len(materials),
        "source_inventory_sha256": SOURCES_SHA256, "native_replay_sha256": REPLAY_SHA256,
        "source_sizes": list(SIZES), "budget_regimes": list(MODES),
        "selection_rule": "same lexically sorted source_id prefix as existing composition.py; fixed before any new training or model call",
        "budget_unit": "planned update on one real repair material; repeat exposure is not source novelty",
        "points": schedule,
        "new_model_calls": 0, "new_training_updates": 0,
        "E1_entry": "Use exact before/after repair files, MIT notice, original tests and receipt-bound observations as A-only material. Compare frozen/retrieval/answer-SFT/actual-model-trajectory-SFT only after same candidate, rendering, tokenizer and actual budgets are frozen.",
        "E2_entry": "Execute the frozen current student on these training tasks and retain its own actions and native feedback before any corrective update. These maintainer transitions cannot substitute for student experience.",
        "E5_entry": "1/4-source schedules are concrete; 16/64 lack 12/60 additional project lineages. Future evaluation must use fresh tasks outside these projects and retain NoUpdate.",
        "numeric_composition_scope": "The existing composition.py trains a small classifier on frozen numeric preaction features and supplied class labels. No such features/labels are fabricated here; its accuracy would not establish coding ability.",
        "remaining_execution_requirements": [
            "Freeze a coding task renderer and candidate interpreter/verifier before collecting new model trajectories; original code/tests remain authoritative.",
            "Freeze initialization, tokenizer, optimizer, padded tokens, target-token masks and actual update counts across arms; caps alone are insufficient.",
            "Freeze fresh source-separated future selection/confirmation tasks; old B and B2 are exposed diagnostics and cannot supply new source choices.",
            "For numeric composition only, collect actual frozen preaction features, named class targets and model/verifier receipts; do not turn source identity into an outcome label.",
            "Authenticated real-user sources remain zero; external custody and pretraining contamination remain unresolved."
        ],
        "independent_user_growth_qualified": False,
        "coding_learning_gain_established": False,
        "native_adoption": False,
    }
    (output / "SOURCE_GROWTH_PROTOCOL.json").write_bytes(json.dumps(plan, sort_keys=True, indent=2).encode() + b"\n")
    print(json.dumps({"material_records": len(materials), "material_sha256": sha(raw),
        "protocol_sha256": sha((output / "SOURCE_GROWTH_PROTOCOL.json").read_bytes()),
        "new_model_calls": 0, "new_training_updates": 0}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    materialize(args.root, args.output)
