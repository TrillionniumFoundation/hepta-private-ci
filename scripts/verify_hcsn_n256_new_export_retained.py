"""Verify retained N256 export bytes only; never import or run the mapper."""

import base64
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    base = root / "qualification/hcsn_n256_new_export"
    evidence = base / "evidence/attempt001"
    publication = json.loads((base / "PUBLICATION.json").read_text())
    actual = {
        name: sha(base / name) for name in publication["retained_evidence_sha256"]
    }
    assert actual == publication["retained_evidence_sha256"]
    encoded = (evidence / "N256_STATE.npz.b64").read_text()
    assert encoded == encoded.rstrip("\n") + "\n"
    decoded = base64.b64decode(encoded.rstrip("\n"), validate=True)
    assert len(decoded) == publication["decoded_N256_STATE_npz"]["bytes"]
    assert (
        hashlib.sha256(decoded).hexdigest()
        == publication["decoded_N256_STATE_npz"]["sha256"]
    )
    metadata = json.loads((evidence / "METADATA.json").read_text())
    costs = json.loads((evidence / "COSTS.json").read_text())
    audit = json.loads((evidence / "AUDIT.json").read_text())
    assert (
        metadata["identity"]
        == costs["identity"]
        == audit["identity"]
        == publication["identity"]
    )
    assert metadata["historical_N256_export_present"] is False
    assert metadata["new_export"] is True
    assert metadata["largegrid_qualification"] is False
    assert metadata["global_HOLD"] is True and metadata["all_closed"] is False
    assert audit["coordinate_byte_comparisons"] == 1542
    assert audit["phase_packets_checked"] == audit["phase_supports_checked"] == 8
    assert audit["exact_probability_total_equal"] is True
    assert audit["exact_signed_content_totals_equal"] == [True] * 4
    assert audit["audit_candidate_imports"] == 0
    forbidden = (
        "DDE_solves",
        "model_calls",
        "matrix_exponentials",
        "spatial_matrix_constructions",
        "discounted_hit_solves",
        "backward_calls",
        "optimizer_steps",
        "training_steps",
    )
    assert all(costs[name] == 0 for name in forbidden)
    freeze = json.loads((base / "FREEZE.json").read_text())
    audit_freeze = json.loads((base / "AUDIT_FREEZE.json").read_text())
    assert freeze["export_invocations_before_freeze_commit"] == 0
    assert audit_freeze["audit_invocations_before_freeze_commit"] == 0
    assert audit_freeze["unexecuted_v1_audit_source"]["invocations"] == 0
    assert publication["historical_N256_export_present"] is False
    assert publication["new_export_only"] is True
    assert publication["largegrid_qualification"] is False
    assert publication["global_HOLD"] is True and publication["all_closed"] is False
    print(
        json.dumps(
            {
                "retained_files": len(actual),
                "decoded_npz_bytes": len(decoded),
                "coordinate_byte_comparisons": 1542,
                "exact_conservation_identities": 5,
                "phase_packets": 8,
                "new_export_only": True,
                "dynamic_calls": 0,
                "largegrid_qualification": False,
                "global_HOLD": True,
                "all_closed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
