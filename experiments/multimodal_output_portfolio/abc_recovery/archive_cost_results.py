"""Archive completed cost aggregates without changing experimental inputs.

The gzip retains the original report bytes. Repeated bootstrap dictionaries are
omitted only from the readable summary; the complete report is authoritative.
No raw media, model checkpoint, or episode row is copied into the Git archive.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


EXPECTED_REPORT_SHA256 = "4c496bffdabf04e90ad717cb4964a340f2c4eef54291077f3e374712667874c6"


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def read_json(path):
    payload = path.read_bytes()
    return {"sha256": sha256(payload), "size_bytes": len(payload),
            "relative_path": str(path), "data": json.loads(payload)}


def write_new(path, payload):
    with path.open("xb") as stream:
        stream.write(payload)


def dump_new(path, data):
    write_new(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())


def compact(value):
    if isinstance(value, dict):
        return {key: compact(child) for key, child in value.items()
                if key not in {"bootstrap", "counts"}}
    if isinstance(value, list):
        return [compact(child) for child in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = (args.runs / "cost-analysis-001/report.json").read_bytes()
    if sha256(payload) != EXPECTED_REPORT_SHA256:
        raise ValueError("The frozen complete report identity does not match")
    report = json.loads(payload)
    receipts = {}
    for name in ("timing-registered-three-001", "timing-supplementary-all-001", "cost-analysis-001"):
        receipts[name] = {}
        for filename in ("registration.json", "result.json", "whole-process-cost.json", "resident-load-cost.json"):
            path = args.runs / name / filename
            if path.exists():
                row = read_json(path)
                row["relative_path"] = f"{name}/{filename}"
                receipts[name][filename] = row
        if receipts[name]["result.json"]["data"]["status"] != "completed":
            raise ValueError(f"Incomplete producer: {name}")
        if receipts[name]["whole-process-cost.json"]["data"]["exit_code"] != 0:
            raise ValueError(f"Unsuccessful process: {name}")
    args.output.mkdir(parents=True, exist_ok=True)
    packed = gzip.compress(payload, compresslevel=9, mtime=0)
    if gzip.decompress(packed) != payload:
        raise ValueError("Compressed report round-trip changed bytes")
    names = ("cost-analysis-report.json.gz", "execution-receipts.json", "summary.json")
    if any((args.output / name).exists() for name in names):
        raise FileExistsError("Aggregate archive already exists; no overwrite")
    provenance = {"report_sha256": EXPECTED_REPORT_SHA256,
                  "report_size_bytes": len(payload), "gzip_sha256": sha256(packed),
                  "gzip_size_bytes": len(packed),
                  "archive_script_sha256": sha256(Path(__file__).read_bytes())}
    write_new(args.output / names[0], packed)
    sequence = read_json(args.runs / "timing-sequence-start-001.json")
    sequence["relative_path"] = "timing-sequence-start-001.json"
    dump_new(args.output / names[1], {
        "schema": "hepta.abc.cost-aggregate-receipts.v1", "provenance": provenance,
        "separate_timing_profiles_not_pooled": True,
        "timing_sequence_registration": sequence, "producers": receipts,
        "raw_evidence_included": False,
        "scope": "Exact parsed aggregate receipts plus losslessly archived report; no raw media, model weights, or episode logs"})
    summary = {key: report[key] for key in (
        "schema", "census", "bootstrap", "input_sha256", "source_sha256", "environment",
        "method_amendment_sha256", "all_prices_descriptive_and_uncalibrated",
        "main128_source_quality_CIs_are_separate", "prior_three_view_timings_not_pooled",
        "primary_success_inferred_from_grid", "production_approved", "all_blockers_closed")}
    summary.update({"schema": "hepta.abc.cost-readable-summary.v1", "provenance": provenance,
                    "summary_omissions": "Repeated per-metric bootstrap/count dictionaries only; complete report retains every field",
                    "counts_per_condition": {"quality_round0_rows": 640, "all_round_cost_rows": 1280,
                                             "priced_rows": 1280, "independent_sources": 8,
                                             "crossed_training_seeds": 5},
                    "conditions": compact(report["conditions"]),
                    "comparisons": compact(report["comparisons"])})
    dump_new(args.output / names[2], summary)
    print(json.dumps({"status": "complete", "provenance": provenance,
                      "files": {name: {"sha256": sha256((args.output / name).read_bytes()),
                                       "size_bytes": (args.output / name).stat().st_size}
                                for name in names}}, sort_keys=True))


if __name__ == "__main__":
    main()
