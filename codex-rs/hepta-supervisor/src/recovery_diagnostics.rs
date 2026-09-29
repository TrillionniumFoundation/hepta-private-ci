//! Actionable inspection of fail-closed supervisor recovery state.
//!
//! This module is read-only. It never terminalizes a transaction, changes a
//! Fleet release state, kills a process, or manufactures authority. It turns
//! durable ambiguity into bounded blocker classes and explicit operator work.

use std::path::Path;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::ReleaseTransactionPhase;
use crate::SignedIntentStatus;
use crate::read_signed_intent;
use crate::release_transaction::read_release_transaction;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryBlockerKind {
    ProcessAmbiguity,
    ReleaseStateAmbiguity,
    IntentMismatch,
    FrontierDrift,
    AuthorityEpochChange,
    DurabilityFailure,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryOperatorAction {
    FenceExactProcessAndObserveExit,
    ReconcileFleetReleaseCas,
    InspectExactIntentAndTransactionDigests,
    RefreshAdmissionFrontierAndRejectStaleGrant,
    ReissueDecisionFromCurrentAuthorityEpoch,
    PreserveBytesAndRepairDurableStorage,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecoveryBlockerDiagnostic {
    pub kind: RecoveryBlockerKind,
    pub detail: String,
    pub operator_action: RecoveryOperatorAction,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecoveryDiagnosticContext {
    pub live_process_present: bool,
    pub observed_release: Option<String>,
    pub current_authority_epoch: Option<u64>,
    pub current_admission_frontier_sha256: Option<Sha256Digest>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecoveryDiagnostic {
    pub agent_id: Option<String>,
    pub recovery_required: bool,
    pub intent_status: Option<SignedIntentStatus>,
    pub release_transaction_phase: Option<ReleaseTransactionPhase>,
    pub intent_sha256: Option<Sha256Digest>,
    pub release_transaction_sha256: Option<Sha256Digest>,
    pub blockers: Vec<RecoveryBlockerDiagnostic>,
}

pub fn diagnose_recovery(
    run_root: &Path,
    context: &RecoveryDiagnosticContext,
) -> RecoveryDiagnostic {
    let mut diagnostic = RecoveryDiagnostic {
        agent_id: None,
        recovery_required: false,
        intent_status: None,
        release_transaction_phase: None,
        intent_sha256: None,
        release_transaction_sha256: None,
        blockers: Vec::new(),
    };

    let intent = match read_signed_intent(run_root) {
        Ok(intent) => intent,
        Err(_) => {
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::DurabilityFailure,
                "the signed intent cannot be read and validated",
                RecoveryOperatorAction::PreserveBytesAndRepairDurableStorage,
            );
            diagnostic.recovery_required = true;
            None
        }
    };
    let transaction = match read_release_transaction(run_root) {
        Ok(transaction) => transaction,
        Err(_) => {
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::DurabilityFailure,
                "the release transaction cannot be read and validated",
                RecoveryOperatorAction::PreserveBytesAndRepairDurableStorage,
            );
            diagnostic.recovery_required = true;
            None
        }
    };

    if let Some(intent) = intent.as_ref() {
        diagnostic.agent_id = Some(intent.agent_id.clone());
        diagnostic.intent_status = Some(intent.status);
        diagnostic.intent_sha256 = Some(intent.intent_sha256.clone());
        if matches!(
            intent.status,
            SignedIntentStatus::Prepared
                | SignedIntentStatus::Queued
                | SignedIntentStatus::RecoveryRequired
        ) {
            diagnostic.recovery_required = true;
        }
        if context.live_process_present && diagnostic.recovery_required {
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::ProcessAmbiguity,
                "a live process still overlaps an unresolved signed transition",
                RecoveryOperatorAction::FenceExactProcessAndObserveExit,
            );
        }
        if context
            .current_authority_epoch
            .is_some_and(|epoch| epoch != intent.authority_epoch)
        {
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::AuthorityEpochChange,
                "the durable intent was issued under a different daemon authority epoch",
                RecoveryOperatorAction::ReissueDecisionFromCurrentAuthorityEpoch,
            );
            diagnostic.recovery_required = true;
        }
    }

    if let Some(transaction) = transaction.as_ref() {
        diagnostic
            .agent_id
            .get_or_insert_with(|| transaction.agent_id.clone());
        diagnostic.release_transaction_phase = Some(transaction.phase);
        diagnostic.release_transaction_sha256 = Some(transaction.transaction_sha256.clone());
        if !transaction.phase.terminal() {
            diagnostic.recovery_required = true;
        }
        if transaction.phase == ReleaseTransactionPhase::RecoveryRequired {
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::ReleaseStateAmbiguity,
                "the release transaction has no independently proven terminal CAS outcome",
                RecoveryOperatorAction::ReconcileFleetReleaseCas,
            );
        }
        if let Some(observed_release) = context.observed_release.as_deref()
            && observed_release != transaction.source_release
            && observed_release != transaction.target_release
        {
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::ReleaseStateAmbiguity,
                "the observed release is neither the durable source nor target",
                RecoveryOperatorAction::ReconcileFleetReleaseCas,
            );
            diagnostic.recovery_required = true;
        }
        if let Some(frontier) = context.current_admission_frontier_sha256.as_ref() {
            let drifted = [
                transaction.source_binding.as_ref(),
                transaction.target_binding.as_ref(),
            ]
            .into_iter()
            .flatten()
            .any(|binding| binding.admission_frontier_sha256 != frontier.as_str());
            if drifted {
                push_blocker(
                    &mut diagnostic,
                    RecoveryBlockerKind::FrontierDrift,
                    "the current Fleet admission frontier differs from the transaction witness",
                    RecoveryOperatorAction::RefreshAdmissionFrontierAndRejectStaleGrant,
                );
                diagnostic.recovery_required = true;
            }
        }
    }

    match (intent.as_ref(), transaction.as_ref()) {
        (Some(intent), Some(transaction)) => {
            let mismatch = intent.agent_id != transaction.agent_id
                || intent.source_release != transaction.source_release
                || intent.target_release != transaction.target_release
                || transaction.grant_sha256.as_ref() != Some(&intent.grant_sha256)
                || transaction.authority_epoch != Some(intent.authority_epoch);
            if mismatch {
                push_blocker(
                    &mut diagnostic,
                    RecoveryBlockerKind::IntentMismatch,
                    "the signed intent and release transaction do not bind the same operation",
                    RecoveryOperatorAction::InspectExactIntentAndTransactionDigests,
                );
                diagnostic.recovery_required = true;
            }
        }
        (Some(intent), None)
            if matches!(
                intent.status,
                SignedIntentStatus::Prepared
                    | SignedIntentStatus::Queued
                    | SignedIntentStatus::RecoveryRequired
            ) =>
        {
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::IntentMismatch,
                "an unresolved signed intent has no matching durable release transaction",
                RecoveryOperatorAction::InspectExactIntentAndTransactionDigests,
            );
            diagnostic.recovery_required = true;
        }
        (None, Some(transaction)) if !transaction.phase.terminal() => {
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::IntentMismatch,
                "a non-terminal release transaction has no matching signed intent",
                RecoveryOperatorAction::InspectExactIntentAndTransactionDigests,
            );
            diagnostic.recovery_required = true;
        }
        _ => {}
    }

    diagnostic.blockers.sort_by_key(|blocker| blocker.kind);
    diagnostic
}

