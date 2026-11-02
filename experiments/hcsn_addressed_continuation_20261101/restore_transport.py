"""Reassemble byte-identical ZIP evidence, checking every public transport part."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "EVIDENCE_TRANSPORT.json").read_text())
    if args.output.exists():
        raise FileExistsError(args.output)
    digest = hashlib.sha256()
    total = 0
    chunks = []
    for part in manifest["parts"]:
        relative = Path(part["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "transport":
            raise ValueError("Unsafe part path")
        data = (root / relative).read_bytes()
        if len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise ValueError("Transport part identity mismatch")
        digest.update(data)
        total += len(data)
        chunks.append(data)
    if total != manifest["bytes"] or digest.hexdigest() != manifest["sha256"]:
        raise ValueError("Combined archive identity mismatch")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as target:
        for data in chunks:
            target.write(data)
    print(json.dumps({"verified": True, "bytes": total, "sha256": digest.hexdigest()}))


if __name__ == "__main__":
    main()
