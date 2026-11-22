"""Zero-numerical readback for the immutable #6934 Actions artifact."""

import hashlib
import io
import json
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
READBACK = HERE / "READBACK.json"
ORIGINAL = HERE / "ORIGINAL.zip"
SOURCE_READBACK = ROOT / "qualification/hcsn_ci_readbacks/6931"
SOURCE_PARTS = (
    "ORIGINAL.zip.part000",
    "ORIGINAL.zip.part001",
    "ORIGINAL.zip.part002",
)
SOURCE_ZIP_SHA256 = (
    "41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae"
)


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _check_envelope(payload, schema):
    envelope = json.loads(payload)
    if _canonical(envelope) != payload:
        raise SystemExit("noncanonical cursor payload")
    if set(envelope) != {"body", "body_sha256"}:
        raise SystemExit("invalid cursor envelope")
    body = envelope["body"]
    if _sha256(_canonical(body)) != envelope["body_sha256"]:
        raise SystemExit("cursor body digest mismatch")
    if body["schema"] != schema or body["included_index"] != 2:
        raise SystemExit("cursor schema or boundary mismatch")
    return body


def main():
    expected = json.loads(READBACK.read_text())
    raw = ORIGINAL.read_bytes()
    if len(raw) != expected["original_zip_bytes"]:
        raise SystemExit("original ZIP byte count mismatch")
    if _sha256(raw) != expected["original_zip_sha256"]:
        raise SystemExit("original ZIP digest mismatch")

    source_raw = b"".join(
        (SOURCE_READBACK / name).read_bytes() for name in SOURCE_PARTS
    )
    if _sha256(source_raw) != SOURCE_ZIP_SHA256:
        raise SystemExit("source ZIP digest mismatch")

    with (
        zipfile.ZipFile(io.BytesIO(raw)) as archive,
        zipfile.ZipFile(io.BytesIO(source_raw)) as source_archive,
    ):
        if archive.testzip() is not None or source_archive.testzip() is not None:
            raise SystemExit("ZIP CRC failure")
        if len(archive.namelist()) != expected["members"]:
            raise SystemExit("original ZIP member count mismatch")
        if sum(item.file_size for item in archive.infolist()) != expected[
            "uncompressed_bytes"
        ]:
            raise SystemExit("original ZIP uncompressed byte count mismatch")
        result = json.loads(archive.read("RESULT.json"))
        if result["execution_key"] != (
            "hcsn-n256-authentic-detached-cursor-20261121-c6bc-001"
        ):
            raise SystemExit("execution key mismatch")
        if result["input_zip_sha256"] != SOURCE_ZIP_SHA256:
            raise SystemExit("source ZIP identity mismatch")
        if result["work"] != expected["source_work"]:
            raise SystemExit("source work mismatch")
        if result["scope"]["all_closed"] is not False:
            raise SystemExit("scope is not fail closed")
        if len(result["cursors"]) != expected["cursor_payloads"]:
            raise SystemExit("cursor count mismatch")

        detached_sizes = []
        source_sizes = []
        saved_sizes = []
        for item in result["cursors"]:
            payload = archive.read(item["file"])
            if len(payload) != item["bytes"] or _sha256(payload) != item["sha256"]:
                raise SystemExit("detached cursor identity mismatch")
            body = _check_envelope(
                payload, "hcsn-n256-authentic-detached-parent-cursor-v1"
            )

            source = source_archive.read(item["source_file"])
            if (
                len(source) != item["source_bytes"]
                or _sha256(source) != item["source_sha256"]
            ):
                raise SystemExit("source cursor identity mismatch")
            source_body = _check_envelope(
                source, "hcsn-n256-authentic-signed-secondstep-cursor-v1"
            )
            parent = source_body["parent_payload_ascii"].encode("ascii")
            if _sha256(parent) != source_body["parent_payload_sha256"]:
                raise SystemExit("source parent digest mismatch")
            if body["parent_payload_sha256"] != item["parent_sha256"]:
                raise SystemExit("detached parent ledger mismatch")
            if body["parent_payload_sha256"] != source_body["parent_payload_sha256"]:
                raise SystemExit("detached parent binding mismatch")

            for key in (
                "coefficient",
                "exponential_sum",
                "growth_coefficient",
                "included_index",
                "iterate",
                "lane",
                "partial",
            ):
                if body[key] != source_body[key]:
                    raise SystemExit(f"detached state mismatch: {key}")
            detached_sizes.append(len(payload))
            source_sizes.append(len(source))
            saved_sizes.append(len(source) - len(payload))

        if (
            sum(detached_sizes) != expected["cursor_payload_bytes"]
            or sum(source_sizes) != expected["source_cursor_payload_bytes"]
            or sum(saved_sizes) != expected["payload_bytes_saved"]
            or min(detached_sizes) != expected["cursor_min_bytes"]
            or max(detached_sizes) != expected["cursor_max_bytes"]
        ):
            raise SystemExit("cursor size ledger mismatch")
    print("PASS_6934_AUTHENTIC_DETACHED_CURSOR_ZERO_NUMERICAL_READBACK")


if __name__ == "__main__":
    main()