fn push_blocker(
    diagnostic: &mut RecoveryDiagnostic,
    kind: RecoveryBlockerKind,
    detail: &str,
    operator_action: RecoveryOperatorAction,
) {
    if diagnostic.blockers.iter().any(|blocker| blocker.kind == kind) {
        return;
    }
    diagnostic.blockers.push(RecoveryBlockerDiagnostic {
        kind,
        detail: detail.to_string(),
        operator_action,
    });
}

#[cfg(test)]
mod tests {
    use codex_hepta_contracts::AgentId;

    use super::*;
    use crate::DurableReleaseTransaction;
    use crate::H7H89ProductionTransition;
    use crate::ReleaseTransactionKind;
    use crate::SignedSupervisorIntent;
    use crate::release_transaction::write_release_transaction;
    use crate::signed_intent::write_intent;

    fn unresolved_state(run_root: &Path) -> (SignedSupervisorIntent, DurableReleaseTransaction) {
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
            .expect("fixed agent");
        let intent = SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"grant"),
            agent.to_string(),
            H7H89ProductionTransition::Upgrade,
            "release-v1",
            "release-v2",
            3,
            7,
            11,
            SignedIntentStatus::RecoveryRequired,
        )
        .expect("intent");
        let transaction = DurableReleaseTransaction::new(
            agent.to_string(),
            ReleaseTransactionKind::Upgrade,
            "release-v1",
            "release-v2",
            Some("release-v1".to_string()),
            None,
            None,
            4,
            7,
        )
        .expect("transaction")
        .with_authority(intent.grant_sha256.clone(), intent.authority_epoch)
        .expect("authority")
        .with_phase(ReleaseTransactionPhase::RecoveryRequired)
        .expect("recovery phase");
        write_intent(run_root, &intent).expect("write intent");
        write_release_transaction(run_root, &transaction).expect("write transaction");
        (intent, transaction)
    }

    #[test]
    fn classifies_process_release_and_authority_blockers() {
        let dir = tempfile::tempdir().expect("temporary directory");
        unresolved_state(dir.path());
        let diagnostic = diagnose_recovery(
            dir.path(),
            &RecoveryDiagnosticContext {
                live_process_present: true,
                observed_release: Some("unknown-release".to_string()),
                current_authority_epoch: Some(12),
                current_admission_frontier_sha256: None,
            },
        );
        assert!(diagnostic.recovery_required);
        for kind in [
            RecoveryBlockerKind::ProcessAmbiguity,
            RecoveryBlockerKind::ReleaseStateAmbiguity,
            RecoveryBlockerKind::AuthorityEpochChange,
        ] {
            assert!(diagnostic.blockers.iter().any(|blocker| blocker.kind == kind));
        }
    }

    #[test]
    fn corrupted_intent_maps_to_durability_failure_without_leaking_bytes() {
        let dir = tempfile::tempdir().expect("temporary directory");
        std::fs::write(
            dir.path().join(crate::SIGNED_INTENT_FILE),
            b"{truncated",
        )
        .expect("corrupt intent");
        let diagnostic = diagnose_recovery(dir.path(), &RecoveryDiagnosticContext::default());
        assert!(diagnostic.recovery_required);
        assert!(diagnostic.blockers.iter().any(|blocker| {
            blocker.kind == RecoveryBlockerKind::DurabilityFailure
                && !blocker.detail.contains("truncated")
        }));
    }

    #[test]
    fn empty_run_root_is_clean() {
        let dir = tempfile::tempdir().expect("temporary directory");
        let diagnostic = diagnose_recovery(dir.path(), &RecoveryDiagnosticContext::default());
        assert!(!diagnostic.recovery_required);
        assert!(diagnostic.blockers.is_empty());
    }
}
