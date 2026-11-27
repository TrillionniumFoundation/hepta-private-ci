#!/usr/bin/env python3
"""Fully verify the archived CI ZIP, embedded original records, and source proof."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import zipfile

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).parent.resolve()

def info(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def safe(name):
    path = PurePosixPath(name)
    assert path.parts and not path.is_absolute() and ".." not in path.parts
    return path

manifest = json.loads((root / "MANIFEST.json").read_bytes())
for member in manifest["members"]:
    data = (root / safe(member["path"])).read_bytes()
    assert info(data) == {key: member[key] for key in ("bytes", "sha256", "git_blob")}
original = (root / "original/mem8-source-gates-v5-43015979473-1.zip").read_bytes()
assert info(original)["bytes"] == 6299090
assert info(original)["sha256"] == "6ecc9f1ab22fcaccbf52f0190c9af0e8edef759a0537dbb8f751b227d09b7c80"
zip_index = json.loads((root / "original/ZIP_MEMBERS.json").read_bytes())
rows = zip_index if isinstance(zip_index, list) else zip_index["members"]
expected_zip = {row["path"]: row for row in rows}
with zipfile.ZipFile(io.BytesIO(original)) as bundle:
    entries = bundle.infolist()
    assert len(entries) == 337 and len({entry.filename for entry in entries}) == 337
    for entry in entries:
        safe(entry.filename)
        assert not entry.is_dir() and not ((entry.external_attr >> 16) & 0o170000) == 0o120000
        data = bundle.read(entry)
        row = expected_zip[entry.filename]
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
    original_tar = bundle.read("mem8-source-gates-v5/mem8-source-gates-v5-records.tar.xz")
assert info(original_tar) == {
    "bytes": 1783500,
    "sha256": "6718333beb6ea7b6faefc2bd026413e8ab1413f24bf4f377a773fc0264dd288a",
    "git_blob": "eb285beb4588ab1aee652a785881c5d37d932292",
}
with tempfile.TemporaryDirectory(prefix="source-ci-original-offline-") as tmp:
    extracted = Path(tmp)
    with tarfile.open(fileobj=io.BytesIO(original_tar), mode="r:xz") as bundle:
        members = bundle.getmembers()
        assert len(members) == 335 and len({m.name for m in members}) == 335
        for member in members:
            name = safe(member.name)
            assert member.isfile()
            data = bundle.extractfile(member).read()
            dest = extracted / "records" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    process = subprocess.run(
        [sys.executable, "-B", str(root / "verify_source_records.py"), str(extracted)],
        capture_output=True, text=True, timeout=120,
    )
    assert process.returncode == 0, process.stderr
    for name in ("OFFLINE_VERIFICATION.json", "FORMAT_ONLY.patch"):
        assert (extracted / name).read_bytes() == (root / "derived" / name).read_bytes()
result = {
    "status": "PASS_ORIGINAL_CI_ZIP_TAR_AND_SOURCE_PROOF",
    "original_run": 43015979473, "original_job": 130507034042, "attempt": 1,
    "zip_members": 337, "tar_members": 335, "source_paths": 103,
    "formatter_changes": 21, "caller_rust_files": 6200, "old_case_name_hits": 0,
    "original_source_head_unchanged": "c842e995b047eb2ee7d81c073f14fb2fcaa6bff2",
    "formatted_tree": "c77785ecb368c44ea699769001a47402c9f50591",
    "native_tests_or_model_calls_started_by_this_verifier": 0,
}
print(json.dumps(result, indent=2))
