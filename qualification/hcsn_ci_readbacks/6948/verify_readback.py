"""Independent zero-recurrence review of the #6948 immutable originals."""

import hashlib
import io
import json
import lzma
from pathlib import Path
import struct
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ARTIFACT_SHA256 = "fe98992972a1779e6ffe1baf2142a2010bd71eb92e633dc69e459578caa9e8f6"
ARTIFACT_BYTES = 17_089_235
PART_COUNT = 35
INPUT_ROOT = ROOT / "qualification/hcsn_ci_readbacks/6944"
INPUT_PART_COUNT = 41
INPUT_SHA256 = "452060c65949e9c1d8ffe74e4303d707e6fe4fe7c2e75e29caacfa3137c37a91"
MAGIC = b"HCSNCPT1"
HEADER = struct.Struct(">8sQQ32s32s")
MAX_COMPACT_BYTES = 8_388_608
MAX_RAW_BYTES = 33_554_432
AGGREGATE_CAP_BYTES = 67_108_864
SCHEMA = "hcsn-n256-authentic-index256-checkpoint-profile-v1"
EXECUTION_KEY = "hcsn-n256-authentic-compact-checkpoint-20261122-c6bc-001"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _parts(root, count):
    return b"".join(
        (root / f"ORIGINAL.zip.part{index:03d}").read_bytes()
        for index in range(count)
    )


def _fail(condition, message):
    if not condition:
        raise SystemExit(message)


def _decode_independently(payload):
    _fail(
        isinstance(payload, bytes) and HEADER.size < len(payload) <= MAX_COMPACT_BYTES,
        "compact payload byte bound differs",
    )
    magic, raw_bytes, compressed_bytes, raw_sha, compressed_sha = HEADER.unpack(
        payload[: HEADER.size]
    )
    compressed = payload[HEADER.size :]
    _fail(magic == MAGIC, "compact magic differs")
    _fail(compressed_bytes == len(compressed), "compressed length differs")
    _fail(0 < raw_bytes <= MAX_RAW_BYTES, "raw length bound differs")
    _fail(hashlib.sha256(compressed).digest() == compressed_sha, "compressed SHA differs")
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    try:
        raw = decoder.decompress(compressed, max_length=MAX_RAW_BYTES + 1)
    except lzma.LZMAError as error:
        raise SystemExit("independent XZ decode failed") from error
    _fail(len(raw) <= MAX_RAW_BYTES, "decoded checkpoint exceeds raw cap")
    _fail(decoder.eof and not decoder.unused_data, "XZ stream is not exact")
    _fail(len(raw) == raw_bytes, "raw length differs")
    _fail(hashlib.sha256(raw).digest() == raw_sha, "raw SHA differs")
    return raw


def _validate_raw_identity(raw, record):
    try:
        envelope = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit("restored state is not ASCII JSON") from error
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    _fail(canonical == raw, "restored state is not canonical")
    _fail(set(envelope) == {"body", "body_sha256"}, "raw envelope differs")
    body = envelope["body"]
    body_raw = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    _fail(_sha256(body_raw) == envelope["body_sha256"], "raw body SHA differs")
    _fail(body.get("schema") == SCHEMA, "raw schema differs")
    _fail(body.get("included_index") == 256, "raw index differs")
    _fail(body.get("lane") == record["lane"], "raw lane differs")
    _fail(len(body.get("iterate", [])) == record["vector_length"], "vector length differs")


