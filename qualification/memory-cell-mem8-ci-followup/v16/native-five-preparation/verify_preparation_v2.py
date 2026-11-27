"""Verify every prepared-source archive member without executing its code."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def tree_hash(raw):
    if not raw.endswith(b"\0"):
        raise ValueError("truncated tree inventory")
    root, seen = {}, set()
    for entry in raw.split(b"\0")[:-1]:
        meta, name = entry.split(b"\t", 1)
        mode, kind, sha = meta.decode().split()
        path = PurePosixPath(name.decode())
        if path.is_absolute() or ".." in path.parts or path in seen:
            raise ValueError("unsafe or repeated tree path")
        seen.add(path)
        node = root
        for part in path.parts[:-1]:
            node = node.setdefault(part, {})
        if path.name in node:
            raise ValueError("tree path conflict")
        if mode not in {"100644", "100755", "120000", "160000"} or (mode == "160000") != (kind == "commit"):
            raise ValueError("unexpected recursive leaf type")
        node[path.name] = (mode, sha)

    def walk(node):
        payload = b""
        for name, value in sorted(node.items(), key=lambda row: (row[0] + ("/" if isinstance(row[1], dict) else "")).encode()):
            mode, sha = ("40000", walk(value)) if isinstance(value, dict) else value
            payload += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)
        return hashlib.sha1(b"tree " + str(len(payload)).encode() + b"\0" + payload).hexdigest()

    return walk(root), len(seen)


def verify(path):
    files = {}
    with tarfile.open(path, "r:xz") as archive:
        for member in archive:
            rel = PurePosixPath(member.name)
            if not member.isfile() or rel.is_absolute() or ".." in rel.parts or str(rel) != member.name or member.name in files:
                raise ValueError("unsafe or repeated archive member")
            data = archive.extractfile(member).read()
            if len(data) != member.size:
                raise ValueError("truncated archive member")
            files[member.name] = data
    manifest = json.loads(files["MEMBER_MANIFEST.json"])
    expected = {row["path"]: {key: row[key] for key in ("bytes", "sha256", "git_blob")} for row in manifest["files"]}
    actual = {name: identity(data) for name, data in files.items() if name != "MEMBER_MANIFEST.json"}
    if len(expected) != len(manifest["files"]) or expected != actual:
        raise ValueError("full archive member set or bytes differ")
    scope = json.loads(files["PACKAGE_SCOPE.json"])
    plan = json.loads(files["mem-five-native-harness-preparation/rendered-c895405/.github/fixtures/mem-native-five-plan.json"])
    tree, leaves = tree_hash(files["final-source/CANDIDATE_TREE.ls-tree"])
    commit = json.loads(files["final-source/FORMATTED_COMMIT_READBACK.json"])
    if tree != plan["source_tree"] or tree != commit["tree"]["sha"] or commit["sha"] != plan["source_head"]:
        raise ValueError("complete final tree or commit binding differs")
    source_index = json.loads(files["FINAL_SOURCE_INDEX.json"])
    if {row["path"] for row in source_index} != set(plan["files"]):
        raise ValueError("final dependency set differs")
    tree_entries = {}
    for entry in files["final-source/CANDIDATE_TREE.ls-tree"].split(b"\0")[:-1]:
        metadata, name = entry.split(b"\t", 1)
        mode, kind, sha = metadata.decode().split()
        tree_entries[name.decode()] = {"mode": mode, "type": kind, "git_blob": sha}
    for row in source_index:
        wanted = {key: plan["files"][row["path"]][key] for key in ("bytes", "sha256", "git_blob")}
        if (identity(files[row["archive_path"]]) != wanted or tree_entries.get(row["path"]) != {
                "mode": row["mode"], "type": "blob", "git_blob": row["git_blob"]}):
            raise ValueError("final dependency bytes differ")
    references = json.loads(files["mem-five-native-harness-preparation/SOURCE_INDEX.json"])["sources"]
    for row in references:
        member_name = "mem-five-native-harness-preparation/" + row["local_path"]
        if identity(files[member_name]) != {key: row[key] for key in ("bytes", "sha256", "git_blob")}:
            raise ValueError("original pinned source reference differs")
    rendered = json.loads(files["mem-five-native-harness-preparation/rendered-c895405/PREPARATION_MANIFEST.json"])
    for name, row in rendered["files"].items():
        if identity(files["mem-five-native-harness-preparation/rendered-c895405/" + name]) != row:
            raise ValueError("rendered harness bytes differ")
    admission = json.loads(files["mem-five-native-harness-preparation/ACTUAL_ADMISSION.json"])
    if admission["source_head"] != commit["sha"] or admission["harness_head"] != scope["harness_head"] or admission["actual_run"]["id"] != 43047914262:
        raise ValueError("original admission differs")
    controls = json.loads(files["mem-five-native-harness-preparation/STATIC_VALIDATION.json"])
    if controls["offline_parser_controls"] != {"run": 7, "failures": 0, "errors": 0, "skipped": 0}:
        raise ValueError("original parser-control outcome differs")
    return {"status": "ALL_PREPARATION_MEMBERS_AND_BINDINGS_VERIFIED", "archive": identity(path.read_bytes()),
            "members": len(files), "final_source_dependencies": len(source_index), "pinned_source_references": len(references),
            "source_head": commit["sha"], "source_tree": tree, "complete_tree_leaves": leaves,
            "historical_parser_controls": controls["offline_parser_controls"],
            "native_results_in_package": False, "archive_code_executed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.archive)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2))
