"""Verify this preparation archive without executing any included project code."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def tree(raw):
    assert raw.endswith(b"\0")
    entries, root = {}, {}
    for item in raw.split(b"\0")[:-1]:
        meta, path = item.split(b"\t", 1)
        mode, kind, sha = meta.decode().split()
        path = path.decode()
        assert path not in entries
        entries[path] = {"mode": mode, "type": kind, "git_blob": sha}
        node = root
        parts = PurePosixPath(path).parts
        for name in parts[:-1]:
            node = node.setdefault(name, {})
        assert parts[-1] not in node
        node[parts[-1]] = (mode, sha)
    def measure(node):
        raw = b""
        for name, entry in sorted(node.items(), key=lambda item: (item[0] + ("/" if isinstance(item[1], dict) else "")).encode()):
            mode, sha = ("40000", measure(entry)) if isinstance(entry, dict) else entry
            raw += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)
        return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return entries, measure(root)

def verify(archive_path):
    objects, total = {}, 0
    with tarfile.open(archive_path, "r:xz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            assert member.isfile() and not name.is_absolute() and ".." not in name.parts
            assert str(name) == member.name and "\\" not in member.name and ":" not in member.name
            assert member.name not in objects
            total += member.size
            assert total <= 64 * 1024 * 1024
            data = archive.extractfile(member).read()
            assert len(data) == member.size
            objects[member.name] = data
    manifest = json.loads(objects["FILE_MANIFEST.json"])
    assert {row["path"] for row in manifest} | {"FILE_MANIFEST.json"} == set(objects)
    assert len(manifest) + 1 == len(objects)
    for row in manifest:
        assert pin(objects[row["path"]]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    refs = json.loads(objects["preparation/SOURCE_INDEX.json"])["sources"]
    assert len(refs) == 19
    for row in refs:
        assert pin(objects["preparation/" + row["local_path"]]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    initial = json.loads(objects["preparation/PREPARATION_MANIFEST.json"])
    for row in initial["files"]:
        assert pin(objects["preparation/" + row["path"]]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    commit = json.loads(objects["SOURCE_COMMIT_READBACK.json"])
    entries, actual_tree = tree(objects["COMPLETE_SOURCE_TREE.ls-tree"])
    assert commit["sha"] == "d0f6507e08f7f5c5855f5164d07c049a34d1a6d9"
    assert actual_tree == commit["tree"]["sha"] == "658fa040046285116b1fd81b94ff8c96444072ad"
    assert len(entries) == 14053
    dependencies = json.loads(objects["FINAL_SOURCE_INDEX.json"])
    assert len(dependencies) == len({row["path"] for row in dependencies}) == 26
    for row in dependencies:
        assert pin(objects["source/" + row["path"]]) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
        assert entries[row["path"]] == {"mode": row["mode"], "type": "blob", "git_blob": row["git_blob"]}
    rendered_prefix = "preparation/rendered-d0f6507/"
    rendered = json.loads(objects[rendered_prefix + "PREPARATION_MANIFEST.json"])
    assert rendered["source_head"] == commit["sha"] and rendered["source_tree"] == actual_tree
    for name, expected in rendered["files"].items():
        assert pin(objects[rendered_prefix + name]) == expected
    for filename in ("mem_native_subagent.py", "mem_native_subagent_support.py"):
        assert objects[rendered_prefix + ".github/scripts/" + filename] == objects["preparation/templates/" + filename]
    workflow = objects["preparation/templates/hepta-mem-native-subagent.yml.in"].decode()
    for token, value in {"__SOURCE_HEAD__": commit["sha"], "__SOURCE_TREE__": actual_tree,
                         "__HARNESS_BRANCH__": "codex/mem8-native-subagent-v10-20261111-ed353817"}.items():
        workflow = workflow.replace(token, value)
    assert workflow.encode() == objects[rendered_prefix + ".github/workflows/hepta-mem-native-subagent.yml"]
    plan = json.loads(objects[rendered_prefix + ".github/fixtures/mem-native-subagent-plan.json"])
    assert plan["job_timeout_minutes"] == 65 and plan["scoped_fix_packages"] == ["codex-core"]
    assert len(plan["groups"]) == 1 and plan["groups"][0]["cases"] == [
        "suite::subagent_notifications::spawned_multi_agent_v2_child_inherits_parent_developer_context",
        "suite::subagent_notifications::skills_toggle_skips_instructions_for_parent_and_spawned_child",
    ]
    assert plan["groups"][0]["binary_id"] == "codex-core::all"
    assert plan["nextest"]["version"] == "0.9.103" and plan["nextest"]["retries"] == 0
    for row in dependencies:
        assert plan["files"][row["path"]] == {key: row[key] for key in ("bytes", "sha256", "git_blob", "mode")}
    controls = json.loads(objects["preparation/STATIC_VALIDATION_V2.json"])
    assert controls["offline_parser_controls"] == {"errors": 0, "failures": 0, "run": 7, "skipped": 0}
    admission = json.loads(objects["preparation/ACTUAL_ADMISSION.json"])
    scope = json.loads(objects["PACKAGE_SCOPE.json"])
    assert scope["source_head"] == commit["sha"] and scope["native_results_included"] is False
    return {"status": "PASS_COMPLETE_PREPARATION_ARCHIVE", "archive": pin(archive_path.read_bytes()),
            "members": len(objects), "reference_sources": len(refs), "final_source_dependencies": len(dependencies),
            "full_source_tree_leaves": len(entries), "source_head": commit["sha"], "source_tree": actual_tree,
            "active_cases": 2, "scoped_fix_packages": ["codex-core"], "job_budget_minutes": 65,
            "offline_parser_controls": controls["offline_parser_controls"], "actual_admission_preserved": bool(admission),
            "source_or_native_tests_or_models_executed_by_reader": 0, "native_results_included": False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive), indent=2))

if __name__ == "__main__":
    main()
