import argparse
import base64
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path


def identity(data):
    return {"bytes": len(data),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def verify(delivery, output):
    assert not output.exists(), "Use a new output directory."
    index = json.loads((delivery / "archive.json").read_bytes())
    manifest_raw = (delivery / "MANIFEST.json").read_bytes()
    assert identity(manifest_raw) == index["manifest"]
    manifest = json.loads(manifest_raw)
    archive_parts = []
    for part in index["parts"]:
        name = Path(part["file"])
        assert name.name == str(name) and not name.is_absolute()
        encoded = (delivery / name).read_bytes()
        assert identity(encoded) == {key: part[key] for key in ("bytes", "git_blob", "sha256")}
        assert encoded.endswith(b"\n") and encoded.count(b"\n") == 1
        decoded = base64.b64decode(encoded[:-1], validate=True)
        assert len(decoded) == part["decoded_bytes"]
        assert hashlib.sha256(decoded).hexdigest() == part["decoded_sha256"]
        archive_parts.append(decoded)
    assert len(archive_parts) == index["part_count"]
    archive = b"".join(archive_parts)
    assert identity(archive) == index["archive"]
    tar_bytes = gzip.decompress(archive)
    records = {item["path"]: item for item in manifest["files"]}
    assert len(records) == len(manifest["files"]) == index["member_count"] == 80
    output.mkdir(parents=True)
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        for member in tar:
            path = Path(member.name)
            assert member.isfile() and not path.is_absolute() and ".." not in path.parts
            assert member.name not in seen and member.mode == 0o644
            seen.add(member.name)
            raw = tar.extractfile(member).read()
            assert len(raw) == member.size
            if member.name == "MANIFEST.json":
                assert raw == manifest_raw
            else:
                assert member.name in records
                assert identity(raw) == {key: records[member.name][key] for key in ("bytes", "git_blob", "sha256")}
            target = output / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(raw)
    assert seen == set(records) | {"MANIFEST.json"}
    assert len(seen) == index["tar_member_count_including_manifest"] == 81
    packet = output / "packet"
    command = [sys.executable, "-B", str(packet / "verify_publications.py"), str(packet)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    (output / "publication-replay.stdout.json").write_bytes(result.stdout)
    (output / "publication-replay.stderr.txt").write_bytes(result.stderr)
    assert result.returncode == 0 and not result.stderr
    assert result.stdout == (packet / "verification-01.stdout.json").read_bytes()
    proof = json.loads(result.stdout)
    assert proof["result"] == "PASS_ORIGINAL_CUSTODY_AND_PUBLICATION_IDENTITIES_ONLY"
    response = {
        "schema": "hepta-integration-successor-portable-restore-verification-v1",
        "result": "PASS_LOSSLESS_RESTORE_AND_LIMITED_OFFLINE_PUBLICATION_VERIFICATION",
        "archive": index["archive"], "parts": len(archive_parts),
        "exact_preserved_members": len(records), "member_bytes": manifest["total_bytes"],
        "complete_arg0_batch_receipts": 4, "complete_original_arg0_GET_payloads": 30,
        "publication_verifier_exit": result.returncode,
        "publication_stdout": identity(result.stdout), "publication_stderr": identity(result.stderr),
        "publication_stdout_original_bytes_equal": True,
        "actual_original_API_publication_heads": ["aaf86881da0b3a7651b4a6a56be49515b9aa9f2e", "840e8b5dbffca017753cdf87482ce325938f313c"],
        "final_composed_tree": proof["tree_reconstruction"]["final"],
        "changed_paths_against_aaf": proof["tree_reconstruction"]["final_changed_paths_against_aaf"],
        "qualification_scope": proof["scope"],
        "scope": "Fresh isolated restoration and limited offline evidence verifier only; no original product/native/CI/externally dependent verifier rerun, no ref or PR changes.",
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    verify(args.delivery.resolve(), args.output.resolve())
