"""Restore the exact raw run from bounded, SHA-256 verified archive parts."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def restore(bundle, output):
    bundle, output = Path(bundle), Path(output)
    manifest = json.loads((bundle / "PARTS.json").read_text())
    if manifest.get("schema") != "hepta.ndu-validation-archive.v1":
        raise ValueError("Unknown archive schema")
    if output.exists():
        raise FileExistsError("Use a new output directory")
    data = bytearray()
    names = set()
    for part in manifest["parts"]:
        if Path(part["path"]).name != part["path"] or part["path"] in names:
            raise ValueError("Invalid or duplicate archive part")
        names.add(part["path"])
        block = (bundle / part["path"]).read_bytes()
        if len(block) != part["bytes"] or hashlib.sha256(block).hexdigest() != part["sha256"]:
            raise ValueError("Archive part is missing or changed")
        data.extend(block)
    if len(data) != manifest["archive_bytes"] or hashlib.sha256(data).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Complete archive identity mismatch")
    expected = {entry["path"]: entry for entry in manifest["files"]}
    if len(expected) != len(manifest["files"]) or not expected:
        raise ValueError("Invalid file roster")
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for entry in archive:
            path = PurePosixPath(entry.name)
            if not entry.isfile() or path.is_absolute() or ".." in path.parts or entry.name not in expected or entry.name in contents:
                raise ValueError("Unexpected archive member")
            identity = expected[entry.name]
            if entry.size != identity["bytes"]:
                raise ValueError("Archived file size mismatch")
            content = archive.extractfile(entry).read()
            if hashlib.sha256(content).hexdigest() != identity["sha256"]:
                raise ValueError("Archived file hash mismatch")
            contents[entry.name] = content
    if set(contents) != set(expected):
        raise ValueError("Incomplete archived file roster")
    output.mkdir(parents=True, exist_ok=False)
    for name, content in contents.items():
        destination = output.joinpath(*PurePosixPath(name).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(content)
    return {"files": len(contents), "bytes": sum(map(len, contents.values())), "source_commit": manifest["source_commit"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(Path(__file__).resolve().parent, args.output), sort_keys=True))
