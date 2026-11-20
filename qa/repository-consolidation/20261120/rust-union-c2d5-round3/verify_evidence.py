"""Verify lossless evidence partitions without extracting or executing members."""

import argparse
import gzip
import hashlib
import io
import json
import pathlib
import tarfile


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest(),
    }


def verify_identity(data, record):
    expected_size = record.get("bytes", record.get("size"))
    actual = identity(data)
    assert actual["bytes"] == expected_size, "Byte count mismatch"
    assert actual["sha256"] == record["sha256"], "SHA256 mismatch"
    assert actual["git_blob"] == record["git_blob"], "Git blob mismatch"


def safe_file(root, relative):
    candidate = root.joinpath(relative).resolve()
    assert candidate.is_relative_to(root), "Path leaves evidence directory"
    assert candidate.is_file(), f"Missing evidence file: {relative}"
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=pathlib.Path, default=pathlib.Path(__file__).parent
    )
    args = parser.parse_args()
    root = args.root.resolve()
    index = json.loads(safe_file(root, "evidence-index.json").read_text())
    results = []
    for group in index["groups"]:
        chunks = []
        for part in group["parts"]:
            data = safe_file(root, part["path"]).read_bytes()
            verify_identity(data, part)
            chunks.append(data)
        archive = b"".join(chunks)
        verify_identity(archive, group["archive"])
        manifest_record = group["member_manifest"]
        manifest_bytes = safe_file(root, manifest_record["path"]).read_bytes()
        verify_identity(manifest_bytes, manifest_record)
        if manifest_record.get("compression") == "gzip":
            manifest_bytes = gzip.decompress(manifest_bytes)
            verify_identity(manifest_bytes, manifest_record["uncompressed"])
        manifest = json.loads(manifest_bytes)
        expected = manifest["members"]
        total_bytes = 0
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            members = tf.getmembers()
            assert len(members) == len(expected) == group["member_count"]
            for member, record in zip(members, expected, strict=True):
                member_name = record.get("member", record.get("path"))
                assert member.name == member_name, "Member order/name mismatch"
                name = pathlib.PurePosixPath(member.name)
                assert not name.is_absolute() and ".." not in name.parts
                assert member.isfile(), "Non-file member"
                assert member.uid == member.gid == member.mtime == 0
                assert member.mode == 0o644
                stream = tf.extractfile(member)
                assert stream is not None
                data = stream.read()
                verify_identity(data, record)
                total_bytes += len(data)
        results.append(
            {
                "group": group["id"],
                "parts": len(group["parts"]),
                "archive_sha256": group["archive"]["sha256"],
                "members_verified": len(expected),
                "uncompressed_member_bytes": total_bytes,
            }
        )
    print(
        json.dumps(
            {
                "status": "PASS_LOSSLESS_EVIDENCE_CONTENT_VERIFICATION",
                "source_head": index["source_head"],
                "groups": results,
                "members_verified": sum(r["members_verified"] for r in results),
                "uncompressed_member_bytes": sum(
                    r["uncompressed_member_bytes"] for r in results
                ),
                "native_tests_executed": False,
                "members_extracted_or_executed": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
