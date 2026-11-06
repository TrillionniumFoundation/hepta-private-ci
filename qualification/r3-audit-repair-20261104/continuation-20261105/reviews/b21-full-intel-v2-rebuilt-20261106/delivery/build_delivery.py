#!/usr/bin/env python3
"""Package frozen evidence losslessly; repeated file bodies are stored once."""
import base64
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
INDEPENDENT = Path("/tmp/hepta-runtime-recovery-20261106/format-review-recovery/b21-final-independent")
ADDENDUM = Path("/tmp/hepta-runtime-recovery-20261106/format-review-recovery/b21-final-author-proof-addendum")


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


freeze = json.loads((ROOT / "freeze-manifest.json").read_text())
files, directories = {}, set()
for item in freeze["members"]:
    data = (ROOT / item["path"]).read_bytes()
    assert identity(data) == {k: item[k] for k in ("bytes", "sha256", "git_blob")}
    files["core/" + item["path"]] = data
files["core/freeze-manifest.json"] = (ROOT / "freeze-manifest.json").read_bytes()
for prefix, folder in (("independent-review", INDEPENDENT), ("author-proof-addendum", ADDENDUM)):
    directories.add(prefix)
    for path in sorted(folder.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        assert not path.is_symlink(), path
        name = prefix + "/" + path.relative_to(folder).as_posix()
        if path.is_dir():
            directories.add(name)
        elif path.is_file():
            files[name] = path.read_bytes()
        else:
            raise AssertionError("nonregular package input")
for name in files:
    for parent in Path(name).parents:
        if str(parent) != ".":
            directories.add(parent.as_posix())
members, objects = [], {}
for name, data in sorted(files.items()):
    ident = identity(data)
    members.append({"path": name, **ident})
    if ident["sha256"] in objects:
        assert objects[ident["sha256"]] == data
    objects[ident["sha256"]] = data
archive = OUT / "payload-objects.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
    for sha, data in sorted(objects.items()):
        info = zipfile.ZipInfo("objects/" + sha, (1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        stream.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
raw = archive.read_bytes()
encoded = base64.b64encode(raw).decode("ascii")
parts = []
for index, start in enumerate(range(0, len(encoded), 400000), 1):
    name = "payload-objects.zip.b64.part-%03d" % index
    body = encoded[start:start + 400000].encode("ascii")
    (OUT / name).write_bytes(body)
    parts.append({"path": name, **identity(body)})
manifest = {
    "schema": "b21-rebuilt-v2-lossless-delivery-v1",
    "representation": "Concatenate ordered base64 parts, decode ZIP; each SHA256 object contains original file bytes. Restore exact path mapping and explicit directories.",
    "source_workflow_actual": "fb5881fa310d3548cd604d2827fe9c29aa1b3873",
    "collector_actual": "00dc37697adde6154a347963ab19e8a6edebac07",
    "independent_review_actual": "ecab7af9dc20c8989b9c8c5a4a099f2c91cbf3d0",
    "author_proof_addendum_actual": "2daeaa86a21ddd58d92f622f6d4b255c37ba9d04",
    "core_frozen_manifest": identity((ROOT / "freeze-manifest.json").read_bytes()),
    "members": members, "member_count": len(members),
    "directories": sorted(directories), "unique_file_bodies": len(objects),
    "original_bytes_total": sum(len(data) for data in files.values()),
    "archive": {"path": archive.name, **identity(raw), "parts": parts},
    "qualification_scope": "Source/static/synthetic evidence only; no ref mutation or native test",
    "historical_snapshots_retained": True, "B21": "OPEN",
}
(OUT / "delivery-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"members":len(members),"unique_bodies":len(objects),"directories":len(directories),
                  "archive_bytes":len(raw),"parts":len(parts)}))
