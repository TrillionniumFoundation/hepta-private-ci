"""Read-only verification of every published R10 file and raw archive member."""

import hashlib
import json
from pathlib import Path
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[2]


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    manifest = json.loads((ROOT / "DELIVERY_MANIFEST.json").read_text())
    for item in manifest["files"]:
        path = (REPOSITORY / item["path"]).resolve()
        if not path.is_relative_to(REPOSITORY):
            raise ValueError("manifest path escapes repository")
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if len(data) != item["bytes"] or sha256(data) != item["sha256"] or blob != item["git_blob_sha1"]:
            raise ValueError((item["path"], "published file identity mismatch"))
    bundles = json.loads((ROOT / "BUNDLES.json").read_text())["bundles"]
    members = 0
    for bundle in bundles:
        expected = {row["path"]: row for row in bundle["files"]}
        raw = (ROOT / bundle["path"]).read_bytes()
        if len(raw) != bundle["bytes"] or sha256(raw) != bundle["sha256"]:
            raise ValueError("bundle identity mismatch")
        with tarfile.open(ROOT / bundle["path"]) as archive:
            entries = [m for m in archive.getmembers() if m.isfile()]
            if len(entries) != len(expected) or {m.name for m in entries} != set(expected):
                raise ValueError("bundle inventory mismatch")
            for member in entries:
                data = archive.extractfile(member).read()
                record = expected[member.name]
                if len(data) != record["bytes"] or sha256(data) != record["sha256"]:
                    raise ValueError((member.name, "bundle member mismatch"))
                members += 1
    ci = json.loads((ROOT / "integration/CI_ARTIFACT.json").read_text())
    raw = (ROOT / ci["path"]).read_bytes()
    if sha256(raw) != ci["sha256"] or len(raw) != ci["bytes"]:
        raise ValueError("CI artifact identity mismatch")
    with zipfile.ZipFile(ROOT / ci["path"]) as archive:
        if len(archive.namelist()) != ci["zip_members"]:
            raise ValueError("CI archive inventory size mismatch")
        for name, record in ci["selected_members"].items():
            data = archive.read(name)
            if len(data) != record["bytes"] or sha256(data) != record["sha256"]:
                raise ValueError((name, "CI member mismatch"))
    print(json.dumps({"published_files_verified": len(manifest["files"]),
                      "raw_bundles_verified": len(bundles), "raw_members_verified": members,
                      "qualified_ci_zip_members": ci["zip_members"],
                      "ci_selected_members_verified": len(ci["selected_members"]),
                      "all_five_scientific_claims_passed": False}))


if __name__ == "__main__":
    verify()
