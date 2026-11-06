"""Restore only the pinned original ZIP bytes; do not extract or execute them."""

import argparse
import hashlib
import json
from pathlib import Path
import zlib


EXPECTED_INDEX_SHA256 = (
    "ccceb0d50a7549504fe33d262113e88a5bebaf001a4818c1b42be4e534ef1cc9"
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    destination = parser.parse_args().output.absolute()
    package = Path(__file__).resolve().parent
    index_path = package / "ORIGINAL_ARTIFACT.json"
    if index_path.is_symlink() or not index_path.is_file():
        raise ValueError("Expected regular artifact index")
    raw = index_path.read_bytes()
    if digest(raw) != EXPECTED_INDEX_SHA256:
        raise ValueError("Original artifact index changed")
    index = json.loads(raw)
    if index["schema"] != "ndu.native-original-artifact.transport.v1":
        raise ValueError("Unexpected artifact format")
    segments = []
    for number, part in enumerate(index["parts"]):
        if part["file"] != f"producer-artifact.zip.part-{number:02}.gz":
            raise ValueError("Unexpected artifact container name")
        path = package / part["file"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("Expected regular artifact container")
        raw = path.read_bytes()
        if len(raw) != part["gzip"]["bytes"] or digest(raw) != part["gzip"]["sha256"]:
            raise ValueError("Artifact container identity differs")
        decoder = zlib.decompressobj(wbits=31)
        segment = decoder.decompress(raw, part["segment"]["bytes"] + 1)
        if (
            not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or len(segment) != part["segment"]["bytes"]
            or digest(segment) != part["segment"]["sha256"]
        ):
            raise ValueError("Artifact segment is not the exact bounded gzip member")
        segments.append(segment)
    original = b"".join(segments)
    if (
        len(original) != index["artifact"]["bytes"]
        or digest(original) != index["artifact"]["sha256"]
    ):
        raise ValueError("Original ZIP identity differs")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to overwrite an existing output")
    if any(p.is_symlink() for p in (destination.parent, *destination.parent.parents)):
        raise ValueError("Output parent must not contain symlinks")
    with destination.open("xb") as output:
        output.write(original)
    destination.chmod(0o644)
    print(
        json.dumps(
            {
                "bytes": len(original),
                "sha256": digest(original),
                "output": str(destination),
            }
        )
    )


if __name__ == "__main__":
    main()
