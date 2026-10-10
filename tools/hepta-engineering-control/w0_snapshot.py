#!/usr/bin/env python3
"""Build or check a read-only W0 source-preparation proposal.

This tool observes committed Git bytes and checkout cleanliness.  It never
issues a source receipt, lane admission, checkpoint, authority, or gate result.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from deployment_inventory import MAX_BYTES, InventoryError, duplicate_keys, git, relative_path

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
LANE_IDS = tuple(f"LANE-{letter}-{name}" for letter, name in (
    ("A", "FOUNDATION"), ("B", "RUNTIME"), ("C", "MEMORY"),
    ("D", "OBJECTIVE-VALUE"), ("E", "LEARNING"),
    ("F", "ADAPTIVE-POLICY"), ("G", "ENGINEERING"),
))
LANE_LETTERS = {identity: identity[5] for identity in LANE_IDS}
INPUT_PATHS = (
    "docs/governance/DOCUMENT_SYSTEM.json",
    "docs/modules/MODULES.json", "docs/modules/MODULE_DOCS.json",
    "docs/modules/SOURCE_BINDINGS.json", "docs/contracts/CONTRACTS.json",
    "docs/contracts/PROTOCOL_SCHEMAS.json", "docs/data/DATA_AUTHORITY.json",
    "docs/delivery/WORK_PACKAGES.json", "docs/delivery/PATH_OWNERSHIP.json",
    "docs/delivery/DEVELOPMENT_DAG.json", "docs/delivery/ACTIVATION_DAG.json",
    "docs/delivery/EVIDENCE_DAG.json", "docs/readiness/READINESS.json",
    "docs/readiness/PROTOCOLS.json", "docs/learning/ALGORITHM_SPECS.json",
    "docs/cns/CNS_ARCHITECTURE.json", "docs/hnmf/HNMF.json",
    "docs/readiness/PARALLEL_DEVELOPMENT.md",
    "docs/readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md",
    "qualification/module-execution-dossiers/MODULE_DOSSIERS.json",
    "qualification/module-execution-dossiers/DETAILS.json",
    "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json",
    "qualification/module-execution-dossiers/TECHNICAL.md",
    "qualification/module-execution-dossiers/IMPLEMENTATION_CONTRACTS.md",
    "qualification/module-execution-dossiers/EXECUTION_SEMANTICS.md",
)
JSON_INPUTS = tuple(path for path in INPUT_PATHS if path.endswith(".json"))
AUTHORITY_FLAGS = (
    "runtimeAuthority", "productionCaller", "productionWriter",
    "modelInvocation", "providerDispatch", "toolExecution", "networkConnect",
    "externalFilesystemMutation", "secretOperation", "matrixSend",
    "externalEffect", "fleetMutation", "mergeAuthority", "promotionAuthority",
    "releaseAuthority", "activationAuthority", "canonicalSelectionAuthority",
)
BASE_BLOCKERS = (
    "FORMAL_SOURCE_RECEIPT_NOT_SUPPLIED",
    "BRANCH_PURPOSE_MANIFEST_NOT_SUPPLIED",
    "REVIEWED_LANE_ENVELOPES_NOT_SUPPLIED",
    "INDEPENDENT_SEMANTIC_ACCEPTANCE_OPEN",
    "EXTERNAL_GATES_UNCLAIMED",
    "INTEGRATION_CHECKPOINT_NOT_ISSUED",
)

class W0Error(InventoryError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code

class DriftError(W0Error):
    pass

def reject(code):
    raise W0Error(code)

def bounded_structure(value, code="JSON_STRUCTURE_EXCEEDED"):
    stack, nodes = [(value, 0)], 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > 64 or nodes > 100_000:
            reject(code)
        children = current.values() if isinstance(current, dict) else current if isinstance(current, list) else ()
        stack.extend((child, depth + 1) for child in children)
    return value

def canonical_bytes(value):
    bounded_structure(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")

def digest(value):
    raw = value if isinstance(value, bytes) else canonical_bytes(value)
    return hashlib.sha256(raw).hexdigest()

def reject_constant(_value):
    raise InventoryError("non-finite JSON number")

def index(rows, key, expected, code):
    if not isinstance(rows, list) or len(rows) != expected:
        reject(code)
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            reject(code)
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in out:
            reject(code)
        out[identity] = row
    return out

def git_read(root, *args):
    try:
        return git(root, *args)
    except (InventoryError, OSError, subprocess.TimeoutExpired, UnicodeError):
        reject("GIT_READ_FAILED")

def commit_identity(root, value, code):
    if not isinstance(value, str) or SHA40.fullmatch(value) is None:
        reject(code)
    resolved = git_read(root, "rev-parse", "--verify", f"{value}^{{commit}}")
    if resolved.decode().strip() != value:
        reject(code)
    tree = git_read(root, "rev-parse", f"{value}^{{tree}}").decode().strip()
    parents = git_read(root, "show", "-s", "--format=%P", value).decode().strip()
    return {"commit": value, "tree": tree,
            "orderedParents": parents.split() if parents else []}

class SourceReader:
    def __init__(self, root, source):
        self.root = root
        self.source = source
        self.total = 0
        self.cache = {}
        self.files = {}
        raw = git_read(root, "ls-tree", "-r", "-l", "-z", source)
        for item in raw.split(b"\0"):
            if not item:
                continue
            try:
                metadata, raw_path = item.split(b"\t", 1)
                mode, kind, blob, size = metadata.decode().split()
                path = relative_path(raw_path.decode("utf-8"))
            except (ValueError, UnicodeError, InventoryError):
                reject("SOURCE_TREE_INVALID")
            if path in self.files:
                reject("SOURCE_TREE_INVALID")
            self.files[path] = {"mode": mode, "kind": kind, "gitBlob": blob,
                                "bytes": int(size) if size.isdecimal() else None}

    def read(self, path):
        try:
            path = relative_path(path)
        except (InventoryError, TypeError):
            reject("CANONICAL_PATH_INVALID")
        entry = self.files.get(path)
        if not entry or entry["kind"] != "blob" or entry["mode"] not in ("100644", "100755"):
            reject("CANONICAL_FILE_MISSING_OR_NONORDINARY")
        if path in self.cache:
            return self.cache[path]
        if (entry["bytes"] is None or entry["bytes"] > MAX_BYTES
                or self.total + entry["bytes"] > MAX_TOTAL_BYTES):
            reject("SOURCE_BUDGET_EXCEEDED")
        raw = git_read(self.root, "show", f"{self.source}:{path}")
        if len(raw) != entry["bytes"]:
            reject("SOURCE_TREE_INVALID")
        self.total += len(raw)
        if self.total > MAX_TOTAL_BYTES:
            reject("SOURCE_BUDGET_EXCEEDED")
        self.cache[path] = raw
        return raw

    def json(self, path):
        try:
            value = json.loads(self.read(path), object_pairs_hook=duplicate_keys,
                               parse_constant=reject_constant)
            return bounded_structure(value, "CANONICAL_JSON_STRUCTURE_EXCEEDED")
        except (json.JSONDecodeError, UnicodeError, InventoryError, RecursionError):
            reject("CANONICAL_JSON_INVALID")

    def record(self, path):
        raw = self.read(path)
        entry = self.files[path]
        return {"path": path, "mode": entry["mode"], "gitBlob": entry["gitBlob"],
                "sha256": digest(raw), "bytes": len(raw)}

def verify_false_authority(documents):
    for value in documents.values():
        flags = value.get("authorityFlags") if isinstance(value, dict) else None
        if flags is not None and (not isinstance(flags, dict)
                                  or any(flag is not False for flag in flags.values())):
            reject("AUTHORITY_FLAG_NOT_FALSE")

def overlap(left, right):
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")

def module_and_lane_records(reader, documents):
    modules = index(documents["docs/modules/MODULES.json"].get("modules"),
                    "id", 40, "MODULE_SET_INVALID")
    guides = index(documents["docs/modules/MODULE_DOCS.json"].get("modules"),
                   "module", 40, "MODULE_GUIDE_SET_INVALID")
    bindings = index(documents["docs/modules/SOURCE_BINDINGS.json"].get("bindings"),
                     "module", 40, "SOURCE_BINDING_SET_INVALID")
    readiness = documents["docs/readiness/READINESS.json"]
    lane_rows = index(readiness.get("implementationLanes"), "id", 7, "LANE_SET_INVALID")
    if set(lane_rows) != set(LANE_IDS):
        reject("LANE_SET_INVALID")
    ready_modules = index(readiness.get("moduleBindings"), "module", 40,
                          "READINESS_MODULE_SET_INVALID")
    ownership = index(documents["docs/delivery/PATH_OWNERSHIP.json"].get("moduleNamespaces"),
                      "module", 40, "PATH_OWNERSHIP_SET_INVALID")
    details = index(documents["qualification/module-execution-dossiers/DETAILS.json"].get("rows"),
                    "module", 40, "DOSSIER_DETAIL_SET_INVALID")
    profiles = index(documents["qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"].get("modules"),
                     "module", 40, "IMPLEMENTATION_PROFILE_SET_INVALID")
    dossier_profiles = documents["qualification/module-execution-dossiers/MODULE_DOSSIERS.json"].get("moduleProfiles")
    if not isinstance(dossier_profiles, dict) or set(dossier_profiles) != set(modules):
        reject("DOSSIER_PROFILE_SET_INVALID")
    expected = set(modules)
    for candidate, code in ((guides, "MODULE_GUIDE_SET_INVALID"),
                            (bindings, "SOURCE_BINDING_SET_INVALID"),
                            (ready_modules, "READINESS_MODULE_SET_INVALID"),
                            (ownership, "PATH_OWNERSHIP_SET_INVALID"),
                            (details, "DOSSIER_DETAIL_SET_INVALID"),
                            (profiles, "IMPLEMENTATION_PROFILE_SET_INVALID")):
        if set(candidate) != expected:
            reject(code)
    lane_for = {}
    for lane_id, lane in lane_rows.items():
        members = lane.get("modules")
        if not isinstance(members, list) or len(members) != len(set(members)):
            reject("LANE_MODULE_COVERAGE_INVALID")
        for module in members:
            if module not in expected or module in lane_for:
                reject("LANE_MODULE_COVERAGE_INVALID")
            lane_for[module] = lane_id
    if set(lane_for) != expected:
        reject("LANE_MODULE_COVERAGE_INVALID")

    module_records, root_records = [], []
    for module in sorted(expected):
        guide = guides[module]
        guide_path = guide.get("path")
        guide_raw = reader.read(guide_path)
        if digest(guide_raw) != guide.get("sha256") or len(guide_raw) != guide.get("bytes"):
            reject("GUIDE_DIGEST_MISMATCH")
        detail = details[module]
        detail_path = detail.get("path")
        detail_raw = reader.read(detail_path)
        if digest(detail_raw) != detail.get("sha256"):
            reject("DOSSIER_DIGEST_MISMATCH")
        roots = bindings[module].get("declaredRoots")
        root_bindings = ownership[module].get("rootBindings")
        if not isinstance(roots, list) or not isinstance(root_bindings, list):
            reject("SOURCE_OWNERSHIP_DRIFT")
        owned = {}
        for item in root_bindings:
            if not isinstance(item, dict) or item.get("mode") not in ("exclusive", "shared"):
                reject("SOURCE_OWNERSHIP_DRIFT")
            try:
                path = relative_path(item.get("path"))
            except (InventoryError, TypeError):
                reject("SOURCE_OWNERSHIP_DRIFT")
            if path in owned:
                reject("SOURCE_OWNERSHIP_DRIFT")
            owned[path] = item["mode"]
        try:
            normalized_roots = [relative_path(path) for path in roots]
        except (InventoryError, TypeError):
            reject("SOURCE_OWNERSHIP_DRIFT")
        if (len(normalized_roots) != len(set(normalized_roots))
                or not set(normalized_roots).issubset(owned)):
            reject("SOURCE_OWNERSHIP_DRIFT")
        lane_id = lane_for[module]
        profile = profiles[module]
        if (ready_modules[module].get("primaryLane") != lane_id
                or detail.get("lane") != lane_id
                or profile.get("lane") != LANE_LETTERS[lane_id]
                or profile.get("guide") != guide_path
                or profile.get("design") != detail_path
                or sorted(profile.get("declaredRoots", [])) != sorted(normalized_roots)):
            reject("MODULE_CROSS_REFERENCE_DRIFT")
        for path, mode in owned.items():
            root_records.append((path, mode, module, lane_id))
        module_records.append({
            "module": module, "lane": lane_id,
            "guide": {"path": guide_path, "sha256": digest(guide_raw)},
            "dossier": {"path": detail_path, "sha256": digest(detail_raw)},
            "declaredRoots": [{"path": path, "mode": owned[path]}
                              for path in sorted(normalized_roots)],
            "additionalOwnedRoots": [{"path": path, "mode": owned[path]}
                                     for path in sorted(set(owned) - set(normalized_roots))],
            "dossierProfileSha256": digest(dossier_profiles[module]),
            "implementationProfileSha256": digest(profile),
        })
    exclusive = [row for row in root_records if row[1] == "exclusive"]
    for position, left in enumerate(exclusive):
        for right in exclusive[position + 1:]:
            if left[2] != right[2] and overlap(left[0], right[0]):
                reject("EXCLUSIVE_PATH_COLLISION")
    lane_proposals = []
    for lane_id in LANE_IDS:
        lane = lane_rows[lane_id]
        roots = [row for row in root_records if row[3] == lane_id]
        lane_proposals.append({
            "id": lane_id, "owner": lane.get("owner"), "deputy": lane.get("deputy"),
            "modules": sorted(lane.get("modules", [])),
            "dependsOn": lane.get("dependsOn", []),
            "entryGate": lane.get("entryGate", []), "exitGate": lane.get("exitGate", []),
            "exclusiveRoots": sorted(row[0] for row in roots if row[1] == "exclusive"),
            "sharedRoots": sorted(row[0] for row in roots if row[1] == "shared"),
            "proposalOnly": True, "formalEnvelopeIssued": False,
            "admissionGranted": False, "authorityGranted": False,
        })
    return module_records, lane_proposals, bool([row for row in root_records if row[1] == "shared"])

def build_snapshot(root, base, source):
    root = root.resolve()
    if not root.is_dir():
        reject("REPOSITORY_ROOT_INVALID")
    base_identity = commit_identity(root, base, "BASE_SHA_INVALID")
    source_identity = commit_identity(root, source, "SOURCE_SHA_INVALID")
    head = git_read(root, "rev-parse", "HEAD^{commit}").decode().strip()
    if head != source:
        reject("SOURCE_NOT_HEAD")
    try:
        git(root, "merge-base", "--is-ancestor", base, source)
    except (InventoryError, OSError, subprocess.TimeoutExpired):
        reject("BASE_NOT_ANCESTOR")
    reader = SourceReader(root, source)
    document_system = reader.json("docs/governance/DOCUMENT_SYSTEM.json")
    paths = document_system.get("canonicalPaths")
    if not isinstance(paths, list) or not paths or len(paths) > 512 or len(paths) != len(set(paths)):
        reject("DOCUMENT_PATH_SET_INVALID")
    try:
        paths = sorted(relative_path(path) for path in paths)
    except (InventoryError, TypeError):
        reject("DOCUMENT_PATH_SET_INVALID")
    canonical_documents = [reader.record(path) for path in paths]
    documents = {}
    for path in JSON_INPUTS:
        documents[path] = document_system if path == "docs/governance/DOCUMENT_SYSTEM.json" else reader.json(path)
    verify_false_authority(documents)
    canonical_inputs = {path: reader.record(path) for path in INPUT_PATHS}
    module_records, lane_proposals, shared_roots = module_and_lane_records(reader, documents)
    status_raw = git_read(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    clean = not status_raw
    blockers = list(BASE_BLOCKERS)
    if not clean:
        blockers.append("WORKING_TREE_NOT_CLEAN")
    if shared_roots:
        blockers.append("SHARED_ROOT_LEASE_REVIEW_REQUIRED")
    result = {
        "schema": "hepta.w0-source-preparation-proposal.v1",
        "scope": "committed_source_pre_entry_preparation_only",
        "preEntrySourcePreparation": True,
        "formalW0Passed": False, "formalReceiptIssued": False,
        "canonicalSelection": False,
        "base": base_identity, "source": source_identity,
        "repository": {key: document_system.get("repository", {}).get(key)
                       for key in ("id", "fullName", "defaultBranch")},
        "freshness": {"pointInTimeOnly": True, "ttlIssued": False,
                      "recomputeBeforeUse": True,
                      "workingTreeClean": clean,
                      "workingTreeStatusSha256": digest(status_raw)},
        "canonicalDocuments": canonical_documents,
        "canonicalInputs": canonical_inputs,
        "modules": module_records, "laneProposals": lane_proposals,
        "exclusivePathCollisionDetected": False,
        "openBlockers": blockers,
        "authorityFlags": {flag: False for flag in AUTHORITY_FLAGS},
    }
    result["snapshotDigest"] = digest(result)
    return result

def load_snapshot(path):
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SNAPSHOT_BYTES:
            reject("SNAPSHOT_FILE_INVALID")
        flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
        descriptor = os.open(path, flags)
        try:
            current = os.fstat(descriptor)
            if (not stat.S_ISREG(current.st_mode) or current.st_size != info.st_size
                    or current.st_dev != info.st_dev or current.st_ino != info.st_ino):
                reject("SNAPSHOT_FILE_CHANGED")
            chunks, total = [], 0
            while total <= MAX_SNAPSHOT_BYTES:
                chunk = os.read(descriptor, min(65536, MAX_SNAPSHOT_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            if (after.st_size != current.st_size or after.st_mtime_ns != current.st_mtime_ns
                    or len(raw) != current.st_size):
                reject("SNAPSHOT_FILE_CHANGED")
        finally:
            os.close(descriptor)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            reject("SNAPSHOT_FILE_INVALID")
        value = json.loads(raw, object_pairs_hook=duplicate_keys,
                           parse_constant=reject_constant)
        bounded_structure(value, "SNAPSHOT_JSON_STRUCTURE_EXCEEDED")
    except W0Error:
        raise
    except (OSError, json.JSONDecodeError, UnicodeError, InventoryError, RecursionError):
        reject("SNAPSHOT_FILE_INVALID")
    if not isinstance(value, dict):
        reject("SNAPSHOT_FILE_INVALID")
    return value

def compare_snapshots(expected, actual):
    bounded_structure(expected, "EXPECTED_SNAPSHOT_SHAPE_INVALID")
    supplied_digest = expected.get("snapshotDigest")
    body = dict(expected)
    body.pop("snapshotDigest", None)
    if supplied_digest != digest(body):
        raise DriftError("EXPECTED_SNAPSHOT_DIGEST_INVALID")
    authority = expected.get("authorityFlags")
    freshness = expected.get("freshness")
    if (not isinstance(authority, dict) or not isinstance(freshness, dict)
            or expected.get("schema") != actual["schema"]
            or expected.get("preEntrySourcePreparation") is not True
            or expected.get("formalW0Passed") is not False
            or expected.get("formalReceiptIssued") is not False
            or any(authority.get(flag) is not False
                   for flag in AUTHORITY_FLAGS)):
        raise DriftError("EXPECTED_SNAPSHOT_SHAPE_INVALID")
    if expected.get("base") != actual["base"]:
        raise DriftError("BASE_PROVENANCE_DRIFT")
    expected_inputs = expected.get("canonicalInputs")
    actual_inputs = actual["canonicalInputs"]
    if not isinstance(expected_inputs, dict):
        raise DriftError("EXPECTED_SNAPSHOT_SHAPE_INVALID")
    for path, code in (
        ("docs/contracts/CONTRACTS.json", "CONTRACT_DIGEST_DRIFT"),
        ("docs/contracts/PROTOCOL_SCHEMAS.json", "PROTOCOL_DIGEST_DRIFT"),
        ("docs/modules/SOURCE_BINDINGS.json", "SOURCE_BINDING_DIGEST_DRIFT"),
        ("docs/delivery/PATH_OWNERSHIP.json", "PATH_OWNERSHIP_DIGEST_DRIFT"),
        ("docs/readiness/READINESS.json", "LANE_REGISTRY_DIGEST_DRIFT"),
    ):
        if expected_inputs.get(path) != actual_inputs.get(path):
            raise DriftError(code)
    if expected.get("canonicalDocuments") != actual["canonicalDocuments"]:
        raise DriftError("CANONICAL_DOCUMENT_DIGEST_DRIFT")
    if expected_inputs != actual_inputs:
        raise DriftError("CANONICAL_INPUT_DIGEST_DRIFT")
    if expected.get("modules") != actual["modules"]:
        raise DriftError("MODULE_PROPOSAL_DRIFT")
    if expected.get("laneProposals") != actual["laneProposals"]:
        raise DriftError("LANE_PROPOSAL_DRIFT")
    if expected.get("source") != actual["source"]:
        raise DriftError("SOURCE_PROVENANCE_DRIFT")
    expected_clean = freshness
    actual_clean = actual["freshness"]
    if (expected_clean.get("workingTreeClean") != actual_clean["workingTreeClean"]
            or expected_clean.get("workingTreeStatusSha256")
            != actual_clean["workingTreeStatusSha256"]):
        raise DriftError("WORKING_TREE_OBSERVATION_DRIFT")
    if expected != actual:
        raise DriftError("SNAPSHOT_DRIFT")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "check"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check" and args.snapshot is None:
            reject("SNAPSHOT_FILE_REQUIRED")
        if args.command == "snapshot" and args.snapshot is not None:
            reject("SNAPSHOT_FILE_NOT_ALLOWED")
        expected = load_snapshot(args.snapshot) if args.command == "check" else None
        actual = build_snapshot(args.root, args.base, args.source)
        if args.command == "snapshot":
            print(json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            compare_snapshots(expected, actual)
            print(json.dumps({"schema": "hepta.w0-snapshot-check.v1",
                              "driftDetected": False,
                              "formalW0Passed": False,
                              "authorityGranted": False,
                              "snapshotDigest": actual["snapshotDigest"]},
                             sort_keys=True))
    except DriftError as error:
        parser.exit(3, f"W0_DRIFT:{error.code}\n")
    except (W0Error, KeyError, TypeError, ValueError, RecursionError) as error:
        code = error.code if isinstance(error, W0Error) else "CANONICAL_SHAPE_INVALID"
        parser.exit(2, f"W0_INPUT_REJECTED:{code}\n")

if __name__ == "__main__":
    main()
