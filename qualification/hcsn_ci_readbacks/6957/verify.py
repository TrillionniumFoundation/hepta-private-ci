"""Independent zero-model readback for PR #6957 hosted originals."""

import hashlib
import io
import json
import lzma
from pathlib import Path
import struct
import tarfile
import zipfile


HERE = Path(__file__).resolve().parent
ORIGINALS = HERE / "originals"
MANIFEST = json.loads((HERE / "MANIFEST.json").read_text())
PARTS = json.loads((HERE / "PARTS.json").read_text())
HEADER = struct.Struct(">8sQQ32s32s")
MAGIC = b"HCSNCPT1"
EXPECTED_IDENTITY = "hcsn-n256-authentic-tailcheck537-hexfix-20261122-c6bc-v1"
EXPECTED_KEY = "hcsn-n256-authentic-tailcheck537-hexfix-20261122-c6bc-001"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_original(record):
    raw = (ORIGINALS / record["file"]).read_bytes()
    if len(raw) != record["size"] or _sha256(raw) != record["sha256"]:
        raise SystemExit(f"original differs: {record['file']}")
    return raw


def _canonical(raw):
    value = json.loads(raw.decode("ascii"))
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if encoded != raw:
        raise SystemExit("JSON member is not canonical")
    return value


def _pretty(raw):
    value = json.loads(raw.decode("ascii"))
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii")
    if encoded != raw:
        raise SystemExit("pretty JSON member differs")
    return value


def _inspect_checkpoint(payload, result):
    if len(payload) != result["checkpoint_compact_bytes"]:
        raise SystemExit("checkpoint compact size differs")
    if _sha256(payload) != result["checkpoint_compact_sha256"]:
        raise SystemExit("checkpoint compact digest differs")
    magic, raw_size, compressed_size, raw_sha, compressed_sha = HEADER.unpack(
        payload[: HEADER.size]
    )
    compressed = payload[HEADER.size :]
    if (
        magic != MAGIC
        or compressed_size != len(compressed)
        or hashlib.sha256(compressed).digest() != compressed_sha
    ):
        raise SystemExit("checkpoint container header differs")
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    raw = decoder.decompress(compressed, max_length=33_554_433)
    if (
        not decoder.eof
        or decoder.unused_data
        or len(raw) != raw_size
        or len(raw) != result["checkpoint_raw_bytes"]
        or hashlib.sha256(raw).digest() != raw_sha
        or _sha256(raw) != result["checkpoint_raw_sha256"]
    ):
        raise SystemExit("checkpoint raw binding differs")
    envelope = _canonical(raw)
    body = envelope["body"]
    body_raw = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        envelope["body_sha256"] != _sha256(body_raw)
        or body["included_index"] != 537
        or body["lane"] != result["lane"]
        or body["schema"] != "hcsn-n256-authentic-index537-tail-checkpoint-v1"
        or len(body["iterate"]) != len(body["partial"])
        or len(body["iterate"]) != result["tail"]["coordinate_count"]
    ):
        raise SystemExit("checkpoint body binding differs")


def _inspect_lane(direct_raw, combined, ordinal):
    with zipfile.ZipFile(io.BytesIO(direct_raw)) as direct:
        if direct.testzip() is not None:
            raise SystemExit(f"lane {ordinal} CRC differs")
        prefix = f"lane-{ordinal:02d}/"
        names = direct.namelist()
        if not names or not all(name.startswith(prefix) for name in names):
            raise SystemExit(f"lane {ordinal} archive paths differ")
        flat = {
            name[len(prefix) :]: direct.read(name)
            for name in names
            if not name.endswith("/")
        }
    result = _pretty(flat["RESULT.json"])
    tail = _pretty(flat["TAIL.json"])
    expected_flat = {
        "PROGRESS.jsonl": f"lane-{ordinal:02d}.PROGRESS.jsonl",
        "RESULT.json": f"lane-{ordinal:02d}.RESULT.json",
        "TAIL.json": f"lane-{ordinal:02d}.TAIL.json",
        result["checkpoint_file"]: result["checkpoint_file"],
    }
    if set(flat) != set(expected_flat):
        raise SystemExit(f"lane {ordinal} member denominator differs")
    for source, target in expected_flat.items():
        if flat[source] != combined.read(target):
            raise SystemExit(f"lane {ordinal} combined copy differs: {source}")
    if (
        result["identity"] != EXPECTED_IDENTITY
        or result["execution_key"] != EXPECTED_KEY
        or result["lane_ordinal"] != ordinal
        or result["status"] != "AUTHENTIC_INDEX537_FIRST_TAIL_CHECK_COMPLETE_HOLD"
        or _sha256(flat["TAIL.json"]) != result["tail_sha256"]
    ):
        raise SystemExit(f"lane {ordinal} result identity differs")
    rows = tail["rounding"]
    rows_raw = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if (
        len(rows) != tail["coordinate_count"]
        or len(rows) != result["tail"]["coordinate_count"]
        or tail["unique_coordinate_count"] != 0
        or tail["all_coordinates_unique"]
        or _sha256(rows_raw) != tail["rounding_sha256"]
        or tail["rounding_sha256"] != result["tail"]["rounding_sha256"]
        or any(row["unique"] or row["lower_hex"] == row["upper_hex"] for row in rows)
    ):
        raise SystemExit(f"lane {ordinal} non-unique tail record differs")
    progress = [
        json.loads(line) for line in flat["PROGRESS.jsonl"].decode().splitlines()
    ]
    events = [record["event"] for record in progress]
    expected_events = (
        ["admitted", "inputs_verified"]
        + ["extension_progress"] * 35
        + ["index537_reached", "tail_checked", "lane_complete"]
    )
    progress_indices = [
        record["included_index"]
        for record in progress
        if record["event"] == "extension_progress"
    ]
    if events != expected_events or progress_indices != list(range(264, 537, 8)):
        raise SystemExit(f"lane {ordinal} progress differs")
    _inspect_checkpoint(flat[result["checkpoint_file"]], result)
    return result


