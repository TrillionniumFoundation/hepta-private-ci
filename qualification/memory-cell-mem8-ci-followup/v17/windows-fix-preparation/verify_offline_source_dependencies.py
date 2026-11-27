#!/usr/bin/env python3
"""Verify/optionally restore frozen source dependencies; execute no archived code."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def check(data, expected):
    assert identity(data) == {key: expected[key] for key in ("bytes", "sha256", "git_blob")}
    return data


def member(archive, name):
    path = PurePosixPath(name)
    assert not path.is_absolute() and all(p not in ("", ".", "..") for p in path.parts)
    info = archive.getmember(name)
    assert info.isfile()
    return archive.extractfile(info).read()


def merkle(rows):
    nodes = {"": {}}
    for name, (mode, sha) in rows.items():
        parts = name.split("/")
        assert all(p not in ("", ".", "..") for p in parts)
        parent = ""
        for part in parts[:-1]:
            child = parent + "/" + part if parent else part
            nodes.setdefault(child, {})
            nodes[parent][part] = ("40000", child)
            parent = child
        assert parts[-1] not in nodes[parent]
        nodes[parent][parts[-1]] = (mode, sha)
    sums = {}
    for path in sorted(nodes, key=lambda p: (p.count("/"), len(p)), reverse=True):
        data = bytearray()
        for name, (mode, value) in sorted(nodes[path].items(), key=lambda row: (row[0] + ("/" if row[1][0] == "40000" else "")).encode()):
            sha = sums[value] if mode == "40000" else value
            data.extend(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha))
        sums[path] = hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()
    return sums[""]


def main(args):
    index = json.loads(args.index.read_bytes())
    plan = json.loads(check(args.plan.read_bytes(), index["plan_identity"]))
    assert plan["source_head"] == index["source_head"]
    assert plan["source_tree"] == index["source_tree"]
    assert len(index["dependencies"]) == len(plan["files"]) == 20
    v16_data = check(args.v16.read_bytes(), index["archives"]["v16"]["identity"])
    v10_data = check(args.v10.read_bytes(), index["archives"]["v10"]["identity"])
    restored = {}
    with tarfile.open(fileobj=io.BytesIO(v16_data), mode="r:xz") as v16, tarfile.open(fileobj=io.BytesIO(v10_data), mode="r:xz") as v10:
        assert len(v16.getmembers()) == index["archives"]["v16"]["members"] == 73
        assert len(v10.getmembers()) == index["archives"]["v10"]["members"] == 32
        zip_info = index["archives"]["v10"]["original_zip"]
        zip_data = check(member(v10, zip_info["member"]), zip_info)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as original_zip:
            assert original_zip.testzip() is None
            assert len(original_zip.infolist()) == zip_info["members"]
            canonical_info = index["archives"]["v10"]["canonical_tar"]
            canonical_data = check(original_zip.read(canonical_info["member"]), canonical_info)
        with tarfile.open(fileobj=io.BytesIO(canonical_data), mode="r:xz") as canonical:
            assert len(canonical.getmembers()) == canonical_info["members"] == 387
            tree_raw = check(member(canonical, "CANDIDATE_TREE.ls-tree"), plan["complete_tree_inventory"])
            rows = {}
            for raw_row in tree_raw.split(b"\0"):
                if not raw_row:
                    continue
                left, name = raw_row.split(b"\t", 1)
                mode, kind, sha = left.decode().split()
                name = name.decode()
                assert kind == "blob" and name not in rows
                rows[name] = mode, sha
            assert len(rows) == 14053 and merkle(rows) == plan["source_tree"]
            for dep in index["dependencies"]:
                name = dep["path"]
                pin = plan["files"][name]
                assert dep["identity"] == pin
                assert rows[name] == (pin["mode"], pin["git_blob"])
                archive = v16 if dep["archive"] == "v16" else canonical
                data = check(member(archive, dep["member"]), pin)
                assert name not in restored
                restored[name] = data
    assert set(restored) == set(plan["files"])
    if args.output:
        assert not args.output.exists()
        args.output.mkdir(parents=True)
        for name, data in restored.items():
            target = args.output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(data)
    return {"status": "PASS_OFFLINE_20_SOURCE_BYTES_AND_FULL_TREE", "source_head": plan["source_head"],
            "source_tree": plan["source_tree"], "tree_entries": len(rows), "dependencies": len(restored),
            "v16_direct_loose_members": sum(d["archive"] == "v16" for d in index["dependencies"]),
            "v10_canonical_post_format_members": sum(d["archive"] == "v10" for d in index["dependencies"]),
            "scope": "This verifies recovery inputs, not CI/native execution; original preparation archive remains unchanged.",
            "archived_commands_executed": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("index", "v16", "v10", "plan"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--output", type=Path)
    print(json.dumps(main(parser.parse_args()), indent=2, sort_keys=True))
