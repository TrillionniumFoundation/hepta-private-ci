"""Zero-numerical readback for the immutable #6936 checkpoint artifact."""

from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
READBACK = HERE / "READBACK.json"
DETACHED = ROOT / "qualification/hcsn_ci_readbacks/6934/ORIGINAL.zip"
PARENT_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6931"
PARENT_NAMES = (
    "ORIGINAL.zip.part000",
    "ORIGINAL.zip.part001",
    "ORIGINAL.zip.part002",
)
SCHEMA = "hcsn-n256-authentic-index32-checkpoint-profile-v1"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def main():
    expected = json.loads(READBACK.read_text())
    raw_parts = []
    for item in expected["parts"]:
        raw = (HERE / item["file"]).read_bytes()
        if len(raw) != item["bytes"] or _sha256(raw) != item["sha256"]:
            raise SystemExit(f"original part mismatch: {item['file']}")
        raw_parts.append(raw)
    raw = b"".join(raw_parts)
    if len(raw) != expected["original_zip_bytes"]:
        raise SystemExit("original ZIP byte count mismatch")
    if _sha256(raw) != expected["original_zip_sha256"]:
        raise SystemExit("original ZIP digest mismatch")

    detached_raw = DETACHED.read_bytes()
    parent_raw = b"".join(
        (PARENT_PARTS / name).read_bytes() for name in PARENT_NAMES
    )
    with (
        zipfile.ZipFile(io.BytesIO(raw)) as archive,
        zipfile.ZipFile(io.BytesIO(detached_raw)) as detached_archive,
        zipfile.ZipFile(io.BytesIO(parent_raw)) as parent_archive,
    ):
        if archive.testzip() is not None:
            raise SystemExit("original ZIP CRC failure")
        if len(archive.namelist()) != expected["members"]:
            raise SystemExit("original ZIP member count mismatch")
        if sum(item.file_size for item in archive.infolist()) != expected[
            "uncompressed_bytes"
        ]:
            raise SystemExit("original ZIP uncompressed byte count mismatch")

        result = json.loads(archive.read("RESULT.json"))
        host = json.loads(archive.read("HOST.json"))
        if result["execution_key"] != (
            "hcsn-n256-authentic-checkpoint-profile-20261121-c6bc-001"
        ):
            raise SystemExit("execution key mismatch")
        if result["cost"] != expected["cost"] or result["work"] != expected["work"]:
            raise SystemExit("cost or work ledger mismatch")
        if result["scope"]["all_closed"] is not False:
            raise SystemExit("result scope is not fail closed")
        if host["github_sha"] != expected["host_github_sha"]:
            raise SystemExit("host merge SHA mismatch")
        if len(result["checkpoints"]) != 40:
            raise SystemExit("checkpoint count mismatch")

        detached_result = json.loads(detached_archive.read("RESULT.json"))
        source_bindings = {}
        for item in detached_result["cursors"]:
            second = parent_archive.read(item["source_file"])
            parent = json.loads(second)["body"]["parent_payload_ascii"].encode(
                "ascii"
            )
            prefix = item["file"].removesuffix(".detached.cursor.json")
            source_bindings[prefix] = (
                item["sha256"],
                _sha256(parent),
                item["lane"],
            )

        grouped = defaultdict(list)
        total_bytes = 0
        seen = set()
        for item in result["checkpoints"]:
            payload = archive.read(item["file"])
            if len(payload) != item["bytes"] or _sha256(payload) != item["sha256"]:
                raise SystemExit("checkpoint file identity mismatch")
            envelope = json.loads(payload)
            if _canonical(envelope) != payload:
                raise SystemExit("noncanonical checkpoint payload")
            if set(envelope) != {"body", "body_sha256"}:
                raise SystemExit("invalid checkpoint envelope")
            body = envelope["body"]
            if _sha256(_canonical(body)) != envelope["body_sha256"]:
                raise SystemExit("checkpoint body digest mismatch")
            boundary = item["boundary"]
            if body["schema"] != SCHEMA or body["included_index"] != boundary:
                raise SystemExit("checkpoint schema or boundary mismatch")
            suffix = f".index{boundary}.checkpoint.json"
            if not item["file"].endswith(suffix):
                raise SystemExit("checkpoint filename boundary mismatch")
            prefix = item["file"].removesuffix(suffix)
            binding = source_bindings.get(prefix)
            if binding is None or (
                body["source_payload_sha256"],
                body["parent_payload_sha256"],
                body["lane"],
            ) != binding:
                raise SystemExit("checkpoint archived-input binding mismatch")
            identity = (prefix, boundary)
            if identity in seen:
                raise SystemExit("duplicate checkpoint boundary")
            seen.add(identity)
            grouped[boundary].append(len(payload))
            total_bytes += len(payload)

        observed_summary = [
            {
                "boundary": boundary,
                "count": len(grouped[boundary]),
                "max_bytes": max(grouped[boundary]),
                "min_bytes": min(grouped[boundary]),
                "sum_bytes": sum(grouped[boundary]),
            }
            for boundary in (4, 8, 16, 32)
        ]
        if observed_summary != expected["boundary_summary"]:
            raise SystemExit("checkpoint boundary ledger mismatch")
        if total_bytes != expected["cost"]["cursor_output_bytes"]:
            raise SystemExit("checkpoint total byte ledger mismatch")
    print("PASS_6936_AUTHENTIC_CHECKPOINT_ZERO_NUMERICAL_READBACK")


if __name__ == "__main__":
    main()
