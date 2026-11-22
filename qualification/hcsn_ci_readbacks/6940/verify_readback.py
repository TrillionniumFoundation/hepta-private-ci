"""Zero-recurrence audit of the immutable #6940 Actions artifact."""

from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile


HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "MANIFEST.json").read_text())
SIGNED_HEX = re.compile(r"-?(?:0|[1-9a-f][0-9a-f]*)\Z")
POSITIVE_HEX = re.compile(r"[1-9a-f][0-9a-f]*\Z")
SCHEMA = "hcsn-n256-authentic-index128-checkpoint-profile-hex-v2"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def validate_pair(pair):
    if (
        not isinstance(pair, list)
        or len(pair) != 2
        or not isinstance(pair[0], str)
        or not isinstance(pair[1], str)
        or SIGNED_HEX.fullmatch(pair[0]) is None
        or POSITIVE_HEX.fullmatch(pair[1]) is None
    ):
        raise SystemExit("noncanonical hexadecimal fraction")


def main():
    parts = []
    for name, expected in MANIFEST["parts"].items():
        raw = (HERE / name).read_bytes()
        if digest(raw) != expected:
            raise SystemExit(f"part digest mismatch: {name}")
        parts.append(raw)
    archive_raw = b"".join(parts)
    if (
        len(archive_raw) != MANIFEST["artifact_size_bytes"]
        or digest(archive_raw) != MANIFEST["artifact_sha256"]
    ):
        raise SystemExit("artifact binding mismatch")

    with zipfile.ZipFile(io.BytesIO(archive_raw)) as archive:
        if archive.testzip() is not None:
            raise SystemExit("artifact CRC failure")
        names = archive.namelist()
        if len(names) != MANIFEST["member_count"] or len(set(names)) != len(names):
            raise SystemExit("artifact member roster mismatch")
        result = json.loads(archive.read("RESULT.json"))
        host = json.loads(archive.read("HOST.json"))
        if host["github_run_id"] != "44988986473" or host["github_run_attempt"] != "1":
            raise SystemExit("host receipt mismatch")
        if (
            result["identity"]
            != "hcsn-n256-authentic-checkpoint-hex-20261122-c6bc-v2"
            or result["execution_key"]
            != "hcsn-n256-authentic-checkpoint-hex-20261122-c6bc-001"
            or result["status"] != "AUTHENTIC_INDEX128_RESOURCE_PROFILE_ONLY_HOLD"
        ):
            raise SystemExit("result identity mismatch")
        rows = result["checkpoints"]
        if len(rows) != 20 or Counter(row["boundary"] for row in rows) != {64: 10, 128: 10}:
            raise SystemExit("checkpoint roster mismatch")
        if sum(row["bytes"] for row in rows) != result["cost"]["cursor_output_bytes"]:
            raise SystemExit("checkpoint byte ledger mismatch")
        expected_names = {"HOST.json", "RESULT.json"}
        for row in rows:
            raw = archive.read(row["file"])
            expected_names.add(row["file"])
            if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
                raise SystemExit(f"checkpoint binding mismatch: {row['file']}")
            envelope = json.loads(raw)
            if canonical(envelope) != raw or set(envelope) != {"body", "body_sha256"}:
                raise SystemExit(f"checkpoint JSON mismatch: {row['file']}")
            body = envelope["body"]
            if body["schema"] != SCHEMA or digest(canonical(body)) != envelope["body_sha256"]:
                raise SystemExit(f"checkpoint body mismatch: {row['file']}")
            for field in ("coefficient", "growth_coefficient", "exponential_sum"):
                validate_pair(body[field])
            for field in ("iterate", "partial"):
                for pair in body[field]:
                    validate_pair(pair)
        if set(names) != expected_names:
            raise SystemExit("unexpected artifact member")

    work = result["work"]
    if (
        work["total_row_actions"] != 3140
        or work["tail_checks"] != 0
        or work["provider_outputs"] != 0
        or work["dynamic_steps"] != 0
        or work["exponential_actions"] != 0
        or work["torch_calls"] != 0
        or work["optimizer_steps"] != 0
    ):
        raise SystemExit("work ledger mismatch")
    scope = result["scope"]
    if (
        scope["resource_gate_closed"] is not False
        or scope["n256_qualified"] is not False
        or scope["all_closed"] is not False
        or scope["cause_of_6901_red"] != "UNKNOWN"
        or scope["hpca_status"] != "NoUpdate"
    ):
        raise SystemExit("scope is not fail closed")
    print("PASS_6940_IMMUTABLE_ARTIFACT_READBACK_ZERO_RECURRENCE")


if __name__ == "__main__":
    main()
