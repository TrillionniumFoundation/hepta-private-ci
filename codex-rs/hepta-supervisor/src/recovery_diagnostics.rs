//! Read-only recovery diagnosis for the supervisor's durable journals.
//!
//! This module never changes a lifecycle, process, Fleet record, journal, or
//! authority epoch. It maps fail-closed durable ambiguity to bounded operator
//! actions without manufacturing a terminal outcome.

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
    pub unresolved_control_intent: bool,
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
        unresolved_control_intent: false,
        blockers: Vec::new(),
    };

    for outcome in [
        crate::read_mutation_status(run_root),
        crate::mutation_journal_slots::read_emergency(run_root)
            .map(|owned| owned.map(|owned| owned.status)),
    ] {
        match outcome {
            Ok(Some(status)) if status.phase != crate::DurableMutationPhaseV1::Committed => {
                diagnostic.agent_id = Some(status.agent_id.to_string());
                diagnostic.recovery_required = true;
                push_blocker(
                    &mut diagnostic,
                    RecoveryBlockerKind::ProcessAmbiguity,
                    "an ordinary lifecycle mutation has no durable committed outcome",
                    RecoveryOperatorAction::FenceExactProcessAndObserveExit,
                );
            }
            Ok(_) => {}
            Err(_) => {
                diagnostic.recovery_required = true;
                push_blocker(
                    &mut diagnostic,
                    RecoveryBlockerKind::DurabilityFailure,
                    "the ordinary mutation outcome journal cannot be read and validated",
                    RecoveryOperatorAction::PreserveBytesAndRepairDurableStorage,
                );
            }
        }
    }

    match crate::control_intent::has_unresolved(run_root) {
        Ok(unresolved) => {
            diagnostic.unresolved_control_intent = unresolved;
            if unresolved {
                diagnostic.recovery_required = true;
                push_blocker(
                    &mut diagnostic,
                    RecoveryBlockerKind::ProcessAmbiguity,
                    "a durable Stop/Kill intent still targets an exact process owner",
                    RecoveryOperatorAction::FenceExactProcessAndObserveExit,
                );
            }
        }
        Err(_) => {
            diagnostic.recovery_required = true;
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::DurabilityFailure,
                "the durable Stop/Kill intent cannot be read and validated",
                RecoveryOperatorAction::PreserveBytesAndRepairDurableStorage,
            );
        }
    }

    let intent = match read_signed_intent(run_root) {
        Ok(intent) => intent,
        Err(_) => {
            diagnostic.recovery_required = true;
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::DurabilityFailure,
                "the signed release intent cannot be read and validated",
                RecoveryOperatorAction::PreserveBytesAndRepairDurableStorage,
            );
            None
        }
    };
    let transaction = match read_release_transaction(run_root) {
        Ok(transaction) => transaction,
        Err(_) => {
            diagnostic.recovery_required = true;
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::DurabilityFailure,
                "the release transaction cannot be read and validated",
                RecoveryOperatorAction::PreserveBytesAndRepairDurableStorage,
            );
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
                "a live process overlaps a non-terminal signed transition",
                RecoveryOperatorAction::FenceExactProcessAndObserveExit,
            );
        }
        if context
            .current_authority_epoch
            .is_some_and(|epoch| epoch != intent.authority_epoch)
        {
            diagnostic.recovery_required = true;
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::AuthorityEpochChange,
                "the durable intent belongs to another daemon authority epoch",
                RecoveryOperatorAction::ReissueDecisionFromCurrentAuthorityEpoch,
            );
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
            diagnostic.recovery_required = true;
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::ReleaseStateAmbiguity,
                "the observed release is neither the durable source nor target",
                RecoveryOperatorAction::ReconcileFleetReleaseCas,
            );
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
                diagnostic.recovery_required = true;
                push_blocker(
                    &mut diagnostic,
                    RecoveryBlockerKind::FrontierDrift,
                    "the current Fleet admission frontier differs from the transaction witness",
                    RecoveryOperatorAction::RefreshAdmissionFrontierAndRejectStaleGrant,
                );
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
                diagnostic.recovery_required = true;
                push_blocker(
                    &mut diagnostic,
                    RecoveryBlockerKind::IntentMismatch,
                    "the signed intent and release transaction bind different operations",
                    RecoveryOperatorAction::InspectExactIntentAndTransactionDigests,
                );
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
            diagnostic.recovery_required = true;
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::IntentMismatch,
                "a non-terminal signed intent has no matching release transaction",
                RecoveryOperatorAction::InspectExactIntentAndTransactionDigests,
            );
        }
        (None, Some(transaction)) if !transaction.phase.terminal() => {
            diagnostic.recovery_required = true;
            push_blocker(
                &mut diagnostic,
                RecoveryBlockerKind::IntentMismatch,
                "a non-terminal release transaction has no matching signed intent",
                RecoveryOperatorAction::InspectExactIntentAndTransactionDigests,
            );
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
    if diagnostic
        .blockers
        .iter()
        .any(|blocker| blocker.kind == kind)
    {
        return;
    }
    diagnostic.blockers.push(RecoveryBlockerDiagnostic {
        kind,
        detail: detail.to_string(),
        operator_action,
    });
}

