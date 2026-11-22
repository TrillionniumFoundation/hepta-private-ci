"""Independently inspect the immutable RED originals from Draft #6950."""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent
ORIGINALS = ROOT / "originals"


def _load_manifest():
    return json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))


def _read_zip(entry):
    path = ORIGINALS / entry["name"]
    raw = path.read_bytes()
    if len(raw) != entry["size"]:
        raise ValueError(f"{path.name}: size mismatch")
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"{path.name}: SHA-256 mismatch")
    archive = ZipFile(path)
    bad_member = archive.testzip()
    if bad_member is not None:
        raise ValueError(f"{path.name}: corrupt member {bad_member}")
    return archive


def _verify_lane(entry, execution_key):
    archive = _read_zip(entry)
    expected_name = f"lane-{entry['lane']:02d}/PROGRESS.jsonl"
    if archive.namelist() != [expected_name]:
        raise ValueError(f"lane {entry['lane']}: unexpected members")
    lines = archive.read(expected_name).decode("utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    events = [record["event"] for record in records]
    if len(records) != 38:
        raise ValueError(f"lane {entry['lane']}: record count")
    if events[:2] != ["admitted", "inputs_verified"]:
        raise ValueError(f"lane {entry['lane']}: admission events")
    if events[2:-1] != ["extension_progress"] * 35:
        raise ValueError(f"lane {entry['lane']}: progress events")
    if events[-1] != "index537_reached":
        raise ValueError(f"lane {entry['lane']}: terminal progress event")
    if records[0]["lane_ordinal"] != entry["lane"]:
        raise ValueError(f"lane {entry['lane']}: ordinal")
    indices = [record["included_index"] for record in records[2:-1]]
    expected_indices = list(range(264, 537, 8))
    if indices != expected_indices:
        raise ValueError(f"lane {entry['lane']}: progress indices")
    forbidden = {"tail_complete", "result_published", "checkpoint_published"}
    if forbidden.intersection(events):
        raise ValueError(f"lane {entry['lane']}: false completion event")
    return {
        "lane": entry["lane"],
        "records": len(records),
        "last_event": events[-1],
        "execution_key": execution_key,
    }


def _verify_collector(entry, manifest):
    archive = _read_zip(entry)
    if archive.namelist() != ["RESULT.json"]:
        raise ValueError("collector: unexpected members")
    result = json.loads(archive.read("RESULT.json"))
    if result["execution_key"] != manifest["execution_key"]:
        raise ValueError("collector: key mismatch")
    if result["status"] != "RED_INCOMPLETE_OR_CAP_EXCEEDED":
        raise ValueError("collector: status mismatch")
    if result["completed_lanes"] != 0:
        raise ValueError("collector: completed lane count")
    expected_failures = [f"lane {lane}: result count 0" for lane in range(10)]
    if result["failures"] != expected_failures:
        raise ValueError("collector: failure ledger")
    expected_zero_work = {
        "dynamic_steps": 0,
        "exponential_actions": 0,
        "index256_compact_decodes": 0,
        "index537_compact_decodes": 0,
        "index537_compact_encodes": 0,
        "optimizer_steps": 0,
        "provider_outputs": 0,
        "recurrence_row_actions": 0,
        "rounding_calls": 0,
        "tail_checks": 0,
        "torch_calls": 0,
    }
    if result["work"] != expected_zero_work:
        raise ValueError("collector: completed work ledger")
    scope = result["scope"]
    required_false = (
        "all_closed",
        "arbitrary_history_resume",
        "first_tail_check_complete",
        "n256_qualified",
        "production_adoption",
        "provider_completion",
        "tail_termination_closed",
    )
    if any(scope[name] for name in required_false):
        raise ValueError("collector: false scope claim")
    if scope["cause_of_6901_red"] != "UNKNOWN":
        raise ValueError("collector: historical UNKNOWN changed")
    if scope["predecessor_6939"] != "RED_DECIMAL_INTEGER_DIGIT_LIMIT":
        raise ValueError("collector: predecessor #6939 changed")
    if scope["predecessor_6942"] != "RED_TIMEOUT":
        raise ValueError("collector: predecessor #6942 changed")
    if scope["hpca_status"] != "NoUpdate":
        raise ValueError("collector: HPCA status changed")
    return result


def main():
    manifest = _load_manifest()
    if manifest["source_head"] != "bf5f5a8567af3faccf86792249fba33d99e498b9":
        raise ValueError("source head mismatch")
    if manifest["run_id"] != 45003362451:
        raise ValueError("run ID mismatch")
    lanes = [
        _verify_lane(entry, manifest["execution_key"])
        for entry in manifest["artifacts"]
    ]
    result = _verify_collector(manifest["collector"], manifest)
    review = {
        "collector_status": result["status"],
        "completed_lanes": result["completed_lanes"],
        "lane_journals": lanes,
        "new_numerical_work": {
            "recurrence_row_actions": 0,
            "rounding_calls": 0,
            "tail_checks": 0,
            "provider_outputs": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "review": "PASS",
    }
    print(json.dumps(review, sort_keys=True))


if __name__ == "__main__":
    main()
