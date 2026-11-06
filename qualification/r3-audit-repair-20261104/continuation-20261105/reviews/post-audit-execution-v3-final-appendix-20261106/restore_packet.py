#!/usr/bin/env python3
"""Restore exact archived bytes and run only the small JSON/hash publication verifier."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

def ident(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}

def check(data, expected):
    assert all(expected[k] == v for k, v in ident(data).items())

packet, output = [Path(value).resolve() for value in sys.argv[1:]]
assert not output.exists(), "Choose a fresh restore directory"
manifest = json.loads((packet / "archive.json").read_bytes())
parts = []
for row in manifest["parts"]:
    name = Path(row["path"])
    assert not name.is_absolute() and ".." not in name.parts
    body = (packet / name).read_bytes()
    check(body, row); parts.append(body)
raw = base64.b64decode(b"".join(parts), validate=True)
check(raw, manifest["archive"])
with zipfile.ZipFile(io.BytesIO(raw)) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert len(names) == len(set(names)) == len(manifest["members"])
    assert sorted(names) == sorted(row["path"] for row in manifest["members"])
    output.mkdir(parents=True)
    for row in manifest["members"]:
        name = Path(row["path"])
        assert not name.is_absolute() and ".." not in name.parts
        body = archive.read(row["path"]); check(body, row)
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
run = subprocess.run([sys.executable, "-B", str(output / "packet-tools/verify_appendix.py"), str(output)], capture_output=True)
assert run.returncode == 0 and not run.stderr, run.stderr.decode("utf-8", errors="replace")
proof = json.loads(run.stdout)
print(json.dumps({"schema": "hepta-fourth-audit-final-appendix-restore-v1", "members_restored": len(manifest["members"]), "archive": ident(raw), "verification": proof, "native_or_qualification_execution": False}, ensure_ascii=False, indent=2))
