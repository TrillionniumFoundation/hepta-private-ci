#!/usr/bin/env python3
"""Lossless package of a previously frozen candidate; never updates its files."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import zipfile

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / "supervisor-unix-connect-bound-candidate-20261106"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/reviews/supervisor-unix-connect-bound-20261106/"


def ident(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


freeze = json.loads((SOURCE / "FREEZE.json").read_bytes())
assert ident((SOURCE / "FREEZE.json").read_bytes())["git_blob"] == "79031a80b8b095fbffda0215aa67ddd7c6f0634f"
members = []
for row in freeze["members"]:
    data = (SOURCE / row["path"]).read_bytes()
    assert all(row[key] == value for key, value in ident(data).items()), row["path"]
    members.append({"path": row["path"], **ident(data)})
members.append({"path": "FREEZE.json", **ident((SOURCE / "FREEZE.json").read_bytes())})
members.sort(key=lambda row: row["path"])
actual_files = sorted(p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
assert actual_files == [row["path"] for row in members]
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for row in members:
        entry = zipfile.ZipInfo(row["path"], (2026, 11, 6, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.create_system = 3
        entry.external_attr = 0o100644 << 16
        archive.writestr(entry, (SOURCE / row["path"]).read_bytes())
raw = buffer.getvalue()
assert not (OUT / "packet.zip").exists()
(OUT / "packet.zip").write_bytes(raw)
encoded = base64.b64encode(raw)
parts = []
for number, start in enumerate(range(0, len(encoded), 400000), 1):
    name = f"packet.zip.b64.part{number:02d}"
    data = encoded[start:start + 400000]
    (OUT / name).write_bytes(data)
    parts.append({"path": name, **ident(data)})
manifest = {
    "schema": "hepta-supervisor-unix-connect-frozen-packet-v1",
    "archive": ident(raw),
    "encoding": "base64 concatenated in numeric part order",
    "part_limit_bytes": 400000,
    "parts": parts,
    "members": members,
    "candidate_tree": freeze["candidate_tree_actual"],
    "limits": [
        "Exact author freeze only; independent review is a separate later observation.",
        "Python preservation/Merkle/patch replay is not Rust, fmt, socket or CI qualification.",
        "Original two 60-second timeouts remain CAUSAL_UNKNOWN; no ledger transition.",
        "Historical assessment FREEZE refers to its separate original directory, not a complete second archive here.",
    ],
}
write_json(OUT / "archive.json", manifest)
copies = {
    "README.zh-CN.md": "README.zh-CN.md",
    "FREEZE.json": "FREEZE.json",
    "candidate-source-map.json": "candidate-source-map.json",
    "candidate-postimages.actual.json": "candidate-postimages.actual.json",
    "verification/static-02.stdout.json": "VERIFICATION.json",
}
for source, target in copies.items():
    shutil.copyfile(SOURCE / source, OUT / target)
names = ["archive.json", *copies.values(), "build_packet.py", "restore_packet.py", *[row["path"] for row in parts]]
objects = [{"local_path": str(OUT / name), "repo_path": PREFIX + name, "mode": "100644", "type": "blob", **ident((OUT / name).read_bytes())} for name in names]
write_json(OUT / "registration-plan.json", {"schema": "hepta-supervisor-unix-connect-registration-plan-v1", "prefix": PREFIX, "objects": objects})
print(json.dumps({"members": len(members), "original_bytes": sum(row["bytes"] for row in members), "archive": ident(raw), "parts": len(parts), "payload_objects": len(objects)}, indent=2))
