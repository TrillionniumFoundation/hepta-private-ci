"""Restore fixed source evidence and independently bind its selected Git leaves."""

import datetime
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys


BASE = Path(__file__).resolve().parent.parent


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    raw = path.read_bytes()
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def main():
    packet = BASE / "round3_ci/linux_delegation_source_review_checkpoint_20261107"
    publication = BASE / "round3_ci/LINUX_DELEGATION_SOURCE_REVIEW_EVIDENCE_PUBLICATION.json"
    proof = BASE / "round3_local_qualification/linux_delegation_checkpoint_root"
    destination = BASE / "round3_root_restore_linux_delegation_0030"
    proof.mkdir(exist_ok=False)
    require(identity(publication)["sha256"] == "f82a7b12b9ee7bc2ac96b11a241188d3765d361e42e2960d9373cf78e7a7d081", "frozen manifest")
    manifest = json.loads(publication.read_bytes())
    index_file = packet / "INDEX.json"
    require(identity(index_file) == manifest["index"], "frozen index")
    index = json.loads(index_file.read_bytes())
    previous = BASE / "round3_ci/arm5160_timeout_timing_checkpoint_20261106/restore.py"
    require(identity(previous)["sha256"] == "f00d134d04ba7e18eb169b217b7d66ee2c2883c04e9e93a806043e5a16b48d2b", "previous reviewed reader")
    pattern = r'EXPECTED_INDEX_SHA256 = "[a-f0-9]{64}"'
    old, old_count = re.subn(pattern, 'EXPECTED_INDEX_SHA256 = "SEAL"', previous.read_text())
    new, new_count = re.subn(pattern, 'EXPECTED_INDEX_SHA256 = "SEAL"', (packet / "restore.py").read_text())
    require(old_count == new_count == 1 and old == new, "only one reader seal changes")
    frozen = {}
    for row in manifest["files"]:
        path = Path(row["source_file"])
        require(path.parent == packet and path.name == row["path"] and row["mode"] == "100644", "publication paths")
        require(identity(path) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "publication identity")
        frozen[str(path.relative_to(BASE))] = identity(path)
    require(len(frozen) == 5, "publication file count")
    command = [sys.executable, "-O", "-B", str(packet / "restore.py"), str(destination)]
    run = subprocess.run(command, capture_output=True)
    (proof / "restore.stdout.log").write_bytes(run.stdout)
    (proof / "restore.stderr.log").write_bytes(run.stderr)
    require(run.returncode == 0, "original reader exit")
    expected = {row["path"] for row in index["files"]}
    actual = {str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()}
    require(expected == actual and len(expected) == len(index["files"]) == 99, "complete inert inventory")
    require(not any(re.search(r"/job_[0-9]+\.(log|raw\.json)$", name) for name in expected), "private job logs excluded")
    total = 0
    for row in index["files"]:
        original = BASE / row["path"]
        restored = destination / row["path"]
        wanted = {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        require(identity(original) == identity(restored) == wanted, "original and restored identities")
        for path in (original, restored):
            require(stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink(), "regular evidence")
        require(stat.S_IMODE(original.stat().st_mode) == int(row["original_mode"], 8), "original permission")
        require(stat.S_IMODE(restored.stat().st_mode) == 0o644, "inert restored permission")
        total += row["bytes"]
    require(total == manifest["raw_source_bytes"] == 6418203, "raw byte total")
    freeze_path = BASE / "round3_ci/restricted_delegation_followup/FREEZE.json"
    require(identity(freeze_path) == manifest["qualification_scope"]["original_source_freeze"], "original freeze identity")
    freeze = json.loads(freeze_path.read_bytes())
    require(len(freeze["files"]) == 95 and freeze["total_bytes"] == 6365093, "original freeze scope")
    for row in freeze["files"]:
        require(row["path"] in expected, "frozen source omitted")
        current = identity(BASE / row["path"])
        require(all(current[key] == row[key] for key in ("bytes", "sha256")), "original freeze changed")
    sources = json.loads((BASE / "round3_ci/restricted_delegation_followup/SOURCE_INDEX.json").read_bytes())
    addendum = json.loads((BASE / "round3_ci/restricted_delegation_followup/host_addendum/POLICY_SOURCE_BINDING.json").read_bytes())
    api_file = BASE / "round3_linux_delegation_root_api.json"
    results = json.loads(api_file.read_bytes())["results"]
    require(len(results) == 4 and all(row["status"] == "fulfilled" for row in results), "fresh API calls")
    counts = []
    for prefix, offset, files in (
        ("repository", 0, sources["repository_files"] + [addendum["source"]]),
        ("kernel", 2, sources["kernel_files"]),
    ):
        commit = json.loads(results[offset]["value"]["structuredContent"]["content"])
        require(commit["sha"] == sources[prefix + "_commit"] and commit["tree"]["sha"] == sources[prefix + "_tree"], "fresh commit and tree")
        leaves = results[offset + 1]["value"]
        require(set(leaves) == {row["repository_path"] for row in files}, "fresh leaf coverage")
        for row in files:
            leaf = leaves[row["repository_path"]]
            require(leaf is not None and (leaf["sha"], leaf["mode"], leaf["size"]) == (row["git_blob"], row["git_mode"], row["bytes"]), "fresh leaf binding")
            require(identity(BASE / row["path"]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "exact selected source body")
        counts.append(len(files))
    require(counts == [12, 16], "selected source counts")
    for path, wanted in frozen.items():
        require(identity(BASE / path) == wanted, "packet changed during restore")
    result = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Independent inert restoration and fresh selected source binding; conditional proof review only",
        "publication": identity(publication), "index": identity(index_file),
        "reader": identity(packet / "restore.py"), "previous_reader": identity(previous),
        "reader_only_fixed_seal_changes": 1, "command": command, "exit_code": run.returncode,
        "files": len(expected), "raw_bytes": total,
        "all_originals_and_restored_bytes_and_modes_match": True,
        "original_95_file_freeze_unchanged_and_complete": True,
        "fresh_selected_repository_leaves": counts[0], "fresh_selected_kernel_leaves": counts[1],
        "fresh_two_commit_tree_bindings": True, "fresh_API": identity(api_file),
        "bundle_before_and_after_unchanged": True, "bundle_identities": frozen,
        "restored_permissions": "0644 regular files", "destination": str(destination),
        "archived_sources_or_native_tests_or_new_syscalls_executed": False,
        "qualification": manifest["qualification_scope"],
        "limits": [
            "Both reports were read in full; the host-path argument is conditional on unimplemented runtime invariants.",
            "A fixed namespace ID alone is not a reachability or policy-alias lifetime proof.",
            "The upstream kernel source is not claimed equal to the observed Azure kernel.",
            "No Linux availability flag, fallback, product implementation or native pass is established.",
        ],
    }
    path = proof / "ROOT_REVIEW.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"files": len(expected), "bytes": total, "review": identity(path)}))


if __name__ == "__main__":
    main()
