"""Lossless original-file archive and ordered-part reconstruction."""

import hashlib
import io
import json
import os
import resource
import tarfile
import time
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(originals, destination, archive_path):
    originals, destination, archive_path = map(Path, (originals, destination, archive_path))
    destination.mkdir(parents=True, exist_ok=False)
    files = sorted(path for path in originals.rglob("*") if path.is_file())
    manifest = [{"path": str(path.relative_to(originals)), "bytes": path.stat().st_size,
                 "sha256": sha(path.read_bytes())} for path in files]
    encoded = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    (destination / "MANIFEST.json").write_bytes(encoded)
    with tarfile.open(archive_path, "w:xz", format=tarfile.PAX_FORMAT, preset=6) as archive:
        for name, raw in [("MANIFEST.json", encoded)] + [("attempt001/" + item["path"], (originals / item["path"]).read_bytes()) for item in manifest]:
            header = tarfile.TarInfo(name)
            header.size = len(raw)
            header.mode = 0o644
            archive.addfile(header, io.BytesIO(raw))
    parts = []
    with archive_path.open("rb") as stream:
        while data := stream.read(4*1024**2):
            name = f"part-{len(parts):03}.tar.xz.part"
            (destination / name).write_bytes(data)
            parts.append({"name": name, "bytes": len(data), "sha256": sha(data),
                "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})
    raw = archive_path.read_bytes()
    if b"".join((destination / item["name"]).read_bytes() for item in parts) != raw:
        raise ValueError("ordered archive-part reconstruction")
    with tarfile.open(archive_path) as archive:
        if len(archive.getmembers()) != len(manifest) + 1 or archive.extractfile("MANIFEST.json").read() != encoded:
            raise ValueError("archive member denominator")
        for item in manifest:
            restored = archive.extractfile("attempt001/" + item["path"]).read()
            if len(restored) != item["bytes"] or sha(restored) != item["sha256"]:
                raise ValueError("actual archived original differs")
    return {"schema": "hcsn-n256-multistep-originals-archive-v1", "source_head": "ac093cec1c45a3b3ce76feaf8c983d0df86c6d1e",
        "archive_bytes": len(raw), "archive_sha256": sha(raw), "original_files": len(manifest),
        "original_bytes": sum(item["bytes"] for item in manifest), "manifest_sha256": sha(encoded),
        "parts": parts, "all_members_read_back": True, "ordered_parts_byte_equal": True,
        "dynamic_actions": 0, "optimizer_steps": 0}


if __name__ == "__main__":
    import sys
    os.sched_setaffinity(0, {8})
    wall, cpu = time.perf_counter(), time.process_time()
    result = build(*sys.argv[1:])
    result["body_cost"] = {"wall_seconds": time.perf_counter()-wall, "cpu_seconds": time.process_time()-cpu,
        "whole_process_peak_RSS_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "scope": "archive body excludes imports; RSS is whole process"}
    (Path(sys.argv[2]) / "ARCHIVE.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "parts"}, sort_keys=True))
