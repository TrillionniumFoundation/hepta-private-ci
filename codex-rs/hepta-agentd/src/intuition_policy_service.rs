//! Live Agentd serving seam for intuition.policy.
//!
//! Both phases revalidate the Fleet generation and normal Agentd admission
//! boundary. A failure after policy commit retains the exact policy receipt,
//! including failures in the subsequent run and context admission boundaries.
//! Such a receipt is recovery evidence, never dispatch authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdIntuitionDecisionReceiptV2;
use crate::AgentdIntuitionPolicyError;
use crate::PreparedAgentdIntuitionDecisionV3;
use crate::state::AgentdState;

#[path = "intuition_policy_admission.rs"]
mod admission;
pub(crate) use admission::CanonicalIntuitionAdmissionV2;
pub(crate) use admission::finish_canonical_admission;

#[derive(Debug)]
pub enum AgentdIntuitionServiceErrorV1 {
    NotConfigured,
    NotReady,
    Agentd(AgentdError),
    Policy(AgentdIntuitionPolicyError),
    GenerationChangedAfterCommit {
        receipt: AgentdIntuitionDecisionReceiptV2,
    },
    /// The policy phase succeeded, but a later canonical admission boundary
    /// failed. Preserve both facts; an error must not imply that no append ran.
    AdmissionFailedAfterPolicy {
        receipt: AgentdIntuitionDecisionReceiptV2,
        source: Box<AgentdError>,
    },
}

impl AgentdIntuitionServiceErrorV1 {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::NotConfigured => "agentd.intuition.service.not_configured",
            Self::NotReady => "agentd.intuition.service.not_ready",
            Self::Agentd(_) => "agentd.intuition.service.agentd_fenced",
            Self::Policy(source) => source.code(),
            Self::GenerationChangedAfterCommit { .. } => {
                "agentd.intuition.service.generation_changed_after_commit"
            }
            Self::AdmissionFailedAfterPolicy { .. } => {
                "agentd.intuition.service.admission_failed_after_policy"
            }
        }
    }

    /// Return the complete successfully acknowledged policy receipt, when one
    /// is known. Callers must still inspect its selected/nonselected disposition.
    #[must_use]
    pub fn acknowledged_policy_receipt(&self) -> Option<&AgentdIntuitionDecisionReceiptV2> {
        match self {
            Self::GenerationChangedAfterCommit { receipt }
            | Self::AdmissionFailedAfterPolicy { receipt, .. } => Some(receipt),
            Self::NotConfigured | Self::NotReady | Self::Agentd(_) | Self::Policy(_) => None,
        }
    }
}

impl fmt::Display for AgentdIntuitionServiceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl StdError for AgentdIntuitionServiceErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Agentd(source) => Some(source),
            Self::Policy(source) => Some(source),
            Self::AdmissionFailedAfterPolicy { source, .. } => Some(source.as_ref()),
            Self::NotConfigured | Self::NotReady | Self::GenerationChangedAfterCommit { .. } => {
                None
            }
        }
    }
}

impl From<AgentdError> for AgentdIntuitionServiceErrorV1 {
    fn from(value: AgentdError) -> Self {
        Self::Agentd(value)
    }
}

impl From<AgentdIntuitionPolicyError> for AgentdIntuitionServiceErrorV1 {
    fn from(value: AgentdIntuitionPolicyError) -> Self {
        Self::Policy(value)
    }
}

/// Once append has succeeded, no subsequent failure may erase its recovery token.
/// In particular an admission I/O error is not proof that append never happened.
fn retain_committed_receipt<T, E>(
    admission: Result<bool, E>,
    receipt: T,
) -> Result<T, (T, Option<E>)> {
    match admission {
        Ok(true) => Ok(receipt),
        Ok(false) => Err((receipt, None)),
        Err(source) => Err((receipt, Some(source))),
    }
}

impl AgentdState {
    #[allow(clippy::too_many_arguments)]
    #[allow(
        clippy::result_large_err,
        reason = "Keep the public service error payload compatible and retain complete acknowledged receipts"
    )]
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

    #[allow(
        clippy::result_large_err,
        reason = "Keep the public service error payload compatible and retain complete acknowledged receipts"
    )]
    pub(crate) fn commit_intuition_policy_v4_checked<F>(
        &self,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
        final_use: F,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionServiceErrorV1>
    where
        F: FnOnce(&dyn crate::IntuitionPolicyClock) -> Result<(), AgentdError>,
    {
        if !self.automation_admission_ready()? {
            return Err(AgentdIntuitionServiceErrorV1::NotReady);
        }
        let host = self
            .intuition_policy
            .get()
            .ok_or(AgentdIntuitionServiceErrorV1::NotConfigured)?;
        let identity = self.identity();
        let receipt = host.commit_v4_checked(
            &identity.agent_id,
            identity.spawn_generation,
            prepared,
            expected_ledger_head,
            decision_evidence,
            |now| {
                if !self.automation_admission_ready()? {
                    return Err(AgentdIntuitionServiceErrorV1::NotReady);
                }
                final_use(now).map_err(AgentdIntuitionServiceErrorV1::from)
            },
        )?;
        retain_committed_receipt(self.automation_admission_ready(), receipt).map_err(
            |(receipt, source)| match source {
                Some(source) => AgentdIntuitionServiceErrorV1::AdmissionFailedAfterPolicy {
                    receipt,
                    source: Box::new(source),
                },
                None => AgentdIntuitionServiceErrorV1::GenerationChangedAfterCommit { receipt },
            },
        )
    }
}

#[cfg(test)]
mod tests {
    use super::retain_committed_receipt;

    #[test]
    fn intuition_policy_post_commit_rejection_preserves_exact_receipt() {
        let receipt = String::from("durable:sequence:7:chain:verified");
        assert_eq!(
            retain_committed_receipt::<_, ()>(Ok(false), receipt.clone()),
            Err((receipt, None))
        );
    }

    #[test]
    fn intuition_policy_post_commit_check_error_is_not_an_uncommitted_failure() {
        let receipt = String::from("durable:sequence:8:chain:verified");
        assert_eq!(
            retain_committed_receipt(Err("generation-store-unavailable"), receipt.clone()),
            Err((receipt, Some("generation-store-unavailable")))
        );
    }

    #[test]
    fn intuition_policy_post_commit_success_retains_the_same_receipt() {
        let receipt = String::from("durable:sequence:9:chain:verified");
        assert_eq!(
            retain_committed_receipt::<_, ()>(Ok(true), receipt.clone()),
            Ok(receipt)
        );
    }
}
