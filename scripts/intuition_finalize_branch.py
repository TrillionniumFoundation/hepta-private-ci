#!/usr/bin/env python3
"""Read-only source inventory under the historical finalizer command name.

The former migration has been retired: the canonical serving hook, module
registration, bounded replay and V3 benchmark are actual committed source.
This command NEVER edits files, formats source, commits, pushes or emits approval.
Marker presence is deliberately not described as compilation or product execution.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECKS = {
    "codex-rs/hepta-agentd/src/lib.rs": [
        "mod intuition_policy_serving;",
        "pub use intelligence_ingress::AgentdIntuitionProductInvocationV1;",
    ],
    "codex-rs/hepta-agentd/src/state.rs": [
        "pub(crate) async fn start_canonical_intelligence(",
        "crate::intuition_policy_serving::authenticate_canonical_intuition(",
        "let policy_now = self.require_current_run_start(record)?;",
    ],
    "codex-rs/hepta-agentd/src/intuition_policy.rs": [
        "pub struct AgentdIntuitionPolicyPinsV2",
        "pub fn prepare_v3(",
        "pub fn commit_v4(",
        "qualification: OwnedIntuitionQualificationEvidenceV2",
        "mod final_use;",
    ],
    "codex-rs/hepta-agentd/src/intuition_policy_final_use.rs": [
        "if current_binding != prepared.host_binding_digest",
        "validate_prepared_time(prepared.prepared_at, prepared.qualification_expires_at, now)?;",
        "fn preserve_known_commit<T, E>",
        "let mut writer = self",
        "let now = self.clock.now()?;",
        ".revalidate_trust(now)",
        "prepared.qualification.as_borrowed()",
    ],
    "codex-rs/hepta-agentd/src/intuition_policy_service.rs": [
        "retain_committed_receipt(self.automation_admission_ready(), receipt)",
        "GenerationChangedAfterCommit",
    ],
    "codex-rs/hepta-agentd/src/intuition_policy_serving.rs": [
        "pub(crate) fn authenticate_canonical_intuition(",
        ".commit_intuition_policy_v4(",
        ".map_err(AgentdError::from)?",
    ],
    "codex-rs/hepta-agentd/src/error.rs": [
        "IntuitionPolicy(Box<crate::AgentdIntuitionServiceErrorV1>)",
    ],
    "codex-rs/hepta-intuition/src/production.rs": [
        "pub fn decide_calibrated_v4(",
        "pub fn canonical_candidate_identity_digest_v2(",
        "pub fn canonical_scored_outputs_digest_v2(",
        "pub fn canonical_assignment_distribution_digest_v2(",
    ],
    "codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs": [
        "decide_authenticated_intuition_v3(",
        "ScoringCommitmentV2",
        "AssignmentCommitmentV2",
        "authenticated-v3,",
    ],
    "codex-rs/hepta-agentd/tests/intuition_policy_commit_boundary.rs": [
        "prepared_decision_rejects_every_changed_host_pin_before_writing",
        "PreparedEvidenceExpired",
        "PreparedClockReversed",
        "writer_wait_samples_fresh_clock_and_expires_before_any_ledger_mutation",
        "final_use_revalidates_scheduled_signer_revocation_and_distribution_expiry",
    ],
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    rows = []
    failures = []
    for relative, markers in CHECKS.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append({"path": relative, "reason": "missing_file"})
            continue
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            failures.append({"path": relative, "missingMarkers": missing})
        rows.append(
            {
                "path": relative,
                "gitBlob": hashlib.sha1(
                    b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
                ).hexdigest(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "sourceMarkersPresent": not missing,
            }
        )
    dirty = git("status", "--porcelain", "--untracked-files=no")
    # A caller may invoke this during an explicitly separate formatting task.
    # The exact qualifier, not this inventory, enforces a clean tested tree.
    record = {
        "schema": "hepta.intuition.source-inventory.v1",
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "trackedWorktreeClean": not dirty,
        "files": rows,
        "failures": failures,
        "compilation": "not_evaluated",
        "productExecution": "not_evaluated",
        "independentAcceptance": "not_established",
        "operatorAcceptance": "not_established",
        "promotion": "not_authorized",
    }
    print(json.dumps(record, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
