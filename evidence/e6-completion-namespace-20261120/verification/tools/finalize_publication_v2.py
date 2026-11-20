"""Read back the complete new publication with an absolute, fixed local root."""

import hashlib
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    publication = HERE / "publication"
    package = publication / "evidence/e6-completion-namespace-20261120"
    manifest_path = publication / "PUBLICATION_FILES.json"
    old_raw = manifest_path.read_bytes()
    old = json.loads(old_raw)
    assert len(old["files"]) == 63
    initial = publication / "PUBLICATION_FILES.initial63.json"
    assert initial.read_bytes() == old_raw
    def record(path):
        raw = path.read_bytes()
        return {"path": str(path.relative_to(publication)), "local_path": str(path), "bytes": len(raw), "sha256": sha(raw), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(), "mode": "100644"}
    for row in old["files"]:
        assert record(Path(row["local_path"])) == row
    extra = [
        (HERE / "publication-reassembled-1/RESULT.json", "verification/PUBLICATION_ARCHIVES_REASSEMBLED.json"),
        (HERE / "PUBLICATION_FINALIZE_FAILURE_1.json", "verification/PUBLICATION_FINALIZE_FAILURE_1.json"),
        (Path(__file__).resolve(), "verification/tools/finalize_publication_v2.py"),
    ]
    origins = []
    for source, relative in extra:
        destination = package / relative
        assert not destination.exists()
        raw = source.read_bytes()
        destination.write_bytes(raw)
        assert destination.read_bytes() == raw
        origins.append({"path": relative, "source_path": str(source), "bytes": len(raw), "sha256": sha(raw), "kind": "exact_byte_copy"})
    before = [record(path) for path in sorted(package.rglob("*")) if path.is_file()]
    assert len(before) == 66
    for link in re.findall(r"\]\(([^)]+)\)", (package / "README.md").read_text()):
        if "://" not in link:
            assert (package / link).is_file(), link
    receipt = {"schema": "hepta.e6.publication-byte-readback.v1", "status": "PASS", "initial_publication_manifest_sha256": sha(old_raw), "initial_files": 63, "checked_files_before_this_receipt": 66, "files": before, "missing_relative_links": [], "whole_tar_files_committed": False, "remote_git_writes": 0, "host_processes_started": 0, "original_seven_tests_or_blob_gate_executed": False}
    receipt_path = package / "verification/PUBLICATION_BYTE_READBACK.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    origins.append({"path": "verification/PUBLICATION_BYTE_READBACK.json", "bytes": receipt_path.stat().st_size, "sha256": sha(receipt_path.read_bytes()), "kind": "actual_local_publication_readback_before_self_record"})
    additions = {"schema": "hepta.e6.publication-additions.v1", "prior_origin_manifest": "FILE_ORIGINS.json", "files": origins}
    (package / "PUBLICATION_ADDITIONS.json").write_text(json.dumps(additions, indent=2) + "\n")
    files = [record(path) for path in sorted(package.rglob("*")) if path.is_file()]
    assert len(files) == 68 and all(row["bytes"] < 512000 for row in files)
    old.update({"files": files, "total_bytes": sum(row["bytes"] for row in files), "max_file_bytes": max(row["bytes"] for row in files), "final_publication_readback_source": "verification/PUBLICATION_BYTE_READBACK.json"})
    manifest_path.write_text(json.dumps(old, indent=2) + "\n")
    final = {"status": "PUBLICATION_PREPARED_NOT_PUBLISHED", "manifest_path": str(manifest_path), "manifest_bytes": manifest_path.stat().st_size, "manifest_sha256": sha(manifest_path.read_bytes()), "files": len(files), "total_bytes": old["total_bytes"], "max_file_bytes": old["max_file_bytes"], "source": "9dfded9cecc74e39a19bccd14b9de9dc46c02c63", "host_archive_sha256": "9d6848aa4145952dbd7b889a76b1f41f67de659ab90c045006c8585c43670341", "cloud_archive_sha256": "119695fed1e1684dcb7a5b6d9b4350c120c923db863ed0301460d51dbc003127", "host_independent_result_sha256": sha((HERE / "verification-host-2/RESULT.json").read_bytes()), "cloud_independent_result_sha256": sha((HERE / "verification-cloud-1/RESULT.json").read_bytes()), "lossless_rpc_reconstruction_result_sha256": sha((HERE / "transport-reconstructed-1/RESULT.json").read_bytes()), "lossless_rpc_count": 70, "private_key_bodies_read_or_extracted": False, "whole_archives_in_git": False, "Git_objects_or_ref_mutations": False, "host_processes_started": 0, "model_or_native_runs": 0}
    (HERE / "FINAL_PUBLICATION_READBACK.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