def main():
    expected_files = {item["file"] for item in PARTS}
    actual_files = {path.name for path in ORIGINALS.iterdir() if path.is_file()}
    if actual_files != expected_files:
        raise SystemExit("original file denominator differs")
    bundle = b"".join(_read_original(item) for item in PARTS)
    if (
        len(bundle) != MANIFEST["bundle"]["size"]
        or _sha256(bundle) != MANIFEST["bundle"]["sha256"]
    ):
        raise SystemExit("restored original bundle differs")
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:") as archive:
        expected_members = {MANIFEST["collector"]["file"]}
        expected_members.update(item["file"] for item in MANIFEST["lanes"])
        if set(archive.getnames()) != expected_members:
            raise SystemExit("bundle member denominator differs")
        archived = {
            name: archive.extractfile(name).read() for name in expected_members
        }
    collector = MANIFEST["collector"]
    collector_raw = archived[collector["file"]]
    if (
        len(collector_raw) != collector["size"]
        or _sha256(collector_raw) != collector["sha256"]
    ):
        raise SystemExit("collector artifact differs")
    with zipfile.ZipFile(io.BytesIO(collector_raw)) as combined:
        if combined.testzip() is not None or len(combined.namelist()) != 41:
            raise SystemExit("combined ZIP member or CRC denominator differs")
        results = [
            _inspect_lane(archived[record["file"]], combined, record["lane"])
            for record in MANIFEST["lanes"]
        ]
        final = _pretty(combined.read("RESULT.json"))
    work_names = (
        "index256_compact_decodes",
        "recurrence_row_actions",
        "tail_checks",
        "rounding_calls",
        "index537_compact_encodes",
        "index537_compact_decodes",
    )
    reaggregated_work = {
        name: sum(result["work"][name] for result in results) for name in work_names
    }
    reaggregated_work.update(
        provider_outputs=0,
        dynamic_steps=0,
        exponential_actions=0,
        torch_calls=0,
        optimizer_steps=0,
    )
    if (
        final["identity"] != EXPECTED_IDENTITY
        or final["execution_key"] != EXPECTED_KEY
        or final["status"] != "AUTHENTIC_INDEX537_FIRST_TAIL_CHECK_COMPLETE_HOLD"
        or final["completed_lanes"] != 10
        or final["failures"]
        or final["work"] != reaggregated_work
        or final["total_coordinates"] != sum(
            result["tail"]["coordinate_count"] for result in results
        )
        or final["total_coordinates"] != 2585
        or final["total_unique_coordinates"] != 0
        or final["all_coordinates_unique_lanes"] != 0
        or final["nonunique_lanes"] != 10
        or final["compact_checkpoint_bytes"] != sum(
            result["checkpoint_compact_bytes"] for result in results
        )
        or final["cost"]["summed_wall_seconds"] != sum(
            result["cost"]["wall_seconds"] for result in results
        )
        or final["cost"]["summed_cpu_seconds"] != sum(
            result["cost"]["cpu_seconds"] for result in results
        )
        or final["cost"]["maximum_rss_kib"] != max(
            result["cost"]["max_rss_kib"] for result in results
        )
        or not final["scope"]["first_tail_check_complete"]
        or final["scope"]["tail_termination_closed"]
        or final["scope"]["n256_qualified"]
        or final["scope"]["production_adoption"]
        or final["scope"]["all_closed"]
    ):
        raise SystemExit("collector aggregation or scope differs")
    print("PASS_6957_EXACT_11_ARTIFACT_READBACK")
    print("PASS_6957_10_LANES_2585_NONUNIQUE_COORDINATES")
    print("PASS_6957_ZERO_MODEL_ZERO_NUMERICAL_REPLAY")


if __name__ == "__main__":
    main()
