"""Zero-numerical readback for the immutable #6931 Actions artifact."""

import hashlib
import io
import json
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
READBACK = HERE / "READBACK.json"


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def main():
    expected = json.loads(READBACK.read_text())
    chunks = []
    for item in expected["original_zip_parts"]:
        path = HERE / item["file"]
        chunk = path.read_bytes()
        if len(chunk) != item["bytes"]:
            raise SystemExit("original ZIP part byte count mismatch")
        if hashlib.sha256(chunk).hexdigest() != item["sha256"]:
            raise SystemExit("original ZIP part digest mismatch")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if len(raw) != expected["original_zip_bytes"]:
        raise SystemExit("original ZIP byte count mismatch")
    if hashlib.sha256(raw).hexdigest() != expected["original_zip_sha256"]:
        raise SystemExit("original ZIP digest mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.testzip() is not None:
            raise SystemExit("original ZIP CRC failure")
        if len(archive.namelist()) != expected["members"]:
            raise SystemExit("original ZIP member count mismatch")
        uncompressed = sum(item.file_size for item in archive.infolist())
        if uncompressed != expected["uncompressed_bytes"]:
            raise SystemExit("original ZIP uncompressed byte count mismatch")
        result = json.loads(archive.read("RESULT.json"))
        if result["execution_key"] != (
            "hcsn-n256-authentic-secondstep-cursor-20261121-c6bc-001"
        ):
            raise SystemExit("execution key mismatch")
        if result["work"] != expected["executed_work"]:
            raise SystemExit("executed-work mismatch")
        if result["scope"]["all_closed"] is not False:
            raise SystemExit("scope is not fail closed")
        if len(result["cursors"]) != expected["child_payloads"]:
            raise SystemExit("child cursor count mismatch")
        for item in result["cursors"]:
            payload = archive.read(item["file"])
            if len(payload) != item["bytes"]:
                raise SystemExit("child cursor byte count mismatch")
            if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise SystemExit("child cursor digest mismatch")
            envelope = json.loads(payload)
            if _canonical(envelope) != payload:
                raise SystemExit("noncanonical child cursor payload")
            body = envelope["body"]
            if hashlib.sha256(_canonical(body)).hexdigest() != envelope["body_sha256"]:
                raise SystemExit("child cursor body digest mismatch")
            if body["included_index"] != 2:
                raise SystemExit("child is not at second-step boundary")
            parent = body["parent_payload_ascii"].encode("ascii")
            if hashlib.sha256(parent).hexdigest() != body["parent_payload_sha256"]:
                raise SystemExit("embedded parent digest mismatch")
            if body["parent_payload_sha256"] != item["parent_sha256"]:
                raise SystemExit("result-to-parent digest mismatch")
            parent_envelope = json.loads(parent)
            if _canonical(parent_envelope) != parent:
                raise SystemExit("noncanonical embedded parent")
            if (
                hashlib.sha256(_canonical(parent_envelope["body"])).hexdigest()
                != parent_envelope["body_sha256"]
            ):
                raise SystemExit("embedded parent body digest mismatch")
            if parent_envelope["body"]["included_index"] != 1:
                raise SystemExit("embedded parent is not at first-step boundary")
    print("PASS_6931_AUTHENTIC_SECONDSTEP_CURSOR_ZERO_NUMERICAL_READBACK")


if __name__ == "__main__":
    main()
