"""Retain and explain a driver identity race without rewriting scientific output."""

import difflib
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    here = Path(__file__).parent
    original = here/"CONFIRMATION_RECONSTRUCTION.json"
    report = json.loads(original.read_text())
    start = here/"CONFIRMATION_RECONSTRUCTION_source/independent_audit.py"
    end = here/"CONFIRMATION_IDENTITY_NOTICE_source/driver_end_of_confirmation.py"
    assert sha(start) == report["audit_sources_snapshot"]["independent_audit.py"]
    assert sha(end) == report["audit_source_sha256"]
    assert sha(start) != sha(end)
    changed = list(difflib.unified_diff(start.read_text().splitlines(), end.read_text().splitlines(),
        fromfile="start_snapshot", tofile="end_disk", lineterm=""))
    expected_end = start.read_text().replace('"constant", "confirmation"))',
        '"constant", "confirmation", "ci"))').replace(
        '    else:\n        result = risk(args.input)',
        '    elif args.study == "ci":\n        from .ci_reconstruction import audit\n        result = audit(args.input)\n    else:\n        result = risk(args.input)')
    assert expected_end == end.read_text()
    for name in ("confirmation_reconstruction.py", "renewal_reconstruction.py"):
        assert sha(here/name) == sha(here/"CONFIRMATION_RECONSTRUCTION_source"/name)
    result = {"schema": "hcsn-v10-review-driver-identity-notice.v1",
        "original_report_sha256": sha(original), "original_report_preserved": True,
        "original_end_of_run_audit_source_sha256": sha(end),
        "start_snapshot_driver_sha256": sha(start), "driver_diff": changed,
        "cause": "Reviewer added the unrelated CI dispatcher mode while confirmation audit ran; old driver read its own changed disk source at report serialization",
        "affected_field": "audit_source_sha256 reports end-of-run disk bytes; audit_sources_snapshot retains start snapshot bytes",
        "interpretation": "Use retained start snapshot for the driver source associated with this audit; do not assert the two identities agree",
        "confirmation_and_replay_checker_sources_unchanged": True,
        "scientific_model_data_statistics_unchanged": True,
        "numerical_result_recomputed_by_this_notice": False,
        "future_fix": "Driver now records its start snapshot digest instead of re-reading disk at completion",
        "notice_source_sha256": sha(Path(__file__))}
    output = here/"CONFIRMATION_IDENTITY_NOTICE.json"
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
