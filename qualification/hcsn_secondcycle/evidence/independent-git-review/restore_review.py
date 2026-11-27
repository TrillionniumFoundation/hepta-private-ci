"""Verify and restore archived review bytes; never execute archived contents.

Only the Python standard library is used. A successful verification establishes
transfer integrity against this manifest, not independent publisher authority.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path,
                        default=Path(__file__).with_name("MANIFEST.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only and args.output is None:
        parser.error("--output is required for restoration")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if digest(Path(__file__).read_bytes()) != manifest["restore_script_sha256"]:
        raise ValueError("restore script digest differs from manifest")
    pieces = []
    for index, record in enumerate(manifest["payloads"]):
        if record["index"] != index or Path(record["name"]).name != record["name"]:
            raise ValueError("invalid part order or path")
        data = (args.manifest.parent / record["name"]).read_bytes()
        if len(data) != record["bytes"] or digest(data) != record["sha256"]:
            raise ValueError("archive payload digest/size mismatch: " + record["name"])
        pieces.append(data)
    archive = b"".join(pieces)
    if len(archive) != manifest["archive_bytes"] or digest(archive) != manifest["archive_sha256"]:
        raise ValueError("reassembled archive digest/size mismatch")
    expected = {record["name"]: record for record in manifest["members"]}
    if len(expected) != len(manifest["members"]):
        raise ValueError("duplicate manifest member")
    restored = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            name = member.name
            if (not member.isfile() or Path(name).name != name or name in (".", "..")
                    or name not in expected or name in restored):
                raise ValueError("unexpected/nonregular/duplicate archive member: " + name)
            record = expected[name]
            if member.size != record["bytes"]:
                raise ValueError("archive member size mismatch: " + name)
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError("missing regular member bytes")
            data = stream.read()
            if len(data) != record["bytes"] or digest(data) != record["sha256"]:
                raise ValueError("archive member digest mismatch: " + name)
            restored[name] = data
    if set(restored) != set(expected):
        raise ValueError("incomplete archive member set")
    if not args.verify_only:
        args.output.mkdir(parents=True, exist_ok=False)
        for name, data in restored.items():
            (args.output / name).write_bytes(data)
    print(json.dumps({"verified_payloads": len(pieces), "verified_members": len(restored),
                      "archive_sha256": manifest["archive_sha256"],
                      "restored": not args.verify_only,
                      "archived_code_executed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
