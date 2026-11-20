"""Reopen every frozen d035/8996 evidence member; do not execute a native task."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "e6_owner_work/ack_order_evidence"
TARGET = ROOT / "metrics_integration/post824-publication/qualification/cell-e6-metrics-integration-20261119/e6-8996-noupdate8-readback"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parts = json.loads((SOURCE / "archive-parts.json").read_bytes())
    manifest_raw = (SOURCE / "expanded/MANIFEST.json").read_bytes()
    assert sha(manifest_raw) == "893562d0cc28b25d782b5c014afacae9ab914c2626f9c6aaaa83d9a961f9666c"
    manifest = json.loads(manifest_raw)
    assert manifest["source"] == "8996e4c5b6a8662c51f47d9e164b8c839635c796"
    assert len(manifest["files"]) == 612 and manifest["raw_bytes"] == 200235726
    chunks = []
    for row in parts["parts"]:
        raw = (SOURCE / row["name"]).read_bytes()
        assert len(raw) == row["bytes"] <= 480000 and sha(raw) == row["sha256"]
        chunks.append(raw)
    packed = b"".join(chunks)
    assert len(packed) == parts["archive_bytes"] == 3400892
    assert sha(packed) == parts["archive_sha256"] == "b86604090557849cadea5992cc2f58a3fd3c7d5320e27cd79bbf31387c3d01f3"
    rows = {row["path"]: row for row in manifest["files"]}
    assert len(rows) == 612
    observed = set()
    extra = []
    with tarfile.open(fileobj=io.BytesIO(packed), mode="r|xz") as archive:
        for member in archive:
            assert member.isfile() and member.name not in observed
            assert not member.name.startswith("/") and ".." not in Path(member.name).parts
            observed.add(member.name)
            raw = archive.extractfile(member).read()
            if member.name in rows:
                row = rows[member.name]
                assert len(raw) == row["bytes"] and sha(raw) == row["sha256"]
            else:
                local = SOURCE / "expanded" / member.name
                assert local.is_file() and not local.is_symlink()
                assert raw == local.read_bytes()
                extra.append({"path": member.name, "bytes": len(raw), "sha256": sha(raw)})
    assert set(rows) <= observed
    summary_raw = (SOURCE / "SUMMARY.json").read_bytes()
    assert sha(summary_raw) == "a316f970778a5257a17b93f7365ffa0b4c7e2c4e5088900db7fc2ad3aa4f8e3c"
    assert summary_raw == (ROOT / "e6_owner_work/ack_marker_noupdate8_failure/ACTUAL_READOUT.json").read_bytes()
    TARGET.mkdir(exist_ok=False)
    copies = [(row["name"], SOURCE / row["name"]) for row in parts["parts"]]
    copies += [(name, SOURCE / name) for name in ["archive-parts.json", "RESULT.json", "CORE_API.json", "SUMMARY.json", "LOCAL_VERIFICATION.json"]]
    copies += [("MANIFEST.json", SOURCE / "expanded/MANIFEST.json")]
    for name, path in copies:
        shutil.copyfile(path, TARGET / name)
        assert sha(path.read_bytes()) == sha((TARGET / name).read_bytes())
    result = {
        "source": manifest["source"],
        "archive_sha256": sha(packed),
        "manifest_sha256": sha(manifest_raw),
        "summary_sha256": sha(summary_raw),
        "raw_originals_verified": 612,
        "raw_original_bytes_verified": manifest["raw_bytes"],
        "additional_archive_metadata_exactly_reopened": extra,
        "root_independent_all_parts_and_members_verified": True,
        "ordinary_NoUpdate_passed": False,
        "request_65_rejected_before_socket_exchange": True,
        "new_model_native_training_host_jobs": 0,
    }
    (TARGET / "ROOT_ARCHIVE_READBACK.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