def main():
    artifact = _parts(HERE, PART_COUNT)
    _fail(len(artifact) == ARTIFACT_BYTES, "artifact byte count differs")
    _fail(_sha256(artifact) == ARTIFACT_SHA256, "artifact SHA differs")
    input_zip = _parts(INPUT_ROOT, INPUT_PART_COUNT)
    _fail(_sha256(input_zip) == INPUT_SHA256, "#6944 input ZIP SHA differs")
    with zipfile.ZipFile(io.BytesIO(artifact)) as archive, zipfile.ZipFile(
        io.BytesIO(input_zip)
    ) as inputs:
        _fail(archive.testzip() is None, "artifact ZIP CRC differs")
        _fail(inputs.testzip() is None, "#6944 ZIP CRC differs")
        _fail(len(archive.namelist()) == 12, "artifact member denominator differs")
        result_raw = archive.read("RESULT.json")
        journal_raw = archive.read("RUN.jsonl")
        _fail(result_raw == (HERE / "RESULT.json").read_bytes(), "RESULT copy differs")
        _fail(journal_raw == (HERE / "RUN.jsonl").read_bytes(), "RUN copy differs")
        result = json.loads(result_raw)
        _fail(result["execution_key"] == EXECUTION_KEY, "execution key differs")
        _fail(result["input_zip_sha256"] == INPUT_SHA256, "input identity differs")
        _fail(result["status"] == "AUTHENTIC_INDEX256_COMPACT_FULLSTATE_ONLY_HOLD", "status differs")
        _fail(result["all_closed"] is False, "all_closed was granted")
        _fail(result["n256_qualified"] is False, "N256 qualification was granted")
        _fail(result["production_adoption"] is False, "production was adopted")
        _fail(
            result["work"]
            == {
                "dynamic_steps": 0,
                "exponential_actions": 0,
                "optimizer_steps": 0,
                "provider_outputs": 0,
                "recurrence_row_actions": 0,
                "serializer_decodes": 10,
                "serializer_encodes": 20,
                "tail_checks": 0,
                "torch_calls": 0,
            },
            "source work ledger differs",
        )
        records = result["checkpoints"]
        _fail(len(records) == 10, "checkpoint denominator differs")
        raw_total = 0
        compact_total = 0
        for ordinal, record in enumerate(records):
            _fail(record["ordinal"] == ordinal, "checkpoint order differs")
            payload = archive.read(record["file"])
            _fail(len(payload) == record["compact_bytes"], "compact bytes differ")
            _fail(_sha256(payload) == record["compact_sha256"], "compact SHA differs")
            restored = _decode_independently(payload)
            original = inputs.read(record["source_file"])
            _fail(restored == original, "restored bytes differ from #6944 original")
            _fail(len(original) == record["raw_bytes"], "raw bytes differ")
            _fail(_sha256(original) == record["raw_sha256"], "raw SHA differs")
            _fail(record["restored_raw_sha256"] == record["raw_sha256"], "restore SHA differs")
            _fail(record["byte_exact"] is True, "byte exact flag differs")
            _validate_raw_identity(restored, record)
            raw_total += len(original)
            compact_total += len(payload)
        _fail(raw_total == result["raw_total_bytes"] == 62_877_713, "raw total differs")
        _fail(compact_total == result["compact_total_bytes"] == 17_078_476, "compact total differs")
        _fail(compact_total <= AGGREGATE_CAP_BYTES, "aggregate cap failed")
        _fail(
            result["aggregate_headroom_bytes"] == AGGREGATE_CAP_BYTES - compact_total,
            "aggregate headroom differs",
        )
        _fail(
            result["maximum_compact_cursor_bytes"]
            == max(record["compact_bytes"] for record in records)
            == 1_744_076,
            "maximum compact cursor differs",
        )
        _fail(result["cost"]["wall_seconds"] > 0.0, "wall cost is missing")
        _fail(result["cost"]["cpu_seconds"] > 0.0, "CPU cost is missing")
        _fail(result["cost"]["max_rss_kib"] > 0, "RSS cost is missing")
    journal = [json.loads(line) for line in journal_raw.splitlines()]
    _fail(len(journal) == 13, "journal event denominator differs")
    _fail(journal[0]["event"] == "admitted", "first journal event differs")
    _fail(journal[-1]["event"] == "complete", "terminal journal event differs")
    _fail(
        sum(record["event"] == "checkpoint_complete" for record in journal) == 10,
        "checkpoint journal denominator differs",
    )
    print(
        json.dumps(
            {
                "status": "PASS_INDEPENDENT_ZERO_RECURRENCE_READBACK",
                "artifact_sha256": ARTIFACT_SHA256,
                "checkpoints": 10,
                "independent_xz_decodes": 10,
                "restored_raw_bytes": 62_877_713,
                "compact_bytes": 17_078_476,
                "recurrence_row_actions": 0,
                "tail_checks": 0,
                "provider_outputs": 0,
                "torch_calls": 0,
                "optimizer_steps": 0,
                "n256_qualified": False,
                "all_closed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
