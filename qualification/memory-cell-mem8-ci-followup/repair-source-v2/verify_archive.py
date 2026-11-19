"""Offline verification of the original source-only records; executes no archive member."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import tarfile

ARCHIVE_SHA = "244d0c156594a7e1bf4ce2136b867c40015be12b77e338d75a8960bdc724e188"
BASE = "2ae5215beaf8d7b7df111a090b82134beae2683d"
BASE_TREE = "12159640adcf073b51f3837e75575e11f5c20233"
CANDIDATE_TREE = "e253b99e0a5c3b3a680569da0d224fabff0781ba"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def oid(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def identity(data):
    return {"bytes": len(data), "sha256": sha(data), "git_blob": oid("blob", data)}


def listing(data):
    result = {}
    for record in data.split(b"\0"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = meta.decode().split()
        path = raw_path.decode("utf-8")
        assert path not in result
        result[path] = {"mode": mode, "type": kind, "git_blob": object_id}
    return result


def tree_hash(entries):
    root = {}
    for path, value in entries.items():
        parts = PurePosixPath(path).parts
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (value["mode"], value["git_blob"])

    def visit(node):
        records = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, digest = ("40000", visit(value)) if directory else value
            raw_name = name.encode("utf-8")
            records.append((raw_name + (b"/" if directory else b""),
                            mode.encode() + b" " + raw_name + b"\0" + bytes.fromhex(digest)))
        return oid("tree", b"".join(raw for _, raw in sorted(records)))
    return visit(root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("publication_manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.read_bytes()
    assert identity(archive) == {
        "bytes": 1347860, "sha256": ARCHIVE_SHA,
        "git_blob": "855b0c8ca5944be407f14011fd8507f4af4fbdfb",
    }
    publication_bytes = args.publication_manifest.read_bytes()
    assert oid("blob", publication_bytes) == "337b8b3c8342dfa84f3f7bb46dac683035866dce"
    publication = json.loads(publication_bytes)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as tf:
        for member in tf:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and ".." not in path.parts
            assert member.name not in files
            data = tf.extractfile(member).read()
            assert len(data) == member.size
            files[member.name] = data
    assert len(files) == 242
    manifest = json.loads(files["FILE_MANIFEST.json"])
    assert len(manifest["members"]) == 241
    assert {r["path"] for r in manifest["members"]} == set(files) - {"FILE_MANIFEST.json"}
    for row in manifest["members"]:
        assert identity(files[row["path"]]) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    assert len(publication["member_manifest"]) == 242
    for row in publication["member_manifest"]:
        assert identity(files[row["path"]]) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    assert sha(files["DRIVER.py"]) == "e5146186d81bb0c5657d119b84d655dc691122aab2609202b036515cbb41b756"
    assert len(files["INPUT.json.xz"]) == 227572
    assert sha(files["INPUT.json.xz"]) == "05a04a0f19bb071fad6395c5ee01d551e07681946992f6d65f524e134ee8d294"
    assert lzma.decompress(files["INPUT.json.xz"]) == files["INPUT.json"]
    config = json.loads(files["INPUT.json"])
    formatted = json.loads(files["FORMAT_RESULT.json"])
    capsule = json.loads(files["FORMATTED_CAPSULE.json"])
    assert (capsule["base_commit"], capsule["base_tree"], capsule["candidate_tree"]) == (BASE, BASE_TREE, CANDIDATE_TREE)
    assert identity(files["FORMATTED_CAPSULE.json"])["sha256"] == "6081a45344f3fa7687b71901033b813499d5dc3913c052e63a6700a9c96b6a37"
    before = {r["path"]: r for r in formatted["before"]}
    after = {r["path"]: r for r in formatted["after"]}
    input_rows = {r["path"]: r for r in config["files"]}
    assert len(input_rows) == 69 and len(config["files"]) == 69 and len(capsule["files"]) == 69
    assert set(before) == set(after) == set(input_rows) == {r["path"] for r in capsule["files"]}
    base = listing(files["BASE_TREE.ls-tree"])
    candidate = listing(files["CANDIDATE_TREE.ls-tree"])
    assert tree_hash(base) == BASE_TREE and tree_hash(candidate) == CANDIDATE_TREE
    expected = dict(base)
    for path, row in input_rows.items():
        data = row["content"].encode("utf-8")
        assert data == files["pre-format/" + path]
        assert identity(data) == {"bytes": row["bytes"], "sha256": row["sha256"], "git_blob": row["input_git_blob"]}
        assert row["mode"] == "100644"
        if row["preimage_git_blob"] is None:
            assert path not in base and "base/" + path not in files
        else:
            assert base[path]["git_blob"] == row["preimage_git_blob"] == oid("blob", files["base/" + path])
        post = files["post-format/" + path]
        assert identity(post) == {key: after[path][key] for key in ("bytes", "sha256", "git_blob")}
        expected[path] = {"mode": row["mode"], "type": "blob", "git_blob": oid("blob", post)}
    assert candidate == expected and len(candidate) == 14043
    for row in capsule["files"]:
        data = base64.b64decode(row["content_base64"], validate=True)
        assert data == files["post-format/" + row["path"]]
        assert identity(data) == {"bytes": row["postimage_bytes"], "sha256": row["postimage_sha256"], "git_blob": row["postimage_git_blob"]}
    result = json.loads(files["RESULT.json"])
    assert result["status"] == "passed_source_gates_only_review_remaining" and result["failure"] is None
    assert result["source_before"] == {"head": BASE, "tree": BASE_TREE, "status": ""}
    assert result["source_after"]["head"] == BASE and result["source_after"]["tree"] == BASE_TREE
    assert result["donor_before"] == result["donor_after"]
    assert result["donor_source_before"] == result["donor_source_after"]
    assert result["native_tests_executed"] == result["model_requests_executed"] == 0
    assert not result["source_candidate_committed"] and not result["source_refs_modified"]
    deadline = datetime.fromisoformat(result["deadline_utc"])
    assert (deadline - datetime.fromisoformat(result["started_at"])).total_seconds() == 600
    for phase in ["format", "diff-check", "caller-self-test", "caller-verify"]:
        receipt = json.loads(files[phase + ".json"])
        assert receipt["exit_code"] == 0 and receipt["timed_out"] is False
        assert datetime.fromisoformat(receipt["finished_at"]) <= deadline
        assert identity(files[receipt["raw_file"]]) == {k: receipt[k] for k in ("bytes", "sha256", "git_blob")}
    assert datetime.fromisoformat(result["finished_at"]) < deadline
    rename = json.loads(files["FULL_TREE_RENAME_SCAN.json"])
    assert rename["renames"] == config["case_renames"] and len(rename["renames"]) == 13
    assert rename["matches"] == [] and rename["review_required"] is False
    assert files["full-tree-old-case-name-scan.raw.log"] == b""
    assert json.loads(files["full-tree-old-case-name-scan.json"])["exit_code"] == 1
    caller = json.loads(files["caller-verify.raw.log"])
    assert caller["status"] == "PASS_HEPTA_CALLER_CLOSED_SET" and caller["authorityGranted"] is False
    assert caller["rustFilesScanned"] == 6196
    audit = {
        "schema": "hepta.mem8.repair-source.independent-root-readback.v2",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "archive": identity(archive), "verified_members": len(files),
        "base_commit": BASE, "base_tree_recomputed": BASE_TREE,
        "candidate_tree_recomputed": CANDIDATE_TREE, "complete_entries": len(candidate),
        "source_paths": len(input_rows), "new_source_files": sum(r["preimage_git_blob"] is None for r in input_rows.values()),
        "formatter_changed_paths": formatted["formatter_changed_paths"],
        "caller_status": caller["status"], "rust_files_scanned": caller["rustFilesScanned"],
        "old_test_names_searched": 13, "old_test_name_matches": 0,
        "original_run_started_at": result["started_at"], "original_run_finished_at": result["finished_at"],
        "original_deadline": result["deadline_utc"], "donor_exact_bytes_unchanged": True,
        "archived_programs_executed_by_this_audit": 0, "native_tests_executed_by_this_audit": 0,
        "model_requests_executed_by_this_audit": 0, "source_refs_modified_by_this_audit": False,
        "scope": "Source-only gates on the exact candidate tree; runtime and scientific adoption remain unqualified.",
    }
    args.output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
