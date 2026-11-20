"""Independently verify retained E6 archives without filesystem extraction."""

import argparse
import base64
import collections
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import time
import traceback


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = "9dfded9cecc74e39a19bccd14b9de9dc46c02c63"
TREE = "d07a8a95a2f0921387446063a1a51661cbd62df7"
HOST_SHA = "9d6848aa4145952dbd7b889a76b1f41f67de659ab90c045006c8585c43670341"
CLOUD_SHA = "119695fed1e1684dcb7a5b6d9b4350c120c923db863ed0301460d51dbc003127"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def safe_name(name):
    path = PurePosixPath(name)
    assert name and not path.is_absolute() and str(path) == name
    assert ".." not in path.parts and "." not in path.parts and "\0" not in name
    assert not path.name.endswith(".key"), "private-key file names are not admitted as archive body members"


def explicit_private_material_check(raw, name):
    for marker in (b"-----BEGIN PRIVATE KEY-----", b"-----BEGIN RSA PRIVATE KEY-----", b"-----BEGIN EC PRIVATE KEY-----", b"-----BEGIN OPENSSH PRIVATE KEY-----"):
        assert marker not in raw, "private PEM marker in a declared non-key physical input"
    if not name.endswith(".json"):
        return
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = key.lower().replace("-", "_")
                if normalized in {"private_key", "private_key_bytes", "secret_key", "secret_key_bytes", "signing_key_bytes", "private_seed", "secret_seed", "keypair_bytes"}:
                    assert item in (None, "", [], {}), "private body field in a declared non-key physical input"
                if normalized == "signing_key":
                    assert isinstance(item, str) and item.startswith("/"), "signing_key must be a path, not a key body"
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(json.loads(raw))


