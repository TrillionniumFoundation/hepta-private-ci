"""Independently reopen published input evidence before the next checkpoint."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "metrics_integration/post824-publication/qualification/cell-e6-metrics-integration-20261119"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_and_copy(source, manifest_name, expected_archive, target_name):
    source = ROOT / source
    manifest = json.loads((source / manifest_name).read_bytes())
    parts = []
    for row in manifest["parts"]:
        path = source / row["path"]
        assert path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
        parts.append(raw)
    packed = b"".join(parts)
    assert sha(packed) == expected_archive == manifest["archive_sha256"]
    assert len(packed) == manifest["archive_bytes"]
    rows = manifest["members"]
    with tarfile.open(fileobj=io.BytesIO(packed), mode="r:*") as archive:
        members = archive.getmembers()
        assert len(members) == len(rows) == manifest["member_count"]
        assert len({m.name for m in members}) == len(members)
        expected = {row["path"]: row for row in rows}
        assert set(expected) == {m.name for m in members}
        for member in members:
            assert member.isfile()
            assert not member.name.startswith("/") and ".." not in Path(member.name).parts
            raw = archive.extractfile(member).read()
            row = expected[member.name]
            assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
    target = OUT / target_name
    target.mkdir(exist_ok=False)
    for path in source.iterdir():
        assert path.is_file() and not path.is_symlink()
        shutil.copyfile(path, target / path.name)
        assert sha((target / path.name).read_bytes()) == sha(path.read_bytes())
    readback = {
        "source_directory": str(source.relative_to(ROOT)),
        "archive_sha256": expected_archive,
        "archive_bytes": len(packed),
        "member_count": len(rows),
        "all_parts_and_members_independently_verified_by_root": True,
        "new_model_native_training_calls": 0,
        "new_host_jobs": 0,
        "copied_original_bytes_unchanged": True,
    }
    (target / "ROOT_ARCHIVE_READBACK.json").write_text(json.dumps(readback, indent=2) + "\n")
    return readback


if __name__ == "__main__":
    results = [
        verify_and_copy(
            "metrics_gate_work/macintel-lease-fixture-review-1/publication",
            "ARCHIVE.json",
            "4005154335c1861c570a0d27604bc8c5f4c1309dba61f2c7c02b1b88689bd8ee",
            "macintel-lease-fixture-review",
        ),
        verify_and_copy(
            "e5_bounded_retrieval_v2/publication/qualification/cell-e5-bounded-retrieval-v2-20261120",
            "EVIDENCE_MANIFEST.json",
            "c29e3372f6765f3c671019150f347eae3a511933ced1a68b161386ab96ff6923",
            "e5-v2-complete-readback",
        ),
    ]
    print(json.dumps(results, indent=2))
