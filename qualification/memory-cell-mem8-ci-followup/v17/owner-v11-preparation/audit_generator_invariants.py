#!/usr/bin/env python3
"""Offline controls for exact original JSON-span preservation; no ledger render."""
import argparse
import json
from pathlib import Path

from prepare_owner_v11 import BASE_IDENTITY, decode, identity, invariant_audit, render_values, require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    raw = args.baseline.read_bytes()
    require(identity(raw) == BASE_IDENTITY, "baseline mismatch")
    base = decode(raw)
    hi = next(i for i, r in enumerate(base["open"]) if r["id"] == "HOSTED-CI")
    common = {("checkpoint_revision",): 11, ("open", hi, "finding"): "OFFLINE IN-MEMORY DESCRIPTION CONTROL"}
    additions = {"source_ci_followup_v9_v11": {}, "v11_update_provenance": {}}
    good = render_values(raw, common, additions)
    audit = invariant_audit(raw, good)
    controls = [{"control": "allowed_local_description_preserves_original_value_spans", "passed": True,
                 "protected_span_count": len(audit["protected_original_value_spans"])}]
    cases = {
        "non_CI_gate_change_rejected": (("open", 0, "status"), "CLOSED"),
        "old_closed_entry_change_rejected": (("closed_this_followup", 0, "status"), "CHANGED"),
        "HOSTED_CI_closure_change_rejected": (("open", hi, "closure"), "RELAXED"),
        "physical_provider_count_change_rejected": (("physical_provider_requests",), 0),
        "scientific_acceptance_change_rejected": (("scientific_acceptance",), "PASS"),
        "non_CI_intake_change_rejected": (("actionable_remaining_inputs", "gates", 0, "next_step"), "CHANGED"),
    }
    for label, (path, value) in cases.items():
        rejected = False
        reason = None
        try:
            invariant_audit(raw, render_values(raw, {**common, path: value}, additions))
        except ValueError as exc:
            rejected, reason = True, str(exc)
        require(rejected, "control failed to reject: " + label)
        controls.append({"control": label, "passed": rejected, "rejection": reason})
    try:
        decode(b'{"same":1,"same":2}')
    except ValueError:
        controls.append({"control": "duplicate_JSON_key_rejected", "passed": True})
    else:
        raise ValueError("duplicate-key control did not reject")
    out = {"schema": "mem8.owner-v11.generator-offline-controls.v1", "status": "PASS",
           "baseline": identity(raw), "controls": controls, "control_count": len(controls),
           "test_fixture_only_in_memory": True, "candidate_ledger_written": False,
           "native_or_model_execution": 0, "Git_or_ref_writes": 0}
    encoded = (json.dumps(out, indent=2) + "\n").encode()
    with args.output.open("xb") as f:
        f.write(encoded)
    print(json.dumps({"output": str(args.output), **identity(encoded), "controls_passed": len(controls)}, indent=2))


if __name__ == "__main__":
    main()
