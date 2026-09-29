#!/usr/bin/env python3
"""Apply intuition.policy final-use hardening to the fixed clean parent."""
from pathlib import Path

R = Path.cwd()


def replace(path: str, before: str, after: str) -> None:
    p = R / path
    text = p.read_text(encoding="utf-8")
    if text.count(before) != 1:
        raise SystemExit(f"precondition failed: {path}: {before[:80]!r}")
    p.write_text(text.replace(before, after, 1), encoding="utf-8", newline="\n")


def append(path: str, text: str) -> None:
    p = R / path
    current = p.read_text(encoding="utf-8")
    if text.strip() not in current:
        p.write_text(current.rstrip() + "\n\n" + text.strip() + "\n", encoding="utf-8", newline="\n")


policy = "codex-rs/hepta-agentd/src/intuition_policy.rs"
replace(policy, "    PreparedClockReversed,\n    MissingDecisionEvidence,", "    PreparedClockReversed,\n    FinalClockUnavailable,\n    MissingDecisionEvidence,")
replace(
    policy,
    '            Self::PreparedClockReversed => "agentd.intuition.prepared_clock_reversed",\n            Self::MissingDecisionEvidence =>',
    '            Self::PreparedClockReversed => "agentd.intuition.prepared_clock_reversed",\n            Self::FinalClockUnavailable => "agentd.intuition.final_clock_unavailable",\n            Self::MissingDecisionEvidence =>',
)
append(
    policy,
    '''#[path = "intuition_policy_final_use.rs"]
mod final_use;
pub use final_use::IntuitionAssignmentCounter;
pub use final_use::IntuitionDecisionSequence;
pub use final_use::IntuitionWallClockMs;
pub use final_use::PreparedAgentdIntuitionDecisionV4;''',
)

service = "codex-rs/hepta-agentd/src/intuition_policy_service.rs"
replace(service, "use std::fmt;\n", "use std::fmt;\nuse std::time::Instant;\n")
replace(
    service,
    "use crate::PreparedAgentdIntuitionDecisionV3;\n",
    "use crate::IntuitionWallClockMs;\nuse crate::PreparedAgentdIntuitionDecisionV4;\n",
)
old = '''impl AgentdState {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn prepare_intuition_policy_v3(
        &self,
        request: CalibratedDecisionRequestV1,
        profile: CanonicalPolicyProfileV1,
        scoring: ScoringCommitmentV2,
        assignment: AssignmentCommitmentV2,
        qualification: IntuitionQualificationEvidenceV2<'_>,
        episode_id: StableId,
        run_snapshot_digest: Digest32,
        now: u64,
    ) -> Result<PreparedAgentdIntuitionDecisionV3, AgentdIntuitionServiceErrorV1> {
        if !self.automation_admission_ready()? {
            return Err(AgentdIntuitionServiceErrorV1::NotReady);
        }
        let host = self
            .intuition_policy
            .get()
            .ok_or(AgentdIntuitionServiceErrorV1::NotConfigured)?;
        let identity = self.identity();
        host.prepare_v3(
            &identity.agent_id,
            identity.spawn_generation,
            request,
            profile,
            scoring,
            assignment,
            qualification,
            episode_id,
            run_snapshot_digest,
            now,
        )
        .map_err(Into::into)
    }

    pub(crate) fn commit_intuition_policy_v3(
        &self,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
        now: u64,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionServiceErrorV1> {
        if !self.automation_admission_ready()? {
            return Err(AgentdIntuitionServiceErrorV1::NotReady);
        }
        let host = self
            .intuition_policy
            .get()
            .ok_or(AgentdIntuitionServiceErrorV1::NotConfigured)?;
        let identity = self.identity();
        let receipt = host.commit_v3(
            &identity.agent_id,
            identity.spawn_generation,
            prepared,
            expected_ledger_head,
            decision_evidence,
            now,
        )?;
        retain_committed_receipt(self.automation_admission_ready(), receipt).map_err(|receipt| {
            AgentdIntuitionServiceErrorV1::GenerationChangedAfterCommit { receipt }
        })
    }
}
'''
new = '''impl AgentdState {
    /// Prepare immutable payloads; authorization is rechecked only at final use.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn prepare_intuition_policy_v4(
        &self,
        request: CalibratedDecisionRequestV1,
        profile: CanonicalPolicyProfileV1,
        scoring: ScoringCommitmentV2,
        assignment: AssignmentCommitmentV2,
        qualification: IntuitionQualificationEvidenceV2<'_>,
        episode_id: StableId,
        run_snapshot_digest: Digest32,
        now: u64,
    ) -> Result<PreparedAgentdIntuitionDecisionV4, AgentdIntuitionServiceErrorV1> {
        if !self.automation_admission_ready()? {
            return Err(AgentdIntuitionServiceErrorV1::NotReady);
        }
        let host = self
            .intuition_policy
            .get()
            .ok_or(AgentdIntuitionServiceErrorV1::NotConfigured)?;
        let identity = self.identity();
        let started = Instant::now();
        let prepared = host.prepare_v4(
            &identity.agent_id,
            identity.spawn_generation,
            request,
            profile,
            scoring,
            assignment,
            qualification,
            episode_id,
            run_snapshot_digest,
            IntuitionWallClockMs::new(now),
        );
        record_service_stage(
            "prepare_static_and_authentication",
            if prepared.is_ok() { "completed" } else { "failed" },
            started.elapsed(),
        );
        prepared.map_err(Into::into)
    }

    /// Read generation and wall clock only after the sole writer lock is held.
    pub(crate) fn commit_intuition_policy_v4(
        &self,
        prepared: PreparedAgentdIntuitionDecisionV4,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionServiceErrorV1> {
        if !self.automation_admission_ready()? {
            return Err(AgentdIntuitionServiceErrorV1::NotReady);
        }
        let host = self
            .intuition_policy
            .get()
            .ok_or(AgentdIntuitionServiceErrorV1::NotConfigured)?;
        let identity = self.identity();
        let started = Instant::now();
        let receipt = host.commit_v4_with_final_clock(
            &identity.agent_id,
            identity.spawn_generation,
            prepared,
            expected_ledger_head,
            decision_evidence,
            || {
                match self.automation_admission_ready() {
                    Ok(true) => {}
                    Ok(false) | Err(AgentdError::GenerationFenced(_)) => {
                        return Err(AgentdIntuitionPolicyError::GenerationFence);
                    }
                    Err(_) => return Err(AgentdIntuitionPolicyError::FinalClockUnavailable),
                }
                crate::authbus_ingress::now_ms()
                    .map(IntuitionWallClockMs::new)
                    .map_err(|_| AgentdIntuitionPolicyError::FinalClockUnavailable)
            },
        );
        record_service_stage(
            "commit_final_use",
            if receipt.is_ok() { "completed" } else { "failed" },
            started.elapsed(),
        );
        let receipt = receipt?;
        retain_committed_receipt(self.automation_admission_ready(), receipt).map_err(|receipt| {
            AgentdIntuitionServiceErrorV1::GenerationChangedAfterCommit { receipt }
        })
    }
}
'''
replace(service, old, new)
append(
    service,
    '''fn record_service_stage(stage: &'static str, status: &'static str, elapsed: std::time::Duration) {
    let Some(metrics) = codex_otel::global() else { return; };
    if let Err(error) = metrics.record_duration(
        "codex.hepta.intuition.policy.service_stage",
        elapsed,
        &[("stage", stage), ("status", status)],
    ) {
        tracing::debug!(stage, status, error = %error, "intuition service stage metric failed");
    }
}''',
)

