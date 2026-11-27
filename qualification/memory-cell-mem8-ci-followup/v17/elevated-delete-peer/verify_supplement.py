"""Verify the thin peer supplement and its immutable original inputs offline.

This reader never executes archived code, starts a native test, or contacts a host.
"""
import argparse
import difflib
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import tarfile
import xml.etree.ElementTree as ET
import zipfile

def ident(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def matches(raw, expected):
    assert ident(raw) == {key: expected[key] for key in ("bytes", "sha256", "git_blob")}

def tar_members(raw):
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            assert member.isfile() and not member.issym() and not member.islnk()
            assert not path.is_absolute() and ".." not in path.parts and "\\" not in member.name
            assert member.name == str(path) and member.name not in files
            files[member.name] = archive.extractfile(member).read()
            assert len(files[member.name]) == member.size
    return files

def check_manifest(files, key):
    manifest = json.loads(files["FILE_MANIFEST.json"])
    rows = manifest[key]
    assert {row["path"] for row in rows} == set(files) - {"FILE_MANIFEST.json"}
    assert len({row["path"] for row in rows}) == len(rows)
    for row in rows:
        matches(files[row["path"]], row)

def parse_tree(raw):
    leaves, hierarchy = {}, {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        header, path_bytes = entry.split(b"\t", 1)
        mode, kind, sha = header.decode().split()
        path = path_bytes.decode()
        assert path not in leaves and not PurePosixPath(path).is_absolute()
        assert ".." not in PurePosixPath(path).parts and re.fullmatch("[0-9a-f]{40}", sha)
        assert mode in {"100644", "100755", "120000", "160000"}
        assert kind == ("commit" if mode == "160000" else "blob")
        leaves[path] = {"mode": mode, "kind": kind, "git_blob": sha}
        current = hierarchy
        parts = path_bytes.split(b"/")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
            assert isinstance(current, dict)
        assert parts[-1] not in current
        current[parts[-1]] = (mode.encode(), bytes.fromhex(sha))
    def tree_hash(node):
        body = b""
        for name, value in sorted(node.items(), key=lambda row: row[0] + (b"/" if isinstance(row[1], dict) else b"")):
            mode, digest = (b"40000", tree_hash(value)) if isinstance(value, dict) else value
            body += mode + b" " + name + b"\0" + digest
        return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).digest()
    return leaves, tree_hash(hierarchy).hex()

def zip_members(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.testzip() is None
        names = [row.filename for row in archive.infolist() if not row.is_dir()]
        assert len(set(names)) == len(names)
        return {name: archive.read(name) for name in names}

def audit(args):
    package = args.package
    refs = json.loads((package / "RECOVERY_INPUTS.json").read_text())
    peer_raw = (package / "MEM_EXPERIMENT_CONTRACT_PEER.json").read_bytes()
    matches(peer_raw, refs["peer"])
    peer = json.loads(peer_raw)
    original_raw = args.original_review.read_bytes()
    matches(original_raw, refs["original_review_archive"])
    original = tar_members(original_raw)
    assert len(original) == 31
    check_manifest(original, "files")
    for name, expected in peer["reviewed_reports"].items():
        matches(original[name], expected)
    source_index = json.loads(original["SOURCE_INDEX.json"])
    assert len(source_index["files"]) == 23
    for row in source_index["files"]:
        matches(original["source/" + row["path"]], row)
    raw = original["sandbox-native-delete-routes.log"]
    matches(raw, peer["original_failure_independently_rechecked"]["raw"])
    decoded = []
    lines = raw.decode().splitlines()
    for line_number in range(220, 232):
        line = lines[line_number - 1]
        assert "delete_matrix elevated-child-done path=" in line
        acl = bytes(int(item.strip(), 16) for item in line.split("acl=[", 1)[1].rstrip("]").split(","))
        revision, _, length, count, _ = struct.unpack_from("<BBHHH", acl)
        assert revision == 2 and length == len(acl)
        offset, aces = 8, []
        for _ in range(count):
            kind, flags, size, mask = struct.unpack_from("<BBHI", acl, offset)
            assert kind in (0, 1) and size >= 16
            sid = acl[offset + 8:offset + size]
            assert sid[0] == 1 and len(sid) == 8 + 4 * sid[1]
            value = "S-1-" + str(int.from_bytes(sid[2:8], "big"))
            value += "".join("-" + str(struct.unpack_from("<I", sid, 8 + 4 * i)[0]) for i in range(sid[1]))
            assert value == "S-1-1-0"
            aces.append({"type": "allow" if kind == 0 else "deny", "flags": flags, "mask": mask, "sid": value})
            offset += size
        assert offset == len(acl)
        decoded.append({"line": line_number, "acl_sha256": hashlib.sha256(acl).hexdigest(), "aces": aces})
    assert decoded == peer["original_failure_independently_rechecked"]["independent_acl_decode"]
    observed = [{"route": route, "file_deleted": f == "true", "directory_deleted": d == "true"} for route, f, d in re.findall(r"DeleteOutcome \{ route: (\w+), file_deleted: (true|false), directory_deleted: (true|false) \}", lines[231])]
    assert observed == peer["original_failure_independently_rechecked"]["outcomes"]

    v10_raw = args.v10_original.read_bytes()
    matches(v10_raw, refs["v10_original_archive"]["archive"])
    offset = 0
    for part in refs["v10_original_archive"]["parts"]:
        assert part["offset"] == offset and part["actual_created"] is True
        matches(v10_raw[offset:offset + part["bytes"]], part)
        offset += part["bytes"]
    assert offset == len(v10_raw)
    v10 = tar_members(v10_raw)
    assert len(v10) == 32
    v10_zip = zip_members(v10["ORIGINAL_ARTIFACT.zip"])
    canonical = tar_members(v10_zip["mem8-source-gates-v10/mem8-source-gates-v10-records.tar.xz"])
    assert len(canonical) == 387
    check_manifest(canonical, "members")
    tree_raw = canonical["CANDIDATE_TREE.ls-tree"]
    matches(tree_raw, peer["current_d0f_comparison"]["complete_tree_identity"])
    leaves, tree_sha = parse_tree(tree_raw)
    assert len(leaves) == 14053 and tree_sha == "658fa040046285116b1fd81b94ff8c96444072ad"
    current_rows = []
    for row in source_index["files"]:
        now = leaves[row["path"]]["git_blob"]
        current_rows.append({"path": row["path"], "reviewed_9bd2_blob": row["git_blob"], "current_d0f_blob": now, "same_blob": now == row["git_blob"]})
    assert current_rows == peer["current_d0f_comparison"]["rows"]
    assert sum(row["same_blob"] for row in current_rows) == 19
    for name, expected in peer["current_d0f_comparison"]["production_delta_full"].items():
        before, after = original["source/" + name], canonical["post-format/" + name]
        matches(after, expected["current_identity"])
        assert ident(after)["git_blob"] == leaves[name]["git_blob"]
        actual_diff = "".join(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True), fromfile="9bd2/" + name, tofile="d0f/" + name))
        assert actual_diff == expected["full_diff"]
    before = original["source/codex-rs/windows-sandbox-rs/src/setup.rs"].decode()
    after = canonical["post-format/codex-rs/windows-sandbox-rs/src/setup.rs"].decode()
    for start, end in (("fn gather_full_read_roots_for_permissions(", "pub(crate) fn gather_write_roots_for_permissions("), ("fn run_setup_refresh_inner(", "fn run_setup_refresh_payload("), ("pub struct SetupMarker {", "impl SetupMarker {")):
        assert before[before.index(start):before.index(end)] == after[after.index(start):after.index(end)]

    five_raw = args.five_original.read_bytes()
    matches(five_raw, refs["five_native_original_archive"])
    five = tar_members(five_raw)
    assert len(five) == 17
    five_audit = json.loads(five["readback/INDEPENDENT_AUDIT.json"])
    assert five_audit["run_id"] == 43047914262 and five_audit["job_id"] == 130616746852
    assert five_audit["source_head"] == "c89540598693697577cda8cba31cb07f6ce65317"
    assert five_audit["observed_status_counts"] == {"PASS": 5}
    assert five_audit["qualification"] == "NOT_QUALIFIED_RETAIN_ORIGINAL_FAILURE_OR_UNKNOWN"
    five_zip = zip_members(five["ORIGINAL_ARTIFACT.zip"])
    leak_case = "unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit"
    terminal = []
    for name, payload in five_zip.items():
        if name.endswith(".junit.xml"):
            assert b"<!DOCTYPE" not in payload and b"<!ENTITY" not in payload
            root = ET.fromstring(payload)
            for case in root.iter("testcase"):
                if case.get("name") == leak_case:
                    terminal.append({"name": leak_case, "uuid": root.get("uuid"), "children": [child.tag for child in case]})
    assert len(terminal) == 1 and all(tag in {"system-out", "system-err"} for tag in terminal[0]["children"])
    return {"schema": "mem.elevated-peer-supplement-offline-audit.v1", "peer": ident(peer_raw), "original_review_archive": ident(original_raw), "original_review_members": 31, "verified_source_files": 23, "independently_decoded_acl_rows": 12, "original_elevated_delete_outcomes": observed, "current_source_tree": tree_sha, "current_tree_leaves": 14053, "unchanged_source_blobs": 19, "changed_production_diffs_verified": 2, "five_native_original": ident(five_raw), "historical_leak_case_later_junit": terminal[0], "historical_five_whole_job": five_audit["qualification"], "result": "PASS_READ_ONLY_BYTE_AND_BINDING_REPLAY", "native_tests_or_models_started": 0, "source_or_ref_changes": 0, "permission_repair_qualified": False}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--original-review", type=Path, required=True)
    parser.add_argument("--v10-original", type=Path, required=True)
    parser.add_argument("--five-original", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args), indent=2, sort_keys=True))
