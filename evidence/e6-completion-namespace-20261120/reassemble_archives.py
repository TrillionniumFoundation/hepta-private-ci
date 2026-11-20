"""Reassemble both complete archives from exact retained publication parts.

This checks every part and full archive and does not extract tar members.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main(args):
    args.output.mkdir(exist_ok=False)
    results = []
    for kind in ("host", "cloud"):
        directory = args.package / kind
        plan = json.loads((directory / "archive-parts.json").read_bytes())
        chunks = []
        names = set()
        for row in plan["parts"]:
            assert PurePosixPath(row["name"]).name == row["name"] and row["name"] not in names
            names.add(row["name"])
            raw = (directory / row["name"]).read_bytes()
            assert len(raw) == row["bytes"] <= 480000 and sha(raw) == row["sha256"]
            chunks.append(raw)
        raw = b"".join(chunks)
        assert len(raw) == plan["archive_bytes"] and sha(raw) == plan["archive_sha256"]
        name = plan["archive_name"]
        assert PurePosixPath(name).name == name
        (args.output / name).write_bytes(raw)
        results.append({"kind": kind, "archive_name": name, "parts": len(chunks), "bytes": len(raw), "sha256": sha(raw)})
    (args.output / "RESULT.json").write_text(json.dumps({"status": "PASS", "archives": results, "members_extracted": 0, "host_calls": 0, "native_or_model_runs": 0}, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "archives": results}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    main(parser.parse_args())
