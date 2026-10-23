"""Verify source-custody and exact decoded-output witness replay (research)."""
import hashlib
import json
from pathlib import Path

from independent_observer import rerun_and_audit

ROOT = Path(__file__).resolve().parent


def verify_independent():
    lock = json.loads((ROOT / "AUDIT_LOCK.json").read_text())
    for name, expected in lock["source_sha256"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"forged independent observer source: {name}")
    orig = json.loads((ROOT / "development-report.json").read_text())
    expected = json.loads((ROOT / "independent-review.json").read_text())
    actual = rerun_and_audit(orig)
    if actual != expected:
        raise ValueError("independent decoded-output ledger or score mismatch")
    if (actual["generated_output_rows"] != 6144
        or actual["source_groups"] != 1536
        or actual["real_pretrained_generation"]
        or actual["external_signature"]
        or actual["production_authority"]):
        raise ValueError("false result or incomplete generated-output census")
    return {"scope":"DEVELOPMENT_ONLY_DENY_ALL",
            "verified_raw_output_rows":actual["generated_output_rows"],
            "source_groups":actual["source_groups"],
            "independent_observer_source_files":len(lock["source_sha256"]),
            "ledger_sha256":actual["raw_output_ledger_sha256"],
            "independent_external_authority":False,
            "natural_generator":False}

if __name__ == "__main__":
    print(json.dumps(verify_independent(), sort_keys=True, indent=2))
