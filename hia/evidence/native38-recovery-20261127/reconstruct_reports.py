#!/usr/bin/env python3
"""Restore original report bytes from bounded UTF-8 parts into a new directory."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "large-reports-parts.json").read_bytes())
    if manifest["schema"] != "codex.hia.multipart-report-evidence.v1":
        raise SystemExit("unknown report evidence schema")
    args.output_directory.mkdir(parents=True, exist_ok=False)
    for report in manifest["reports"]:
        name = Path(report["logical_path"])
        if name.name != report["logical_path"]:
            raise SystemExit("noncanonical logical report path")
        digest = hashlib.sha256()
        git_digest = hashlib.sha1(b"blob " + str(report["bytes"]).encode() + b"\0")
        offset = 0
        with (args.output_directory / name).open("xb") as output:
            for part in report["parts"]:
                part_name = Path(part["path"])
                if part_name.name != part["path"] or part["offset"] != offset:
                    raise SystemExit("noncanonical part path or offset")
                data = (root / part_name).read_bytes()
                git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                if (len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]
                        or git_blob != part["git_blob"]):
                    raise SystemExit("part bytes differ: " + part["path"])
                output.write(data)
                digest.update(data)
                git_digest.update(data)
                offset += len(data)
        if offset != report["bytes"] or digest.hexdigest() != report["sha256"] or git_digest.hexdigest() != report["git_blob"]:
            raise SystemExit("complete report identity differs")
        print(json.dumps({"logical_path": str(name), "bytes": offset, "sha256": digest.hexdigest()}))


if __name__ == "__main__":
    main()
