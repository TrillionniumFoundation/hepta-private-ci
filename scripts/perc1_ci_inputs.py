"""Fetch exact public PERC CI inputs into a fresh, runner-private directory.

The official FUNSD archive and torchvision checkpoint must match full SHA-256
pins before extraction/use. This module never uploads dataset contents. The
panel is an explicit-ROI engineering input, not independent source confirmation.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile


FUNSD = {
    "url": "https://guillaumejaume.github.io/FUNSD/dataset.zip",
    "sha256": "c31735649e4f441bcbb4fd0f379574f7520b42286e80b01d80b445649d54761f",
    "bytes": 16838830,
}
WEIGHTS = {
    "url": "https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth",
    "sha256": "047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f",
    "bytes": 10306551,
}


def download(path, source):
    """Publish a download only after complete length and SHA verification."""
    if path.exists():
        raise ValueError("refuse to overwrite a previous download")
    temporary = path.with_name(path.name + ".partial")
    hasher, total = hashlib.sha256(), 0
    started = time.perf_counter_ns()
    request = Request(source["url"], headers={"User-Agent": "Hepta-PERC-CI/1"})
    with urlopen(request, timeout=30) as response, temporary.open("xb") as stream:
        if response.status != 200 or not response.geturl().startswith("https://"):
            raise ValueError("source transport did not return HTTPS success")
        while chunk := response.read(65536):
            total += len(chunk)
            if total > source["bytes"]:
                raise ValueError("download exceeded its pinned byte count")
            hasher.update(chunk)
            stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    if total != source["bytes"] or hasher.hexdigest() != source["sha256"]:
        raise ValueError("download length or full SHA-256 pin mismatch")
    temporary.rename(path)
    return {**source, "download_wall_ns": time.perf_counter_ns() - started}


def extract_zip(archive, destination):
    """Extract a bounded regular-file ZIP into a new directory without aliases."""
    if destination.exists():
        raise ValueError("refuse to overwrite a previous extraction")
    with ZipFile(archive) as source:
        members, seen = source.infolist(), set()
        if len(members) > 1000 or sum(m.file_size for m in members) > 40 * 1024 * 1024:
            raise ValueError("archive member or expanded-size bound exceeded")
        for member in members:
            path = PurePosixPath(member.filename)
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (
                not member.filename
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in member.filename
                or PureWindowsPath(member.filename).drive
                or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                or member.filename in seen
                or member.flag_bits & 1
            ):
                raise ValueError("unsafe, encrypted or aliased ZIP member")
            seen.add(member.filename)
        destination.mkdir(mode=0o700)
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            count = 0
            with source.open(member) as reader, target.open("xb") as writer:
                while chunk := reader.read(65536):
                    count += len(chunk)
                    if count > member.file_size:
                        raise ValueError("ZIP member exceeded declared size")
                    writer.write(chunk)
            if count != member.file_size:
                raise ValueError("ZIP member size mismatch")
    return len(members), sum(member.file_size for member in members)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    archive = download(root / "funsd-official.zip", FUNSD)
    weights = download(root / "mobilenet_v3_small-047dcff4.pth", WEIGHTS)
    members, expanded = extract_zip(root / "funsd-official.zip", root / "funsd")
    record = {
        "schema": "perc1.funsd-source-acquisition.v1",
        "url": FUNSD["url"],
        "archive_sha256": FUNSD["sha256"],
        "archive_bytes": FUNSD["bytes"],
        "archive_members": members,
        "expanded_bytes": expanded,
        "observed_at_unix_ns": time.time_ns(),
        "source": "official FUNSD noncommercial research",
        "download_wall_ns": archive["download_wall_ns"],
        "scientific_qualified": False,
    }
    (root / "funsd-acquisition.json").write_text(json.dumps(record, indent=2) + "\n")
    (root / "weight-acquisition.json").write_text(json.dumps(weights, indent=2) + "\n")
    from perc1.document_data import prepare

    panel = prepare(root / "funsd/dataset", root / "funsd-panel", 64, 16, 32)
    print(json.dumps({"funsd": record, "weights": weights, "panel": panel}, indent=2))


if __name__ == "__main__":
    main()
