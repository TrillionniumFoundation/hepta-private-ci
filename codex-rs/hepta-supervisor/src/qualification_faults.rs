//! Explicit qualification-only helpers for process-kill and durability tests.
//!
//! Nothing in this module is compiled into the default product. The probe uses
//! the real process lease, restart record, release transaction, and signed
//! intent writers so a subprocess can be killed after all four publications
//! and a fresh process can validate the exact durable bytes.

use std::path::Path;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::DurableReleaseTransaction;
use crate::H7H89ProductionTransition;
use crate::ProcessIdentity;
use crate::ReleaseTransactionKind;
use crate::ReleaseTransactionPhase;
use crate::SignedIntentStatus;
use crate::SignedSupervisorIntent;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::validate_lease;
use crate::lease::write_lease;
use crate::release_transaction::read_release_transaction;
use crate::release_transaction::write_release_transaction;
use crate::restart_budget::claim_restart;
use crate::restart_budget::pending_restart;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationCrashProbeReceipt {
    pub agent_id: AgentId,
    pub process_lease_valid: bool,
    pub restart_pending: bool,
    pub intent_sha256: Sha256Digest,
    pub release_transaction_sha256: Sha256Digest,
}

#[derive(Debug, Error)]
pub enum QualificationCrashProbeError {
    #[error(transparent)]
    Supervisor(#[from] crate::SupervisorError),
    #[error(transparent)]
    SignedIntent(#[from] crate::SignedIntentError),
    #[error(transparent)]
    ReleaseTransaction(#[from] crate::release_transaction::ReleaseTransactionError),
    #[error(transparent)]
    RestartBudget(#[from] crate::restart_budget::RestartBudgetError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("qualification crash probe invariant failed: {0}")]
    Invalid(String),
}

pub fn publish_qualification_crash_probe(
    run_root: &Path,
    agent_id: AgentId,
) -> Result<QualificationCrashProbeReceipt, QualificationCrashProbeError> {
    std::fs::create_dir_all(run_root)?;
    let source_release = ReleaseId::parse("qualification-v1")
        .map_err(|error| QualificationCrashProbeError::Invalid(error.to_string()))?;
    let target_release = ReleaseId::parse("qualification-v2")
        .map_err(|error| QualificationCrashProbeError::Invalid(error.to_string()))?;
    let lease = ProcessLease {
        schema_version: crate::lease::PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: agent_id.clone(),
        spawn_generation: 1,
        release_id: source_release.clone(),
        identity: ProcessIdentity::new(42_424, "qualification-crash-probe")
            .map_err(|error| QualificationCrashProbeError::Invalid(error.to_string()))?,
    };
    write_lease(run_root, &lease)?;
    claim_restart(
        run_root,
        3,
        Duration::from_secs(300),
        Duration::from_millis(250),
    )?;

    let grant_sha256 = Sha256Digest::for_bytes(b"qualification-crash-probe-grant");
    let intent = SignedSupervisorIntent::new(
        grant_sha256.clone(),
        agent_id.to_string(),
        H7H89ProductionTransition::Upgrade,
        source_release.to_string(),
        target_release.to_string(),
        0,
        1,
        1,
        SignedIntentStatus::Prepared,
    )?;
    let transaction = DurableReleaseTransaction::new(
        agent_id.to_string(),
        ReleaseTransactionKind::Upgrade,
        source_release.to_string(),
        target_release.to_string(),
        Some(source_release.to_string()),
        None,
        None,
        0,
        1,
    )?
    .with_authority(grant_sha256, 1)?
    .with_phase(ReleaseTransactionPhase::Prepared)?;
    write_release_transaction(run_root, &transaction)?;
    write_intent(run_root, &intent)?;
    inspect_qualification_crash_probe(run_root, &agent_id)
}

pub fn inspect_qualification_crash_probe(
    run_root: &Path,
    expected_agent_id: &AgentId,
) -> Result<QualificationCrashProbeReceipt, QualificationCrashProbeError> {
    let lease = read_lease(run_root)?.ok_or_else(|| {
        QualificationCrashProbeError::Invalid("process lease is missing".to_string())
    })?;
    validate_lease(&lease, expected_agent_id, 1, AgentLifecycle::Starting)?;
    let restart_pending = pending_restart(run_root, 3)?.is_some();
    let intent = read_intent(run_root)?.ok_or_else(|| {
        QualificationCrashProbeError::Invalid("signed intent is missing".to_string())
    })?;
    let transaction = read_release_transaction(run_root)?.ok_or_else(|| {
        QualificationCrashProbeError::Invalid("release transaction is missing".to_string())
    })?;
    if intent.agent_id != expected_agent_id.to_string()
        || transaction.agent_id != expected_agent_id.to_string()
        || transaction.grant_sha256.as_ref() != Some(&intent.grant_sha256)
        || transaction.authority_epoch != Some(intent.authority_epoch)
        || intent.source_release != transaction.source_release
        || intent.target_release != transaction.target_release
    {
        return Err(QualificationCrashProbeError::Invalid(
            "durable records do not bind the same operation".to_string(),
        ));
    }
    Ok(QualificationCrashProbeReceipt {
        agent_id: expected_agent_id.clone(),
        process_lease_valid: true,
        restart_pending,
        intent_sha256: intent.intent_sha256,
        release_transaction_sha256: transaction.transaction_sha256,
    })
}
