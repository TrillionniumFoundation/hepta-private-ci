"""Receipt-stable entrypoint for the fixed cosine-residual study.

GitHub run and artifact JSON contain mutable fields such as timestamps and
artifact-list state. A completed upstream study saved the metadata digest
observed at that time; a later query of the SAME immutable run/source/artifact
can therefore have a different metadata digest. This wrapper requires the exact
fixed run, source, artifact ID, artifact ZIP SHA and attempt, while retaining
both well-formed observation digests. It then delegates every scientific check
and all model execution to the original frozen implementation.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import five_causal_experiments as c
import shared_gate_cosine_residual as residual
import shared_gate_cosine_residual_trial as legacy

_ORIGINAL_VALIDATE_SIMILARITY = legacy.validate_similarity


def bind_saved_similarity_origins(saved, current):
    """Bind immutable origin identity, not equality of two observation times."""
    roles = ("heads", "crossed")
    c.require(isinstance(saved, dict) and isinstance(current, dict)
              and set(saved) == set(roles) and set(current) >= set(roles),
              "complete saved/current similarity origins required")
    for role in roles:
        expected = residual.ORIGINS[role]
        old, now = saved[role], current[role]
        for record in (old, now):
            c.require(isinstance(record, dict)
                      and all(record.get(key) == value for key, value in expected.items())
                      and record.get("ready") is True
                      and record.get("observed_status") == "completed"
                      and record.get("observed_conclusion") == "success"
                      and type(record.get("run_attempt")) is int
                      and record["run_attempt"] >= 1
                      and type(record.get("artifact_id")) is int
                      and record["artifact_id"] > 0
                      and c.sha(record.get("artifact_sha256"))
                      and c.sha(record.get("metadata_sha256")),
                      "invalid fixed similarity origin receipt")
        c.require(old["run_attempt"] == now["run_attempt"]
                  and old["artifact_id"] == now["artifact_id"]
                  and old["artifact_sha256"] == now["artifact_sha256"],
                  "saved similarity bytes differ from current fixed origin")
    return {role: {"saved_metadata_sha256": saved[role]["metadata_sha256"],
                   "current_metadata_sha256": current[role]["metadata_sha256"],
                   "same_observation_digest": saved[role]["metadata_sha256"] == current[role]["metadata_sha256"],
                   "artifact_id": saved[role]["artifact_id"],
                   "artifact_sha256": saved[role]["artifact_sha256"]}
            for role in roles}


def validate_similarity(root, dependency_receipt, select_inputs):
    """Verify immutable bytes, then reuse the original complete validator."""
    root = Path(root)
    plan = c.load(root / "study" / "plan.json")
    c.require(isinstance(dependency_receipt, dict)
              and isinstance(dependency_receipt.get("origins"), dict),
              "current residual dependency receipt missing")
    saved = plan.get("origins")
    current = dependency_receipt["origins"]
    bind_saved_similarity_origins(saved, current)
    patched = deepcopy(dependency_receipt)
    # The legacy validator checks exact equality to the receipt stored by the
    # similarity analysis. After proving that the current query names the same
    # immutable bytes, supply that historical receipt verbatim. The returned
    # threshold object remains byte-for-byte the saved threshold receipt.
    for role in ("heads", "crossed"):
        patched["origins"][role] = deepcopy(saved[role])
    return _ORIGINAL_VALIDATE_SIMILARITY(root, patched, select_inputs)


legacy.validate_similarity = validate_similarity


def main():
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
