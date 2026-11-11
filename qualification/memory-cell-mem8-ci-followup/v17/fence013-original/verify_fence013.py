#!/usr/bin/env python3
"""Offline verification of one original Fence audit-mode qualification.

Uses only the Python standard library and retained bytes. It does not execute
the bundled binary, any original script, a test, Git, a host or a network call.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile

RUN = 43055103354
JOB = 130642329146
HARNESS = "0e92c37a012733882ce4c120afc38b6757edb7cb"
HARNESS_TREE = "60f86e9520355850e289769a83dc2bcca2f26811"
SOURCE = "c89540598693697577cda8cba31cb07f6ce65317"
SOURCE_TREE = "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae"
ACTION = "c7675fea986c29f1d655753a7a61fd6b4141be8f"
ACTION_SOURCE = "64acdc94f531728494efbdf2d8f05faa26e90f7a"
BRANCH = "codex/mem8-fence013-qualification-20261111-ed353817"
WORKFLOW = ".github/workflows/hepta-mem-fence013-qualification.yml"
ZIP_PIN = (1259429, "f6659c76f23a24d2a0b1e160f4874f2b6494922d39b016a65e4071455ce64574")
RAW_PIN = (1636940, "3743a63be1479793b42f4ba35415e6a4e5c26af43ff744909dc54196e08acb27")
TAR_PIN = (1251032, "895c0a1cfc36d539bf554a14d0c5412bd4ff4912b0b61ab67dd153690f851b99")
CAPTURE_PIN = (11520, "dcfeedbd7c96bab509c0cb38e43824c57fae8651cf84fafd020b10c5fde21f13")
WORKFLOW_PIN = (17930, "7174a2c51e265731df14838bc52ddde4986bbbcf8a1290fa769ba1eb6a68b91c")
BINARY_PIN = (2203880, "1a1ac7ad60216e7803403645c202e8c8a4e738326350ce340f8138df1c9a5e04")


def require(value, message):
    if not value:
        raise AssertionError(message)


def fingerprint(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def pin(data, expected, label):
    actual = fingerprint(data)
    require((actual["bytes"], actual["sha256"]) == expected, label)
    return actual


def match_fingerprint(data, expected, label):
    actual = fingerprint(data)
    require(all(actual[key] == expected[key] for key in actual), label)
    return actual


def safe_path(name):
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts and "\\" not in name,
            "unsafe archive path")
    require(str(path) == name and name not in ("", "."), "noncanonical archive path")


def parse_tree(data):
    require(data.endswith(b"\0"), "tree missing NUL terminator")
    entries = {}
    for record in data[:-1].split(b"\0"):
        header, path = record.split(b"\t", 1)
        mode, kind, sha = header.split(b" ")
        require(mode in (b"100644", b"100755", b"120000", b"160000"), "unknown Git mode")
        require(kind == (b"commit" if mode == b"160000" else b"blob"), "Git entry kind")
        require(re.fullmatch(b"[0-9a-f]{40}", sha) is not None, "Git object ID")
        safe_path(path.decode("utf-8"))
        require(path not in entries, "duplicate tree path")
        entries[path] = (mode, sha)
    return entries


def tree_sha(entries):
    root = {}
    for path, leaf in entries.items():
        node = root
        components = path.split(b"/")
        for name in components[:-1]:
            node = node.setdefault(name, {})
            require(isinstance(node, dict), "tree path collision")
        require(components[-1] not in node, "tree duplicate")
        node[components[-1]] = leaf

    def build(node):
        chunks = []
        for name, child in sorted(node.items(), key=lambda row: row[0] + (b"/" if isinstance(row[1], dict) else b"")):
            if isinstance(child, dict):
                mode, sha = b"40000", build(child)
            else:
                mode, sha = child[0], bytes.fromhex(child[1].decode())
            chunks.append(mode + b" " + name + b"\0" + sha)
        content = b"".join(chunks)
        return hashlib.sha1(b"tree " + str(len(content)).encode() + b"\0" + content).digest()
    return build(root).hex()


def moment(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify(root):
    original = root / "original"
    run = json.loads((original / "RUN_METADATA.json").read_bytes())
    jobs = json.loads((original / "JOBS_METADATA.json").read_bytes())
    artifact = json.loads((original / "ARTIFACT_METADATA.json").read_bytes())
    require(run["id"] == RUN and run["run_attempt"] == 1 and run["event"] == "push", "original run identity")
    require(run["head_sha"] == HARNESS and run["head_branch"] == BRANCH, "run source identity")
    require(run["status"] == "completed" and run["conclusion"] == "success", "run terminal")
    require(jobs["total_count"] == len(jobs["jobs"]) == 1, "single original job")
    job = jobs["jobs"][0]
    require(job["id"] == JOB and job["run_id"] == RUN and job["run_attempt"] == 1, "job identity")
    require(job["head_sha"] == HARNESS and job["head_branch"] == BRANCH, "job source")
    require(job["status"] == "completed" and job["conclusion"] == "success", "job terminal")
    require(job["labels"] == ["ubuntu-24.04"], "original runner label")
    require(len(job["steps"]) == 14 and all(s["status"] == "completed" and s["conclusion"] == "success" for s in job["steps"]), "all original steps")
    steps = {s["name"]: s for s in job["steps"]}
    require(len(steps) == 14, "unique original step names")
    post = steps["Post Run openai/fence@" + ACTION]
    require(moment(post["started_at"]) >= moment(steps["Preserve original qualification evidence before action post hooks"]["completed_at"]), "post after artifact")
    require(artifact["id"] == 13871008355 and artifact["workflow_run"]["id"] == RUN, "artifact identity")
    require(artifact["workflow_run"]["head_sha"] == HARNESS and artifact["workflow_run"]["head_branch"] == BRANCH, "artifact source")
    require(artifact["name"] == "mem8-fence013-qualification-43055103354-1", "artifact name")
    zip_bytes = (original / "ORIGINAL_ARTIFACT.zip").read_bytes()
    zip_identity = pin(zip_bytes, ZIP_PIN, "original ZIP bytes")
    require(artifact["size_in_bytes"] == len(zip_bytes) and artifact["digest"] == "sha256:" + zip_identity["sha256"], "API ZIP digest")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        require(z.testzip() is None, "original ZIP CRC")
        names = z.namelist()
        require(len(names) == len(set(names)) == 4, "original ZIP member count")
        for name in names:
            safe_path(name)
        require(set(names) == {"mem-fence013-qualification.tar.xz", "MANIFEST.json", "records/PREFLIGHT_CAPTURE.json", "records/AFTER_CAPTURE.json"}, "ZIP exact members")
        zipped = {name: z.read(name) for name in names}
    tar_identity = pin(zipped["mem-fence013-qualification.tar.xz"], TAR_PIN, "original inner archive")
    with tarfile.open(fileobj=io.BytesIO(zipped["mem-fence013-qualification.tar.xz"]), mode="r:xz") as t:
        members = t.getmembers()
        require(len(members) == 114 and all(m.isfile() for m in members), "all 114 regular tar members")
        require(len({m.name for m in members}) == 114, "no duplicate tar paths")
        for m in members:
            safe_path(m.name)
        data = {m.name: t.extractfile(m).read() for m in members}
    manifest = json.loads(data["MANIFEST.json"])
    require(manifest["fence_post_not_in_this_artifact"] is True and manifest["final_job_log_required"] is True, "original artifact limitation")
    rows = manifest["files"]
    require(len(rows) == len({r["path"] for r in rows}) == 113, "inner manifest count")
    require(set(data) == {r["path"] for r in rows} | {"MANIFEST.json"}, "manifest closed set")
    for row in rows:
        match_fingerprint(data[row["path"]], row, "inner file " + row["path"])
    for name in ("MANIFEST.json", "records/PREFLIGHT_CAPTURE.json", "records/AFTER_CAPTURE.json"):
        require(zipped[name] == data[name], "ZIP loose copy equality " + name)
    capture_identity = pin(data["capture.py"], CAPTURE_PIN, "capture script identity")
    workflow_identity = pin(data["records/harness-workflow.yml"], WORKFLOW_PIN, "actual workflow identity")
    capture_assignments = {}
    for node in ast.parse(data["capture.py"]).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                capture_assignments[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    expected_action = capture_assignments["EXPECTED_FILES"]
    require(len(expected_action) == 7, "seven fixed action files")
    require(capture_assignments["SOURCE"] == SOURCE and capture_assignments["SOURCE_TREE"] == SOURCE_TREE and capture_assignments["ACTION"] == ACTION and capture_assignments["ACTION_SOURCE"] == ACTION_SOURCE, "literal source/action identity")
    workflow_text = data["records/harness-workflow.yml"].decode()
    embedded = workflow_text.split("          cat > \"$root/capture.py\" <<'PY'\n", 1)[1].split("          PY\n", 1)[0]
    embedded = "".join(line[10:] for line in embedded.splitlines(keepends=True)).encode()
    require(embedded == data["capture.py"], "embedded capture is exact actual script")
    require("timeout-minutes: 30" in workflow_text and "runs-on: ubuntu-24.04" in workflow_text and "mode: audit" in workflow_text, "original qualification limits")
    captures = [json.loads(data["records/" + name + "_CAPTURE.json"]) for name in ("PREFLIGHT", "BEFORE", "AFTER")]
    for phase in captures:
        require(phase["capture_status"] == "complete" and phase["harness_sha"] == HARNESS and phase["source_anchor"] == SOURCE and phase["source_tree"] == SOURCE_TREE and phase["action_commit"] == ACTION, "capture identity")
        require(phase["run_id"] == str(RUN) and phase["run_attempt"] == "1", "capture original attempt")
        require(phase["model_requests"] == phase["native_tests_started_by_capture"] == 0, "capture does not run models/native")
        require(moment(job["started_at"]) <= moment(phase["started_at"]) <= moment(phase["completed_at"]) <= moment(job["completed_at"]), "capture in original job interval")
    require(all(moment(a["completed_at"]) <= moment(b["started_at"]) for a, b in zip(captures, captures[1:])), "capture order")
    preflight, before, after = captures
    require(after["capture_problems"] == [] and after["qualification_result"] == "NOT_FINAL", "original pre-post status preserved")
    require(after["fence_post_outcome"] == "NOT_YET_OBSERVED_REQUIRES_TERMINAL_FULL_JOB_LOG", "no fabricated artifact post")
    require(len(after["step_outcomes_before_posts"]) == 8 and set(after["step_outcomes_before_posts"].values()) == {"success"}, "original eight step outcomes")
    action_changes = {}
    for path, expected in expected_action.items():
        actual = match_fingerprint(data["records/action-runtime/" + path], expected, "actual action bytes " + path)
        a = preflight["action_files"][path]
        b = after["action_after"][path]
        require(all(a[k] == b[k] == actual[k] for k in actual), "action bytes before/after")
        for phase, observed in (("before", a), ("after", b)):
            require(json.loads(data["records/action-" + phase + "/" + path.replace("/", "__") + ".json"]) == observed, "action per-file receipt")
        action_changes[path] = {**actual, "mode_before": a["mode"], "mode_after": b["mode"]}
    binary_identity = pin(data["records/action-runtime/action/bin/fence"], BINARY_PIN, "full actual binary")
    bundle = json.loads(data["records/action-runtime/action/bundle-manifest.json"])
    require(bundle["source_commit"] == bundle["signer_digest"] == ACTION_SOURCE and bundle["release_tag"] == "v0.13.0" and bundle["repository"] == "openai/fence", "bundle provenance")
    require(bundle["artifact_sha256"] == binary_identity["sha256"] and bundle["bundle_path"] == "action/bin/fence", "binary manifest binding")
    require(before["source_before"] == after["source_after"], "whole source identity before/after")
    verified = before["source_before"]
    require(verified["head"] == HARNESS and verified["tree"] == HARNESS_TREE and verified["base_tree"] == SOURCE_TREE and verified["parents"] == [SOURCE] and verified["clean"] is True, "source verified identity")
    require(verified["workflow"] == workflow_identity, "source workflow proof")
    for phase in ("before", "after"):
        prefix = "records/source-" + phase + "/"
        require(json.loads(data[prefix + "VERIFIED.json"]) == verified, "source receipt equality")
        for path in sorted(data):
            if path.startswith(prefix) and path.endswith(".json"):
                receipt = json.loads(data[path])
                if "argv" not in receipt:
                    continue
                require(receipt["exit_code"] == 0 and receipt["argv"][:2] == ["git", "-C"], "original Git command exit")
                stem = path[:-5]
                match_fingerprint(data[stem + ".stdout"], receipt["stdout"], "Git stdout receipt")
                match_fingerprint(data[stem + ".stderr"], receipt["stderr"], "Git stderr receipt")
                require(data[stem + ".stderr"] == b"", "Git stderr empty")
        require(data[prefix + "status.stdout"] == data[prefix + "worktree-diff.stdout"] == b"", "actual clean source")
        require(data[prefix + "head.stdout"].strip().decode() == HARNESS and data[prefix + "tree.stdout"].strip().decode() == HARNESS_TREE, "raw source identity")
        require(data[prefix + "changes.stdout"] == b"A\0" + WORKFLOW.encode() + b"\0", "single added harness path")
    tree_bytes = data["records/source-before/full-tree.stdout"]
    require(tree_bytes == data["records/source-after/full-tree.stdout"], "full tree byte equality")
    match_fingerprint(tree_bytes, verified["full_tree"], "full tree receipt")
    entries = parse_tree(tree_bytes)
    require(len(entries) == 14054 and tree_sha(entries) == HARNESS_TREE, "full harness Merkle recomputation")
    require(entries[WORKFLOW.encode()] == (b"100644", workflow_identity["git_blob"].encode()), "workflow tree entry")
    base_entries = {p: e for p, e in entries.items() if p != WORKFLOW.encode()}
    require(len(base_entries) == 14053 and tree_sha(base_entries) == SOURCE_TREE, "exact source anchor Merkle recomputation")
    require(set(verified["source_files"]) == set(capture_assignments["SOURCE_FILES"]), "five policy files")
    for path, expected in verified["source_files"].items():
        body = data["records/original-policy-source/" + path]
        match_fingerprint(body, expected, "full original policy source")
        require(entries[path.encode()][1].decode() == expected["git_blob"], "policy source Git tree binding")
        for phase in ("before", "after"):
            require(data["records/source-" + phase + "/pinned-" + path.replace("/", "__") + ".stdout"] == body, "full pinned source equality")
    raw_bytes = (original / "original-job-130642329146.log").read_bytes()
    raw_identity = pin(raw_bytes, RAW_PIN, "complete original job raw")
    raw = raw_bytes.decode("utf-8-sig")
    lines = raw.splitlines()
    observed_markers = {}
    for label, marker in {
        "ready_audit_only": "Fence ready: audit mode is observing traffic, not blocking it",
        "seven_python_tests": "Ran 7 tests in 0.685s",
        "one_file_original_threshold": "Checked 1 changed file(s) against the 512000-byte limit.",
        "post_healthy": "Fence network report: healthy",
        "post_controls": "Controls: network=verified; sudo=preserved_verified; containers=preserved_verified",
        "post_verified": "✅ Fence evidence verified",
    }.items():
        matches = [i + 1 for i, line in enumerate(lines) if marker in line]
        require(len(matches) == 1, "unique actual raw marker " + label)
        observed_markers[label] = matches[0]
    ran_line = observed_markers["seven_python_tests"]
    require(any(re.fullmatch(r"\S+ OK", x) for x in lines[ran_line:ran_line + 3]), "actual unittest OK")
    report_lines = [(i + 1, line) for i, line in enumerate(lines) if " FENCE_REPORT_JSON=" in line]
    require(len(report_lines) == 1, "one actual final report")
    report_line, report_text = report_lines[0]
    report = json.loads(report_text.split(" FENCE_REPORT_JSON=", 1)[1])
    expected_controls = {"network": "verified", "sudo": "preserved_verified", "containers": "preserved_verified", "protection_available": False, "readiness": "ready_observation_only", "resident_health": "healthy"}
    require(report["schema_version"] == 1 and report["mode"] == "audit" and report["result"] == "healthy" and report["controls"] == expected_controls, "actual final Fence report")
    require(observed_markers["one_file_original_threshold"] < observed_markers["post_healthy"] < report_line < observed_markers["post_verified"], "raw downstream/post order")
    require(moment(after["completed_at"]) < moment(report_text.split(" ", 1)[0]), "report strictly after capture")
    report_identity = fingerprint(report_text.split(" FENCE_REPORT_JSON=", 1)[1].encode())
    prep = root / "preparation"
    prep_manifest = json.loads((prep / "PREPARATION_MANIFEST.json").read_bytes())
    require(len(prep_manifest["files"]) == 12, "frozen preparation closed set")
    for row in prep_manifest["files"]:
        match_fingerprint((prep / row["path"]).read_bytes(), row, "original preparation file")
    require((prep / "capture.py").read_bytes() == data["capture.py"], "prepared capture actual equality")
    require((prep / "source" / WORKFLOW).read_bytes() == data["records/harness-workflow.yml"], "prepared workflow actual equality")
    if (root / "MANIFEST.json").exists():
        package_manifest = json.loads((root / "MANIFEST.json").read_bytes())
        expected_paths = {r["path"] for r in package_manifest["files"]}
        actual_paths = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p != root / "MANIFEST.json"}
        require(expected_paths == actual_paths and len(expected_paths) == len(package_manifest["files"]), "outer package closed set")
        for row in package_manifest["files"]:
            safe_path(row["path"])
            match_fingerprint((root / row["path"]).read_bytes(), row, "outer package file")
    return {
        "schema": "mem-fence013-original-offline-audit-v1", "offline_verification": "PASS",
        "run_id": RUN, "job_id": JOB, "attempt": 1, "event": "push", "branch": BRANCH,
        "run_conclusion": run["conclusion"], "job_conclusion": job["conclusion"],
        "started_at": job["started_at"], "completed_at": job["completed_at"],
        "harness": {"head": HARNESS, "tree": HARNESS_TREE, "leaf_entries": len(entries)},
        "source_anchor": {"head": SOURCE, "tree": SOURCE_TREE, "leaf_entries": len(base_entries)},
        "source_before_after": {"whole_identity_equal": True, "full_tree_bytes_equal": True,
                                "clean_before": True, "clean_after_original_checks": True,
                                "recaptured_after_action_post": False, "five_original_policy_files_equal": True},
        "action_commit": ACTION, "reviewed_action_source": ACTION_SOURCE,
        "actual_action_files": action_changes, "bundle_manifest": bundle,
        "original_zip": zip_identity, "original_zip_members": 4,
        "original_tar": tar_identity, "original_tar_regular_members": 114,
        "all_manifest_entries_verified": 113, "full_raw": raw_identity,
        "workflow": workflow_identity, "capture": capture_identity,
        "actual_python_tests": 7, "python_summary": "OK", "changed_files_checked": 1,
        "original_blob_threshold_bytes": 512000,
        "original_steps_success": 14, "post_api_success": True,
        "raw_markers": observed_markers, "post_report_line": report_line,
        "post_report_json_utf8": report_identity,
        "post_controls": report["controls"], "post_mode": report["mode"], "post_result": report["result"],
        "original_capture_qualification_result": after["qualification_result"],
        "final_qualification": "PASS_FOR_THIS_AUDIT_MODE_ACTION_AND_ORIGINAL_POLICY_JOB",
        "model_requests_started_by_qualification": 0, "rust_native_tests_started": 0,
        "limitations": [
            "Audit mode observes traffic; protection_available=false is retained. No block-mode protection claim.",
            "The original changed-file range is the isolated one-workflow child of c895, not the full PR5935 diff.",
            "Original capture remains NOT_FINAL; the terminal API and complete original raw provide the later post outcome.",
            "Source snapshots bracket the original checks and precede action post hooks; no post-hook source snapshot was taken.",
            "This fresh original qualification does not establish the historical v0.10 unavailable subreason.",
            "No complete hosted CI, product owner custody, memory benefit or adoption gate is inferred.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--compare-audit", action="store_true")
    args = parser.parse_args()
    result = verify(args.root.resolve())
    if args.compare_audit:
        require(result == json.loads((args.root / "AUDIT.json").read_bytes()), "whole stored audit equality")
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
