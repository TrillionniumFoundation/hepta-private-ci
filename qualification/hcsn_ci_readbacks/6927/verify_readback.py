"""Zero-numerical readback for the immutable #6927 Actions artifact."""

import hashlib
import json
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "ORIGINAL.zip"
READBACK = HERE / "READBACK.json"


def main():
    expected = json.loads(READBACK.read_text())
    raw = ARCHIVE.read_bytes()
    if len(raw) != expected["original_zip_bytes"]:
        raise SystemExit("original ZIP byte count mismatch")
    if hashlib.sha256(raw).hexdigest() != expected["original_zip_sha256"]:
        raise SystemExit("original ZIP digest mismatch")
    with zipfile.ZipFile(ARCHIVE) as archive:
        if archive.testzip() is not None:
            raise SystemExit("original ZIP CRC failure")
        if len(archive.namelist()) != expected["members"]:
            raise SystemExit("original ZIP member count mismatch")
        if sum(item.file_size for item in archive.infolist()) != expected["uncompressed_bytes"]:
            raise SystemExit("original ZIP uncompressed byte count mismatch")
        result = json.loads(archive.read("RESULT.json"))
        if result["execution_key"] != "hcsn-n256-authentic-firststep-cursor-20261121-c6bc-001":
            raise SystemExit("execution key mismatch")
        if result["work"] != expected["executed_work"]:
            raise SystemExit("executed-work mismatch")
        if result["scope"]["all_closed"] is not False:
            raise SystemExit("scope is not fail closed")
        seen = 0
        for lane in ("discounted", "undiscounted"):
            for item in result["lanes"][lane]["cursors"]:
                payload = archive.read(item["file"])
                if len(payload) != item["bytes"]:
                    raise SystemExit("cursor byte count mismatch")
                if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                    raise SystemExit("cursor digest mismatch")
                envelope = json.loads(payload)
                canonical = json.dumps(
                    envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                ).encode("ascii")
                if canonical != payload:
                    raise SystemExit("noncanonical cursor payload")
                body_bytes = json.dumps(
                    envelope["body"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
                if hashlib.sha256(body_bytes).hexdigest() != envelope["body_sha256"]:
                    raise SystemExit("cursor body digest mismatch")
                if envelope["body"]["included_index"] != 1:
                    raise SystemExit("cursor is not at the first-step boundary")
                seen += 1
        if seen != expected["cursor_payloads"]:
            raise SystemExit("cursor count mismatch")
    print("PASS_6927_AUTHENTIC_FIRSTSTEP_CURSOR_ZERO_NUMERICAL_READBACK")


if __name__ == "__main__":
    main()
