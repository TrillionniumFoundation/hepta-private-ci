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
SOURCE = OUT.parent / "supervisor-unix-connect-bound-independent-20261106"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/reviews/supervisor-unix-connect-bound-independent-20261106/"


def ident(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


freeze = json.loads((SOURCE / "DELIVERY-MANIFEST.json").read_bytes())
assert ident((SOURCE / "DELIVERY-MANIFEST.json").read_bytes())["git_blob"] == "facf8440f968cb88061c9793de793a267e8d7529"
members = []
for row in freeze["files"]:
    data = (SOURCE / row["path"]).read_bytes()
    assert all(row[key] == value for key, value in ident(data).items()), row["path"]
    members.append({"path": row["path"], **ident(data)})
members.append({"path": "DELIVERY-MANIFEST.json", **ident((SOURCE / "DELIVERY-MANIFEST.json").read_bytes())})
members.sort(key=lambda row: row["path"])
assert len(freeze["files"]) == freeze["file_count"] == 16
assert sum(row["bytes"] for row in freeze["files"]) == freeze["total_member_bytes"] == 132058
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
    "schema": "hepta-supervisor-unix-connect-independent-packet-v1",
    "archive": ident(raw),
    "encoding": "base64 concatenated in numeric part order",
    "part_limit_bytes": 400000,
    "parts": parts,
    "members": members,
    "candidate_tree": "44e8f7176037a5455476c068ad6ad8d692868769",
    "limits": [
        "Exact independent reviewer files only; author77 and old terminal package are separate required inputs.",
        "Python preservation/Merkle/patch replay is not Rust, fmt, socket or CI qualification.",
        "Original two 60-second timeouts remain CAUSAL_UNKNOWN; no ledger transition.",
        "Full independent verifier replay requires author registry b336a8470de7111b0bb037a3c1d801bcadaba0d2 and old native registry 23e67ce20a439e2968eb63ae4e9a74a214ccd081.",
    ],
}
write_json(OUT / "archive.json", manifest)
copies = {
    "README.zh-CN.md": "README.zh-CN.md",
    "DELIVERY-MANIFEST.json": "DELIVERY-MANIFEST.json",
    "REVIEW.json": "REVIEW.json",
    "REVIEW.actual.receipt.json": "REVIEW.actual.receipt.json",
    "independent-01.stdout.json": "INDEPENDENT_VERIFICATION.json",
}
for source, target in copies.items():
    shutil.copyfile(SOURCE / source, OUT / target)
names = ["archive.json", *copies.values(), "build_packet.py", "restore_packet.py", *[row["path"] for row in parts]]
objects = [{"local_path": str(OUT / name), "repo_path": PREFIX + name, "mode": "100644", "type": "blob", **ident((OUT / name).read_bytes())} for name in names]
write_json(OUT / "registration-plan.json", {"schema": "hepta-supervisor-unix-connect-registration-plan-v1", "prefix": PREFIX, "objects": objects})
print(json.dumps({"members": len(members), "original_bytes": sum(row["bytes"] for row in members), "archive": ident(raw), "parts": len(parts), "payload_objects": len(objects)}, indent=2))
