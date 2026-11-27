"""Restore the exact published C2 resource program without executing it."""
from argparse import ArgumentParser
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import stat
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
MAX_ARCHIVE_BYTES = 512_000
MAX_EXTRACTED_BYTES = 1_000_000
MANIFEST = "MANIFEST.json"


def verify(raw, record, label):
    if len(raw) != record["bytes"] or sha256(raw).hexdigest() != record["sha256"]:
        raise ValueError(f"published {label} does not match its frozen identity")


def read_program():
    freeze = json.loads((ROOT / "FREEZE.json").read_bytes())
    with (ROOT / "program.zip").open("rb") as stream:
        raw = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError("published archive is too large")
    verify(raw, freeze["program_zip"], "archive")

    with ZipFile(BytesIO(raw)) as archive:
        entries = archive.infolist()
        names = {entry.filename for entry in entries}
        if len(names) != len(entries) or MANIFEST not in names:
            raise ValueError("invalid archive member roster")
        if sum(entry.file_size for entry in entries) > MAX_EXTRACTED_BYTES:
            raise ValueError("published program is too large")
        for entry in entries:
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if (
                not entry.filename
                or entry.filename in {".", ".."}
                or "/" in entry.filename
                or "\\" in entry.filename
                or entry.is_dir()
                or kind not in {0, stat.S_IFREG}
            ):
                raise ValueError("program archive must contain only flat regular files")

        manifest = archive.read(MANIFEST)
        verify(manifest, freeze["program_manifest"], "manifest")
        records = json.loads(manifest)["files"]
        if names != set(records) | {MANIFEST} or MANIFEST in records:
            raise ValueError("archive members differ from the published manifest")
        contents = {MANIFEST: manifest}
        for name, record in records.items():
            contents[name] = archive.read(name)
            verify(contents[name], record, name)
        return contents


def restore(destination):
    contents = read_program()
    destination.mkdir(mode=0o700)
    written = []
    try:
        for name, raw in contents.items():
            path = destination / name
            with path.open("xb") as stream:
                written.append(path)
                stream.write(raw)
    except BaseException:
        for path in written:
            path.unlink()
        destination.rmdir()
        raise
    return len(contents)


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="a new directory")
    args = parser.parse_args()
    print(f"Restored {restore(args.destination)} verified original files")
