#!/usr/bin/env python3
"""Classify one inference.control qualification lane without manufacturing success.

The classifier consumes immutable command records emitted by hepta_ci_exec.py.
A real repository command failure is `source_failed`. Missing or malformed
evidence, or a lane that never reached a ready toolchain, is
`infrastructure_invalid`. Only a complete set of exact passing records is
`passed`. The classifier writes evidence but deliberately exits zero so an
always-run upload step can retain the diagnosis; a later gate must require the
`passed` classification.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
from typing import Any

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_LANES = {"source-head", "base-merge", "native-host"}
ALLOWED_RECORD_STATUS = {"running", "passed", "failed", "rejected", "interrupted"}
MAX_EXPECTED_RECORDS = 64


class DuplicateKey(ValueError):
    pass


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKey(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=strict_object
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_name(name: str) -> None:
    require(name == Path(name).name, f"non-canonical record name: {name}")
    require(name.endswith(".json") and len(name) <= 128, f"invalid record name: {name}")


def validate_setup(
    setup: Any,
    *,
    lane: str,
    source_sha: str,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not isinstance(setup, dict):
        return False, ["setup_not_object"]
    if setup.get("schema") != "hepta.inference-control-lane-setup.v1":
        reasons.append("setup_schema_invalid")
    if setup.get("lane") != lane:
        reasons.append("setup_lane_mismatch")
    if setup.get("sourceSha") != source_sha:
        reasons.append("setup_source_mismatch")
    if setup.get("checkoutBound") is not True:
        reasons.append("checkout_not_bound")
    if setup.get("toolchainReady") is not True:
        reasons.append("toolchain_not_ready")
    return not reasons, reasons


def validate_record(
    record: Any,
    *,
    lane: str,
    source_sha: str,
    tested_sha: str,
) -> tuple[bool, str]:
    if not isinstance(record, dict):
        return False, "record_not_object"
    if record.get("schema_version") != 1:
        return False, "record_schema_invalid"
    if record.get("lane") != lane:
        return False, "record_lane_mismatch"
    if record.get("source_sha") != source_sha:
        return False, "record_source_mismatch"
    if record.get("tested_sha") != tested_sha:
        return False, "record_tested_mismatch"
    status = record.get("status")
    if status not in ALLOWED_RECORD_STATUS:
        return False, "record_status_invalid"
    exit_code = record.get("exit_code")
    if type(exit_code) is not int:
        return False, "record_exit_code_invalid"
    if status == "passed" and exit_code == 0:
        return True, "passed"
    return True, "failed"


def classify(
    *,
    records_dir: Path,
    setup_marker: Path,
    output: Path,
    expected: list[str],
    lane: str,
    source_sha: str,
    tested_sha: str,
) -> dict[str, Any]:
    require(lane in ALLOWED_LANES, "invalid lane")
    require(SHA_PATTERN.fullmatch(source_sha) is not None, "invalid source SHA")
    require(SHA_PATTERN.fullmatch(tested_sha) is not None, "invalid tested SHA")
    require(expected and len(expected) <= MAX_EXPECTED_RECORDS, "invalid expected record count")
    require(len(expected) == len(set(expected)), "expected record names must be unique")
    for name in expected:
        validate_name(name)
    require(records_dir.is_absolute(), "records directory must be absolute")
    require(setup_marker.is_absolute(), "setup marker must be absolute")
    require(output.is_absolute(), "classification output must be absolute")
    require(output.parent == records_dir.parent / "evidence", "classification output must be in the lane evidence directory")

    setup_valid = False
    setup_reasons: list[str] = []
    try:
        setup = load_json(setup_marker)
        setup_valid, setup_reasons = validate_setup(
            setup, lane=lane, source_sha=source_sha
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        setup_reasons = ["setup_missing_or_malformed", str(exc)]

    passed: list[str] = []
    failed: list[dict[str, str]] = []
    missing: list[str] = []
    malformed: list[dict[str, str]] = []
    observed: list[str] = []
    for name in expected:
        path = records_dir / name
        if not path.is_file():
            missing.append(name)
            continue
        observed.append(name)
        try:
            record = load_json(path)
            valid, state = validate_record(
                record,
                lane=lane,
                source_sha=source_sha,
                tested_sha=tested_sha,
            )
            if not valid:
                malformed.append({"name": name, "reason": state})
            elif state == "passed":
                passed.append(name)
            else:
                failed.append(
                    {
                        "name": name,
                        "status": str(record.get("status")),
                        "exitCode": str(record.get("exit_code")),
                    }
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            malformed.append({"name": name, "reason": str(exc)})

    if not setup_valid:
        classification = "infrastructure_invalid"
        reason_codes = setup_reasons
    elif failed:
        classification = "source_failed"
        reason_codes = ["one_or_more_commands_failed"]
    elif missing or malformed:
        classification = "infrastructure_invalid"
        reason_codes = []
        if missing:
            reason_codes.append("expected_command_records_missing")
        if malformed:
            reason_codes.append("command_records_malformed")
    elif len(passed) == len(expected):
        classification = "passed"
        reason_codes = ["complete_exact_command_set_passed"]
    else:
        classification = "infrastructure_invalid"
        reason_codes = ["classification_incomplete"]

    result = {
        "schema": "hepta.inference-control-lane-classification.v1",
        "schemaVersion": 1,
        "module": "inference.control",
        "lane": lane,
        "sourceSha": source_sha,
        "testedSha": tested_sha,
        "classification": classification,
        "reasonCodes": reason_codes,
        "setupValid": setup_valid,
        "expectedRecords": expected,
        "observedRecords": observed,
        "passedRecords": passed,
        "failedRecords": failed,
        "missingRecords": missing,
        "malformedRecords": malformed,
        "classifiedAt": datetime.now(timezone.utc).isoformat(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as stream:
        pending = Path(stream.name)
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
    try:
        pending.replace(output)
    finally:
        pending.unlink(missing_ok=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-dir", type=Path, required=True)
    parser.add_argument("--setup-marker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", action="append", default=[])
    parser.add_argument("--lane", choices=sorted(ALLOWED_LANES), required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tested-sha", required=True)
    args = parser.parse_args()
    result = classify(
        records_dir=args.records_dir,
        setup_marker=args.setup_marker,
        output=args.output,
        expected=args.expected,
        lane=args.lane,
        source_sha=args.source_sha,
        tested_sha=args.tested_sha,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
