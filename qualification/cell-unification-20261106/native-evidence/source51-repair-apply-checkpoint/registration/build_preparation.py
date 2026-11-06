#!/usr/bin/env python3
"""Derive an inert two-file source51 plan from seven immutable direct trees."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
BASE_COMMIT = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
BASE_TREE = "ea48acf562499192a25e05ae28926a32632dee62"
REPO = "TrillionniumFoundation/hepta-private-ci"
TREE_SPECS = {
    "root": ("", BASE_TREE),
    "codex": ("codex-rs", "6640ff87fe177e3a49c3356c487bee0329d74768"),
    "exec": ("codex-rs/exec-server", "9906e97bad73cb14868c42bb56feb038aba9fb00"),
    "exec_tests": ("codex-rs/exec-server/tests", "ec4d348841738c5bbf5431877b5eeda495d4443b"),
    "exec_common": ("codex-rs/exec-server/tests/common", "f7e9f755c1e8f20b7c3fc1966ea3230567a6db0e"),
    "network": ("codex-rs/network-proxy", "37b5d6d529a1632cecc1b1c023fb1c874065fba4"),
    "network_src": ("codex-rs/network-proxy/src", "69903c19eeb71b1f28247d5bda82b51e5146d939"),
}
EDGES = [
    ("root", "codex-rs", "codex"),
    ("codex", "exec-server", "exec"),
    ("exec", "tests", "exec_tests"),
    ("exec_tests", "common", "exec_common"),
    ("codex", "network-proxy", "network"),
    ("network", "src", "network_src"),
]
TARGETS = [
    {
        "path": "codex-rs/exec-server/tests/common/fake_bwrap.rs",
        "directory": "exec_common",
        "name": "fake_bwrap.rs",
        "origin": "exec-server-bwrap-r24-repair",
        "patch_name": "repair.patch",
        "before_blob": "cc79362f7a8a3a44b0a93949d18494281511ec7b",
        "after_blob": "e74489437549cf2c61075fd893945cd78e34247c",
        "after_sha256": "83d3637f2648b967c70e2368c623fe0b84afe1cdf32860284d897923ad0dc1ca",
        "patch_sha256": "0f8ee51664c850a9fd450bcba800d3ffb6866633f1924845b058ffadcc7b1ba8",
    },
    {
        "path": "codex-rs/network-proxy/src/http_proxy.rs",
        "directory": "network_src",
        "name": "http_proxy.rs",
        "origin": "source51-network-candidate",
        "patch_name": "network-fixture.patch",
        "before_blob": "50135c6cd4c426c3ec16d65d448c01a1fb776ddd",
        "after_blob": "17220a242091325aa66bd4cdb3419cd3a30b09ed",
        "after_sha256": "f8b6cb1adf67ea828efb29f68e10fd97a30e379574c93374c2a88f5364153967",
        "patch_sha256": "24fcba74cab54f242f1249bddf43ebc3be2bd3bbb7f16964dd7f24f334989198",
    },
]


def pin(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def exact(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data, f"Existing different bytes: {path}"
    else:
        with path.open("xb") as handle:
            handle.write(data)


def emit(path: str, value: dict) -> None:
    exact(HERE / path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def canonical_entries(entries: list[dict]) -> list[dict]:
    assert len({e["path"] for e in entries}) == len(entries)
    result = []
    for entry in entries:
        assert entry["path"] and "/" not in entry["path"] and "\0" not in entry["path"]
        mode = int(entry["mode"], 8)
        expected_type = "tree" if mode == 0o40000 else ("commit" if mode == 0o160000 else "blob")
        assert mode in (0o40000, 0o100644, 0o100755, 0o120000, 0o160000)
        assert entry["type"] == expected_type
        assert re.fullmatch("[0-9a-f]{40}", entry["sha"])
        result.append({k: entry[k] for k in ("path", "mode", "type", "sha")})
    return sorted(result, key=lambda e: e["path"].encode() + (b"/" if e["type"] == "tree" else b""))


def tree_hash(entries: list[dict]) -> tuple[str, bytes]:
    body = b"".join(
        f"{int(e['mode'], 8):o} ".encode() + e["path"].encode() + b"\0" + bytes.fromhex(e["sha"])
        for e in canonical_entries(entries)
    )
    return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest(), body


def apply_unified(inputs: dict[str, bytes], patch: bytes, reverse: bool = False) -> dict[str, bytes]:
    """Small strict unified-hunk reader; all context/deletion lines must match."""
    lines = patch.decode().splitlines(keepends=True)
    cursor = 0
    result = {}
    while cursor < len(lines):
        assert lines[cursor].startswith("--- a/")
        path = lines[cursor][6:].rstrip("\n")
        assert lines[cursor + 1] == f"+++ b/{path}\n"
        assert path in inputs and path not in result
        cursor += 2
        original = inputs[path].decode().splitlines(keepends=True)
        old_cursor, output = 0, []
        while cursor < len(lines) and lines[cursor].startswith("@@ "):
            match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*\n", lines[cursor])
            assert match
            old_start, old_count, new_start, new_count = (int(match.group(1)), int(match.group(2) or 1), int(match.group(3)), int(match.group(4) or 1))
            if reverse:
                old_start, old_count, new_start, new_count = new_start, new_count, old_start, old_count
            assert old_start >= 1 and new_start >= 1 and old_cursor <= old_start - 1
            output.extend(original[old_cursor:old_start - 1])
            old_cursor = old_start - 1
            assert len(output) == new_start - 1
            old_used = new_used = 0
            cursor += 1
            while old_used < old_count or new_used < new_count:
                row = lines[cursor]
                operation, content = row[0], row[1:]
                assert operation in " +-"
                if reverse and operation != " ":
                    operation = "+" if operation == "-" else "-"
                if operation in " -":
                    assert original[old_cursor] == content
                    old_cursor += 1
                    old_used += 1
                if operation in " +":
                    output.append(content)
                    new_used += 1
                cursor += 1
            assert old_used == old_count and new_used == new_count
        output.extend(original[old_cursor:])
        result[path] = "".join(output).encode()
    assert set(result) == set(inputs)
    return result


def main() -> None:
    original_trees, queries = {}, []
    for key, (path, expected_sha) in TREE_SPECS.items():
        filename = f"input/original-trees/{key}.json"
        raw = (HERE / filename).read_bytes()
        payload = json.loads(raw)
        assert payload["sha"] == expected_sha and payload["truncated"] is False
        calculated, body = tree_hash(payload["tree"])
        assert calculated == expected_sha, (key, calculated, expected_sha)
        original_trees[key] = canonical_entries(payload["tree"])
        queries.append({"directory": path, "key": key, "file": filename, **pin(raw), "request_url": f"https://api.github.com/repos/{REPO}/git/trees/{expected_sha}", "recursive": False, "git_tree": expected_sha, "computed_git_tree": calculated, "entries": len(payload["tree"]), "tree_object_body_bytes": len(body)})
    for parent, name, child in EDGES:
        entry = next(e for e in original_trees[parent] if e["path"] == name)
        assert entry["type"] == "tree" and entry["sha"] == TREE_SPECS[child][1]

    base_path = WORK / "source50-preparation/native-candidate-r24-source.json"
    base_raw = base_path.read_bytes()
    assert pin(base_raw)["sha256"] == "ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0"
    exact(HERE / "input/source50-actual-manifest.json", base_raw)
    base = json.loads(base_raw)
    assert base["source_commit"] == BASE_COMMIT and base["source_tree"] == BASE_TREE
    assert len(base["changed_files"]) == 194
    assert len({row["path"] for row in base["changed_files"]}) == 194

    before_map, after_map, changes, patch_parts = {}, {}, [], []
    for target in TARGETS:
        path = target["path"]
        before = (WORK / target["origin"] / "original" / path).read_bytes()
        after = (WORK / target["origin"] / "source" / path).read_bytes()
        patch = (WORK / target["origin"] / target["patch_name"]).read_bytes()
        assert pin(before)["git_blob"] == target["before_blob"]
        assert pin(after)["git_blob"] == target["after_blob"] and pin(after)["sha256"] == target["after_sha256"]
        assert pin(patch)["sha256"] == target["patch_sha256"]
        entry = next(e for e in original_trees[target["directory"]] if e["path"] == target["name"])
        assert entry == {"path": target["name"], "mode": "100644", "type": "blob", "sha": target["before_blob"]}
        old_manifest = next(row for row in base["changed_files"] if row["path"] == path)
        assert old_manifest == {"path": path, "mode": "100644", **pin(before)}
        regenerated = "".join(difflib.unified_diff(before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}")).encode()
        assert patch == regenerated
        before_map[path], after_map[path] = before, after
        changes.append({"path": path, "mode": "100644", "before": pin(before), "after": pin(after), "source_candidate_directory": target["origin"], "original_patch": {"path": target["patch_name"], **pin(patch)}})
        patch_parts.append(patch)
        exact(HERE / "original" / path, before)
        exact(HERE / "source" / path, after)
    combined = b"".join(patch_parts)
    assert apply_unified(before_map, combined) == after_map
    assert apply_unified(after_map, combined, reverse=True) == before_map
    exact(HERE / "combined.patch", combined)

    derived = copy.deepcopy(original_trees)
    for target in TARGETS:
        entry = next(e for e in derived[target["directory"]] if e["path"] == target["name"])
        entry["sha"] = target["after_blob"]
    # Child directories first; original hashes were all independently verified above.
    hashes = {}
    for key in ("exec_common", "exec_tests", "exec", "network_src", "network", "codex", "root"):
        for parent, name, child in EDGES:
            if parent == key:
                entry = next(e for e in derived[key] if e["path"] == name)
                entry["sha"] = hashes[child]
        calculated, body = tree_hash(derived[key])
        hashes[key] = calculated
        allowed_changes = {name for parent, name, child in EDGES if parent == key}
        allowed_changes.update(t["name"] for t in TARGETS if t["directory"] == key)
        observed_changes = []
        assert len(derived[key]) == len(original_trees[key])
        for before, after in zip(original_trees[key], derived[key], strict=True):
            assert before["path"] == after["path"] and before["mode"] == after["mode"] and before["type"] == after["type"]
            if before != after:
                assert before["path"] in allowed_changes
                observed_changes.append({"path": before["path"], "before": before["sha"], "after": after["sha"]})
        assert {r["path"] for r in observed_changes} == allowed_changes
        emit(f"derived-trees/{key}.json", {"schema": "hepta.offline-derived-direct-tree.v1", "directory": TREE_SPECS[key][0], "original_git_tree": TREE_SPECS[key][1], "expected_git_tree": calculated, "entries": derived[key], "changes": observed_changes, "all_other_canonical_entries_byte_identical": True, "tree_object_body_bytes": len(body), "git_object_created": False})

    new_rows = copy.deepcopy(base["changed_files"])
    for row in new_rows:
        if row["path"] in after_map:
            row.update(pin(after_map[row["path"]]))
    unchanged = [r["path"] for r, n in zip(base["changed_files"], new_rows, strict=True) if r == n]
    assert len(unchanged) == 192
    assert sorted(r["path"] for r in base["changed_files"]) == sorted(r["path"] for r in new_rows)
    manifest = {
        "schema": "hepta.source51-offline-candidate-manifest.v1",
        "stage": 51, "status": "PROVISIONAL_NOT_CREATED_NOT_APPLIED",
        "source_commit": None, "source_tree": hashes["root"], "source_parent_commit": BASE_COMMIT,
        "source_tree_is_offline_expected_identity": True,
        "native_checkout_or_execution_not_claimed": True,
        "cargo_lock_sha256": base["cargo_lock_sha256"], "bazel_lock_sha256": base["bazel_lock_sha256"],
        "changed_files": new_rows,
        "base_source_manifest": {"path": "input/source50-actual-manifest.json", **pin(base_raw)},
        "source_changes_from_parent": changes,
        "unchanged_parent_manifest_entries": 192,
        "rust_qualification": "PENDING", "final_fix_fmt_executed": False,
        "science": "HOLD", "authority": "DENY_ALL",
    }
    emit("candidate-source-manifest.json", manifest)
    emit("input/GIT-TREE-QUERIES.json", {"schema": "hepta.source51-direct-git-tree-inputs.v1", "base_commit": BASE_COMMIT, "base_tree": BASE_TREE, "payload_note": "Exact UTF-8 content returned by the GitHub connector for each fixed nonrecursive GitData endpoint; not claimed as raw HTTP wire framing.", "queries": queries, "git_writes_performed": False})
    emit("TREE-AND-PATCH-READBACK.json", {
        "schema": "hepta.source51-offline-tree-patch-readback.v1", "status": "LOCAL_OFFLINE_READBACK_PASS_NO_NATIVE_EXECUTION",
        "script": {"path": "build_preparation.py", **pin(Path(__file__).read_bytes())},
        "base_commit": BASE_COMMIT, "base_tree": BASE_TREE, "expected_tree": hashes["root"],
        "direct_trees_independently_rehashed": 7, "direct_entries_examined": sum(len(v) for v in original_trees.values()),
        "original_ancestry_edges_verified": len(EDGES),
        "original_tree_sha_checks": {key: TREE_SPECS[key][1] for key in TREE_SPECS},
        "derived_tree_shas": hashes,
        "tree_algorithm": "Git SHA1 of tree header plus canonical mode, UTF-8 name, NUL, raw 20-byte child SHA; directory-aware byte sorting. All seven original objects must equal their API identities before replacing only two leaf SHAs.",
        "all_other_directory_entries_unchanged": True,
        "changed_paths": [x["path"] for x in changes],
        "combined_patch": {"path": "combined.patch", **pin(combined)},
        "original_individual_patches_regenerated_exactly": True,
        "combined_unified_patch_forward_and_reverse_exact": True,
        "source_manifest_entries": len(new_rows), "rust_source_entries": sum(r["path"].endswith(".rs") for r in new_rows),
        "unchanged_manifest_entries": len(unchanged),
        "full_old_leaf_map_not_used": True,
        "git_objects_or_commits_created": False,
        "rust_metadata_fmt_or_tests_executed": False,
    })
    emit("PLAN.json", {
        "schema": "hepta.source51-two-path-plan.v1", "status": "PREPARATION_ONLY_NOT_CREATED_NOT_APPLIED",
        "base_commit": BASE_COMMIT, "base_tree": BASE_TREE,
        "expected_tree": hashes["root"], "source_commit": None,
        "changed_source_paths_from_parent": changes,
        "parent_manifest_entries": 194, "candidate_manifest_entries": 194, "rust_source_entries": 180,
        "combined_patch": {"path": "combined.patch", **pin(combined)},
        "candidate_manifest": {"path": "candidate-source-manifest.json", **pin((HERE / "candidate-source-manifest.json").read_bytes())},
        "native_execution": False, "root_publication_required": True,
        "source50_original_gate": {"r24": "FAILED_100", "unique_test_counts": {"PASS": 1561, "FAIL": 3, "TIMEOUT": 0}, "reported_skipped": 3, "does_not_qualify_candidate": True},
        "future_validation": "Root/native must bind the actually published source51 identity and original gates; this plan grants no native or formatter qualification.",
        "old_r25_snapshot": "Remains inert and blocked by its failed r24 prerequisite; not edited or bypassed here.",
        "boundary": "No production sandbox policy changes. The helper changes only test program discovery; the network change is one fixture-local direct-policy flag. Original assertions remain in both candidates.",
    })
    source_refs = [
        ("exec-server-bwrap-r24-repair/HANDOFF-MANIFEST.json", "input/exec-server-candidate-HANDOFF.json"),
        ("exec-server-bwrap-r24-repair/repair-audit.json", "input/exec-server-candidate-audit.json"),
        ("exec-server-bwrap-r24-repair/PROBE-INDEPENDENT-READBACK.json", "input/exec-server-probe-independent-readback.json"),
        ("source51-network-candidate/READBACK.json", "input/network-candidate-readback.json"),
    ]
    copied = []
    for src, dest in source_refs:
        raw = (WORK / src).read_bytes()
        exact(HERE / dest, raw)
        copied.append({"source": src, "destination": dest, **pin(raw)})
    emit("CANDIDATE-INPUT-MAPPING.json", {"schema": "hepta.source51-candidate-input-mapping.v1", "files": copied, "original_source_and_patch_origins": changes})
    files = [{"path": p.relative_to(HERE).as_posix(), **pin(p.read_bytes())} for p in sorted(HERE.rglob("*")) if p.is_file() and p.name != "HANDOFF-MANIFEST.json" and "__pycache__" not in p.parts]
    emit("HANDOFF-MANIFEST.json", {"schema": "hepta.source51-offline-preparation-handoff.v1", "status": "FROZEN_PREPARATION_NOT_NATIVE_EXECUTION", "base_commit": BASE_COMMIT, "base_tree": BASE_TREE, "expected_tree": hashes["root"], "source_commit": None, "file_count": len(files), "total_bytes": sum(r["bytes"] for r in files), "files": files})
    print(json.dumps({"expected_tree": hashes["root"], "files": len(files), "bytes": sum(r["bytes"] for r in files), "reports": {name: pin((HERE / name).read_bytes()) for name in ("PLAN.json", "candidate-source-manifest.json", "TREE-AND-PATCH-READBACK.json", "combined.patch", "HANDOFF-MANIFEST.json")}}, indent=2))


if __name__ == "__main__":
    main()
