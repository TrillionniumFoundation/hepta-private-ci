"""Prepare exact E6 archive parts/receipts for a later evidence-only commit."""

import hashlib
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PREFIX = "evidence/e6-completion-namespace-20261120"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def main():
    publication = HERE / "publication"
    package = publication / PREFIX
    package.mkdir(parents=True, exist_ok=False)
    origins = {}
    def copy(source, relative):
        destination = package / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = source.read_bytes()
        assert len(raw) < 512000 and not destination.exists()
        destination.write_bytes(raw)
        assert destination.read_bytes() == raw
        origins[relative] = {"kind": "exact_byte_copy", "source_path": str(source.resolve()), "bytes": len(raw), "sha256": sha(raw)}
    def derived(relative, value, source):
        destination = package / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(value, indent=2) + "\n").encode()
        assert len(raw) < 512000 and not destination.exists()
        destination.write_bytes(raw)
        origins[relative] = {"kind": "explicit_derived_metadata", "source": source, "bytes": len(raw), "sha256": sha(raw)}

    for kind in ("host", "cloud"):
        retained = HERE / ("retained-" + kind)
        result_path = retained / "RESULT.json"
        result = json.loads(result_path.read_bytes())
        for row in result["parts"]:
            copy(retained / row["name"], kind + "/" + row["name"])
        for name in ("MANIFEST.json", "RESULT.json"):
            copy(retained / name, kind + "/" + name)
        if kind == "host":
            for name in ("SUMMARY.json", "archive-parts.json", "EXCLUDED_KEY_METADATA.json"):
                copy(retained / name, kind + "/" + name)
        else:
            copy(retained / "READBACK.json", "cloud/ORIGINAL_READBACK.json")
            parts = {"archive_name": "cloud-originals.tar.xz", "archive_bytes": result["archive_bytes"], "archive_sha256": result["archive_sha256"], "parts": result["parts"]}
            derived("cloud/archive-parts.json", parts, {"file": "cloud/RESULT.json", "sha256": sha(result_path.read_bytes())})
            derived("cloud/PARTS_DERIVATION.json", {"kind": "deterministic_exact_fields_from_original_RESULT", "original_sidecar": "RESULT.json", "original_sidecar_sha256": sha(result_path.read_bytes()), "derived_file": "archive-parts.json", "fields": ["archive_bytes", "archive_sha256", "parts"], "archive_name": "cloud-originals.tar.xz", "host_original_file_claimed": False}, "cloud RESULT original")
    old = ROOT / "e6_owner_work/completion_namespace_evidence"
    for name in ("ARCHIVE_OWNER_START.json", "ARCHIVE_OWNER_TERMINAL.json", "ARCHIVE_CORE_READBACK.json", "ARCHIVE_REVIEW.json", "ARCHIVE_REVISION2.diff", "PRIVATE_MATERIAL_SCOPE.json"):
        copy(old / name, "original-owner/" + name)
    for local, public in (("verification-host-1", "host-v1"), ("verification-host-2", "host-v2"), ("verification-cloud-1", "cloud-v1")):
        for source in sorted((HERE / local).iterdir()):
            assert source.is_file()
            copy(source, "verification/" + public + "/" + source.name)
    for name in ("VERIFIER_REVISION_2.diff", "VERIFIER_REVISION_2.json", "NATIVE_47_RETRY_SOURCE_INDEX.json"):
        copy(HERE / name, "verification/" + name)
    copy(HERE / "DOWNLOAD_READBACK.json", "verification/transport/DOWNLOAD_READBACK.json")
    copy(HERE / "RECEIPT_TEMPLATES.json", "verification/transport/RECEIPT_TEMPLATES.json")
    copy(HERE / "transport-reconstructed-1/RESULT.json", "verification/transport/RECONSTRUCTION_RESULT.json")
    for source in sorted((HERE / "receipts").glob("*.json")):
        if "-chunk-" not in source.name:
            copy(source, "verification/transport/original-metadata/" + source.name)
    for name in ("verify_archives.py", "verify_archives_v2.py", "restore_download_receipts.py", "build_publication.py"):
        copy(HERE / name, "verification/tools/" + name)
    copy(HERE / "reassemble_archives.py", "reassemble_archives.py")
    copy(HERE / "READOUT.md", "README.md")
    derived("FILE_ORIGINS.json", {"schema": "hepta.e6.archive-publication-origins.v1", "prefix_proposed": PREFIX, "remote_git_objects_created": False, "files": origins}, "Exact byte-copy and explicitly derived metadata records")
    files = []
    for path in sorted(package.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        assert len(raw) < 512000
        files.append({"path": str(path.relative_to(publication)), "local_path": str(path.resolve()), "bytes": len(raw), "sha256": sha(raw), "git_blob": git_blob(raw), "mode": "100644"})
    manifest = {"schema": "hepta.e6.archive-evidence-publication-files.v1", "prefix": PREFIX, "files": files, "source_anchor": "9dfded9cecc74e39a19bccd14b9de9dc46c02c63", "head_created": False, "refs_changed": False, "total_bytes": sum(row["bytes"] for row in files), "max_file_bytes": max(row["bytes"] for row in files), "whole_archives_in_git": False, "unencoded_binary_rpc_json_in_git": False, "lossless_reconstruction_verified": True}
    (publication / "PUBLICATION_FILES.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"files": len(files), "total_bytes": manifest["total_bytes"], "maximum": manifest["max_file_bytes"], "manifest_sha256": sha((publication / "PUBLICATION_FILES.json").read_bytes())}))


if __name__ == "__main__":
    main()
