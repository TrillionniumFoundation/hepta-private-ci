"""Bind only inspected production and fixture sources to the Windows44 tree."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path("/workspace/scratch/3f6a885bb83c")
HERE = Path(__file__).resolve().parent
NATIVE = Path("/dev/shm/ndu_windows44_20261107/source_auto_ci_42352197933")
FROZEN = ROOT / "round3_native/windows_mutation_deny_44"
PREFIX = "codex-rs/windows-sandbox-rs/src/"


def need(value, reason):
    if not value:
        raise ValueError(reason)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def tree_sha(rows):
    data = b"".join(
        ("40000" if row["type"] == "tree" else row["mode"]).encode()
        + b" "
        + row["path"].encode()
        + b"\0"
        + bytes.fromhex(row["sha"])
        for row in sorted(
            rows,
            key=lambda x: x["path"].encode() + (b"/" if x["type"] == "tree" else b""),
        )
    )
    return hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()


def main():
    safe_raw = (NATIVE / "SAFE_NATIVE_OBSERVATIONS.json").read_bytes()
    need(
        identity(safe_raw)["sha256"]
        == "da2b21954d83b2ef840d63368598a5c819411be8061f63688d955b17a478f107",
        "NATIVE_BINDING_CHANGED",
    )
    safe = json.loads(safe_raw)
    api_path = FROZEN / "source-api/src_recursive_api.json"
    api_raw = api_path.read_bytes()
    api = json.loads(api_raw)
    need(api["truncated"] is False, "INCOMPLETE_SOURCE_TREE")
    entries = {row["path"]: row for row in api["tree"]}
    need(len(entries) == len(api["tree"]), "DUPLICATE_PATH")
    for path in entries:
        p = PurePosixPath(path)
        need(
            not p.is_absolute() and p.as_posix() == path and ".." not in p.parts,
            "UNSAFE_SOURCE_PATH",
        )
    trees = [""] + [p for p, row in entries.items() if row["type"] == "tree"]
    for parent in trees:
        children = [
            {**row, "path": PurePosixPath(p).name}
            for p, row in entries.items()
            if str(PurePosixPath(p).parent) == (parent or ".")
        ]
        need(
            tree_sha(children)
            == (api["sha"] if not parent else entries[parent]["sha"]),
            "TREE_OBJECT_HASH",
        )
    before = json.loads((FROZEN / "source-api/src_tree_api.json").read_bytes())
    need(
        api["sha"] == before["sha"] and tree_sha(before["tree"]) == api["sha"],
        "PARENT_SOURCE_TREE",
    )
    changed = {
        row["repository_path"][len(PREFIX) :]: row
        for row in safe["source"]["source_leaves"]
        if row["repository_path"] in (PREFIX + "acl.rs", PREFIX + "acl_tests.rs")
    }
    proposed = [
        {**row, "sha": changed[row["path"]]["git_blob"]}
        if row["path"] in changed
        else row
        for row in before["tree"]
    ]
    need(
        tree_sha(proposed) == safe["source"]["derived_subtrees"]["src"],
        "ACTUAL_SOURCE_TREE",
    )
    selected = {
        row["repository_path"][len(PREFIX) :]: Path(row["local_path"])
        for row in safe["source"]["source_leaves"]
    }
    for name in ("spawn_prep.rs", "cap.rs", "lib.rs"):
        selected[name] = FROZEN / "source" / PREFIX / name
    older = ROOT / "round3_native/windows_delete_repair_33/source" / PREFIX
    for name in (
        "unified_exec/backends/legacy.rs",
        "bin/command_runner/win.rs",
        "bin/setup_main/win.rs",
    ):
        selected[name] = older / name
    files = []
    for name, path in sorted(selected.items()):
        raw = path.read_bytes()
        value = identity(raw)
        expected = (
            changed[name]["git_blob"] if name in changed else entries[name]["sha"]
        )
        need(
            entries[name]["mode"] == "100644" and value["git_blob"] == expected,
            "SOURCE_BYTES",
        )
        files.append(
            {
                "repository_path": PREFIX + name,
                "local_path": str(path),
                "mode": "100644",
                **value,
            }
        )
    result = {
        "schema": "windows45-read-only-call-chain-binding-v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            k: safe["source"][k] for k in ("head", "tree", "parent", "actual_checkout")
        },
        "scope": "Exact source identities only; no new production candidate, ACL, token, host or native execution.",
        "native_binding_receipt": identity(safe_raw),
        "complete_recursive_src_api": {
            "path": str(api_path),
            **identity(api_raw),
            "entries": len(entries),
            "tree_objects_rehashed": len(trees),
        },
        "current_src_tree": tree_sha(proposed),
        "files": files,
        "code_identity": identity(Path(__file__).read_bytes()),
        "broader_repository_identity_claimed": False,
    }
    with (HERE / "SOURCE_BINDING.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "source": result["source"],
                "source_files": len(files),
                "tree_objects_rehashed": len(trees),
                "result": identity((HERE / "SOURCE_BINDING.json").read_bytes()),
            }
        )
    )


if __name__ == "__main__":
    main()
