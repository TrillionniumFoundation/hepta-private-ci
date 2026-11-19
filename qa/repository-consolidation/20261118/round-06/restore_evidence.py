"""Verify original evidence bundles and optionally restore one outside the repository."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile


MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


def checked(raw, size, digest):
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("evidence byte length or SHA-256 mismatch")
    return raw


def relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        raise ValueError("invalid evidence path")
    return path


def bounded_gunzip(raw, expected):
    if not isinstance(expected, int) or not 0 <= expected <= MAX_ARCHIVE_BYTES:
        raise ValueError("invalid evidence expansion bound")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(expected + 1)
    if len(expanded) != expected:
        raise ValueError("evidence expansion length mismatch")
    return expanded


def verify_bundle(here, bundle):
    chunks = []
    for part in bundle["parts"]:
        path = here.joinpath(*relative(part["path"]).parts)
        cursor = path
        while cursor != here:
            if cursor.is_symlink():
                raise ValueError("symbolic link in evidence carrier path")
            cursor = cursor.parent
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("evidence carrier is not a regular file")
        with path.open("rb") as stream:
            compressed = checked(
                stream.read(part["bytes"] + 1), part["bytes"], part["sha256"]
            )
        chunks.append(
            checked(
                bounded_gunzip(compressed, part["payload_bytes"]),
                part["payload_bytes"],
                part["payload_sha256"],
            )
        )
    original_archive = checked(
        b"".join(chunks), bundle["archive_bytes"], bundle["archive_sha256"]
    )
    raw_tar = checked(
        bounded_gunzip(original_archive, bundle["tar_bytes"]),
        bundle["tar_bytes"],
        bundle["tar_sha256"],
    )
    names = [entry["path"] for entry in bundle["files"]]
    if len(names) != len(set(names)):
        raise ValueError("duplicate evidence member")
    verified = []
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
        members = archive.getmembers()
        if [member.name for member in members] != names:
            raise ValueError("evidence archive membership mismatch")
        for member, entry in zip(members, bundle["files"], strict=True):
            name = relative(entry["path"])
            if not member.isfile() or member.size != entry["bytes"]:
                raise ValueError("evidence member is not the expected regular file")
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError("missing evidence member data")
            contents = checked(
                handle.read(entry["bytes"] + 1), entry["bytes"], entry["sha256"]
            )
            if member.mode & 0o777 != entry["mode"]:
                raise ValueError("evidence member mode mismatch")
            verified.append((name, contents, entry["mode"]))
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / "evidence-manifest.json").read_text())
    if manifest.get("schema") != "hepta.consolidation-evidence.v2":
        raise ValueError("unknown evidence schema")
    if args.bundle not in manifest["bundles"]:
        raise ValueError("unknown evidence bundle")
    verified = verify_bundle(here, manifest["bundles"][args.bundle])
    if args.output is not None:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("output must be a new directory")
        output = args.output.resolve()
        repository = here.parents[3]
        if output == repository or output.is_relative_to(repository):
            raise ValueError("output must be outside the source repository")
        output.mkdir(parents=True, exist_ok=False)
        for name, contents, mode in verified:
            destination = output.joinpath(*name.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(contents)
            destination.chmod(mode)
    print(
        json.dumps(
            {
                "bundle": args.bundle,
                "verified_files": len(verified),
                "restored": args.output is not None,
            }
        )
    )


if __name__ == "__main__":
    main()