serving = "codex-rs/hepta-agentd/src/intuition_policy_serving.rs"
replace(serving, ".prepare_intuition_policy_v3(", ".prepare_intuition_policy_v4(")
replace(
    serving,
    '''        // A lease validated at prepare cannot be extended by reusing its time.
        let commit_now = crate::authbus_ingress::now_ms()?;
        let committed = state
            .commit_intuition_policy_v3(
                policy_prepared,
                expected_ledger_head,
                decision_evidence,
                commit_now,
            )''',
    '''        let committed = state
            .commit_intuition_policy_v4(
                policy_prepared,
                expected_ledger_head,
                decision_evidence,
            )''',
)

(R / "scripts/intuition_legacy_consumers.py").write_text(
    '''#!/usr/bin/env python3
"""Reject product source callers that bypass final-use V4."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
violations = []
for path in (ROOT / "codex-rs/hepta-agentd/src").glob("*.rs"):
    text = path.read_text(encoding="utf-8")
    for needle in ("prepare_intuition_policy_v3(", "commit_intuition_policy_v3("):
        if needle in text:
            violations.append(f"{path.relative_to(ROOT)}: {needle}")
if violations:
    raise SystemExit("legacy product consumers remain:\\n" + "\\n".join(violations))
print("intuition legacy product consumer boundary: clean")
''',
    encoding="utf-8",
    newline="\n",
)

technical = R / "docs/modules/intuition.policy/TECHNICAL.md"
text = technical.read_text(encoding="utf-8")
section = '''

### Final-use owner serialization boundary

The product path retains immutable canonical qualification payloads at prepare
time but never caches an authorization conclusion. The sole `LedgerWriter`
mutex is acquired before the owner reads the final wall clock, rechecks the
current Agentd generation, reverifies generator/evaluator/observer evidence
(including scheduled revocation), recomputes the authenticated V3 binding, and
starts a new selected Decision append. Writer wait, final clock/generation,
qualification reverification, durable append/witness, preparation, and service
commit are measured separately with bounded-cardinality labels. A known durable
commit remains recovery evidence and is never rewritten as an uncommitted
failure. This source hardening does not itself assert target-host capacity,
policy effectiveness, operator acceptance, promotion, or release.
'''
if "### Final-use owner serialization boundary" not in text:
    technical.write_text(text.rstrip() + section + "\n", encoding="utf-8", newline="\n")
