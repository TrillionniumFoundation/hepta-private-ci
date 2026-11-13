import collections
import hashlib
import json
import os
from pathlib import Path
import subprocess


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


inventory_path = Path("/tmp/hepta-36fa-c0f-format-base-recovery-v1/CC57_INVENTORY.json")
map_path = Path("/tmp/hepta-36fa-at-b-composed-candidate-v1/EXACT_COMPOSED_OVERLAY.json")
overlay_dir = map_path.parent / "overlay"
inventory_bytes = inventory_path.read_bytes()
map_bytes = map_path.read_bytes()
assert identity(inventory_bytes) == {
    "bytes": 5611184,
    "sha256": "13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9",
    "git_blob": "7f94788b70546a8b8030dfd2b9182a7d9287c537",
}
assert identity(map_bytes) == {
    "bytes": 54410,
    "sha256": "ba2b642c5e1014fffa1151cca87e1b516c255f8d5ef549c633ce3f73fb615e57",
    "git_blob": "148e9efc242f3ee3ee4e525281ec170feecf3f19",
}
inventory = json.loads(inventory_bytes)
overlay = json.loads(map_bytes)
assert overlay["canonical_source_deletions"] == []
assert overlay["materializer_delete_operations"] == []
base = {}
for item in inventory["files"]:
    assert item["stable"] and item["matches_index"]
    assert item["working_blob"] == item["index_blob"]
    assert item["path"] not in base
    base[item["path"]] = {
        "path": item["path"], "mode": item["index_mode"],
        "sha": item["index_blob"], "type": "blob",
    }
assert len(base) == 15188
final = dict(base)
classes = collections.Counter()
updates = []
coverage = overlay["rust_files"] + overlay["non_rust_prepared"]
assert len(coverage) == 110
assert len({item["path"] for item in coverage}) == 110
for item in coverage:
    raw = (overlay_dir / item["path"]).read_bytes()
    assert identity(raw) == {k: item[k] for k in ("bytes", "sha256", "git_blob")}
    old = base.get(item["path"])
    assert item["original_git_blob"] == (old["sha"] if old else None)
    if old:
        assert old["mode"] == item["mode"]
    row = {"path": item["path"], "mode": item["mode"], "sha": item["git_blob"], "type": "blob"}
    kind = "new" if old is None else "unchanged" if old == row else "modified"
    classes[kind] += 1
    final[item["path"]] = row
    if row != old:
        updates.append(row)
assert dict(classes) == {"new": 49, "modified": 60, "unchanged": 1}

out = Path("/tmp/hepta-36fa-root-git-source-tree-audit-v1")
out.mkdir(exist_ok=False)
gitdir = out / "audit.git"
subprocess.run(["git", "init", "--bare", "--quiet", str(gitdir)], check=True, capture_output=True)
roots = {}
for name, rows in [("baseline", base), ("candidate", final)]:
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(out / (name + ".index"))
    index_info = b"".join(
        (row["mode"] + " " + row["sha"] + "\t" + path).encode() + b"\0"
        for path, row in sorted(rows.items())
    )
    subprocess.run(["git", "--git-dir", str(gitdir), "update-index", "-z", "--index-info"],
                   input=index_info, env=env, check=True, capture_output=True)
    result = subprocess.run(["git", "--git-dir", str(gitdir), "write-tree", "--missing-ok"],
                            env=env, check=True, capture_output=True)
    roots[name] = result.stdout.decode().strip()
assert roots["baseline"] == "b7b357c07b5539769a068c6b9b009629f5612d1e"
proof = {
    "format": "hepta-final110-independent-git-write-tree-review-v1",
    "inventory": identity(inventory_bytes), "overlay": identity(map_bytes),
    "roots": roots, "classification": dict(classes),
    "baseline_files": len(base), "expected_candidate_files": len(final),
    "expected_candidate_rust_files_all_repository": sum(p.endswith(".rs") for p in final),
    "expected_candidate_rust_files_codex_rs": sum(p.startswith("codex-rs/") and p.endswith(".rs") for p in final),
    "candidate_modes": dict(collections.Counter(x["mode"] for x in final.values())),
    "update_count": len(updates), "canonical_deletions": [],
    "all_110_local_source_bytes_match_fixed_map": True,
    "method": "Git update-index --index-info and write-tree --missing-ok in a create-only empty local bare repository with separate new indices. No original source repository or index is touched. The supplied graph identifies missing blobs; this does not materialize their whole source snapshot.",
    "physical_source_materialized": False, "source_ref_changed": False,
    "H_executed": False, "qualification": False,
}
(out / "REVIEW.json").write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
(out / "UPDATES.json").write_text(json.dumps(updates, indent=2, sort_keys=True) + "\n")
(out / "FINAL_FILE_GRAPH.json").write_text(json.dumps(final, indent=2, sort_keys=True) + "\n")
print(json.dumps(proof, indent=2, sort_keys=True))
