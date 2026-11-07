"""Retain a complete, verified ARM view ZIP without writing its raw ZIP copy."""

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.request
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
HEAD = "8b0fcf80afb95c5199be9b5f131d6454663c1632"
RUN = 42353199414
MAX_ZIP_BYTES = 144 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MIN_FREE_AFTER_WRITE = 4 * 1024 * 1024


class AuditError(Exception):
    pass


def require(value, code):
    if not value:
        raise AuditError(code)


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def artifact_from_api(api_path, artifact_id):
    value = json.loads(Path(api_path).read_text())
    if "content" in value:
        value = json.loads(value["content"])
    rows = [row for row in value["artifacts"] if row["id"] == artifact_id]
    require(len(rows) == 1, "ARTIFACT_NOT_UNIQUE")
    artifact = rows[0]
    require(artifact["expired"] is False, "ARTIFACT_EXPIRED")
    require(artifact["workflow_run"]["id"] == RUN, "WRONG_RUN")
    require(artifact["workflow_run"]["head_sha"] == HEAD, "WRONG_SOURCE")
    require(0 < artifact["size_in_bytes"] <= MAX_ZIP_BYTES, "ZIP_SIZE_BOUND")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]), "BAD_DIGEST")
    return artifact


def check_members(raw, role):
    expected = (
        ["DIAGNOSTICS.json", "PROJECTION.json", "SOURCE_DIRECTORY.json"]
        if role == "manifest"
        else [f"part-{int(role):02d}.tar.part"]
    )
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(archive.namelist() == expected, "UNEXPECTED_MEMBERS")
        for info in archive.infolist():
            require(not info.is_dir(), "DIRECTORY_MEMBER")
            require(0 <= info.file_size <= MAX_MEMBER_BYTES, "MEMBER_SIZE_BOUND")
            digest, crc, size = hashlib.sha256(), 0, 0
            with archive.open(info) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    crc = zlib.crc32(chunk, crc)
                    size += len(chunk)
                    require(size <= info.file_size, "MEMBER_OVERFLOW")
            require(size == info.file_size, "MEMBER_SIZE_MISMATCH")
            require(crc & 0xFFFFFFFF == info.CRC, "MEMBER_CRC_MISMATCH")
            result[info.filename] = {
                "bytes": size,
                "sha256": digest.hexdigest(),
                "crc32": f"{crc & 0xFFFFFFFF:08x}",
                "zip_compression": info.compress_type,
            }
    return result


def main():
    require(len(sys.argv) == 5, "ARGUMENTS")
    api_path, artifact_id, role, url_file = sys.argv[1:]
    url_path = Path(url_file)
    try:
        require(url_path.stat().st_mode & 0o777 == 0o600, "PRIVATE_URL_MODE")
        download_url = url_path.read_text()
    finally:
        url_path.unlink(missing_ok=True)
    require(len(download_url) <= 8192, "DOWNLOAD_URL_BOUND")
    require(role == "manifest" or role in [str(n) for n in range(1, 9)], "ROLE")
    artifact_id = int(artifact_id)
    artifact = artifact_from_api(api_path, artifact_id)
    target = HERE / f"artifact-{artifact_id}.zip.gz"
    receipt_path = HERE / f"artifact-{artifact_id}.WRAPPER.json"
    require(not target.exists() and not receipt_path.exists(), "OUTPUT_EXISTS")
    require(download_url.startswith("https://"), "DOWNLOAD_SCHEME")
    # The tool-provided storage URL receives no repository Authorization header.
    request = urllib.request.Request(download_url, headers={})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read(artifact["size_in_bytes"] + 1)
    original = identity(raw)
    require(original["bytes"] == artifact["size_in_bytes"], "ZIP_SIZE")
    require("sha256:" + original["sha256"] == artifact["digest"], "ZIP_DIGEST")
    members = check_members(raw, role)
    wrapped = gzip.compress(raw, compresslevel=9, mtime=0)
    decoder = zlib.decompressobj(wbits=31)
    restored = decoder.decompress(wrapped, len(raw) + 1)
    require(
        decoder.eof
        and not decoder.unused_data
        and not decoder.unconsumed_tail
        and restored == raw,
        "SINGLE_MEMBER_EXACT_ROUNDTRIP",
    )
    del restored
    free_before = shutil.disk_usage(HERE).free
    require(
        free_before >= len(wrapped) + MIN_FREE_AFTER_WRITE,
        "INSUFFICIENT_FREE_SPACE_FOR_WRAPPER",
    )
    with target.open("xb") as stream:
        os.chmod(target, 0o600)
        stream.write(wrapped)
        stream.flush()
        os.fsync(stream.fileno())
    require(target.read_bytes() == wrapped, "WRAPPER_READBACK")
    receipt = {
        "source_head": HEAD,
        "run_id": RUN,
        "artifact_id": artifact_id,
        "artifact_name": artifact["name"],
        "artifact_api_file": str(Path(api_path).resolve()),
        "artifact_api_identity": identity(Path(api_path).read_bytes()),
        "role": role,
        "official_complete_zip": original,
        "all_zip_member_crc_and_sha_verified": members,
        "complete_zip_wrapper": {"file": target.name, **identity(wrapped)},
        "compression": {"format": "gzip", "level": 9, "mtime": 0, "members": 1},
        "original_zip_roundtrip_byte_equal": True,
        "raw_zip_written_to_disk": False,
        "zip_members_extracted_to_disk": False,
        "wrapper_mode": "0600",
        "free_bytes_before_wrapper": free_before,
        "free_bytes_after_wrapper": shutil.disk_usage(HERE).free,
        "qualification_or_promotion": False,
        "scope": "Whole original ZIP bytes, not a digest-only or selected-content substitute. Projection/source/business interpretation is a separate audit. No rejected content is reconstructed.",
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "artifact_id": artifact_id,
                "zip": original,
                "wrapper": identity(wrapped),
                "member_count": len(members),
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print storage URLs, response bodies, or external exception text.
        result = {"success": False, "exception_type": type(error).__name__}
        if isinstance(error, AuditError):
            result["reason"] = error.args[0]
        print(json.dumps(result), file=sys.stderr)
        raise SystemExit(1) from None
