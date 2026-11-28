"""Restore exact scientific file trees from the bounded public cloud package.

Reconstructs the original chunk02 gzip byte-for-byte, then restores every chunk01
file using its content map and one preserved prior metadata file. It deliberately
does not claim to reproduce the original chunk01 gzip container bytes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def safe_relative(value):
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Unsafe path in evidence manifest")
    return p


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    manifest = json.loads((package / "PACKAGE_MANIFEST.json").read_text())
    for item in manifest["files"]:
        path = package / safe_relative(item["path"])
        assert path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]
    index = json.loads((package / "results/cloud/member_index.json").read_text())
    chunks = json.loads((package / "artifacts/colab_chunk02_evidence.tar.gz.manifest.json").read_text())
    archive = output / "chunk02-evidence.tar.gz"
    with archive.open("xb") as target:
        for part in chunks["parts"]:
            path = package / safe_relative(part["path"])
            assert path.stat().st_size == part["bytes"] and sha(path) == part["sha256"]
            with path.open("rb") as source:
                shutil.copyfileobj(source, target)
    assert archive.stat().st_size == chunks["bytes"] and sha(archive) == chunks["sha256"]
    final = output / "chunk02"
    final.mkdir()
    with tarfile.open(archive, "r:gz") as t:
        members = t.getmembers()
        assert len({m.name for m in members}) == len(members)
        assert sum(m.size for m in members) < 256*1024*1024
        for m in members:
            safe_relative(m.name)
            assert m.isfile() or m.isdir()
        t.extractall(final, filter="data")
    final_root = final / "weightcode_rule_to_data"
    for rec in index["chunk02_files"]:
        path = final_root / safe_relative(rec["path"])
        assert path.stat().st_size == rec["bytes"] and sha(path) == rec["sha256"]
    first = output / "chunk01" / "weightcode_rule_to_data"
    first.mkdir(parents=True)
    for rec in index["chunk01_files"]:
        rel = safe_relative(rec["path"])
        source = (final_root / rel) if rec["source"] == "chunk02" else (package / "artifacts/cloud_chunk01_overrides" / rel)
        assert source.stat().st_size == rec["bytes"] and sha(source) == rec["sha256"]
        target = first / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert sha(target) == rec["sha256"]
    receipt = {"schema": "hepta.wsp.cloud-content-restore.v1",
               "chunk02_original_gzip_byte_exact": True,
               "chunk02_original_archive_sha256": sha(archive),
               "chunk01_all_scientific_member_bytes_exact": True,
               "chunk01_original_gzip_bytes_reconstructed": False,
               "chunk01_original_gzip_sha256_reference": index["chunk01_original_archive_sha256"],
               "chunk01_files": len(index["chunk01_files"]), "chunk02_files": len(index["chunk02_files"])}
    (output / "RESTORE_RECEIPT.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
