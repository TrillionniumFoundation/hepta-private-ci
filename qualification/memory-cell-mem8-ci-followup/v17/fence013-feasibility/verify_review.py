#!/usr/bin/env python3
"""Offline byte, tree and one-line candidate verification; no host/native execution."""
import argparse
import hashlib
import json
from pathlib import Path

def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def tree(entries):
    root = {}
    for entry in entries:
        if entry["type"] != "blob":
            continue
        node = root
        parts = entry["path"].split("/")
        assert all(p not in ("", ".", "..") for p in parts)
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (entry["mode"], entry["sha"])
    def walk(node):
        data = b""
        for name, item in sorted(node.items(), key=lambda kv: (kv[0] + ("/" if isinstance(kv[1], dict) else "")).encode()):
            mode, sha = ("40000", walk(item)) if isinstance(item, dict) else (item[0].lstrip("0"), item[1])
            data += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)
        return hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()
    return walk(root)

def function(source, name):
    start = source.index("fn " + name + "(")
    pos = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[pos] == "{") - (source[pos] == "}")
        pos += 1
    return source[start:pos].encode()

def verify(root):
    manifest = json.loads((root / "FILE_MANIFEST.json").read_text())
    for item in manifest["files"]:
        path = root / item["path"]
        assert path.is_file() and not path.is_symlink()
        data = path.read_bytes()
        assert len(data) == item["bytes"], item["path"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"], item["path"]
        assert blob(data) == item["git_blob"], item["path"]
    source = json.loads((root / "SOURCE_TREE.json").read_text())
    action = json.loads((root / "TREE.json").read_text())
    sc = json.loads((root / "SOURCE_COMMIT.json").read_text())
    ac = json.loads((root / "ACTION_COMMIT.json").read_text())
    assert tree(source["tree"]) == sc["tree"]["sha"] == "228ce4925c73cf194b76094cbaf70494f2ff4ad9"
    assert tree(action["tree"]) == ac["tree"]["sha"] == "e19987188c430cdbf901557955ca537a644bbbbd"
    assert [p["sha"] for p in ac["parents"]] == [sc["sha"]]
    src = {e["path"]:(e["mode"],e["sha"]) for e in source["tree"] if e["type"] == "blob"}
    act = {e["path"]:(e["mode"],e["sha"]) for e in action["tree"] if e["type"] == "blob"}
    diff = [p for p in sorted(src.keys() | act.keys()) if src.get(p) != act.get(p)]
    assert diff == ["action/bin/fence", "action/bundle-manifest.json"]
    for index_name, prefix in [("SOURCE_INDEX.json", ""), ("v010/SOURCE_INDEX.json", "v010/")]:
        index = json.loads((root / index_name).read_text())
        for item in index["files"]:
            path = item["path"] if prefix else "upstream/" + item["path"]
            data = (root / (prefix + path)).read_bytes()
            assert len(data) == item.get("bytes", item.get("size"))
            assert blob(data) == item.get("git_blob", item.get("sha"))
    original = (root / "original-workflow.yml").read_bytes()
    candidate = (root / "candidate/.github/workflows/blob-size-policy.yml").read_bytes()
    before = b"openai/fence@e6b39c80c51cb2b2a39448ddeff74b3b886c0a63 # pin@v0.10.0"
    after = b"openai/fence@c7675fea986c29f1d655753a7a61fd6b4141be8f # pin@v0.13.0"
    assert original.count(before) == candidate.count(after) == 1
    assert original.replace(before, after) == candidate
    assert blob(original) == "d870b6f9c1e025aff458c32f0461c752fcd2f0b3"
    assert blob(candidate) == "7e01fc010f7c5dd48a2d5f688283e8795436fdcf"
    old = (root / "v010/upstream/src/local_control.rs").read_text()
    new = (root / "upstream/src/local_control.rs").read_text()
    for name in ("verify_complete_local_control_observation", "verify_local_control_observation"):
        assert function(old, name) == function(new, name)
    old_limits = [l for l in old.splitlines() if l.startswith("pub const ")]
    new_limits = [l for l in new.splitlines() if l.startswith("pub const ")]
    assert old_limits == new_limits and len(old_limits) == 11
    bm = json.loads((root / "upstream/action/bundle-manifest.json").read_text())
    release = json.loads((root / "RELEASE.json").read_text())
    asset = next(x for x in release["assets"] if x["name"] == bm["artifact_name"])
    assert "sha256:" + bm["artifact_sha256"] == asset["digest"]
    assert bm["source_commit"] == sc["sha"]
    assert release["target_commitish"] == ac["sha"]
    return {"offline_identity_and_candidate_verified":True, "manifest_files":len(manifest["files"]), "source_leaves":len(src), "action_leaves":len(act), "only_action_additions":diff, "all_11_limits_byte_equal":True, "both_rejection_functions_byte_equal":True, "candidate_single_pin_line_only":True, "binary_bytes_independently_read":False, "native_or_host_executions":0, "original_subreason":"UNKNOWN", "security_audit_of_entire_release":False}
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parent))
    result = verify(Path(parser.parse_args().root))
    print(json.dumps(result, sort_keys=True))
