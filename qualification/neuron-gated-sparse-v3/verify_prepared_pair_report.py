#!/usr/bin/env python3
"""Independent structural replay of every prepared Q24 A/B report metric.

A valid report is internally self-consistent. Neither locally generated
hashes nor matched binaries authenticate target-host execution or NDU utility.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from run_prepared_pair import (
    ARMS, MODES, SCALES, SCHEMA, reject_nonfinite_number, require,
    sha256_binary, unique_json_keys, validate_pair,
)

MAX_REPORT_BYTES = 4 * 1024 * 1024
HEX = frozenset("0123456789abcdef")
ROOT_FIELDS = {
    "schema", "evidence_kind", "source_trace_sha256",
    "source_binary_sha256_claim", "source_binary_independently_attested",
    "arms", "scales", "pair_count", "native_subprocess_count",
    "hosted_ci_run_id_claim", "pairs", "private_model_parameter_budgets_matched",
    "real_training_or_model_efficacy", "real_encoder_model_batch_queue_wal_cas_cost",
    "target_host_certified", "ndu_eligible", "production_qualification",
    "decision", "limitations",
}


def lowercase_digest(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(symbol in HEX for symbol in value)
        and value != "0" * 64
    )


def load_report(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    require(0 < size <= MAX_REPORT_BYTES, "unbounded paired report")
    try:
        payload = json.loads(
            path.read_bytes(),
            object_pairs_hook=unique_json_keys,
            parse_constant=reject_nonfinite_number,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("invalid paired report JSON") from exc
    require(isinstance(payload, dict), "paired report must be a JSON object")
    return payload


def audit(
    report: Any, *, binary: Path | None = None,
) -> dict[str, Any]:
    require(isinstance(report, dict) and set(report) == ROOT_FIELDS,
            "missing or unregistered paired root field")
    require(report["schema"] == SCHEMA, "unregistered paired schema")
    require(report["evidence_kind"] == "UNVERIFIED_HOST_UNTRAINED_KERNEL_ONLY",
            "paired report impersonates host evidence")
    require(report["arms"] == list(ARMS) and report["scales"] == list(SCALES),
            "missing or reordered five-arm four-scale preregistration")
    for key in (
        "source_binary_independently_attested",
        "private_model_parameter_budgets_matched",
        "real_training_or_model_efficacy",
        "real_encoder_model_batch_queue_wal_cas_cost",
        "target_host_certified",
        "ndu_eligible",
        "production_qualification",
    ):
        require(report[key] is False, f"{key}: fixture cannot assert production evidence")
    require(report["decision"] == "NO_PROMOTION", "unauthorized model selection claim")
    require(isinstance(report["hosted_ci_run_id_claim"], str),
            "invalid CI run identity claim")
    require(isinstance(report["limitations"], list)
            and len(report["limitations"]) >= 3
            and all(isinstance(item, str) and item for item in report["limitations"]),
            "missing fixture limitations")
    require(lowercase_digest(report["source_binary_sha256_claim"])
            and lowercase_digest(report["source_trace_sha256"]),
            "missing executable or trace digest")
    require(type(report["pair_count"]) is int and report["pair_count"] == 20,
            "incomplete A/B arm-scale matrix")
    require(type(report["native_subprocess_count"]) is int
            and report["native_subprocess_count"] == 40,
            "incomplete physical process count")
    pairs = report["pairs"]
    require(isinstance(pairs, list) and len(pairs) == 20,
            "require 20 complete raw A/B pairs")
    seen: set[tuple[str, int]] = set()
    events = None
    for row in pairs:
        require(isinstance(row, dict), "paired entry is not an object")
        arm, cells = row.get("arm"), row.get("cells")
        require(arm in ARMS and type(cells) is int and cells in SCALES,
                "unregistered paired arm or Cell scale")
        key = arm, cells
        require(key not in seen, "duplicate A/B arm-scale receipt pair")
        seen.add(key)
        current_events = row.get("events")
        require(type(current_events) is int and 1 <= current_events <= 1024,
                "invalid Q24 event count")
        if events is None:
            events = current_events
        require(events == current_events, "A/B pairs have unequal event counts")
        records = row.get("raw_mode_receipts")
        require(isinstance(records, dict) and set(records) == set(MODES),
                "missing one original mode receipt")
        derived = validate_pair(
            records, arm, cells, report["source_trace_sha256"], current_events
        )
        require(row == derived,
                "paired summary, frontier, local receipt hashes or ratios are not reproducible")
    require(len(seen) == len(ARMS) * len(SCALES), "missing arm-scale combination")
    if binary is not None:
        require(binary.is_file(), "missing supplied replay executable")
        require(sha256_binary(binary) == report["source_binary_sha256_claim"],
                "physical executable SHA does not match paired observations")
    return {
        "schema": "hepta.neuron.prepared-paired-structural-audit.v1",
        "structural_integrity": "SELF_CONSISTENT_UNVERIFIED_FIXTURE_ONLY",
        "source_trace_sha256": report["source_trace_sha256"],
        "source_binary_sha256_claim": report["source_binary_sha256_claim"],
        "binary_bytes_checked_against_report": binary is not None,
        "independently_authenticated_host": False,
        "real_model_trained_or_deployed": False,
        "original_raw_mode_receipts_recomputed": 40,
        "exact_checkpoint_frontier_pairs_rechecked": 20,
        "ndu_eligible": False,
        "production_qualification": False,
        "decision": "NO_PROMOTION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    try:
        result = audit(load_report(args.report), binary=args.binary)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED_PREPARED_REPLAY_AUDIT", "error": str(exc)}),
              file=sys.stderr)
        return 2
    output = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.audit:
        args.audit.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