def verify(kind):
    output = HERE / ("verification-" + kind + "-1")
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    result = {"schema": "hepta.e6.independent-archive-readback.v1", "kind": kind, "source": SOURCE, "archive_members_extracted_to_filesystem": 0, "native_experiments": 0, "model_calls": 0, "host_processes_started": 0, "remote_git_writes": 0, "qualification_granted": False, "status": "VERIFYING"}
    try:
        if kind == "cloud":
            original = ROOT / "e6_owner_work/completion_namespace_evidence/cloud-originals-1"
            directory = HERE / "retained-cloud"
            directory.mkdir(exist_ok=False)
            for path in sorted(original.iterdir()):
                assert path.is_file() and not path.is_symlink()
                shutil.copyfile(path, directory / path.name)
                assert path.read_bytes() == (directory / path.name).read_bytes()
            expected_sha, expected_files, expected_bytes = CLOUD_SHA, 516, 25904697
            archive = directory / "cloud-originals.tar.xz"
        else:
            directory = HERE / "retained-host"
            expected_sha, expected_files, expected_bytes = HOST_SHA, 791, 222686491
            archive = directory / "original-evidence.tar.xz"
        archive_raw = archive.read_bytes()
        assert sha(archive_raw) == expected_sha
        manifest_raw = (directory / "MANIFEST.json").read_bytes()
        manifest = json.loads(manifest_raw)
        sidecar = json.loads((directory / "RESULT.json").read_bytes())
        assert sidecar["successful"] and sidecar["source"] == manifest["source"] == SOURCE
        assert sidecar["archive_sha256"] == expected_sha and sidecar["archive_bytes"] == len(archive_raw)
        assert sidecar["manifest_sha256"] == sha(manifest_raw)
        assert sidecar["original_files"] == len(manifest["files"]) == expected_files
        assert sidecar["original_bytes"] == sum(row["bytes"] for row in manifest["files"]) == expected_bytes
        indexed = {row["path"]: row for row in manifest["files"]}
        assert len(indexed) == expected_files
        for name in indexed:
            safe_name(name)
        parts = sidecar["parts"]
        if kind == "host":
            parts_sidecar = json.loads((directory / "archive-parts.json").read_bytes())
            assert parts_sidecar["parts"] == parts and parts_sidecar["archive_sha256"] == expected_sha
            assert parts_sidecar["archive_bytes"] == len(archive_raw) and parts_sidecar["archive_name"] == archive.name
        offset = 0
        for row in parts:
            safe_name(row["name"])
            assert 0 < row["bytes"] <= 480000
            raw = archive_raw[offset:offset + row["bytes"]]
            assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
            target = directory / row["name"]
            if target.exists():
                assert target.read_bytes() == raw
            else:
                target.write_bytes(raw)
            if kind == "host":
                info = json.loads((HERE / "receipts" / (row["name"] + "-file-info.json")).read_bytes())
                remote = json.loads(info["result"]["content"][0]["text"])
                assert remote["size"] == row["bytes"] and remote["sha256"] == row["sha256"]
            offset += row["bytes"]
        assert offset == len(archive_raw) and len(parts) == (9 if kind == "host" else 5)

        cache, verified = {}, []
        with tarfile.open(archive, "r:xz") as stream:
            members = stream.getmembers()
            names = [member.name for member in members]
            assert len(names) == len(set(names))
            extras = {"MANIFEST.json", "ORIGINAL_FILES.nul"} if kind == "host" else {"MANIFEST.json"}
            assert set(names) == set(indexed) | extras
            for member in members:
                safe_name(member.name)
                assert member.isfile() and not member.linkname and member.size >= 0
                if member.name in indexed:
                    assert member.size == indexed[member.name]["bytes"]
                else:
                    assert member.size < 512000
            for member in members:
                file = stream.extractfile(member)
                digest, count = hashlib.sha256(), 0
                retain = member.name in extras or (kind == "host" and (member.name in {"INPUT.json", "PHYSICAL_ORIGINALS.json", "EXCLUDED_KEY_METADATA.json", "PRIVATE_MATERIAL_SCOPE.json", "SUMMARY.json", "TERMINAL_OBSERVATIONS.json"} or member.name.startswith("source-9df/") or "namespace-noupdate11-original-inputs-2/" in member.name or "namespace-noupdate11-runtime-inputs-4/" in member.name))
                collected = []
                while chunk := file.read(1048576):
                    digest.update(chunk)
                    count += len(chunk)
                    if retain:
                        collected.append(chunk)
                assert count == member.size
                if member.name in indexed:
                    assert digest.hexdigest() == indexed[member.name]["sha256"], member.name
                verified.append({"path": member.name, "bytes": count, "sha256": digest.hexdigest(), "regular": True})
                if retain:
                    cache[member.name] = b"".join(collected)
        assert cache["MANIFEST.json"] == manifest_raw
        save(output / "ALL_MEMBERS_VERIFIED.json", verified)
        if kind == "host":
            assert manifest["tree"] == sidecar["tree"] == TREE
            assert manifest["private_key_file_bodies_read"] is False and sidecar["private_key_file_bodies_read"] is False
            assert sha(cache["ORIGINAL_FILES.nul"]) == manifest["original_files_nul_sha256"]
            paths = [part.decode() for part in cache["ORIGINAL_FILES.nul"].split(b"\0") if part]
            assert len(paths) == expected_files and len(set(paths)) == expected_files and set(paths) == set(indexed)
            assert cache["SUMMARY.json"] == (directory / "SUMMARY.json").read_bytes()
            assert sha(cache["SUMMARY.json"]) == sidecar["summary_sha256"]
            assert cache["EXCLUDED_KEY_METADATA.json"] == (directory / "EXCLUDED_KEY_METADATA.json").read_bytes()
            meta = json.loads(cache["INPUT.json"])
            supplied_meta = ROOT / "e6_owner_work/completion_namespace_evidence/ARCHIVE_META_REV2.json"
            assert supplied_meta.read_bytes() == cache["INPUT.json"]
            assert (meta["source"], meta["tree"]) == (SOURCE, TREE)
            keys = json.loads(cache["EXCLUDED_KEY_METADATA.json"])
            assert len(keys) == 3 and keys == meta["excluded_keys"]
            key_paths = {row["path"] for row in keys}
            assert len(key_paths) == 3 and all(row["body_readback"] == "metadata-only; key and authority bodies are not emitted" for row in keys)
            assert not key_paths.intersection(row.get("original_path") for row in indexed.values())
            physical = json.loads(cache["PHYSICAL_ORIGINALS.json"])
            assert len(physical) == sidecar["physical_original_count"] == 94
            physical_expected = []
            for capture in meta["physical_captures"]:
                prefix = "raw/" + capture["directory"] + "/"
                raw = cache[prefix + "CAPTURED_INPUTS.json"]
                assert sha(raw) == capture["manifest_sha256"]
                rows = json.loads(raw)
                assert len(rows) == capture["count"] and sum(row["bytes"] for row in rows) == capture["bytes"]
                for row in rows:
                    assert row["original_path"] not in key_paths and not Path(row["original_path"]).name.endswith(".key")
                    name = prefix + row["captured_path"]
                    actual = indexed[name]
                    assert actual["bytes"] == row["bytes"] and actual["sha256"] == row["sha256"]
                    raw = cache[name]
                    assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
                    explicit_private_material_check(raw, name)
                    physical_expected.append(dict(row, capture_directory=capture["directory"]))
            assert physical_expected == physical
            assert [row["count"] for row in meta["physical_captures"]] == [58, 36]
            assert json.loads(cache["PRIVATE_MATERIAL_SCOPE.json"])["captured_non_key_files_checked"] == 94
            source_rows = []
            prepared = json.loads((ROOT / "e6_final_blob_gate_work/prepared-shadow/MANIFEST.json").read_bytes())
            source_objects = {row["oid"]: row for row in prepared["objects"]}
            for row in meta["source_files"]:
                raw = cache["source-9df/" + row["path"]]
                assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
                assert git_blob(raw) == row["git_blob_oid"]
                original = source_objects[row["git_blob_oid"]]
                assert original["bytes"] == len(raw) and original["sha256"] == sha(raw)
                source_rows.append({"path": row["path"], "bytes": len(raw), "sha256": sha(raw), "git_blob": row["git_blob_oid"], "independent_git_source_match": True})
            assert len(source_rows) == 11
            for path, digest in meta["result_sha256"].items():
                assert indexed["raw/" + path]["sha256"] == digest
            for row in meta["host_driver_files"]:
                assert indexed["drivers/" + row["path"]]["sha256"] == row["sha256"]
            for name, row in meta["supplied_cloud_files"].items():
                raw = base64.b64decode(row["base64"], validate=True)
                assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
                assert indexed[name]["sha256"] == row["sha256"] and indexed[name]["bytes"] == row["bytes"]
            for session, terminal in meta["terminals"].items():
                assert terminal["status"]["state"] == "exited" and terminal["output_complete"] is True
                assert terminal["status"].get("capture_error") is None
                assert indexed["terminals/" + session + "/output.log"]["bytes"] == terminal["available_end"]
            crosscheck = {"physical_inputs": 94, "physical_batches": meta["physical_captures"], "physical_bytes": sum(row["bytes"] for row in physical), "excluded_key_metadata_count": 3, "private_key_file_bodies_present": False, "explicit_private_material_check": "Known PEM markers and named private-body JSON fields checked on the 94 physical files; not a universal secret detector.", "source_files": source_rows, "result_sha_bindings": len(meta["result_sha256"]), "host_drivers": len(meta["host_driver_files"]), "supplied_cloud_files": len(meta["supplied_cloud_files"]), "terminal_logs": len(meta["terminals"]), "source_qualification_not_implied": True}
            save(output / "PHYSICAL_SOURCE_TERMINAL_CROSSCHECK.json", crosscheck)
            result["crosscheck"] = crosscheck
        result.update({"status": "PASS", "archive_sha256": expected_sha, "archive_bytes": len(archive_raw), "manifest_sha256": sha(manifest_raw), "original_files": expected_files, "original_bytes": expected_bytes, "tar_regular_members": len(verified), "extra_manifest_members": len(extras), "parts": len(parts), "max_part_bytes": max(row["bytes"] for row in parts), "all_member_names_unique_safe": True, "all_member_sizes_and_sha256_match": True, "all_members_regular_no_links": True, "sidecar_result_preserved_outside_tar": True})
    except Exception as error:
        result.update({"status": "FAIL", "error": type(error).__name__ + ": " + str(error)})
        (output / "exception.txt").write_text(traceback.format_exc())
    result["wall_seconds"] = time.monotonic() - started
    save(output / "RESULT.json", result)
    print(json.dumps({key: result.get(key) for key in ("kind", "status", "original_files", "original_bytes", "tar_regular_members", "error", "wall_seconds")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("host", "cloud"))
    raise SystemExit(verify(parser.parse_args().kind))
