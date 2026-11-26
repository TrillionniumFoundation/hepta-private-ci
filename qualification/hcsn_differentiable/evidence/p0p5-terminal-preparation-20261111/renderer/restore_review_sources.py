"""Restore four archived renderer review sources to a new directory.

The original review, execution permission and recorded manifests are unchanged.
Restoring source bytes does not execute any of the historical checks.
"""
from argparse import ArgumentParser
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import stat
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
ARCHIVE = "renderer/complete-preparation.zip"
FROZEN_BYTES = 322_699
FROZEN_SHA256 = "5601bea47a9f0b775c414d9f73cf3fb2f758111ce8d97ba97729b9cfafccd511"
MEMBERS = (
    "independent-review/closure-with-postcheck-gap/launch_probe.py",
    "independent-review/closure-with-postcheck-gap/probe.py",
    "independent-review/coverage-rebind/check.py",
    "independent-review/coverage-rebind/launch.py",
)


def read_sources(root):
    rows = json.loads((root.parent / "ARCHIVES.json").read_bytes())["archives"]
    binding, = (row for row in rows if row["path"] == ARCHIVE)
    if (binding["bytes"], binding["sha256"]) != (FROZEN_BYTES, FROZEN_SHA256):
        raise ValueError("renderer archive binding differs from the frozen identity")
    with (root / "complete-preparation.zip").open("rb") as stream:
        raw = stream.read(FROZEN_BYTES + 1)
    if len(raw) != FROZEN_BYTES or sha256(raw).hexdigest() != FROZEN_SHA256:
        raise ValueError("renderer archive differs from the frozen identity")

    contents = {}
    with ZipFile(BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(binding["members"]):
            raise ValueError("renderer archive member roster differs")
        for member in MEMBERS:
            name = "renderer/" + member
            record = binding["members"][name]
            entry = archive.getinfo(name)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if entry.is_dir() or kind not in {0, stat.S_IFREG} or entry.file_size != record["bytes"]:
                raise ValueError(f"invalid regular archive member: {name}")
            data = archive.read(entry)
            if len(data) != record["bytes"] or sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"archive member differs from its original identity: {name}")
            contents[member] = data
    return contents


def restore(destination):
    contents = read_sources(ROOT)
    destination.mkdir(mode=0o700)
    for name, data in contents.items():
        target = destination / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    return len(contents)


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="a new renderer directory")
    args = parser.parse_args()
    print(f"Restored {restore(args.destination)} verified original files")
