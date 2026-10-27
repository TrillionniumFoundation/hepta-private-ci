"""Enumerate a terminal V4 evidence package without copying raw inputs.

Requires an explicit terminal-authorized configuration. Do not invoke while
training, evaluation, audits or the mechanism report are still running.
Every V4 raw file is retained; only caches and named archive-self receipts
are excluded. The builder independently rechecks this complete identity list.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import time

sys.dont_write_bytecode = True
from archive_integrity_v4 import canonical, file_sha, require, safe_name, strict_json, validate_manifest
from archive_reanalysis_v4 import required_members

PREFIX = "hepta.field-bridge.v4"
BASE = "repository/experiments/multimodal_output_portfolio/"
SCIENCE = "field_bridge_v4_20261027"
REVIEW = "field_bridge_v4_20261027_review"
SEEDS = (17, 29, 43)
METHODS = ("ordinary_0", "ordinary_1", "ordinary_2", "ordinary_3", "raw_field",
           "origin_field", "origin_generic", "origin_richer", "origin_h7")
SCHEDULES = (14000, 14001, 14002, 14003)
SELF_RECEIPTS = {
    "ARCHIVE_INPUTS.json", "ARCHIVE_INPUTS.json.gz", "ARCHIVE_SELECTIVE_RESTORE.json",
    "ARCHIVE_BUILD_RECEIPT.json", "ARCHIVE_INTEGRITY.json", "ARCHIVE_REANALYSIS.json",
    "ARCHIVE_AND_RESTORE_VERIFICATION.json", "EVIDENCE_ARCHIVE.json",
    "ARCHIVE_PLAN_RECEIPT.json", "ARCHIVE_STORAGE_PLAN.json", "ARCHIVE_COVERAGE.json",
}
TOOLS = ("archive_plan_v4.py", "archive_build_v4.py", "archive_integrity_v4.py", "archive_reanalysis_v4.py", "archive_reanalysis_bindings_v4.py")
SCOPE = ("Complete terminal V4 raw execution, original restored assets, all frozen inputs and source bindings; "
         "exact archived statistical replay. Earlier V1-V3 generated histories and large prior archives are "
         "referenced by identity, not nested. This is not a complete historical model-training rerun.")


def json_file(path):
    return strict_json(Path(path).read_bytes())


def exclude_reason(path, member):
    if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
        return "reproducible Python bytecode/cache"
    if path.name in SELF_RECEIPTS and (member.startswith("run/") or member.startswith(BASE + SCIENCE + "/")
                                      or member.startswith(BASE + REVIEW + "/")):
        return "archive-self or postpackage receipt; excluded to avoid self-reference"
    return None


class Collection:
    def __init__(self):
        self.entries, self.expected, self.exclusions, self.trees = {}, {}, [], []

    def add(self, source, member, expected=None):
        source, member = Path(source), safe_name(member)
        require(source.is_absolute() and not source.is_symlink() and source.is_file(),
                "Missing or nonregular explicit archive input: " + str(source))
        source = source.resolve()
        require(not source.name.lower().endswith((".tar", ".tar.gz", ".tgz")),
                "Nested archives are not payload inputs; register a prior archive reference instead")
        previous = self.entries.get(member)
        require(previous is None or previous == str(source), "Conflicting source for archive path: " + member)
        self.entries[member] = str(source)
        if expected is not None:
            require(member not in self.expected or self.expected[member] == expected, "Conflicting identity: " + member)
            self.expected[member] = expected

    def names(self, root, prefix, record_exclusions=False):
        root = Path(root).resolve()
        require(root.is_dir() and not root.is_symlink(), "Missing declared source tree: " + str(root))
        result = {}
        for source in sorted(root.rglob("*")):
            require(not source.is_symlink(), "Symlink in evidence tree: " + str(source))
            if not source.is_file():
                continue
            member = prefix.rstrip("/") + "/" + source.relative_to(root).as_posix()
            reason = exclude_reason(source, member)
            if reason:
                if record_exclusions:
                    self.exclusions.append({"source": str(source), "path": member, "bytes": source.stat().st_size,
                                            "reason": reason})
                continue
            result[member] = str(source)
        return result

    def tree(self, root, prefix):
        values = self.names(root, prefix, True)
        for member, source in values.items():
            self.add(Path(source), member)
        self.trees.append((Path(root), prefix, values))

    def identities(self):
        result = []
        for member, source in sorted(self.entries.items()):
            path = Path(source)
            before = path.stat()
            identity = file_sha(path)
            after = path.stat()
            require((before.st_ino, before.st_size, before.st_mtime_ns) ==
                    (after.st_ino, after.st_size, after.st_mtime_ns), "Input changed while planning: " + source)
            require(member not in self.expected or identity == self.expected[member], "Frozen input differs: " + member)
            result.append({"path": member, "bytes": before.st_size, "sha256": identity})
        for root, prefix, before in self.trees:
            require(self.names(root, prefix) == before, "Evidence tree changed while enumerating: " + str(root))
        return result


def bind_complete(collection, root, relative):
    complete = json_file(root / relative / "COMPLETE.json")
    require(isinstance(complete.get("files"), dict) and complete["files"], "Missing completed evidence inventory")
    for name, identity in complete["files"].items():
        safe_name("run/" + relative + "/" + name)
        collection.add(root / relative / name, "run/" + relative + "/" + name, identity)
    return complete


def require_terminal_run(config, collection, run, protocol):
    require(config["terminal_access_authorized"] is True, "Terminal root authorization has not been supplied")
    mandatory = ("TRAINING_SEAL.json", "QUALIFICATION.json", "V4_EXECUTION_LEDGER.json", "STUDY_DISPOSITION.json")
    require(all((run / name).is_file() for name in mandatory), "Required terminal study receipts are not complete")
    require(not (run / "QUALIFICATION_FAILED.json").exists(), "Statistical execution did not complete")
    for seed in SEEDS:
        for phase in ("train", "evaluate"):
            relative = f"{phase}/{seed}"
            record = bind_complete(collection, run, relative)
            require(record["study_id"] == protocol["study_id"] and record["seed"] == seed,
                    "Terminal phase belongs to another study/model")
            expected = {f"{method}/schedule-{sid}" for method in METHODS for sid in SCHEDULES}
            require(set(record["paths"]) == expected, "Incomplete 36-path phase: " + relative)
            for path in expected:
                bind_complete(collection, run, relative + "/" + path)
        for name in (f"PHASE_RECEIPTS/train-{seed}.json", f"PHASE_RECEIPTS/evaluate-{seed}.json"):
            require((run / name).is_file(), "Missing successful phase-end receipt: " + name)
    seal = json_file(run / "TRAINING_SEAL.json")
    require(seal["study_id"] == protocol["study_id"] and seal["paths"] == 108, "Incomplete all-path training seal")
    for name, identity in seal["files"].items():
        collection.add(run / name, "run/" + name, identity)
    media = [f"run/evaluate/{seed}/original-{panel}.npz" for seed in SEEDS for panel in ("task", "clean")]
    media += [f"run/evaluate/{seed}/{method}/schedule-{sid}/{panel}.npz"
              for seed in SEEDS for method in METHODS for sid in SCHEDULES for panel in ("task", "clean")]
    checkpoints = [f"run/train/{seed}/{method}/schedule-{sid}/checkpoint.pt"
                   for seed in SEEDS for method in METHODS for sid in SCHEDULES]
    traces = [name.removesuffix("checkpoint.pt") + "decisions-and-outcomes.jsonl.gz" for name in checkpoints]
    require(len(media) == 222 and all(name in collection.entries for name in (*media, *checkpoints, *traces)),
            "A V4 media, checkpoint, or full trajectory would be omitted")
    # The mechanism stage is required to finish before preservation, but its numbers are not reanalyzed here.
    mechanism = list(run.rglob("MECHANISM.json"))
    require(len(mechanism) == 1 and mechanism[0].with_suffix(".md").is_file(), "Completed mechanism report is required")
    return mandatory, {"media_files": len(media), "checkpoints": len(checkpoints), "full_trace_files": len(traces)}


def collect(config_path):
    started = time.perf_counter_ns()
    config_path = Path(config_path).resolve()
    config = json_file(config_path)
    require(config.get("schema") == PREFIX + ".archive-collection-config.1"
            and config.get("terminal_access_authorized") is True,
            "No terminal archive authorization; refusing to inspect run data")
    require(config.get("library_upload_authorized", False) is False, "This tool performs no upload")
    repo, run, old, freezes, assets = [Path(config[key]).resolve() for key in
        ("repository_root", "run_root", "old_run_root", "freezes_root", "assets_root")]
    require(run != old and all(path.is_dir() for path in (repo, run, old, freezes, assets)), "Missing or aliased source roots")
    portfolio = repo / "experiments/multimodal_output_portfolio"
    protocol_path = portfolio / SCIENCE / "PROTOCOL.json"
    protocol = json_file(protocol_path)
    require(protocol["study_id"] == config["study_id"] and protocol["seeds"] == list(SEEDS), "Wrong V4 terminal study")
    require(protocol["qualification"]["methods"] == list(METHODS)
            and protocol["qualification"]["schedule_ids"] == list(SCHEDULES), "Wrong path inventory")
    collection = Collection()
    collection.tree(run, "run")
    for name in (SCIENCE, REVIEW):
        collection.tree(portfolio / name, BASE + name)
    collection.tree(freezes, "freezes")
    collection.add(config_path, "operations/ARCHIVE_COLLECTION_CONFIG.json")
    mandatory, coverage = require_terminal_run(config, collection, run, protocol)

    training_path = freezes / "TRAINING_FREEZE.json"
    training = json_file(training_path)
    require(training["study_id"] == protocol["study_id"] and training["protocol_sha256"] == file_sha(protocol_path)
            and len(training["source_files"]) == 58 and len(training["old_artifacts"]) == 25, "Initial registered inputs differ")
    source_bindings, receipts, commits, executed_freezes = {}, {}, set(), []
    freeze_objects = []
    for path in sorted(freezes.rglob("*.json")):
        record = json_file(path)
        if isinstance(record, dict) and {"source_files", "old_artifacts", "protocol_sha256", "registered_commit"} <= record.keys():
            if record["protocol_sha256"] == training["protocol_sha256"] and record.get("study_id") == protocol["study_id"]:
                freeze_objects.append((path, record))
    require(any(path == training_path for path, _ in freeze_objects), "Training freeze was not collected")
    for path, record in freeze_objects:
        require(re.fullmatch(r"[0-9a-f]{40}", record["registered_commit"]) is not None, "Invalid committed source identity")
        commits.add(record["registered_commit"])
        member = "freezes/" + path.relative_to(freezes).as_posix()
        receipts[member] = file_sha(path); executed_freezes.append(member)
        for name, identity in record["source_files"].items():
            collection.add(portfolio / name, BASE + name, identity)
            require(BASE + name not in source_bindings or source_bindings[BASE + name] == identity,
                    "Conflicting phase source versions require explicit historical snapshot handling")
            source_bindings[BASE + name] = identity
        for name, identity in record["old_artifacts"].items():
            collection.add(old / name, "legacy/v3-run/" + name, identity)
        for name, identity in record.get("artifacts", {}).items():
            collection.add(run / name, "run/" + name, identity)

    # Preserve full old allocation identities, not merely a statement of freshness.
    allocation = json_file(portfolio / SCIENCE / "SOURCE_ALLOCATION.json")
    prior = allocation["prior_allocations"]
    collection.add(Path(config["v2_registry"]).resolve(), "legacy/v2-source-identity/SOURCE_IDENTITIES.json",
                   prior["v2_registry_sha256"])
    old_allocation = portfolio / "field_bridge_v3_20261027/SOURCE_ALLOCATION.json"
    old_registry = old_allocation.with_name("SOURCE_IDENTITIES.json.gz")
    old_manifest = json_file(old_allocation)
    require(old_manifest["manifest_sha256"] == prior["v3_manifest_sha256"]
            and hashlib.sha256(canonical({k: v for k, v in old_manifest.items() if k != "manifest_sha256"})).hexdigest()
                == prior["v3_manifest_sha256"]
            and old_manifest["registry_sha256"] == prior["v3_registry_sha256"], "Prior allocation identity mismatch")
    require(hashlib.sha256(gzip.decompress(old_registry.read_bytes())).hexdigest() == prior["v3_registry_sha256"],
            "Complete old registry content differs")
    collection.add(old_allocation, BASE + "field_bridge_v3_20261027/SOURCE_ALLOCATION.json")
    collection.add(old_registry, BASE + "field_bridge_v3_20261027/SOURCE_IDENTITIES.json.gz", old_manifest["registry_gzip_sha256"])

    restoration_path = assets / "RESTORATION.json"
    restoration = json_file(restoration_path)
    collection.add(restoration_path, "assets/full002/RESTORATION.json")
    for row in restoration["selected_files"]:
        source = (assets / row["path"]).resolve()
        require(source.is_relative_to(assets) and source.stat().st_size == row["bytes"], "Old asset restoration boundary differs")
        collection.add(source, "assets/full002/" + row["path"], row["sha256"])
    # Every regular original-asset file is retained, including original metadata.
    collection.tree(assets, "assets/full002")

    prior_archives = []
    for entry in config["prior_archive_receipts"]:
        path = Path(entry["source"]).resolve()
        record = json_file(path)
        data = record.get("archive")
        if isinstance(data, dict):
            reference = {"filename": data["filename"], "sha256": data["sha256"], "bytes": data["bytes"],
                         "manifest_sha256": data["manifest_sha256"]}
        else:
            reference = {"filename": record["archive"], "sha256": record["archive_sha256"], "bytes": record["archive_bytes"],
                         "manifest_sha256": record["manifest_sha256"]}
        require(re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is not None, "Missing prior archive SHA")
        member = "legacy/archive-references/" + entry["name"]
        collection.add(path, member)
        prior_archives.append({**reference, "receipt": member, "receipt_sha256": file_sha(path),
                               "payload_included": False, "identity_from_prior_verified_receipt_not_rehashed_now": True})
    require(len(prior_archives) >= 2, "V2 and V3 raw-archive references are required")
    for entry in config.get("operation_files", []):
        require(entry["path"].startswith("operations/"), "Extra operations must use the operations root")
        collection.add(Path(entry["source"]).resolve(), entry["path"], entry.get("sha256"))
    for entry in config.get("operation_trees", []):
        require(entry["path"].startswith("operations/"), "Extra operation trees must use the operations root")
        collection.tree(Path(entry["source"]).resolve(), entry["path"])

    archive_tools = {}
    for name in TOOLS:
        path = Path(__file__).with_name(name)
        member = BASE + REVIEW + "/" + name
        collection.add(path, member)
        archive_tools[member] = file_sha(path)
        source_bindings[member] = archive_tools[member]
    for name in mandatory:
        receipts["run/" + name] = file_sha(run / name)
    for member, source in collection.entries.items():
        if member.startswith(("run/", "freezes/")) and Path(source).suffix == ".json":
            receipts.setdefault(member, file_sha(source))
    provenance = {"study_id": protocol["study_id"], "registered_commits": sorted(commits),
        "protocol": {"path": BASE + SCIENCE + "/PROTOCOL.json", "sha256": file_sha(protocol_path)},
        "source_files": source_bindings, "receipts": receipts, "training_freeze_path": "freezes/TRAINING_FREEZE.json",
        "phase_freezes_collected": executed_freezes, "archive_tools": archive_tools,
        "source_binding_scope": {"initial_registered_sources": 58, "initial_old_artifacts": 25,
                                "posthoc_archive_tools": sorted(archive_tools)},
        "scope": SCOPE, "prior_archives": prior_archives, "original_asset_archive_sha256": restoration["archive_sha256"],
        "asset_root_path": "assets/full002/",
        "excluded_items": [*collection.exclusions,
            {"category": "prior V2/V3 tar payloads", "reason": "explicit identities only; no nested multi-gigabyte historical archives"},
            {"category": "temporary Torch/dependency runtime", "source": "/tmp/hepta-field-v4-python",
             "reason": "reproducible environment; exact restoration source/receipt retained; no 612MB runtime payload"},
            {"category": "archive, manifest-self and postpackage archive receipts",
             "reason": "kept outside the package; independent receipts bind the final archive without a hash cycle"}],
        "full_v4_raw_media_retained": True, "old_entire_generated_history_embedded": False,
        "statistical_replay_is_verification_not_new_outcome_look": True, "network_or_upload_operations": 0}
    rows = collection.identities()
    manifest = {"schema": PREFIX + ".evidence-archive-manifest.1", "provenance": provenance, "members": rows}
    validate_manifest(manifest)
    selected = required_members(manifest)
    by_name = {row["path"]: row for row in rows}
    require(set(selected) <= by_name.keys(), "Literal restore needs an unarchived member")
    index = {"schema": PREFIX + ".archive-input-index.1",
        "entries": [{"source": source, "path": name} for name, source in sorted(collection.entries.items())],
        "expected_members": rows, "restore_members": selected, "provenance": provenance}
    restore_plan = {"schema": PREFIX + ".archive-selective-restore.1", "members": selected,
                    "payload_bytes": sum(by_name[name]["bytes"] for name in selected),
                    "scope": "Literal archived statistics and metadata; all remaining media/checkpoints verified in the complete stream"}
    report = {"schema": PREFIX + ".archive-input-coverage.1", "planned": True, "archive_built": False,
        "terminal_access_authorized": True, **coverage, "members": len(rows), "payload_bytes": sum(row["bytes"] for row in rows),
        "restore_files": len(selected), "restore_payload_bytes": restore_plan["payload_bytes"],
        "source_freeze_sources": len(training["source_files"]), "old_inputs": len(training["old_artifacts"]),
        "restored_original_asset_selected_files": len(restoration["selected_files"]),
        "full_v4_run_enumeration": True, "input_files_copied": 0, "exclusions": provenance["excluded_items"],
        "config_sha256": file_sha(config_path), "script_sha256": file_sha(__file__),
        "scope": SCOPE, "planning_wall_ns": time.perf_counter_ns() - started, "library_upload_attempts": 0}
    return index, restore_plan, report


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--restore-plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    outputs = [args.index.resolve(), args.restore_plan.resolve(), args.receipt.resolve()]
    require(len(set(outputs)) == 3 and all(not path.exists() for path in outputs), "Refusing to overwrite preservation evidence")
    index, restore_plan, report = collect(args.config)
    for path, value in zip(outputs, (index, restore_plan, report), strict=True):
        write_new(path, value)
    print(json.dumps({"archive_built": False, "members": report["members"], "payload_bytes": report["payload_bytes"],
                      "restore_payload_bytes": report["restore_payload_bytes"], "raw_input_copies": 0}))
