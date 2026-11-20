"""Verify the final 824 workflow capture and copy the independent gate review."""

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


def main():
    source = ROOT / "metrics_gate_work/post824-final-ci-1/publication"
    manifest = json.loads((source / "ARCHIVE.json").read_bytes())
    chunks = []
    for row in manifest["parts"]:
        raw = (source / row["path"]).read_bytes()
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
        chunks.append(raw)
    packed = b"".join(chunks)
    assert len(packed) == manifest["bytes"] == 526052
    assert sha(packed) == manifest["sha256"] == "f3abb9657fb4bdd6bc0082c2ae5b313025fa31e05c4673f5a9fbdc7fb0af7e84"
    rows = {row["path"]: row for row in manifest["members"]}
    assert len(rows) == manifest["member_count"] == 41
    with tarfile.open(fileobj=io.BytesIO(packed), mode="r:xz") as archive:
        members = archive.getmembers()
        assert len(members) == len(rows)
        assert {m.name for m in members} == set(rows)
        for member in members:
            assert member.isfile()
            assert not member.name.startswith("/") and ".." not in Path(member.name).parts
            raw = archive.extractfile(member).read()
            row = rows[member.name]
            assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
    target = OUT / "ci-824-complete"
    target.mkdir(exist_ok=False)
    for path in source.iterdir():
        assert path.is_file() and not path.is_symlink()
        shutil.copyfile(path, target / path.name)
    result = {
        "archive_sha256": sha(packed),
        "archive_bytes": len(packed),
        "member_count": len(rows),
        "all_parts_and_members_independently_reopened_by_root": True,
        "new_native_model_training_host_jobs": 0,
    }
    (target / "ROOT_ARCHIVE_READBACK.json").write_text(json.dumps(result, indent=2) + "\n")
    source = ROOT / "metrics_gate_work/post824-peer-review-1/publication"
    peer_raw = (source / "PEER_REVIEW.json").read_bytes()
    assert sha(peer_raw) == "0f8581af9704f184a82e303cec97481246b9cf563576968b535d70277e302c9d"
    peer = json.loads(peer_raw)
    assert peer["status"] == "PASS" and peer["prior_verified_unique_objects"] == 240
    assert peer["extra_verified_objects"] == 2
    assert sha((ROOT / "metrics_gate_work/post824_blob_gate.py").read_bytes()) == peer["reviewed_controller_sha256"]
    assert sha((source / "READONLY_INPUT_VERIFICATION.json").read_bytes()) == peer["verification_sha256"]
    assert sha((source / "PEER_REVIEW.md").read_bytes()) == peer["review_md_sha256"]
    target = OUT / "post824-original-gate-peer-review"
    target.mkdir(exist_ok=False)
    for path in source.iterdir():
        assert path.is_file() and not path.is_symlink()
        shutil.copyfile(path, target / path.name)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