#[cfg(test)]
#[path = "recovery_mutation_tests.rs"]
mod mutation_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_run_root_is_clean() {
        let dir = tempfile::tempdir().expect("temporary directory");
        let diagnostic = diagnose_recovery(dir.path(), &RecoveryDiagnosticContext::default());
        assert!(!diagnostic.recovery_required);
        assert!(diagnostic.blockers.is_empty());
    }

    #[test]
    fn corrupted_intent_is_actionable_durability_failure() {
        let dir = tempfile::tempdir().expect("temporary directory");
        std::fs::write(dir.path().join(crate::SIGNED_INTENT_FILE), b"{truncated")
            .expect("corrupt intent");
        let diagnostic = diagnose_recovery(dir.path(), &RecoveryDiagnosticContext::default());
        assert!(diagnostic.recovery_required);
        assert!(diagnostic.blockers.iter().any(|blocker| {
            blocker.kind == RecoveryBlockerKind::DurabilityFailure
                && blocker.operator_action
                    == RecoveryOperatorAction::PreserveBytesAndRepairDurableStorage
        }));
    }

    #[test]
    fn contextual_blockers_are_actionable_and_distinct() {
        use codex_hepta_fleet::ReleaseBinding;
        use codex_hepta_fleet::ReleaseId;

        let dir = tempfile::tempdir().expect("temporary directory");
        let grant = Sha256Digest::for_bytes(b"recovery-diagnostic-grant");
        let frontier = Sha256Digest::for_bytes(b"transaction-frontier");
        let source_release = ReleaseId::parse("release-v1").expect("source release");
        let target_release = ReleaseId::parse("release-v2").expect("target release");
        let binding = |release_id: ReleaseId| ReleaseBinding {
            release_id,
            manifest_sha256: Sha256Digest::for_bytes(b"manifest").as_str().to_string(),
            agentd_program_sha256: Sha256Digest::for_bytes(b"agentd").as_str().to_string(),
            matrixd_program_sha256: None,
            admission_frontier_sha256: frontier.as_str().to_string(),
        };

        let intent = crate::SignedSupervisorIntent::new(
            grant.clone(),
            "agent-a",
            crate::H7H89ProductionTransition::Upgrade,
            "release-v1",
            "release-v2",
            5,
            7,
            3,
            SignedIntentStatus::RecoveryRequired,
        )
        .expect("intent");
        crate::signed_intent::write_intent(dir.path(), &intent).expect("write intent");

        let transaction = crate::DurableReleaseTransaction::new(
            "agent-a",
            crate::ReleaseTransactionKind::Upgrade,
            "release-v1",
            "release-v2",
            Some("release-v1".to_string()),
            Some(binding(source_release)),
            Some(binding(target_release)),
            11,
            7,
        )
        .expect("transaction")
        .with_authority(grant, 3)
        .expect("authority")
        .with_phase(ReleaseTransactionPhase::RecoveryRequired)
        .expect("recovery phase");
        crate::release_transaction::write_release_transaction(dir.path(), &transaction)
            .expect("write transaction");

        let diagnostic = diagnose_recovery(
            dir.path(),
            &RecoveryDiagnosticContext {
                live_process_present: true,
                observed_release: Some("release-v3".to_string()),
                current_authority_epoch: Some(4),
                current_admission_frontier_sha256: Some(Sha256Digest::for_bytes(
                    b"current-frontier",
                )),
            },
        );
        let pairs = diagnostic
            .blockers
            .iter()
            .map(|blocker| (blocker.kind, blocker.operator_action))
            .collect::<Vec<_>>();
        assert!(pairs.contains(&(
            RecoveryBlockerKind::ProcessAmbiguity,
            RecoveryOperatorAction::FenceExactProcessAndObserveExit,
        )));
        assert!(pairs.contains(&(
            RecoveryBlockerKind::ReleaseStateAmbiguity,
            RecoveryOperatorAction::ReconcileFleetReleaseCas,
        )));
        assert!(pairs.contains(&(
            RecoveryBlockerKind::FrontierDrift,
            RecoveryOperatorAction::RefreshAdmissionFrontierAndRejectStaleGrant,
        )));
        assert!(pairs.contains(&(
            RecoveryBlockerKind::AuthorityEpochChange,
            RecoveryOperatorAction::ReissueDecisionFromCurrentAuthorityEpoch,
        )));
    }

    #[test]
    fn mismatched_intent_and_transaction_require_digest_inspection() {
        let dir = tempfile::tempdir().expect("temporary directory");
        let intent = crate::SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"intent-grant"),
            "agent-a",
            crate::H7H89ProductionTransition::Upgrade,
            "release-v1",
            "release-v2",
            5,
            7,
            3,
            SignedIntentStatus::Prepared,
        )
        .expect("intent");
        crate::signed_intent::write_intent(dir.path(), &intent).expect("write intent");
        let transaction = crate::DurableReleaseTransaction::new(
            "agent-a",
            crate::ReleaseTransactionKind::Upgrade,
            "release-v1",
            "release-v2",
            Some("release-v1".to_string()),
            None,
            None,
            11,
            7,
        )
        .expect("transaction")
        .with_authority(Sha256Digest::for_bytes(b"different-grant"), 3)
        .expect("authority");
        crate::release_transaction::write_release_transaction(dir.path(), &transaction)
            .expect("write transaction");

        let diagnostic = diagnose_recovery(dir.path(), &RecoveryDiagnosticContext::default());
        assert!(diagnostic.blockers.iter().any(|blocker| {
            blocker.kind == RecoveryBlockerKind::IntentMismatch
                && blocker.operator_action
                    == RecoveryOperatorAction::InspectExactIntentAndTransactionDigests
        }));
    }
}
