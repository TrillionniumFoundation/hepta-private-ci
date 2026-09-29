use std::path::Path;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::ReleaseTransactionPhase;
use crate::SignedIntentStatus;
use crate::lease::read_lease;
use crate::release_transaction::DurableReleaseTransaction;
use crate::release_transaction::read_release_transaction;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;

pub const RECOVERY_DIAGNOSTIC_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryBlockerClass {
    NoBlocker,
    ProcessAmbiguity,
    ReleaseCasAmbiguity,
    IntentMismatch,
    FrontierDrift,
    AuthorityEpochChange,
    DurabilityFailure,
    AwaitingIndependentDecision,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryOperatorAction {
    None,
    FenceAndIdentifyProcess,
    InspectReleaseCas,
    ReinspectIntentAndTransaction,
    RefreshAdmissionAndIssueNewGrant,
    RotateAuthorityAndIssueFreshGrant,
    RestoreDurableState,
    ObtainIndependentRecoveryDecision,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecoveryObservation {
    pub observed_release: Option<String>,
    pub current_authority_epoch: Option<u64>,
    pub current_admission_frontier_sha256: Option<String>,
    pub process_present: Option<bool>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecoveryDiagnostic {
    pub schema_version: u32,
    pub blocker: RecoveryBlockerClass,
    pub operator_action: RecoveryOperatorAction,
    pub summary: String,
    pub agent_id: Option<String>,
    pub grant_sha256: Option<Sha256Digest>,
    pub intent_sha256: Option<Sha256Digest>,
    pub transaction_sha256: Option<Sha256Digest>,
    pub intent_status: Option<SignedIntentStatus>,
    pub transaction_phase: Option<ReleaseTransactionPhase>,
    pub authority_epoch: Option<u64>,
    pub expected_admission_frontier_sha256: Option<String>,
    pub process_lease_present: bool,
    pub observed_release: Option<String>,
}

pub fn diagnose_supervisor_recovery(
    run_root: &Path,
    observation: Option<&RecoveryObservation>,
) -> RecoveryDiagnostic {
    let observation = observation.cloned().unwrap_or_default();
    let intent = match read_intent(run_root) {
        Ok(intent) => intent,
        Err(error) => {
            return diagnostic(
                RecoveryBlockerClass::DurabilityFailure,
                RecoveryOperatorAction::RestoreDurableState,
                format!("signed intent cannot be read or validated: {error}"),
                None,
                None,
                false,
                &observation,
            );
        }
    };
    let Some(intent) = intent else {
        return diagnostic(
            RecoveryBlockerClass::NoBlocker,
            RecoveryOperatorAction::None,
            "no signed supervisor intent exists".to_string(),
            None,
            None,
            false,
            &observation,
        );
    };
    if matches!(
        intent.status,
        SignedIntentStatus::Committed
            | SignedIntentStatus::RolledBack
            | SignedIntentStatus::Aborted
    ) {
        return diagnostic(
            RecoveryBlockerClass::NoBlocker,
            RecoveryOperatorAction::None,
            "the signed supervisor intent is terminal".to_string(),
            Some(&intent),
            None,
            false,
            &observation,
        );
    }
    let transaction = match read_release_transaction(run_root) {
        Ok(transaction) => transaction,
        Err(error) => {
            return diagnostic(
                RecoveryBlockerClass::DurabilityFailure,
                RecoveryOperatorAction::RestoreDurableState,
                format!("release transaction cannot be read or validated: {error}"),
                Some(&intent),
                None,
                false,
                &observation,
            );
        }
    };
    let lease_present = match read_lease(run_root) {
        Ok(lease) => lease.is_some(),
        Err(error) => {
            return diagnostic(
                RecoveryBlockerClass::DurabilityFailure,
                RecoveryOperatorAction::RestoreDurableState,
                format!("process lease cannot be read or validated: {error}"),
                Some(&intent),
                transaction.as_ref(),
                false,
                &observation,
            );
        }
    };
    let blocker = classify(&intent, transaction.as_ref(), lease_present, &observation);
    let (action, summary) = blocker_action(blocker);
    diagnostic(
        blocker,
        action,
        summary.to_string(),
        Some(&intent),
        transaction.as_ref(),
        lease_present,
        &observation,
    )
}

fn classify(
    intent: &SignedSupervisorIntent,
    transaction: Option<&DurableReleaseTransaction>,
    lease_present: bool,
    observation: &RecoveryObservation,
) -> RecoveryBlockerClass {
    if lease_present || observation.process_present == Some(true) {
        return RecoveryBlockerClass::ProcessAmbiguity;
    }
    let Some(transaction) = transaction else {
        return RecoveryBlockerClass::ReleaseCasAmbiguity;
    };
    if transaction.agent_id != intent.agent_id
        || transaction.source_release != intent.source_release
        || transaction.target_release != intent.target_release
        || transaction.grant_sha256.as_ref() != Some(&intent.grant_sha256)
        || transaction.authority_epoch != Some(intent.authority_epoch)
    {
        return RecoveryBlockerClass::IntentMismatch;
    }
    if observation
        .current_authority_epoch
        .is_some_and(|epoch| epoch != intent.authority_epoch)
    {
        return RecoveryBlockerClass::AuthorityEpochChange;
    }
    if let Some(current_frontier) = observation.current_admission_frontier_sha256.as_deref()
        && expected_frontier(transaction).is_some_and(|expected| expected != current_frontier)
    {
        return RecoveryBlockerClass::FrontierDrift;
    }
    if let Some(observed_release) = observation.observed_release.as_deref()
        && observed_release != intent.source_release
        && observed_release != intent.target_release
    {
        return RecoveryBlockerClass::ReleaseCasAmbiguity;
    }
    if intent.status == SignedIntentStatus::RecoveryRequired
        || transaction.phase == ReleaseTransactionPhase::RecoveryRequired
    {
        return RecoveryBlockerClass::AwaitingIndependentDecision;
    }
    RecoveryBlockerClass::ReleaseCasAmbiguity
}

fn blocker_action(
    blocker: RecoveryBlockerClass,
) -> (RecoveryOperatorAction, &'static str) {
    match blocker {
        RecoveryBlockerClass::NoBlocker => (
            RecoveryOperatorAction::None,
            "no recovery blocker is present",
        ),
        RecoveryBlockerClass::ProcessAmbiguity => (
            RecoveryOperatorAction::FenceAndIdentifyProcess,
            "an exact process may still carry effects; fence it and establish process identity before terminalization",
        ),
        RecoveryBlockerClass::ReleaseCasAmbiguity => (
            RecoveryOperatorAction::InspectReleaseCas,
            "release state does not independently establish a terminal source or target outcome; inspect the Fleet CAS and immutable release bytes",
        ),
        RecoveryBlockerClass::IntentMismatch => (
            RecoveryOperatorAction::ReinspectIntentAndTransaction,
            "the signed intent and durable release transaction do not bind the same operation; stop and re-inspect both journals",
        ),
        RecoveryBlockerClass::FrontierDrift => (
            RecoveryOperatorAction::RefreshAdmissionAndIssueNewGrant,
            "the Fleet admission frontier changed; do not reuse the old grant and obtain a fresh independently authorized transition",
        ),
        RecoveryBlockerClass::AuthorityEpochChange => (
            RecoveryOperatorAction::RotateAuthorityAndIssueFreshGrant,
            "the daemon authority epoch changed; reject the stale decision and use the currently pinned signer/epoch",
        ),
        RecoveryBlockerClass::DurabilityFailure => (
            RecoveryOperatorAction::RestoreDurableState,
            "a required journal is missing, corrupt, truncated, or unreadable; restore or independently reconstruct it before retry",
        ),
        RecoveryBlockerClass::AwaitingIndependentDecision => (
            RecoveryOperatorAction::ObtainIndependentRecoveryDecision,
            "the process and durable bindings are coherent, but an independently signed recovery decision is still required",
        ),
    }
}

fn expected_frontier(transaction: &DurableReleaseTransaction) -> Option<&str> {
    transaction
        .target_binding
        .as_ref()
        .or(transaction.source_binding.as_ref())
        .map(|binding| binding.admission_frontier_sha256.as_str())
}

fn diagnostic(
    blocker: RecoveryBlockerClass,
    operator_action: RecoveryOperatorAction,
    summary: String,
    intent: Option<&SignedSupervisorIntent>,
    transaction: Option<&DurableReleaseTransaction>,
    process_lease_present: bool,
    observation: &RecoveryObservation,
) -> RecoveryDiagnostic {
    RecoveryDiagnostic {
        schema_version: RECOVERY_DIAGNOSTIC_SCHEMA_VERSION,
        blocker,
        operator_action,
        summary,
        agent_id: intent.map(|value| value.agent_id.clone()),
        grant_sha256: intent.map(|value| value.grant_sha256.clone()),
        intent_sha256: intent.map(|value| value.intent_sha256.clone()),
        transaction_sha256: transaction.map(|value| value.transaction_sha256.clone()),
        intent_status: intent.map(|value| value.status),
        transaction_phase: transaction.map(|value| value.phase),
        authority_epoch: intent.map(|value| value.authority_epoch),
        expected_admission_frontier_sha256: transaction
            .and_then(expected_frontier)
            .map(str::to_string),
        process_lease_present,
        observed_release: observation.observed_release.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::H7H89ProductionTransition;
    use crate::ReleaseTransactionKind;

    fn intent(status: SignedIntentStatus) -> SignedSupervisorIntent {
        SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"grant"),
            "agent-a",
            H7H89ProductionTransition::Upgrade,
            "release-v1",
            "release-v2",
            7,
            9,
            11,
            status,
        )
        .expect("intent")
    }

    fn transaction(phase: ReleaseTransactionPhase) -> DurableReleaseTransaction {
        DurableReleaseTransaction::new(
            "agent-a",
            ReleaseTransactionKind::Upgrade,
            "release-v1",
            "release-v2",
            None,
            None,
            None,
            3,
            9,
        )
        .expect("transaction")
        .with_authority(Sha256Digest::for_bytes(b"grant"), 11)
        .expect("authority")
        .with_phase(phase)
        .expect("phase")
    }

    #[test]
    fn classifies_process_authority_and_independent_decision_blockers() {
        let intent = intent(SignedIntentStatus::RecoveryRequired);
        let transaction = transaction(ReleaseTransactionPhase::RecoveryRequired);
        assert_eq!(
            classify(
                &intent,
                Some(&transaction),
                true,
                &RecoveryObservation::default()
            ),
            RecoveryBlockerClass::ProcessAmbiguity
        );
        assert_eq!(
            classify(
                &intent,
                Some(&transaction),
                false,
                &RecoveryObservation {
                    current_authority_epoch: Some(12),
                    ..RecoveryObservation::default()
                }
            ),
            RecoveryBlockerClass::AuthorityEpochChange
        );
        assert_eq!(
            classify(
                &intent,
                Some(&transaction),
                false,
                &RecoveryObservation::default()
            ),
            RecoveryBlockerClass::AwaitingIndependentDecision
        );
    }

    #[test]
    fn missing_or_mismatched_transaction_is_actionable() {
        let intent = intent(SignedIntentStatus::Queued);
        assert_eq!(
            classify(&intent, None, false, &RecoveryObservation::default()),
            RecoveryBlockerClass::ReleaseCasAmbiguity
        );
        let mut transaction = transaction(ReleaseTransactionPhase::Draining);
        transaction.agent_id = "other-agent".to_string();
        assert_eq!(
            classify(
                &intent,
                Some(&transaction),
                false,
                &RecoveryObservation::default()
            ),
            RecoveryBlockerClass::IntentMismatch
        );
    }
}
