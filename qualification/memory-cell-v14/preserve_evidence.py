"""Pack complete immutable runner evidence into bounded, hashed Git blobs."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    index = {"schema": "hepta.memory.v14.evidence-pack.v1", "source_commit": args.commit,
             "github_run": args.run, "archives": []}
    for directory in sorted(args.input.iterdir()):
        if not directory.is_dir():
            continue
        raw = io.BytesIO()
        inventory = {}
        with tarfile.open(fileobj=raw, mode="w") as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_symlink():
                    raise ValueError("evidence symlinks are forbidden")
                if not path.is_file():
                    continue
                data, name = path.read_bytes(), path.relative_to(directory).as_posix()
                inventory[name] = {"bytes": len(data), "sha256": sha(data)}
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o644
                archive.addfile(info, io.BytesIO(data))
                if path.suffix == ".json" and path.name in {
                    "SUMMARY.json", "DEPENDENCY_AUDIT.json", "SELECTION.json", "receipt.json",
                    "language_run.json", "language_failure.json", "process.json", "QUALITY.json"}:
                    dest = args.output / "readable" / directory.name / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
        payload = gzip.compress(raw.getvalue(), compresslevel=6, mtime=0)
        chunks = []
        for number, start in enumerate(range(0, len(payload), 512 * 1024)):
            block = payload[start:start + 512 * 1024]
            name = f"{directory.name}.tar.gz.part{number:04d}"
            (args.output / name).write_bytes(block)
            chunks.append({"name": name, "bytes": len(block), "sha256": sha(block)})
        index["archives"].append({"name": directory.name, "format": "concatenated gzip tar",
                                  "bytes": len(payload), "sha256": sha(payload),
                                  "parts": chunks, "files": inventory})
    if not index["archives"]:
        raise ValueError("no actual runner artifacts were available")
    (args.output / "INDEX.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
