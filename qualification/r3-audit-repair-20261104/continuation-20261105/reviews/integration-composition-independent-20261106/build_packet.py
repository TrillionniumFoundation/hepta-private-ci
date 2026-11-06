#!/usr/bin/env python3
"""Preserve the original frozen review and separate publication addendum."""
import base64
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTHOR = ROOT.parent / "integration-composition-independent-review"


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


freeze_bytes = (AUTHOR / "freeze-manifest.json").read_bytes()
assert identity(freeze_bytes)["git_blob"] == "f7ea095f3d8d597993e7732168f77f1481429e5c"
freeze = json.loads(freeze_bytes)
assert freeze["members"] == len(freeze["files"]) == 14
selected = []
for row in freeze["files"]:
    data = (AUTHOR / row["path"]).read_bytes()
    assert identity(data) == {key: row[key] for key in ("bytes", "git_blob", "sha256")}
    selected.append(("frozen-review/" + row["path"], data))
selected.append(("frozen-review/freeze-manifest.json", freeze_bytes))
for path in sorted((ROOT / "post-publication").iterdir()):
    assert path.is_file() and path.suffix == ".json"
    selected.append(("post-publication/" + path.name, path.read_bytes()))
assert len(selected) == 22
archive = ROOT / "review-packet.original.zip"
assert not archive.exists()
members = []
with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for name, data in sorted(selected):
        members.append({"path": name, **identity(data)})
        item = zipfile.ZipInfo(name, (2026, 11, 6, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED
        item.external_attr = 0o100644 << 16
        z.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
data = archive.read_bytes()
parts = []
for offset in range(0, len(data), 300000):
    chunk = base64.b64encode(data[offset:offset + 300000])
    name = f"review-packet.zip.part-{len(parts) + 1:04d}.b64"
    (ROOT / name).write_bytes(chunk)
    parts.append({"path": name, **identity(chunk)})
manifest = {"schema": "integration-composition-independent-portable-packet-v1",
            "archive": {"path": archive.name, **identity(data)}, "parts": parts, "members": members,
            "prior_review": identity((AUTHOR / "REVIEW.zh-CN.md").read_bytes()), "prior_freeze": identity(freeze_bytes),
            "original_review_members": 14, "original_review_unchanged": True,
            "separate_addendum": identity((ROOT / "post-publication/ADDENDUM.json").read_bytes()),
            "scope": "Frozen composition review and separate post-publication identity verification; no native/CI qualification expansion"}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
shutil.copyfile(AUTHOR / "REVIEW.zh-CN.md", ROOT / "REVIEW.zh-CN.md")
shutil.copyfile(AUTHOR / "freeze-manifest.json", ROOT / "input-freeze.original.json")
shutil.copyfile(ROOT / "post-publication/ADDENDUM.json", ROOT / "post-publication-ADDENDUM.json")
print(json.dumps({"archive": manifest["archive"], "parts": len(parts), "members": len(members),
                  "original_14_and_freeze_unchanged": True, "publication_addendum_separate": True}, indent=2))
