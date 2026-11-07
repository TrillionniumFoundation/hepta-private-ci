#!/usr/bin/env python3
"""Verify or restore an unchanged historical failure from compressed storage."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


EXPECTED = {
    "strict-clippy.stderr": {
        "bytes": 45345,
        "sha256": "f88c27cc094d499312489496917d3af4a3fedbad80f3b47bbd8e41c595ef8b10",
    },
    "strict-clippy.stdout": {
        "bytes": 0,
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    },
    "STATUS.json": {
        "bytes": 2271,
        "sha256": "e0b4b56f993df210ed236163caede11ab33e3c6586381d6ce0807be17fb80bcf",
    },
}


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-dir", type=Path, help="Create a new directory with all three original files")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    manifest = json.loads((source / "ARCHIVE.json").read_text())
    archive = manifest["archive"]
    require(archive["file"] == "strict-clippy.stderr.gz", "Unexpected archive path")
    compressed = (source / archive["file"]).read_bytes()
    require(identity(compressed) == {key: archive[key] for key in ("bytes", "sha256")},
            "Compressed bytes differ from the archive manifest")
    with gzip.open(source / archive["file"], "rb") as stream:
        raw = stream.read(EXPECTED["strict-clippy.stderr"]["bytes"] + 1)
        require(not stream.read(1), "Decompressed content exceeds the original length")
    original = {"strict-clippy.stderr": raw}
    for name in ("STATUS.json", "strict-clippy.stdout"):
        original[name] = (source / name).read_bytes()
        require(manifest["unchanged"][name] == EXPECTED[name], "Changed manifest identity: " + name)
    for name, data in original.items():
        require(identity(data) == EXPECTED[name], "Original identity differs: " + name)
    require({key: manifest["original"][key] for key in ("bytes", "sha256")}
            == EXPECTED["strict-clippy.stderr"], "Changed original manifest identity")
    status = json.loads(original["STATUS.json"])
    stage, = status["stages"]
    require(stage["name"] == "strict-clippy" and stage["exit_code"] == 101
            and stage["state"] == "failed", "Historical stage failure changed")
    require(stage["stderr"] == EXPECTED["strict-clippy.stderr"]
            and stage["stdout"] == EXPECTED["strict-clippy.stdout"], "Historical stream identity changed")
    require(status["exit_code"] == 101 and status["qualification_complete"] is False,
            "Historical failure outcome changed")
    require(manifest["historical_exit_code"] == 101
            and manifest["qualification_complete"] is False
            and manifest["qualification_decision"] == "HOLD", "Archive outcome changed")
    if args.restore_dir is not None:
        args.restore_dir.mkdir(exist_ok=False)
        for name, data in original.items():
            with (args.restore_dir / name).open("xb") as stream:
                stream.write(data)
    print(json.dumps({
        "schema": "hepta.cell-unified.historical-stderr-readback.v1",
        "archive_integrity": "VERIFIED",
        "original_files": EXPECTED,
        "restored": args.restore_dir is not None,
        "historical_exit_code": 101,
        "qualification_complete": False,
        "qualification_decision": "HOLD",
        "native_gate_executed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
