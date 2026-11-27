"""Verify exact evidence bytes without extracting or executing archive members."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest(),
    }


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_identity(data, record):
    actual = identity(data)
    for key in ("bytes", "sha256", "git_blob"):
        require(actual[key] == record[key], f"Evidence {key} mismatch")


def safe_name(value):
    name = PurePosixPath(value)
    require(
        bool(value)
        and not name.is_absolute()
        and str(name) == value
        and ".." not in name.parts
        and "\\" not in value
        and not any(c in value for c in "\n\r\t\0"),
        "Unsafe evidence path",
    )
    return name


def safe_file(root, relative):
    safe_name(relative)
    candidate = root / relative
    require(not candidate.is_symlink(), "Evidence file is a symbolic link")
    resolved = candidate.resolve(strict=True)
    require(resolved.is_relative_to(root), "Evidence file leaves root")
    require(resolved.is_file(), "Evidence file is not a regular file")
    return resolved


def verify(root):
    index = json.loads(safe_file(root, "evidence-index.json").read_bytes())
    require(index["schema"] == "hepta.gzip-fragment-evidence.v1", "Unknown schema")
    group_ids = set()
    all_stored_paths = set()
    results = []
    for group in index["groups"]:
        require(group["id"] not in group_ids, "Duplicate evidence group")
        group_ids.add(group["id"])
        fragments = []
        offset = 0
        for number, part in enumerate(group["parts"]):
            require(part["number"] == number, "Fragment sequence mismatch")
            require(part["offset"] == offset, "Fragment offset mismatch")
            require(part["path"] not in all_stored_paths, "Duplicate stored path")
            all_stored_paths.add(part["path"])
            stored = safe_file(root, part["path"]).read_bytes()
            verify_identity(stored, part["stored"])
            require(
                stored[:8] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00",
                "Unexpected gzip header",
            )
            require(b"\0" in stored[:1024], "Missing binary header")
            fragment = gzip.decompress(stored)
            verify_identity(fragment, part["fragment"])
            require(
                0 < len(fragment) <= group["fragment_bytes"], "Invalid fragment size"
            )
            require(
                number == len(group["parts"]) - 1
                or len(fragment) == group["fragment_bytes"],
                "Short nonterminal fragment",
            )
            offset += len(fragment)
            fragments.append(fragment)
        archive = b"".join(fragments)
        verify_identity(archive, group["archive"])
        require(offset == group["archive"]["bytes"], "Incomplete archive")
        record = group["member_manifest"]
        require(record["path"] not in all_stored_paths, "Duplicate manifest path")
        all_stored_paths.add(record["path"])
        manifest_bytes = safe_file(root, record["path"]).read_bytes()
        verify_identity(manifest_bytes, record)
        manifest = json.loads(manifest_bytes)
        expected = manifest["members"]
        require(manifest["archive"] == group["archive"], "Archive manifest mismatch")
        require(len(expected) == group["member_count"], "Member count mismatch")
        names = set()
        member_bytes = 0
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            actual_members = tf.getmembers()
            require(len(actual_members) == len(expected), "Unexpected archive members")
            for member, item in zip(actual_members, expected, strict=True):
                safe_name(member.name)
                require(member.name not in names, "Duplicate archive member")
                names.add(member.name)
                require(member.name == item["path"], "Member name or order mismatch")
                require(member.isfile(), "Archive contains a non-file member")
                require(member.mode == 0o644, "Unexpected archive mode")
                require(
                    member.uid == member.gid == member.mtime == 0,
                    "Archive metadata mismatch",
                )
                require(member.uname == member.gname == "", "Unexpected archive owner")
                require(member.size == item["bytes"], "Tar member size mismatch")
                stream = tf.extractfile(member)
                require(stream is not None, "Missing member stream")
                data = stream.read()
                verify_identity(data, item)
                member_bytes += len(data)
        require(member_bytes == group["member_bytes"], "Member byte total mismatch")
        results.append(
            {
                "group": group["id"],
                "stored_fragments": len(fragments),
                "archive_sha256": group["archive"]["sha256"],
                "members_verified": len(expected),
                "member_bytes": member_bytes,
            }
        )
    return {
        "status": "PASS_EXACT_EVIDENCE_VERIFICATION",
        "source_head": index["source_head"],
        "source_tree": index["source_tree"],
        "groups": results,
        "members_verified": sum(row["members_verified"] for row in results),
        "member_bytes": sum(row["member_bytes"] for row in results),
        "archive_members_extracted_or_executed": False,
        "native_or_repository_tests_run": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve(strict=True)), indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
