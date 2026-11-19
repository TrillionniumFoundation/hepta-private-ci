"""Restore the captured audit records into a new directory."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or path.as_posix() != value:
        raise ValueError("Invalid relative path")
    if any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("Invalid path component")
    return path


def verify(data, size, expected):
    if len(data) != size or digest(data) != expected:
        raise ValueError("Content identity mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    manifest = json.loads(
        gzip.decompress((source / "root-proof-manifest.json.gz").read_bytes())
    )
    if manifest["schema"] != 1:
        raise ValueError("Unsupported manifest schema")
    chunks = []
    seen_parts = set()
    for row in manifest["parts"]:
        name = row["path"]
        if (
            not re.fullmatch(r"proof-parts/[0-9]{3}\.part\.gz", name)
            or name in seen_parts
        ):
            raise ValueError("Invalid or repeated part")
        seen_parts.add(name)
        raw = (source / relative_path(name)).read_bytes()
        verify(raw, row["bytes"], row["sha256"])
        data = gzip.decompress(raw)
        verify(data, row["restoredBytes"], row["restoredSha256"])
        chunks.append(data)
    archive = b"".join(chunks)
    verify(archive, manifest["archiveBytes"], manifest["archiveSha256"])
    objects = {}
    with tarfile.open(
        fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:"
    ) as bundle:
        for member in bundle.getmembers():
            if not member.isfile() or not re.fullmatch(
                r"objects/[a-f0-9]{64}", member.name
            ):
                raise ValueError("Unexpected archive member")
            if member.name in objects:
                raise ValueError("Duplicate archive object")
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError("Missing archive content")
            data = stream.read()
            verify(data, member.size, member.name[8:])
            objects[member.name] = data
    if len(objects) != manifest["uniqueObjects"]:
        raise ValueError("Object count mismatch")
    names = set()
    used = set()
    for row in manifest["members"]:
        path = relative_path(row["path"])
        if path.as_posix() in names:
            raise ValueError("Duplicate logical path")
        names.add(path.as_posix())
        data = objects[row["object"]]
        verify(data, row["bytes"], row["sha256"])
        if row["object"] != "objects/" + row["sha256"]:
            raise ValueError("Unexpected object identity")
        if not isinstance(row["mode"], int) or row["mode"] < 0 or row["mode"] > 0o777:
            raise ValueError("Invalid file mode")
        used.add(row["object"])
    if used != set(objects):
        raise ValueError("Unused archive objects")
    for name in names:
        if any(parent.as_posix() in names for parent in PurePosixPath(name).parents):
            raise ValueError("File and directory collision")
    destination = args.destination.absolute()
    destination.mkdir(mode=0o700, exist_ok=False)
    for row in manifest["members"]:
        target = destination.joinpath(*relative_path(row["path"]).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(objects[row["object"]])
        os.chmod(target, row["mode"])
        verify(target.read_bytes(), row["bytes"], row["sha256"])
        if stat.S_IMODE(target.stat().st_mode) != row["mode"]:
            raise ValueError("Restored mode mismatch")
    print(
        json.dumps(
            {
                "members": len(names),
                "objects": len(objects),
                "archiveSha256": manifest["archiveSha256"],
                "allBytesAndModesVerified": True,
            }
        )
    )


if __name__ == "__main__":
    main()
