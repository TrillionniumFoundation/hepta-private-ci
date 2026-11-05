#!/usr/bin/env python3
"""Read-only C58 -> navigation-C1 evidence; never re-label a test execution.

Only stdout is written. The caller archives it outside the source checkout.
The original qualification verifier and JUnit coverage audit remain separate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


C58 = "58c81ccdd25002ae0f481d434af067a56fa7ddb8"
C58_TREE = "57809be09ef01c02389ef37a817f1447d13d167b"
RUN2_SHA256 = "3c778511d56ee7b8181fe409bc9a31438473d7ec1c3d98580969fd0fa64df847"
LEDGER = "qualification/module-execution-dossiers/SOURCE_NAVIGATION_REBIND_20261105_A9F4EBC7.json"
MODULES = frozenset("""platform.types platform.wire kernel.authority kernel.operations
kernel.evidence runtime.supervisor runtime.fleet runtime.agentd runtime.codex
auth.authbus secrets.heptabao inference.control inference.worker objective.compiler
utility.ndu neuron.runtime intuition.policy prompt.registry prompt.optimizer
context.compiler intelligence.control cognitive.types cognitive.store cognitive.read
memory.retrieval memory.federation knowledge.graph compact.engine learning.ledger
learning.operator learning.eval learning.artifacts learning.plasticity automation.taskflow
channel.matrix browser.servo ui.control ui.native control.runtime control.engineering""".split())
MAPS = {f"docs/modules/{mid}/IMPLEMENTATION_MAP.json": mid for mid in MODULES}
OID = re.compile(r"[0-9a-f]{40}\Z")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(raw):
    return json.loads(raw, object_pairs_hook=unique)


def checked_oid(value):
    if not isinstance(value, str) or not OID.fullmatch(value):
        raise ValueError("full lowercase SHA-1 required")
    return value


class Git:
    def __init__(self, repo):
        self.repo = Path(repo).resolve(strict=True)
        self.env = {key: val for key, val in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1",
                        GIT_OPTIONAL_LOCKS="0")

    def run(self, *args):
        result = subprocess.run(
            ["git", "--no-replace-objects", "--literal-pathspecs", "-C", str(self.repo),
             "-c", "core.fsmonitor=false", "-c", "core.ignorestat=false",
             "-c", "core.hooksPath=" + os.devnull, *args],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode:
            raise ValueError(f"git {args[0]} failed ({result.returncode}): "
                             + result.stderr.decode(errors="replace").strip())
        return result.stdout

    def object(self, kind, oid):
        raw = self.run("cat-file", kind, checked_oid(oid))
        actual = hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if actual != oid:
            raise ValueError("raw Git object hash mismatch")
        return raw

    def commit(self, oid, expected_tree):
        raw = self.object("commit", oid)
        headers = raw.split(b"\n\n", 1)[0].splitlines()
        trees = [line[5:].decode("ascii") for line in headers if line.startswith(b"tree ")]
        parents = [checked_oid(line[7:].decode("ascii")) for line in headers if line.startswith(b"parent ")]
        if trees != [expected_tree]:
            raise ValueError("commit tree does not match expected identity")
        self.object("tree", expected_tree)
        return parents

    def entries(self, tree):
        result = {}
        for row in self.run("ls-tree", "-r", "-z", "--full-tree", tree).split(b"\0"):
            if not row:
                continue
            header, path = row.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split(" ")
            name = path.decode("utf-8", errors="strict")
            if name in result:
                raise ValueError("duplicate Git tree path")
            result[name] = {"mode": mode, "type": kind, "oid": checked_oid(oid)}
        return result

    def clean_at(self, expected):
        if self.run("rev-parse", "HEAD").decode().strip() != expected:
            raise ValueError("current HEAD is not the expected C1")
        for option in ("-v", "-f"):
            for entry in self.run("ls-files", option, "-z").split(b"\0"):
                if entry and (entry[:1].islower() or entry[:1] == b"S"):
                    raise ValueError("index hides tracked paths")
        self.run("diff", "--quiet", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none", "HEAD", "--")
        self.run("diff", "--cached", "--quiet", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none", "HEAD", "--")
        if self.run("status", "--porcelain=v1", "--untracked-files=normal", "--ignore-submodules=none"):
            raise ValueError("candidate checkout is not clean")


def stable_map(row):
    result = copy.deepcopy(row)
    for key in ("sourceObjects", "observedAtHead", "observedSourcePaths", "mappingSourceIdentityMode"):
        result.pop(key, None)
    for operation in result.get("operations", []):
        operation.pop("sourceBlob", None)
    for caller in result.get("productCallers", []):
        caller.pop("blobSha", None)
    evidence = result.get("exactSourceEvidence")
    if isinstance(evidence, dict) and evidence.get("kind") == "path_blob_manifest_v1":
        for entry in evidence.get("entries", []):
            entry.pop("blobSha", None)
    return result


def projection(entries):
    kept = {path: value for path, value in entries.items() if path not in MAPS and path != LEDGER}
    raw = json.dumps(kept, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return kept, sha256(raw)


def verify(git, c1, c1_tree, receipt_path, log_path, junit_path):
    git.clean_at(c1)
    git.commit(C58, C58_TREE)
    if git.commit(c1, c1_tree) != [C58]:
        raise ValueError("C1 must have exactly the original executed C58 as its sole parent")
    before, after = git.entries(C58_TREE), git.entries(c1_tree)
    changes = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    if not changes or any(path not in MAPS and path != LEDGER for path in changes):
        raise ValueError("candidate changes extend beyond the exact navigation allowlist")
    if LEDGER in before or LEDGER not in after or after[LEDGER]["mode"] != "100644":
        raise ValueError("navigation ledger must be a newly added regular file")
    old_projection, old_digest = projection(before)
    new_projection, new_digest = projection(after)
    if old_projection != new_projection:
        raise ValueError("tracked execution inputs changed")
    for path in MAPS:
        if path not in before or path not in after or before[path]["mode"] != "100644" or after[path]["mode"] != "100644":
            raise ValueError("a fixed implementation Map is missing or is not a regular file")
    registry = parse_json(git.object("blob", before["docs/modules/MODULES.json"]["oid"]))
    registered = [row["id"] for row in registry["modules"]]
    if len(registered) != 40 or set(registered) != MODULES:
        raise ValueError("module registry no longer matches the exact 40-module scope")
    ledger_raw = git.object("blob", after[LEDGER]["oid"])
    ledger = parse_json(ledger_raw)
    if (ledger.get("schema") != "hepta.source-navigation-observation-rebind.v1"
            or ledger.get("sourceCandidate") != {"commit": C58, "tree": C58_TREE}
            or ledger.get("scope") != "source_navigation_only"
            or ledger.get("qualificationAfterCommitRequired") is not True):
        raise ValueError("ledger scope or source identity differs")
    for key in ("executionEvidenceTransferred", "qualificationRulesModified",
                "historicalSourceBasesModified", "historicalExecutionRecordsModified"):
        if ledger.get(key) is not False:
            raise ValueError("ledger attempts to transfer execution or change history")
    records = {row["mapPath"]: row for row in ledger["records"]}
    changed_maps = set(changes) - {LEDGER}
    if len(records) != len(ledger["records"]) or set(records) != changed_maps:
        raise ValueError("ledger records do not exactly cover changed Maps")
    rows = []
    for path in sorted(MAPS):
        old_raw = git.object("blob", before[path]["oid"])
        new_raw = git.object("blob", after[path]["oid"])
        old, new = parse_json(old_raw), parse_json(new_raw)
        if old.get("module") != MAPS[path] or new.get("module") != MAPS[path] or stable_map(old) != stable_map(new):
            raise ValueError("historical anchors, claims, candidates or non-navigation fields changed: " + path)
        if not set(old.get("observedSourcePaths", [])).issubset(new.get("observedSourcePaths", [])):
            raise ValueError("observed source path coverage narrowed")
        if not {row["path"] for row in old.get("sourceObjects", [])}.issubset({row["path"] for row in new.get("sourceObjects", [])}):
            raise ValueError("sourceObjects path coverage narrowed")
        if path in records:
            record = records[path]
            if new.get("observedAtHead") != {"commit": C58, "tree": C58_TREE}:
                raise ValueError("replacement observation is not the exact C58 source identity")
            expected_previous = {"commit": C58, "tree": C58_TREE, "blob": before[path]["oid"],
                                 "sha256": sha256(old_raw), "bytes": len(old_raw)}
            expected = {"module": MAPS[path], "previousMap": expected_previous,
                        "previousSourceBase": old.get("sourceBase"), "replacementSourceBase": new.get("sourceBase"),
                        "previousObservedAtHead": old.get("observedAtHead"), "replacementObservedAtHead": new.get("observedAtHead"),
                        "previousClaimBoundary": old.get("claimBoundary"), "withdrawnClaims": [],
                        "historicalCandidateRecordsModified": False, "replacementSha256": sha256(new_raw)}
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError("ledger original or replacement Map binding differs: " + path)
            old_observed = old.get("observedAtHead")
            if isinstance(old_observed, dict) and set(old_observed) - {"commit", "tree"}:
                archive = record.get("reviewedObservationArchival", {})
                if (MAPS[path] != "runtime.supervisor"
                        or before[path]["oid"] != "0ebfc4d68fd9cc6c60b9e612d3003f55bb97b89c"
                        or sha256(json.dumps(old_observed, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode())
                        != "68b7b5826763ebc54617a46d4d48b19fb4baa4a183f5b382923e5f56dc7a7be3"
                        or archive.get("previousObservedAtHead") != old_observed):
                    raise ValueError("special prior observation was not exactly retained")
        rows.append({"module": MAPS[path], "path": path, "changed": path in changed_maps,
                     "previous_blob": before[path]["oid"], "current_blob": after[path]["oid"],
                     "sourceBase_preserved": True, "claims_and_candidates_preserved": True})
    receipt_raw = Path(receipt_path).read_bytes()
    if sha256(receipt_raw) != RUN2_SHA256:
        raise ValueError("Run2 receipt is not the fixed reviewed evidence")
    receipt = parse_json(receipt_raw)
    if (receipt.get("candidate_commit") != C58 or receipt.get("source_after") != C58
            or receipt.get("candidate_tree") != C58_TREE or receipt.get("tree_after") != C58_TREE
            or receipt.get("exit") != 0 or receipt.get("source_status_before") != ""
            or receipt.get("status_after") != ""):
        raise ValueError("Run2 identity/result is inconsistent")
    for path, digest, size in [(log_path, receipt["log_sha256"], receipt["log_bytes"]),
                               (junit_path, receipt["junit"]["sha256"], receipt["junit"]["bytes"])]:
        raw = Path(path).read_bytes()
        if sha256(raw) != digest or len(raw) != size:
            raise ValueError("Run2 native log or XML differs from its original receipt")
    important = ["justfile", "codex-rs/justfile", "scripts/run-nextest.py", "codex-rs/.config/nextest.toml",
                 "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "rust-toolchain.toml", "codex-rs/rust-toolchain.toml"]
    git.clean_at(c1)
    return {"schema": "hepta.navigation-execution-input-equivalence.v1", "status": "TRACKED_INPUT_EQUIVALENCE_VERIFIED",
            "executed_source": {"commit": C58, "tree": C58_TREE}, "navigation_candidate": {"commit": c1, "tree": c1_tree},
            "candidate_parents": [C58], "tracked_projection_entries": len(old_projection),
            "before_projection_sha256": old_digest, "after_projection_sha256": new_digest,
            "projection_format": "UTF-8 canonical sorted JSON: path -> mode/type/oid; excludes only exact 40 Maps plus this one ledger",
            "changed_paths": [{"path": path, "before": before.get(path), "after": after.get(path)} for path in changes],
            "unchanged_key_inputs": {path: before[path] for path in important if path in before},
            "modules": rows, "ledger": {"path": LEDGER, "blob": after[LEDGER]["oid"], "sha256": sha256(ledger_raw)},
            "execution_evidence": {"original_commit_retained": C58, "receipt_sha256": RUN2_SHA256,
                                   "log_sha256": receipt["log_sha256"], "junit_sha256": receipt["junit"]["sha256"]},
            "candidate_checkout_clean_before_and_after": True,
            "tests_reexecuted_on_C1": False, "execution_identity_transferred": False,
            "qualification_verifier_required_separately": True,
            "limits": ["This verifies committed tracked inputs and navigation invariants, not a C1 execution.",
                       "The C58 Run2 environment/toolchain and result remain bound only to the original execution.",
                       "Native JUnit coverage and original strict Map qualification are separate receipts.",
                       "No product activation, production, release or external provider qualification is conferred."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--candidate-tree", required=True)
    parser.add_argument("--run-receipt", required=True)
    parser.add_argument("--run-log", required=True)
    parser.add_argument("--run-junit", required=True)
    args = parser.parse_args()
    try:
        report = verify(Git(args.repo), checked_oid(args.candidate), checked_oid(args.candidate_tree),
                        args.run_receipt, args.run_log, args.run_junit)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
