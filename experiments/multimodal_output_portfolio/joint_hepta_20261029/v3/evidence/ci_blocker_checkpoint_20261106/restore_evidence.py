"""Restore a pinned, inert evidence archive after checking every original byte."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import zlib


EXPECTED_INDEX_SHA256 = (
    "2c5910ea845b0b54362370ea325791d6ce799f8f974c0c22807bb5cefe1ad6c1"
)
EXPECTED_TRANSPORT_SHA256 = (
    "42d3ff6917301749f484f18d25c193f91608bb6904767ed1feca1088654025c4"
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (
        not isinstance(name, str)
        or not name
        or path.is_absolute()
        or path.as_posix() != name
        or ".." in path.parts
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        raise ValueError("Noncanonical evidence member path")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    index_path = package / "INDEX.json"
    if index_path.is_symlink():
        raise ValueError("Evidence index must be a regular file")
    raw_index = index_path.read_bytes()
    if digest(raw_index) != EXPECTED_INDEX_SHA256:
        raise ValueError("Evidence index differs from the pinned package")
    index = json.loads(raw_index)
    if index["schema"] != "ndu.ci-evidence.archive.v1":
        raise ValueError("Unknown archive schema")
    transport_path = package / "TRANSPORT.json"
    if transport_path.is_symlink() or not transport_path.is_file():
        raise ValueError("Missing regular evidence transport record")
    raw_transport = transport_path.read_bytes()
    if digest(raw_transport) != EXPECTED_TRANSPORT_SHA256:
        raise ValueError("Evidence transport differs from its fixed review seal")
    transport = json.loads(raw_transport)
    if (
        transport["schema"] != "ndu.ci-evidence.part-transport.v1"
        or transport["representation"] != "one-bounded-gzip-member-per-original-segment"
        or transport["index_sha256"] != EXPECTED_INDEX_SHA256
        or transport["original_archive_sha256"] != index["archive"]["sha256"]
        or set(transport["parts"]) != {part["file"] for part in index["parts"]}
    ):
        raise ValueError("Evidence transport changed its original archive binding")
    destination = args.destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to overwrite an existing destination")
    for part in (destination.parent, *destination.parent.parents):
        if part.is_symlink():
            raise ValueError("Destination parent must not contain symlinks")
    if not destination.parent.is_dir():
        raise ValueError("Destination parent must already exist")
    expected = index["files"]
    for name in expected:
        safe_name(name)
    with tempfile.TemporaryDirectory(
        prefix="ndu-evidence-", dir=destination.parent
    ) as temporary:
        work = Path(temporary)
        archive_path = work / "archive.tar.gz"
        combined = hashlib.sha256()
        total = 0
        names = set()
        with archive_path.open("xb") as output:
            for entry in index["parts"]:
                name = entry["file"]
                safe_name(name)
                if "/" in name or name in names:
                    raise ValueError("Duplicate or nested part name")
                names.add(name)
                wrapped = transport["parts"][name]
                wrapped_name = wrapped["file"]
                safe_name(wrapped_name)
                if wrapped_name != name + ".gz":
                    raise ValueError("Unexpected evidence container path")
                path = package / wrapped_name
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Missing regular evidence container")
                compressed = path.read_bytes()
                if (
                    len(compressed) != wrapped["bytes"]
                    or digest(compressed) != wrapped["sha256"]
                ):
                    raise ValueError("Evidence container differs from its identity")
                inflater = zlib.decompressobj(wbits=31)
                raw = inflater.decompress(compressed, entry["bytes"] + 1)
                if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                    raise ValueError(
                        "Evidence container is not exactly one bounded gzip member"
                    )
                if len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
                    raise ValueError("Archive part differs from its identity")
                output.write(raw)
                combined.update(raw)
                total += len(raw)
        if (
            total != index["archive"]["bytes"]
            or combined.hexdigest() != index["archive"]["sha256"]
        ):
            raise ValueError("Combined archive differs from its original identity")
        staging = work / "restored"
        staging.mkdir()
        seen = set()
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive:
                safe_name(member.name)
                if (
                    not member.isfile()
                    or member.name not in expected
                    or member.name in seen
                ):
                    raise ValueError(
                        "Unexpected, duplicate, linked or special archive member"
                    )
                identity = expected[member.name]
                if member.size != identity["bytes"]:
                    raise ValueError("Member size differs from its original identity")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Missing member contents")
                target = staging / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                check = hashlib.sha256()
                count = 0
                with source, target.open("xb") as output:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        count += len(block)
                        check.update(block)
                        output.write(block)
                if (
                    count != identity["bytes"]
                    or check.hexdigest() != identity["sha256"]
                ):
                    raise ValueError("Member bytes differ from their original identity")
                # Restored material is inert data. Nothing is automatically run.
                target.chmod(0o644)
                seen.add(member.name)
        if seen != set(expected):
            raise ValueError("Archive omitted expected evidence")
        staging.rename(destination)
    print(
        json.dumps(
            {
                "status": "restored",
                "files": len(expected),
                "bytes": sum(item["bytes"] for item in expected.values()),
                "index_sha256": EXPECTED_INDEX_SHA256,
                "destination": str(destination),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
