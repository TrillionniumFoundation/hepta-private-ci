#!/usr/bin/env python3
"""Root offline verification of the original source-only CI bytes and identities."""
import base64
import datetime
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
# Pass the restored original-run directory when replaying from an evidence checkout.
P = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else ROOT.parent / "mem8-source-ci-v5-original-run"
assert len(sys.argv) <= 2, "usage: verify_source_ci_original.py [original-run-directory]"

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def obj(kind, raw):
    return hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def valid_name(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and "\\" not in name

def tree_rows(raw):
    rows = {}
    for line in raw.split(b"\0"):
        if not line:
            continue
        attr, path = line.split(b"\t", 1)
        mode, kind, ident = attr.decode().split()
        path = path.decode()
        assert valid_name(path) and path not in rows and kind in ["blob", "commit"]
        rows[path] = (mode, kind, ident)
    return rows

def tree_hash(rows):
    root = {}
    for name, value in rows.items():
        d = root
        parts = name.split("/")
        for part in parts[:-1]:
            d = d.setdefault(part, {})
            assert isinstance(d, dict)
        assert parts[-1] not in d
        d[parts[-1]] = value
    def visit(d):
        content = b""
        for name, value in sorted(d.items(), key=lambda p: (p[0] + ("/" if isinstance(p[1], dict) else "")).encode()):
            mode, ident = ("40000", visit(value)) if isinstance(value, dict) else (value[0], value[2])
            content += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(ident)
        return obj("tree", content)
    return visit(root)

tar_raw = (P / "mem8-source-gates-v5-records.tar.xz").read_bytes()
assert len(tar_raw) == 1783500 and sha(tar_raw) == "6718333beb6ea7b6faefc2bd026413e8ab1413f24bf4f377a773fc0264dd288a"
assert obj("blob", tar_raw) == "eb285beb4588ab1aee652a785881c5d37d932292"
with tarfile.open(fileobj=io.BytesIO(tar_raw), mode="r:xz") as t:
    entries = t.getmembers()
    assert len(entries) == len({m.name for m in entries}) == 335
    assert all(m.isfile() and valid_name(m.name) for m in entries)
    data = {m.name: t.extractfile(m).read() for m in entries}
manifest = json.loads(data["FILE_MANIFEST.json"])["members"]
assert len(manifest) == len({r["path"] for r in manifest}) == 334
assert set(data) == {r["path"] for r in manifest} | {"FILE_MANIFEST.json"}
for r in manifest:
    raw = data[r["path"]]
    assert len(raw) == r["bytes"] and sha(raw) == r["sha256"] and obj("blob", raw) == r["git_blob"]
    assert raw == (P / "records" / r["path"]).read_bytes()
zip_raw = (P / "mem8-source-gates-v5-43015979473-1.zip").read_bytes()
assert len(zip_raw) == 6299090
with zipfile.ZipFile(io.BytesIO(zip_raw)) as z:
    assert z.testzip() is None
    assert len(z.namelist()) == len(set(z.namelist())) == 337
    assert all(valid_name(n) and not n.endswith("/") for n in z.namelist())
    zip_members = [{"name": n, "bytes": len(z.read(n)), "sha256": sha(z.read(n))} for n in z.namelist()]
    names = [n for n in z.namelist() if n.endswith("/mem8-source-gates-v5-records.tar.xz") or n == "mem8-source-gates-v5-records.tar.xz"]
    assert len(names) == 1 and z.read(names[0]) == tar_raw
source_input = json.loads(data["INPUT.json"])
assert lzma.decompress(data["INPUT.json.xz"]) == data["INPUT.json"]
assert len(data["INPUT.json.xz"]) == 333228 and sha(data["INPUT.json.xz"]) == "948e8c9ff924317f55feaa45a0c9bac92c29196f6bf652a888ddf7c8795bb0d0"
assert len(data["DRIVER.py"]) == 23280 and sha(data["DRIVER.py"]) == "f32ca75f21c2097a30bda5892606aef80c62e4072837de7e99e42b56b17cfcf9"
assert obj("blob", data["AGENTS.md"]) == "faa57cc0db48123e1011f1eb47692cd3bbbcfc3a"
capsule = json.loads(data["FORMATTED_CAPSULE.json"])
before = tree_rows(data["BASE_TREE.ls-tree"])
initial = tree_rows(data["INITIAL_TREE.ls-tree"])
after = tree_rows(data["CANDIDATE_TREE.ls-tree"])
assert len(before) == 14037 and len(initial) == len(after) == 14048
expected = ["12159640adcf073b51f3837e75575e11f5c20233", "e9ba2746237562d68b1c732bee0f86df9e352cde", "c77785ecb368c44ea699769001a47402c9f50591"]
assert [tree_hash(x) for x in [before, initial, after]] == expected
assert len(source_input["files"]) == len(capsule["files"]) == 103
initial_overlay, final_overlay = dict(before), dict(before)
for r in source_input["files"]:
    raw = r["content"].encode()
    assert len(raw) == r["bytes"] and sha(raw) == r["sha256"] and obj("blob", raw) == r["input_git_blob"]
    assert data["pre-format/" + r["path"]] == raw
    initial_overlay[r["path"]] = (r["mode"], "blob", r["input_git_blob"])
    if r["preimage_git_blob"] is None:
        assert r["path"] not in before
    else:
        assert before[r["path"]][2] == r["preimage_git_blob"] == obj("blob", data["base/" + r["path"]])
for r in capsule["files"]:
    raw = base64.b64decode(r["content_base64"], validate=True)
    assert len(raw) == r["postimage_bytes"] and sha(raw) == r["postimage_sha256"] and obj("blob", raw) == r["postimage_git_blob"]
    assert data["post-format/" + r["path"]] == raw
    final_overlay[r["path"]] = (r["mode"], "blob", r["postimage_git_blob"])
assert initial_overlay == initial and final_overlay == after
changed = sorted(p for p in after if after[p] != initial[p])
assert len(changed) == 21
for p in ["codex-rs/Cargo.lock", "MODULE.bazel.lock"]:
    assert before[p] == initial[p] == after[p]
result = json.loads(data["RESULT.json"])
start = json.loads(data["START.json"])
assert result["status"] == "passed_source_gates_only_review_remaining" and result["failure"] is None
assert result["candidate_tree"] == expected[2] and result["initial_tree"] == expected[1]
assert result["source_before"]["status"] == ""
assert result["source_before"]["head"] == result["source_after"]["head"] == "c842e995b047eb2ee7d81c073f14fb2fcaa6bff2"
assert sorted(line[3:] for line in result["source_after"]["status"].splitlines()) == changed
assert result["source_after"]["tree"] == expected[1]
t0, t1, deadline = [datetime.datetime.fromisoformat(result[k]) for k in ["started_at", "finished_at", "deadline_utc"]]
assert (deadline - t0).total_seconds() == 600 and t0 < t1 < deadline
assert start["workflow_commit"] == "720f7ff5042a66490e2433bf4652c2eef93e4b7d" and start["workflow_run"] == "43015979473"
assert result["native_tests_executed"] == result["model_requests_executed"] == 0
assert result["source_refs_modified"] is False and result["source_candidate_committed"] is False
phases = ["format", "diff-check", "full-tree-old-case-name-scan", "caller-self-test", "caller-verify", "stage-formatted-candidate"]
for phase in phases:
    r = json.loads(data[phase + ".json"])
    raw = data[r["raw_file"]]
    assert len(raw) == r["bytes"] and sha(raw) == r["sha256"] and obj("blob", raw) == r["git_blob"]
    assert not r["timed_out"] and r["exit_code"] == (1 if phase == "full-tree-old-case-name-scan" else 0)
    assert t0 <= datetime.datetime.fromisoformat(r["started_at"]) <= datetime.datetime.fromisoformat(r["finished_at"]) <= t1
assert json.loads(data["format.json"])["command"] == ["just", "fmt", "--base", "2ae5215beaf8d7b7df111a090b82134beae2683d"]
rename = json.loads(data["FULL_TREE_RENAME_SCAN.json"])
assert len(rename["renames"]) == 13 and not rename["matches"] and rename["review_required"] is False
caller = json.loads(data["caller-verify.raw.log"])
assert caller["status"] == "PASS_HEPTA_CALLER_CLOSED_SET" and caller["rustFilesScanned"] == 6200 and caller["authorityGranted"] is False
patch = (P / "FORMAT_ONLY.patch").read_bytes()
assert len(patch) == 27705 and sha(patch) == "2fab5b3fad7459e925260f1173a07a56fdf15ac71c3ab4a9c5a5d0c13304ae79"
report = {"schema": "hepta.mem8.source-ci-v5.root-original-audit.v1", "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "original_run": 43015979473, "original_job": 130507034042, "workflow_head": start["workflow_commit"], "source_head_unchanged": result["initial_commit"], "source_initial_tree": expected[1], "formatted_tree": expected[2], "zip": {"bytes": len(zip_raw), "sha256": sha(zip_raw), "regular_members_crc_and_hash_verified": 337}, "tar": {"bytes": len(tar_raw), "sha256": sha(tar_raw), "git_blob": obj("blob", tar_raw), "regular_members_verified": 335}, "three_complete_trees_independently_recomputed": True, "overlay_paths_verified": 103, "formatter_delta_reviewed_in_full": {"paths": changed, "patch_bytes": len(patch), "patch_sha256": sha(patch), "finding": "Rust formatting and import order; BUILD load and keyword argument order, final newline. No semantic change identified."}, "source_after": "original HEAD unchanged; exact 21 formatter modifications staged", "original_deadline_seconds": 600, "started_at": result["started_at"], "finished_at": result["finished_at"], "elapsed_seconds": (t1-t0).total_seconds(), "old_case_names_scanned": 13, "old_case_hits": 0, "caller_rust_files_scanned": 6200, "caller_authority_granted": False, "locks_unchanged": True, "native_tests": 0, "model_requests": 0, "qualification": "SOURCE_GATES_PASSED_AND_FORMAT_DELTA_REVIEWED", "remaining": ["New Bazel dependency graph and lock qualification", "Native tests for the changed source", "Original owner, provider, scientific benefit and independent trust/adoption gates"]}
(ROOT / "ROOT_SOURCE_CI_V5_AUDIT.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
