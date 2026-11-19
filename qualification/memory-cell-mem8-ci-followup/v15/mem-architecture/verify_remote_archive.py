"""Verify the complete immutable remote evidence carrier; never run tests/models."""
from pathlib import Path, PurePosixPath
import base64
import hashlib
import io
import json
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
REMOTE = ROOT / "remote-readback"
OUT = ROOT / "root-extracted"


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def checked(data, row):
    assert identity(data) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}


def safe(name):
    p = PurePosixPath(name)
    assert name and not p.is_absolute() and ".." not in p.parts and "." not in p.parts
    return p


publication = json.loads((REMOTE / "PUBLICATION.json").read_bytes())
assert identity((REMOTE / "PUBLICATION.json").read_bytes())["git_blob"] == "7bf3e6db9d54c7e279c3d993173098e1d7feee54"
assert publication["source_head"] == "9bd2f589debdba4a93baa363817c3669cb103721"
assert publication["source_tree"] == "c77785ecb368c44ea699769001a47402c9f50591"
archive = bytearray()
for part in publication["parts"]:
    data = base64.b64decode((REMOTE / (part["name"] + ".b64")).read_bytes())
    checked(data, part)
    assert len(archive) == part["offset"]
    archive.extend(data)
checked(archive, publication["archive"])
for row in publication["text_objects"]:
    checked((REMOTE / Path(row["path"]).name).read_bytes(), row)
manifest_bytes = (REMOTE / "MEMBER_MANIFEST.json").read_bytes()
manifest = json.loads(manifest_bytes)
expected = {row["path"]: row for row in manifest["files"]}
assert len(expected) == len(manifest["files"]) == 40
seen = set()
OUT.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as bundle:
    members = bundle.getmembers()
    assert len(members) == publication["regular_members"] == 41
    for member in members:
        name = safe(member.name)
        assert member.isfile() and member.name not in seen
        seen.add(member.name)
        data = bundle.extractfile(member).read()
        if member.name == "MEMBER_MANIFEST.json":
            assert data == manifest_bytes
        else:
            checked(data, expected[member.name])
        dest = OUT / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
assert seen == set(expected) | {"MEMBER_MANIFEST.json"}
zip_counts = []
for row in publication["original_artifacts"]:
    root = OUT / "artifacts" / str(row["id"])
    metadata = json.loads((root / "GITHUB_ARTIFACT_METADATA.json").read_bytes())
    source = root / (row["name"] + ".zip")
    data = source.read_bytes()
    checked(data, row)
    assert metadata["id"] == row["id"] and metadata["size_in_bytes"] == len(data)
    assert metadata["digest"] == "sha256:" + row["sha256"]
    zmanifest = json.loads((root / "ZIP_READBACK.json").read_bytes())
    zexpected = {x["name"]: x for x in zmanifest["regular_members"]}
    assert len(zexpected) == len(zmanifest["regular_members"]) == row["regular_members"]
    zseen = set()
    with zipfile.ZipFile(source) as bundle:
        assert bundle.testzip() is None
        for member in bundle.infolist():
            name = safe(member.filename)
            assert not member.is_dir() and member.filename not in zseen
            assert (member.external_attr >> 16) & 0o170000 != 0o120000
            zseen.add(member.filename)
            data = bundle.read(member)
            checked(data, zexpected[member.filename])
            dest = root / "files" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    assert zseen == set(zexpected)
    zip_counts.append({"artifact_id": row["id"], "regular_members": len(zseen), "all_crc_and_full_hashes_checked": True})
assert sum(x["regular_members"] for x in zip_counts) == publication["original_zip_regular_members"] == 230
record = {
    "schema": "hepta.mem8.v15.mem-architecture-root-remote-byte-audit.v1",
    "status": "PASS_COMPLETE_REMOTE_BYTES_AND_ORIGINAL_ZIPS",
    "source_head": publication["source_head"],
    "source_tree": publication["source_tree"],
    "immutable_carrier_commit": "ee112a2a3970b0cdd93a6b30911b56bc4d164a80",
    "archive": identity(archive),
    "full_remote_parts": 5,
    "outer_regular_members": 41,
    "original_artifacts": zip_counts,
    "original_zip_regular_members": 230,
    "count_audits_replayed": False,
    "counts_are_not_established_by_byte_verification_alone": True,
    "native_tests_or_model_requests_by_this_verifier": 0,
}
(ROOT / "ROOT_BYTE_AUDIT.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
