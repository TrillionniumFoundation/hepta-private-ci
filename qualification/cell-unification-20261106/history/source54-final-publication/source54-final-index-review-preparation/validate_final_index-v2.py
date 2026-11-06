#!/usr/bin/env python3
"""Read-only artifact7 INDEX validation against frozen historical identities.

This program reads local data only. It neither invokes Git nor changes a source,
index, ledger, or publication map. An optional report is create-only and must be
outside the canonical repository. Actual remote object publication remains a
separate root responsibility.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys


WORKSPACE = Path(__file__).resolve().parent.parent
PREFIX = "qualification/cell-unification-20261106/native-evidence/"
INDEX_PATH = PREFIX + "INDEX.json"
PRIOR_RAW_PIN = (1548794, "fe9d15906ac379e33e7d58e0bed4e385592cf79d4b8eaf6e76e2c90beb48dc61")
BASE_PIN = (735691, "5adec73ba544d2a4de453921c6abeed3632eaf51e0314816fabbaf2e41ab021d")
STAGED_PIN = (389725, "e68b08d354ec782ef9a142cde77f0840d1eb06101b5258a16ca72bfcd15e6c8d")
REGISTRATION_PIN = (3786, "7b9642d8c6a50393dc4f6421b9d1499135efb4faaf3347a1550c678900ca32ac")
CHECKPOINT6 = "9896f63f1352906a6afec53b94d4d123143ba35e"
TESTED_COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TESTED_TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
FINAL_COMMIT = "b5209cfdf509e990f10922197b32540bf8c353a7"
FINAL_TREE = "42c1dd4e1a751c690c2800dfc3868e771dc9c70b"
PRESERVE_ARRAYS = {
    "artifacts": 2109,
    "historical_artifact_git_bindings": 1673,
    "additional_inherited_git_paths_not_in_prior_raw_inventory": 50,
    "observed_local_artifacts": 436,
    "unmaterialized_binary_references": 139,
}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def parse_json(data, label):
    try:
        return json.loads(data, object_pairs_hook=no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Invalid(f"invalid JSON in {label}: {exc}") from exc


def raw_pin(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def same_file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def stable_bytes(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), f"not a regular non-symlink file: {path}")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        require(same_file_identity(before) == same_file_identity(opened), f"file changed before read: {path}")
        data = stream.read()
        closed = os.fstat(stream.fileno())
    after = path.lstat()
    require(same_file_identity(before) == same_file_identity(closed) == same_file_identity(after),
            f"file changed during read: {path}")
    require(len(data) == before.st_size, f"short local read: {path}")
    return data


def read_json(path, expected=None, allow_gzip=False):
    encoded = stable_bytes(path)
    data = gzip.decompress(encoded) if allow_gzip and encoded.startswith(b"\x1f\x8b") else encoded
    pin = raw_pin(data)
    if expected is not None:
        require((pin["bytes"], pin["sha256"]) == expected, f"frozen input pin mismatch: {path}")
    provenance = {"path": str(path), **raw_pin(encoded)}
    if data is not encoded:
        provenance["decompressed"] = pin
    return parse_json(data, str(path)), provenance, data


def safe_path(value, label):
    require(isinstance(value, str) and value, f"{label}: empty/non-string path")
    require("\\" not in value and "\0" not in value, f"{label}: invalid path characters")
    parts = value.split("/")
    require(not value.startswith("/") and all(part not in ("", ".", "..") for part in parts),
            f"{label}: path must be canonical relative POSIX: {value!r}")
    require(str(PurePosixPath(value)) == value, f"{label}: noncanonical path")
    return value


def is_size(value):
    return type(value) is int and value >= 0


def require_sha(value, pattern, label):
    require(isinstance(value, str) and pattern.fullmatch(value) is not None, f"{label}: invalid hash")


def contains_exact_raw_pin(value, expected):
    if isinstance(value, dict):
        for prefix in ("", "raw_", "decompressed_", "uncompressed_", "original_"):
            if (value.get(prefix + "bytes"), value.get(prefix + "sha256")) == expected:
                return True
        return any(contains_exact_raw_pin(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(contains_exact_raw_pin(item, expected) for item in value)
    return False


def mapping(document, label):
    require(isinstance(document, dict), f"{label}: map object required")
    files, sizes = document.get("files"), document.get("file_sizes")
    require(isinstance(files, dict) and isinstance(sizes, dict), f"{label}: files/file_sizes dictionaries required")
    require(set(files) == set(sizes), f"{label}: files/file_sizes path sets differ")
    for path, blob in files.items():
        safe_path(path, label)
        require_sha(blob, HEX40, f"{label}:{path}")
        require(is_size(sizes[path]), f"{label}:{path}: invalid size")
    if "count" in document:
        require(document["count"] == len(files), f"{label}: count differs from files")
    return files, sizes


def rows_by_path(document, key):
    rows = document.get(key)
    require(isinstance(rows, list), f"INDEX missing array {key}")
    result = {}
    for row in rows:
        require(isinstance(row, dict), f"{key}: row must be object")
        path = safe_path(row.get("path"), key)
        require(path not in result, f"{key}: duplicate path {path}")
        require(path != "INDEX.json", f"{key}: main INDEX must remain self-excluded")
        result[path] = row
    return result


def preserve_rows(old, new, key):
    for path, row in old.items():
        require(path in new, f"lost historical row {key}:{path}")
        for field, value in row.items():
            require(field in new[path] and canonical(new[path][field]) == canonical(value),
                    f"historical field changed {key}:{path}:{field}")


def local_evidence_file(repo_root, relative):
    current = repo_root
    for part in (PREFIX + relative).split("/"):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        require(not stat.S_ISLNK(info.st_mode), f"canonical evidence contains symlink: {current}")
    require(stat.S_ISREG(info.st_mode), f"canonical evidence is not regular: {current}")
    return current


def validate(args, report):
    repo_root = Path(args.canonical_root).resolve(strict=True)
    prior_path = Path(args.prior_index) if args.prior_index else repo_root / PREFIX / "history/source54-index/INDEX-v4.json.gz"
    old, old_pin, _ = read_json(prior_path, PRIOR_RAW_PIN, allow_gzip=True)
    base, base_pin, _ = read_json(WORKSPACE / "publication-recovery-prep/checkpoint6-actual-leaf-map.json", BASE_PIN)
    staged, staged_pin, _ = read_json(WORKSPACE / "r31-formal-root-preparation/COMBINED-STAGED-OVERLAY.json", STAGED_PIN)
    registration, registration_pin, _ = read_json(WORKSPACE / "source54-root-registration/ROOT-REGISTRATION-READBACK.json", REGISTRATION_PIN)
    candidate, candidate_pin, _ = read_json(Path(args.candidate_index))
    supplied, supplied_pin, _ = read_json(Path(args.new_blobmap))
    report["inputs"] = {"prior_index": old_pin, "checkpoint6": base_pin, "staged_1103": staged_pin,
                        "source54_registration": registration_pin, "candidate": candidate_pin,
                        "supplied_actual_blobmap": supplied_pin}
    require(old.get("schema") == "hepta.cell-unification-evidence-index.v4", "wrong prior INDEX schema")
    require(base.get("checkpoint_commit") == CHECKPOINT6, "wrong actual checkpoint6")
    require((registration.get("source_commit"), registration.get("source_tree"), registration.get("parents"))
            == (FINAL_COMMIT, FINAL_TREE, [TESTED_COMMIT]), "actual source54 registration differs")
    base_files, base_sizes = mapping(base, "checkpoint6")
    stage_files, stage_sizes = mapping(staged, "staged1103")
    new_files, new_sizes = mapping(supplied, "supplied_actual_map")
    require(len(base_files) == 2370 and len(stage_files) == 1103, "frozen map counts differ")
    require(not set(base_files).intersection(stage_files), "frozen stage unexpectedly replaces prior leaves")
    require(all(path.startswith(PREFIX) for path in stage_files), "staged scope escaped native-evidence")
    for path, blob in stage_files.items():
        require(new_files.get(path) == blob and new_sizes.get(path) == stage_sizes[path],
                f"complete new map lost/changed staged identity: {path}")
    if args.map_kind == "complete":
        require(set(base_files).issubset(new_files), "complete publication map drops checkpoint6 paths")
        files, sizes = dict(new_files), dict(new_sizes)
    else:
        files, sizes = dict(base_files), dict(base_sizes)
        files.update(new_files)
        sizes.update(new_sizes)
    for path, blob in base_files.items():
        if path.startswith(PREFIX) and path != INDEX_PATH:
            require(files.get(path) == blob and sizes.get(path) == base_sizes[path],
                    f"historical evidence Git identity changed: {path}")
    if INDEX_PATH in new_files:
        require(new_files[INDEX_PATH] in (base_files[INDEX_PATH], candidate_pin["git_blob"]),
                "supplied INDEX leaf is neither frozen prior nor exact candidate")
        wanted_size = candidate_pin["bytes"] if new_files[INDEX_PATH] == candidate_pin["git_blob"] else base_sizes[INDEX_PATH]
        require(new_sizes[INDEX_PATH] == wanted_size, "INDEX self leaf size mismatch")
    require(isinstance(candidate, dict), "candidate must be object")
    schema = candidate.get("schema", "")
    match = re.fullmatch(r"hepta\.cell-unification-evidence-index\.v([0-9]+)", schema)
    require(match is not None and int(match.group(1)) >= 5, "artifact7 candidate must explicitly upgrade v4 schema")
    old_groups, groups = {}, {}
    for key, expected_count in PRESERVE_ARRAYS.items():
        old_groups[key], groups[key] = rows_by_path(old, key), rows_by_path(candidate, key)
        require(len(old_groups[key]) == expected_count, f"unexpected frozen {key} count")
        preserve_rows(old_groups[key], groups[key], key)
    report["preserved_old_rows"] = dict(PRESERVE_ARRAYS)
    artifacts = groups["artifacts"]
    git_only = groups["additional_inherited_git_paths_not_in_prior_raw_inventory"]
    require(not set(artifacts).intersection(git_only), "raw and Git-only classes overlap")
    native_map_paths = {path[len(PREFIX):] for path in files if path.startswith(PREFIX)}
    indexed_paths = set(artifacts) | set(git_only) | {"INDEX.json"}
    require(indexed_paths == native_map_paths,
            f"INDEX/map coverage differs: omitted={sorted(native_map_paths-indexed_paths)[:10]}, unmapped={sorted(indexed_paths-native_map_paths)[:10]}")
    require({path[len(PREFIX):] for path in stage_files}.issubset(artifacts), "staged local artifacts must retain raw rows")
    raw_readbacks, unavailable_old = [], []
    for path, row in artifacts.items():
        require(is_size(row.get("bytes")), f"{path}: invalid bytes")
        require_sha(row.get("sha256"), HEX64, path)
        repo_path = PREFIX + path
        require(row["bytes"] == sizes[repo_path], f"{path}: row size differs from actual map")
        if "git_blob" in row:
            require(row["git_blob"] == files[repo_path], f"{path}: row Git blob differs from actual map")
        local_path = local_evidence_file(repo_root, path)
        if local_path is None:
            require(path in old_groups["artifacts"], f"new raw row cannot be verified without actual local bytes: {path}")
            unavailable_old.append(path)
            continue
        data = stable_bytes(local_path)
        pin = raw_pin(data)
        require((pin["bytes"], pin["sha256"], pin["git_blob"]) == (row["bytes"], row["sha256"], files[repo_path]),
                f"{path}: local raw/SHA256/Git blob does not match row and actual map")
        if "decompressed_bytes" in row or "decompressed_sha256" in row:
            require(is_size(row.get("decompressed_bytes")), f"{path}: invalid decompressed size")
            require_sha(row.get("decompressed_sha256"), HEX64, path + ":decompressed")
            unpacked = gzip.decompress(data)
            require((len(unpacked), hashlib.sha256(unpacked).hexdigest()) == (row["decompressed_bytes"], row["decompressed_sha256"]),
                    f"{path}: gzip roundtrip pin mismatch")
        raw_readbacks.append({"path": path, **pin, "new_row": path not in old_groups["artifacts"]})
    git_only_readbacks = []
    for path, row in git_only.items():
        repo_path = PREFIX + path
        require((row.get("bytes"), row.get("git_blob")) == (sizes[repo_path], files[repo_path]), f"{path}: Git-only identity mismatch")
        require(row.get("raw_sha256_observed_this_inventory") is None and row.get("raw_bytes_re_read_this_inventory") is False,
                f"{path}: Git-only row contains a new raw observation claim")
        local_path = local_evidence_file(repo_root, path)
        if local_path is not None:
            pin = raw_pin(stable_bytes(local_path))
            require((pin["bytes"], pin["git_blob"]) == (sizes[repo_path], files[repo_path]), f"{path}: available Git-only bytes mismatch")
            git_only_readbacks.append({"path": path, **pin, "historical_row_observation_flags_unchanged": True})
    for path, row in groups["historical_artifact_git_bindings"].items():
        require(path in artifacts, f"historical binding lacks raw row: {path}")
        require((row.get("historical_sha256"), row.get("published_git_blob"), row.get("published_size"))
                == (artifacts[path]["sha256"], files[PREFIX+path], sizes[PREFIX+path]), f"historical binding mismatch: {path}")
    available_raw_paths = {row["path"] for row in raw_readbacks}
    for path, row in groups["observed_local_artifacts"].items():
        require(path in artifacts, f"observed row lacks raw artifact: {path}")
        require((row.get("bytes"), row.get("sha256"), row.get("git_blob"))
                == (artifacts[path]["bytes"], artifacts[path]["sha256"], files[PREFIX+path]), f"observed raw identity mismatch: {path}")
        if path not in old_groups["observed_local_artifacts"]:
            require(path in available_raw_paths, f"new observed-local claim has no current raw bytes: {path}")
    for path, row in groups["unmaterialized_binary_references"].items():
        require(path in artifacts or path in git_only, f"unmaterialized reference is unclassified: {path}")
        require(row.get("git_blob") == files[PREFIX+path], f"unmaterialized Git identity differs: {path}")
        if row.get("published_remote_blob") is not None:
            require(row["published_remote_blob"] == files[PREFIX+path], f"unmaterialized observed remote Git identity differs: {path}")
        else:
            prior_row = old_groups["unmaterialized_binary_references"].get(path)
            require(prior_row is not None and "published_remote_blob" in prior_row and prior_row["published_remote_blob"] is None,
                    f"unmaterialized null remote observation is not an unchanged historical field: {path}")
            require(row.get("sha256_observed_this_run") is None and row.get("bytes_observed_this_run") is None
                    and row.get("raw_bytes_re_read_this_run") is False and row.get("formal_group_completeness_not_claimed") is True,
                    f"unmaterialized historical null/false observation boundary changed: {path}")
        if row.get("historical_index_sha256") is not None:
            require(path in artifacts and row["historical_index_sha256"] == artifacts[path]["sha256"], f"unmaterialized historical SHA differs: {path}")
        if row.get("historical_index_bytes") is not None:
            require(row["historical_index_bytes"] == sizes[PREFIX+path], f"unmaterialized historical size differs: {path}")
    counters = {
        "artifact_count": "artifacts", "historical_artifact_count": "historical_artifact_git_bindings",
        "current_raw_hash_count": "observed_local_artifacts",
        "inherited_additional_git_reference_count": "additional_inherited_git_paths_not_in_prior_raw_inventory",
        "unmaterialized_reference_count": "unmaterialized_binary_references",
    }
    for key, array in counters.items():
        require(type(candidate.get(key)) is int and candidate[key] == len(groups[array]), f"counter mismatch: {key}")
    for key in ("self_excluded", "all_prior_Git_paths_retained_by_publication_plan_required", "qualification_not_inferred_from_integrity"):
        require(candidate.get(key) is True, f"required integrity boundary missing/false: {key}")
    require(type(candidate.get("formal_INDEX_written")) is bool, "formal_INDEX_written must remain an explicit adoption-state boolean")
    require(candidate.get("science") == "HOLD" and candidate.get("authority") == "DENY_ALL", "science/authority boundary changed")
    identity = candidate.get("source_identity", {})
    require((identity.get("commit"), identity.get("tree"), identity.get("stage")) == (FINAL_COMMIT, FINAL_TREE, 54), "current source identity is not actual registered source54")
    require((identity.get("changed_paths"), identity.get("rust_paths"), identity.get("other_paths")) == (197, 183, 14), "source54 scope counts differ")
    require(identity.get("gitdata_identity_not_native_checkout") is True, "GitData/native-checkout boundary lost")
    for key, gate in (("last_closed_workspace_gate", "r31"), ("last_closed_complete_project_gate", "r30")):
        value = candidate.get(key, {})
        require((value.get("source_commit"), value.get("source_tree")) == (TESTED_COMMIT, TESTED_TREE), f"{key}: qualification incorrectly moved off tested source53")
        require(value.get("gate") == gate and value.get("outcome") == "PASS" and type(value.get("exit_code")) is int and value["exit_code"] == 0,
                f"{key}: closed gate identity/outcome differs")
    workspace_gate = candidate["last_closed_workspace_gate"]
    require(workspace_gate.get("command") == ["just", "test", "--locked", "--retries", "0"], "workspace original no-p command differs")
    for key in ("qualification_transferred_to_mutated_tree", "post_fix_or_format_tests_executed", "post_format_tests_executed"):
        if key in candidate:
            require(candidate[key] is False, f"unsupported post-format qualification claim: {key}")
    require(isinstance(candidate.get("previous_index"), dict), "previous_index provenance must be retained")
    require(contains_exact_raw_pin(candidate["previous_index"], PRIOR_RAW_PIN),
            "previous_index must explicitly distinguish retained gzip from exact decompressed v4 raw pin")
    report.update({
        "status": "PASS_LOCAL_INDEX_INTEGRITY_ONLY",
        "map_kind": args.map_kind,
        "supplied_map_count": len(new_files), "merged_publication_paths": len(files),
        "native_evidence_map_paths": len(native_map_paths),
        "artifact_count": len(artifacts), "new_raw_rows": len(set(artifacts)-set(old_groups["artifacts"])),
        "git_only_count": len(git_only), "unmaterialized_reference_count": len(groups["unmaterialized_binary_references"]),
        "old_139_overlap": {"raw": len(set(old_groups["unmaterialized_binary_references"]) & set(old_groups["artifacts"])),
                            "git_only": len(set(old_groups["unmaterialized_binary_references"]) & set(old_groups["additional_inherited_git_paths_not_in_prior_raw_inventory"]))},
        "local_raw_rehashed_count": len(raw_readbacks),
        "old_raw_not_available_count": len(unavailable_old),
        "old_raw_not_available_paths_sha256": hashlib.sha256(canonical(sorted(unavailable_old)).encode()).hexdigest(),
        "raw_readbacks": sorted(raw_readbacks, key=lambda row: row["path"]),
        "git_only_raw_available_now": sorted(git_only_readbacks, key=lambda row: row["path"]),
        "candidate_self_blob_present_in_supplied_map": new_files.get(INDEX_PATH) == candidate_pin["git_blob"],
        "outside_native_evidence_prior_paths_changed": sorted(path for path in base_files if not path.startswith(PREFIX) and files[path] != base_files[path]),
        "current_source": {"commit": FINAL_COMMIT, "tree": FINAL_TREE},
        "tested_source": {"commit": TESTED_COMMIT, "tree": TESTED_TREE},
        "remote_publication_or_tree_not_independently_queried": True,
        "gate_logs_not_reparsed_by_this_inventory_validator": True,
        "new_tests_or_metadata_executed": False,
        "canonical_index_ledger_or_source_changed": False,
        "qualification_transferred_to_formatted_tree": False,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-index", required=True)
    parser.add_argument("--new-blobmap", required=True)
    parser.add_argument("--map-kind", choices=("overlay", "complete"), required=True)
    parser.add_argument("--canonical-root", default=str(WORKSPACE / "hepta-cell"))
    parser.add_argument("--prior-index", help="Exact original v4 JSON or gzip; default is retained canonical history gzip")
    parser.add_argument("--report", help="Optional create-only JSON report outside canonical repository")
    args = parser.parse_args()
    report = {"schema": "hepta.source54-final-index-independent-readback.v1", "status": "FAIL_CLOSED"}
    try:
        validate(args, report)
        returncode = 0
    except (Invalid, OSError, EOFError, ValueError, TypeError, KeyError) as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        returncode = 1
    data = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode()
    if args.report:
        report_path = Path(args.report).absolute()
        repo = Path(args.canonical_root).resolve()
        require(not report_path.resolve().is_relative_to(repo), "report must not modify canonical repository")
        require(not report_path.exists(), "report path already exists")
        with report_path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"status": report["status"], "report": str(report_path), **raw_pin(data), "error": report.get("error")}, ensure_ascii=False))
    else:
        sys.stdout.buffer.write(data)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
