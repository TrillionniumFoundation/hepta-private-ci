"""Audit one completed calibration stratum without qualifying the whole study."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

from .independent_v2_calibration_check import cp_upper, owner_check

ROOT = Path(__file__).parent


def main():
    start = time.process_time()
    parser = argparse.ArgumentParser()
    parser.add_argument("stratum", choices=("calibrate", "calibrate_reverse", "calibrate_lag2"))
    args = parser.parse_args()
    spec = json.loads((ROOT / "protocol_v2.json").read_text())
    directory = ROOT / "calibration_v2_01" / args.stratum
    manifests = json.loads((directory / "ARCHIVES.json").read_text())
    declared = json.loads((directory / "COUNTS.json").read_text())
    counters = {name:dict(accepted=0, errors=0, fractional=0, fractional_errors=0, invalid=0,
        payoff_sum=0., before_brier_sum=0., actual_reads=0) for name in spec["models"]}
    worlds, records, archive_checks = 0, 0, 0
    for item in manifests:
        path = ROOT / item["path"]
        assert path.resolve().is_relative_to(directory.resolve())
        compressed = path.read_bytes()
        raw = gzip.decompress(compressed)
        assert hashlib.sha256(compressed).hexdigest() == item["sha256"]
        assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
        rows = json.loads(raw)
        assert len(rows) == item["records"]
        archive_checks += 1
        for row in rows:
            assert row["stratum"] == args.stratum and row["generator"] == worlds
            assert row["phase"] == "r20_calibration_power_v2"
            worlds += 1
            for name, count in counters.items():
                assert list(row["predictions"][name]) == [str(spec["threshold"])]
                value = row["predictions"][name][str(spec["threshold"])]
                owner_check(row, value, spec["threshold"])
                records += 1
                count["invalid"] += value["invalid"]
                if not value["invalid"]:
                    a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
                    for key, amount in (("accepted", a), ("errors", a and e), ("fractional", f), ("fractional_errors", f and e)):
                        count[key] += amount
                    count["payoff_sum"] += value["payoff"]
                    count["before_brier_sum"] += value["before_brier"]
                    count["actual_reads"] += value["read_index"] is not None
    assert worlds == spec["calibration_strata"][args.stratum]
    delta = spec["family_error_probability"] / (len(spec["models"]) * len(spec["calibration_strata"]) * 2)
    for name, count in counters.items():
        assert all(abs(count[key] - expected) < 2e-10 for key, expected in declared[name].items())
        count["independent_upper_error"] = cp_upper(count["errors"], count["accepted"], delta)
        count["independent_upper_fractional_error"] = cp_upper(count["fractional_errors"], count["fractional"], delta)
    print(json.dumps(dict(passed=True, completed_stratum=args.stratum, worlds=worlds, owner_prediction_records=records,
        checked_archives=archive_checks, independent_bounds=6, simultaneous_delta=delta, counts=counters,
        whole_calibration_qualified=None, final_all_strata_audit_executed=False,
        scope="Completedstratum only; fixedsample retained; no optionalstopping or newmodel/threshold/sampledecision",
        process_cpu_seconds=time.process_time() - start), sort_keys=True))


if __name__ == "__main__":
    main()
