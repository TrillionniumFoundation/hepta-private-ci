//! H8/H9 qualification-only supervisor rollback state machine.
//!
//! This is a deterministic shadow controller.  It models the durable CAS and
//! recovery witnesses needed by a real supervisor without owning a process,
//! socket, provider, channel, or production release.  Every receipt and
//! state carries explicit false authority/effect flags.

use codex_hepta_contracts::QualificationGovernanceReceipt;
use codex_hepta_contracts::QualificationReceiptStatus;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

pub const H8_H9_SHADOW_SCHEMA_VERSION: u32 = 1;
pub const H8_H9_SHADOW_NAMESPACE: &str = "local_qualification_only";
pub const H8_H9_SHADOW_PRODUCTION_AUTHORITY: bool = false;
pub const H8_H9_SHADOW_EXTERNAL_EFFECTS: bool = false;
pub const H8_H9_SHADOW_PROMOTION_ELIGIBLE: bool = false;
pub const H8_H9_SHADOW_PRODUCTION_CALLER: bool = false;
pub const H8_H9_SHADOW_PRODUCTION_WRITER: bool = false;
pub const H8_H9_SHADOW_EFFECT_AUTHORITY: bool = false;
pub const H8_H9_SHADOW_OPERATOR_ACCEPTANCE: bool = false;
pub const H8_H9_SHADOW_PROMOTION: bool = false;
pub const H8_H9_SHADOW_G5_ALLOWED: bool = false;
pub const H8_H9_SHADOW_EXECUTE_ALLOWED: bool = false;
pub const H8_H9_SHADOW_GOVERNANCE_BYPASS: bool = false;
const STATE_DOMAIN: &[u8] = b"hepta-supervisor:h8-h9-shadow-state:v1";
const OPERATION_DOMAIN: &[u8] = b"hepta-supervisor:h8-h9-shadow-operation:v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum H8H9RollbackPhase {
    Cold,
    Running,
    RollbackPrepared,
    RecoveryRequired,
    Failed,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H8H9PendingRollback {
    pub operation_id: Sha256Digest,
    pub owner_id: String,
    pub source_release: String,
    pub target_release: String,
    pub expected_revision: u64,
    pub authority_epoch: u64,
    pub callback_seq: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H8H9SupervisorState {
    pub schema_version: u32,
    pub namespace: String,
    pub agent_id: String,
    pub owner_id: String,
    pub authority_epoch: u64,
    pub revision: u64,
    pub active_release: String,
    pub previous_release: Option<String>,
    pub phase: H8H9RollbackPhase,
    pub pending: Option<H8H9PendingRollback>,
    pub completed_operation_ids: Vec<Sha256Digest>,
    pub last_receipt: Option<QualificationGovernanceReceipt>,
    pub production_authority: bool,
    pub external_effects: bool,
    pub promotion_eligible: bool,
    pub production_caller: bool,
    pub production_writer: bool,
    pub effect_authority: bool,
    pub operator_acceptance: bool,
    pub promotion: bool,
    pub g5_allowed: bool,
    pub execute_allowed: bool,
    pub governance_bypass: bool,
    pub state_sha256: Sha256Digest,
}

#[derive(Serialize)]
struct StateDigest<'a> {
    schema_version: u32,
    namespace: &'a str,
    agent_id: &'a str,
    owner_id: &'a str,
    authority_epoch: u64,
    revision: u64,
    active_release: &'a str,
    previous_release: &'a Option<String>,
    phase: H8H9RollbackPhase,
    pending: &'a Option<H8H9PendingRollback>,
    completed_operation_ids: &'a Vec<Sha256Digest>,
    production_authority: bool,
    external_effects: bool,
    promotion_eligible: bool,
    production_caller: bool,
    production_writer: bool,
    effect_authority: bool,
    operator_acceptance: bool,
    promotion: bool,
    g5_allowed: bool,
    execute_allowed: bool,
    governance_bypass: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum H8H9RecoveryOutcome {
    NoPending,
    Recovered(QualificationGovernanceReceipt),
    NeedsOperator(QualificationGovernanceReceipt),
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum H8H9SupervisorError {
    #[error("invalid H8/H9 qualification supervisor state: {0}")]
    Invalid(String),
    #[error("H8/H9 qualification supervisor state digest mismatch")]
    StateDigestMismatch,
    #[error(
        "H8/H9 qualification supervisor revision fence mismatch: expected {expected}, actual {actual}"
    )]
    RevisionFence { expected: u64, actual: u64 },
    #[error(
        "H8/H9 qualification supervisor authority epoch mismatch: expected {expected}, actual {actual}"
    )]
    AuthorityEpochFence { expected: u64, actual: u64 },
    #[error("H8/H9 qualification supervisor callback owner is stale")]
    StaleOwner,
    #[error("H8/H9 qualification supervisor callback was already committed")]
    DuplicateCallback,
    #[error("H8/H9 qualification supervisor has a pending rollback")]
    PendingOperation,
    #[error("H8/H9 qualification supervisor has no pending rollback")]
    NoPendingRollback,
    #[error("H8/H9 qualification supervisor operation id mismatch")]
    OperationMismatch,
    #[error("H8/H9 qualification supervisor callback sequence is not contiguous")]
    CallbackSequence,
    #[error("H8/H9 qualification supervisor predecessor CAS mismatch")]
    PredecessorMismatch,
    #[error("H8/H9 qualification supervisor cannot recover an ambiguous power-loss state")]
    AmbiguousRecovery,
    #[error("H8/H9 qualification receipt failed validation: {0}")]
    Receipt(String),
    #[error("H8/H9 qualification supervisor snapshot serialization failed: {0}")]
    Serialization(String),
}

/// Shadow-only rollback controller.  It never starts/stops a process or
/// mutates a fleet registry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct H8H9ShadowSupervisor {
    state: H8H9SupervisorState,
}

impl H8H9ShadowSupervisor {
    pub fn new(
        agent_id: impl Into<String>,
        owner_id: impl Into<String>,
        authority_epoch: u64,
        active_release: impl Into<String>,
    ) -> Result<Self, H8H9SupervisorError> {
        let mut state = H8H9SupervisorState {
            schema_version: H8_H9_SHADOW_SCHEMA_VERSION,
            namespace: H8_H9_SHADOW_NAMESPACE.to_string(),
            agent_id: agent_id.into(),
            owner_id: owner_id.into(),
            authority_epoch,
            revision: 0,
            active_release: active_release.into(),
            previous_release: None,
            phase: H8H9RollbackPhase::Running,
            pending: None,
            completed_operation_ids: Vec::new(),
            last_receipt: None,
            production_authority: H8_H9_SHADOW_PRODUCTION_AUTHORITY,
            external_effects: H8_H9_SHADOW_EXTERNAL_EFFECTS,
            promotion_eligible: H8_H9_SHADOW_PROMOTION_ELIGIBLE,
            production_caller: H8_H9_SHADOW_PRODUCTION_CALLER,
            production_writer: H8_H9_SHADOW_PRODUCTION_WRITER,
            effect_authority: H8_H9_SHADOW_EFFECT_AUTHORITY,
            operator_acceptance: H8_H9_SHADOW_OPERATOR_ACCEPTANCE,
            promotion: H8_H9_SHADOW_PROMOTION,
            g5_allowed: H8_H9_SHADOW_G5_ALLOWED,
            execute_allowed: H8_H9_SHADOW_EXECUTE_ALLOWED,
            governance_bypass: H8_H9_SHADOW_GOVERNANCE_BYPASS,
            state_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        state.state_sha256 = state.compute_digest()?;
        let machine = Self { state };
        machine.validate()?;
        Ok(machine)
    }

    pub fn state(&self) -> &H8H9SupervisorState {
        &self.state
    }

    pub fn state_digest(&self) -> &Sha256Digest {
        &self.state.state_sha256
    }

    /// Current durable revision used by callback CAS fences.
    pub const fn revision(&self) -> u64 {
        self.state.revision
    }

    /// Current authority epoch pinned to this shadow state.
    pub const fn authority_epoch(&self) -> u64 {
        self.state.authority_epoch
    }

    pub fn pending_operation_id(&self) -> Option<&Sha256Digest> {
        self.state
            .pending
            .as_ref()
            .map(|pending| &pending.operation_id)
    }

    pub fn validate(&self) -> Result<(), H8H9SupervisorError> {
        self.state.validate()
    }

    /// Prepare a rollback with a strict revision, authority epoch, owner, and
    /// predecessor-state CAS.  Preparation is durable state in the shadow
    /// machine but does not imply that the target process was started.
    pub fn prepare_rollback(
        &mut self,
        expected_revision: u64,
        expected_authority_epoch: u64,
        owner_id: &str,
        target_release: impl Into<String>,
    ) -> Result<QualificationGovernanceReceipt, H8H9SupervisorError> {
        self.validate()?;
        self.check_fences(expected_revision, expected_authority_epoch)?;
        if owner_id != self.state.owner_id {
            return Err(H8H9SupervisorError::StaleOwner);
        }
        if self.state.pending.is_some() {
            return Err(H8H9SupervisorError::PendingOperation);
        }
        if self.state.phase != H8H9RollbackPhase::Running {
            return Err(H8H9SupervisorError::Invalid(
                "rollback preparation requires the running phase".to_string(),
            ));
        }
        let target_release = target_release.into();
        validate_release(&target_release)?;
        if target_release == self.state.active_release {
            return Err(H8H9SupervisorError::Invalid(
                "rollback target is already active".to_string(),
            ));
        }
        let predecessor = self.state.state_sha256.clone();
        let operation_id = operation_digest(
            &self.state.agent_id,
            owner_id,
            &self.state.active_release,
            &target_release,
            expected_revision,
            expected_authority_epoch,
            &predecessor,
        );
        let next_revision = expected_revision
            .checked_add(1)
            .ok_or_else(|| H8H9SupervisorError::Invalid("revision overflow".to_string()))?;
        // The prior receipt is bound to the old state head.  Drop it before
        // recomputing the new digest; `receipt` below installs the new bound
        // witness after the CAS mutation is complete.
        self.state.last_receipt = None;
        self.state.pending = Some(H8H9PendingRollback {
            operation_id: operation_id.clone(),
            owner_id: owner_id.to_string(),
            source_release: self.state.active_release.clone(),
            target_release,
            expected_revision,
            authority_epoch: expected_authority_epoch,
            callback_seq: 0,
        });
        self.state.phase = H8H9RollbackPhase::RollbackPrepared;
        self.state.revision = next_revision;
        self.refresh_digest()?;
        self.receipt(
            "rollback_prepare",
            operation_id,
            owner_id,
            expected_revision,
            next_revision,
            Some(predecessor),
            QualificationReceiptStatus::Prepared,
        )
    }

    /// Atomically transfer the shadow owner under the same revision and
    /// authority-epoch fences used by rollback callbacks.  This only changes
    /// the durable qualification owner witness; it never grants process,
    /// provider, channel, execution, or promotion authority.
    pub fn transfer_owner(
        &mut self,
        expected_revision: u64,
        expected_authority_epoch: u64,
        current_owner: &str,
        new_owner: impl Into<String>,
    ) -> Result<QualificationGovernanceReceipt, H8H9SupervisorError> {
        self.validate()?;
        self.check_fences(expected_revision, expected_authority_epoch)?;
        if current_owner != self.state.owner_id {
            return Err(H8H9SupervisorError::StaleOwner);
        }
        if self.state.pending.is_some() {
            return Err(H8H9SupervisorError::PendingOperation);
        }
        if self.state.phase != H8H9RollbackPhase::Running {
            return Err(H8H9SupervisorError::Invalid(
                "owner transfer requires the running phase".to_string(),
            ));
        }
        let new_owner = new_owner.into();
        validate_release(&new_owner)?;
        if new_owner == self.state.owner_id {
            return Err(H8H9SupervisorError::Invalid(
                "owner transfer target is already the current owner".to_string(),
            ));
        }
        let predecessor = self.state.state_sha256.clone();
        let operation_id = operation_digest(
            &self.state.agent_id,
            current_owner,
            &self.state.owner_id,
            &new_owner,
            expected_revision,
            expected_authority_epoch,
            &predecessor,
        );
        let next_revision = expected_revision
            .checked_add(1)
            .ok_or_else(|| H8H9SupervisorError::Invalid("revision overflow".to_string()))?;
        self.state.last_receipt = None;
        self.state.owner_id = new_owner.clone();
        self.state.revision = next_revision;
        self.refresh_digest()?;
        self.receipt(
            "owner_transfer",
            operation_id,
            &new_owner,
            expected_revision,
            next_revision,
            Some(predecessor),
            QualificationReceiptStatus::Committed,
        )
    }

    /// Commit the callback exactly once.  A callback from an old owner/epoch
    /// or revision is rejected before touching state; a callback replay after
    /// commit returns `DuplicateCallback`.
    pub fn commit_rollback(
        &mut self,
        expected_revision: u64,
        expected_authority_epoch: u64,
        owner_id: &str,
        operation_id: &Sha256Digest,
        callback_seq: u32,
    ) -> Result<QualificationGovernanceReceipt, H8H9SupervisorError> {
        self.validate()?;
        if self
            .state
            .completed_operation_ids
            .iter()
            .any(|completed| completed == operation_id)
        {
            return Err(H8H9SupervisorError::DuplicateCallback);
        }
        self.check_fences(expected_revision, expected_authority_epoch)?;
        let pending = self
            .state
            .pending
            .clone()
            .ok_or(H8H9SupervisorError::NoPendingRollback)?;
        if owner_id != pending.owner_id {
            return Err(H8H9SupervisorError::StaleOwner);
        }
        if pending.operation_id != *operation_id {
            return Err(H8H9SupervisorError::OperationMismatch);
        }
        if callback_seq != pending.callback_seq.saturating_add(1) {
            return Err(H8H9SupervisorError::CallbackSequence);
        }
        if self.state.phase != H8H9RollbackPhase::RollbackPrepared {
            return Err(H8H9SupervisorError::Invalid(
                "rollback callback arrived in a non-prepared phase".to_string(),
            ));
        }
        let predecessor = self.state.state_sha256.clone();
        let next_revision = expected_revision
            .checked_add(1)
            .ok_or_else(|| H8H9SupervisorError::Invalid("revision overflow".to_string()))?;
        self.state.last_receipt = None;
        self.state.previous_release = Some(self.state.active_release.clone());
        self.state.active_release = pending.target_release;
        self.state.pending = None;
        self.state.phase = H8H9RollbackPhase::Running;
        self.state.revision = next_revision;
        self.state
            .completed_operation_ids
            .push(operation_id.clone());
        if self.state.completed_operation_ids.len() > 16 {
            self.state.completed_operation_ids.remove(0);
        }
        self.refresh_digest()?;
        self.receipt(
            "rollback_commit",
            operation_id.clone(),
            owner_id,
            expected_revision,
            next_revision,
            Some(predecessor),
            QualificationReceiptStatus::Committed,
        )
    }

    /// Rehydrate a snapshot after a power loss.  If the observed release is
    /// exactly the pending target, the operation is completed idempotently;
    /// if it is the source or unknown, the machine remains fail-closed and
    /// emits a `RecoveryRequired` receipt.
    pub fn recover_after_power_loss(
        &mut self,
        new_authority_epoch: u64,
        observed_release: Option<&str>,
    ) -> Result<H8H9RecoveryOutcome, H8H9SupervisorError> {
        self.validate()?;
        if new_authority_epoch <= self.state.authority_epoch {
            return Err(H8H9SupervisorError::AuthorityEpochFence {
                expected: self.state.authority_epoch + 1,
                actual: new_authority_epoch,
            });
        }
        // An epoch change invalidates a receipt produced under the previous
        // authority lease.  It is replaced below when a pending operation is
        // deterministically recovered, or intentionally omitted for a clean
        // no-pending restart.
        self.state.last_receipt = None;
        self.state.authority_epoch = new_authority_epoch;
        let Some(pending) = self.state.pending.clone() else {
            self.refresh_digest()?;
            return Ok(H8H9RecoveryOutcome::NoPending);
        };
        let predecessor = self.state.state_sha256.clone();
        match observed_release {
            Some(observed) if observed == pending.target_release => {
                let expected_revision = self.state.revision;
                let next_revision = expected_revision
                    .checked_add(1)
                    .ok_or_else(|| H8H9SupervisorError::Invalid("revision overflow".to_string()))?;
                self.state.previous_release = Some(self.state.active_release.clone());
                self.state.active_release = pending.target_release;
                self.state.pending = None;
                self.state.phase = H8H9RollbackPhase::Running;
                self.state.revision = next_revision;
                self.state
                    .completed_operation_ids
                    .push(pending.operation_id.clone());
                if self.state.completed_operation_ids.len() > 16 {
                    self.state.completed_operation_ids.remove(0);
                }
                self.refresh_digest()?;
                let receipt = self.receipt(
                    "rollback_recovered",
                    pending.operation_id,
                    &pending.owner_id,
                    expected_revision,
                    next_revision,
                    Some(predecessor),
                    QualificationReceiptStatus::Recovered,
                )?;
                Ok(H8H9RecoveryOutcome::Recovered(receipt))
            }
            _ => {
                self.state.phase = H8H9RollbackPhase::RecoveryRequired;
                self.refresh_digest()?;
                let receipt = self.receipt(
                    "rollback_recovery_required",
                    pending.operation_id,
                    &pending.owner_id,
                    self.state.revision.saturating_sub(1),
                    self.state.revision,
                    Some(predecessor),
                    QualificationReceiptStatus::RecoveryRequired,
                )?;
                Ok(H8H9RecoveryOutcome::NeedsOperator(receipt))
            }
        }
    }

    pub fn snapshot(&self) -> Result<Vec<u8>, H8H9SupervisorError> {
        self.validate()?;
        serde_json::to_vec(&self.state)
            .map_err(|error| H8H9SupervisorError::Serialization(error.to_string()))
    }

    pub fn rehydrate(snapshot: &[u8]) -> Result<Self, H8H9SupervisorError> {
        let state: H8H9SupervisorState = serde_json::from_slice(snapshot)
            .map_err(|error| H8H9SupervisorError::Serialization(error.to_string()))?;
        let machine = Self { state };
        machine.validate()?;
        Ok(machine)
    }

    fn check_fences(
        &self,
        expected_revision: u64,
        expected_authority_epoch: u64,
    ) -> Result<(), H8H9SupervisorError> {
        if expected_revision != self.state.revision {
            return Err(H8H9SupervisorError::RevisionFence {
                expected: expected_revision,
                actual: self.state.revision,
            });
        }
        if expected_authority_epoch != self.state.authority_epoch {
            return Err(H8H9SupervisorError::AuthorityEpochFence {
                expected: expected_authority_epoch,
                actual: self.state.authority_epoch,
            });
        }
        Ok(())
    }

    fn refresh_digest(&mut self) -> Result<(), H8H9SupervisorError> {
        self.state.state_sha256 = self.state.compute_digest()?;
        self.state.validate()
    }

    #[allow(clippy::too_many_arguments)]
    fn receipt(
        &mut self,
        operation: &str,
        operation_id: Sha256Digest,
        owner_id: &str,
        expected_revision: u64,
        committed_revision: u64,
        predecessor_state_sha256: Option<Sha256Digest>,
        status: QualificationReceiptStatus,
    ) -> Result<QualificationGovernanceReceipt, H8H9SupervisorError> {
        let receipt = QualificationGovernanceReceipt::new(
            self.state.agent_id.clone(),
            operation,
            operation_id,
            owner_id.to_string(),
            expected_revision,
            committed_revision,
            self.state.authority_epoch,
            predecessor_state_sha256,
            self.state.state_sha256.clone(),
            status,
        )
        .map_err(H8H9SupervisorError::Receipt)?;
        self.state.last_receipt = Some(receipt.clone());
        Ok(receipt)
    }
}

impl H8H9SupervisorState {
    pub fn validate(&self) -> Result<(), H8H9SupervisorError> {
        if self.schema_version != H8_H9_SHADOW_SCHEMA_VERSION
            || self.namespace != H8_H9_SHADOW_NAMESPACE
            || self.production_authority
            || self.external_effects
            || self.promotion_eligible
            || self.production_caller
            || self.production_writer
            || self.effect_authority
            || self.operator_acceptance
            || self.promotion
            || self.g5_allowed
            || self.execute_allowed
            || self.governance_bypass
        {
            return Err(H8H9SupervisorError::Invalid(
                "H8/H9 state crosses the qualification boundary".to_string(),
            ));
        }
        for (label, value) in [
            ("agent id", self.agent_id.as_str()),
            ("owner id", self.owner_id.as_str()),
            ("active release", self.active_release.as_str()),
        ] {
            if value.trim().is_empty() || value.len() > 256 || value.as_bytes().contains(&0) {
                return Err(H8H9SupervisorError::Invalid(format!(
                    "H8/H9 {label} is malformed"
                )));
            }
        }
        if self.authority_epoch == 0 {
            return Err(H8H9SupervisorError::Invalid(
                "H8/H9 authority epoch must be non-zero".to_string(),
            ));
        }
        if self.completed_operation_ids.len() > 16 {
            return Err(H8H9SupervisorError::Invalid(
                "H8/H9 completed operation history exceeds its bound".to_string(),
            ));
        }
        if matches!(
            self.phase,
            H8H9RollbackPhase::Running | H8H9RollbackPhase::Cold
        ) && self.pending.is_some()
        {
            return Err(H8H9SupervisorError::Invalid(
                "H8/H9 running state cannot retain a pending rollback".to_string(),
            ));
        }
        if matches!(
            self.phase,
            H8H9RollbackPhase::RollbackPrepared | H8H9RollbackPhase::RecoveryRequired
        ) && self.pending.is_none()
        {
            return Err(H8H9SupervisorError::Invalid(
                "H8/H9 pending phase requires a rollback operation".to_string(),
            ));
        }
        for digest in &self.completed_operation_ids {
            parse_digest(digest, "completed operation")?;
        }
        if let Some(pending) = &self.pending {
            parse_digest(&pending.operation_id, "pending operation")?;
            if pending.authority_epoch == 0 || pending.expected_revision >= self.revision {
                return Err(H8H9SupervisorError::Invalid(
                    "H8/H9 pending rollback fence is malformed".to_string(),
                ));
            }
            if pending.expected_revision.checked_add(1) != Some(self.revision) {
                return Err(H8H9SupervisorError::Invalid(
                    "H8/H9 pending rollback revision is not the immediate predecessor".to_string(),
                ));
            }
            if pending.authority_epoch > self.authority_epoch {
                return Err(H8H9SupervisorError::Invalid(
                    "H8/H9 pending rollback authority epoch is from the future".to_string(),
                ));
            }
            if pending.owner_id != self.owner_id {
                return Err(H8H9SupervisorError::Invalid(
                    "H8/H9 pending rollback owner does not match state owner".to_string(),
                ));
            }
            if pending.source_release != self.active_release {
                return Err(H8H9SupervisorError::Invalid(
                    "H8/H9 pending rollback source does not match the active release".to_string(),
                ));
            }
            validate_release(&pending.source_release)?;
            validate_release(&pending.target_release)?;
            if pending.source_release == pending.target_release {
                return Err(H8H9SupervisorError::Invalid(
                    "H8/H9 pending rollback target equals the source release".to_string(),
                ));
            }
            if pending.callback_seq > 1 {
                return Err(H8H9SupervisorError::Invalid(
                    "H8/H9 callback sequence is outside the one-shot bound".to_string(),
                ));
            }
        }
        if let Some(receipt) = &self.last_receipt {
            receipt.validate().map_err(H8H9SupervisorError::Receipt)?;
            if receipt.resulting_state_sha256 != self.state_sha256
                || receipt.authority_epoch != self.authority_epoch
                || receipt.committed_revision != self.revision
            {
                return Err(H8H9SupervisorError::Receipt(
                    "qualification receipt is not bound to the current state head".to_string(),
                ));
            }
        }
        if self.state_sha256 != self.compute_digest()? {
            return Err(H8H9SupervisorError::StateDigestMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, H8H9SupervisorError> {
        let payload = serde_json::to_vec(&StateDigest {
            schema_version: self.schema_version,
            namespace: &self.namespace,
            agent_id: &self.agent_id,
            owner_id: &self.owner_id,
            authority_epoch: self.authority_epoch,
            revision: self.revision,
            active_release: &self.active_release,
            previous_release: &self.previous_release,
            phase: self.phase,
            pending: &self.pending,
            completed_operation_ids: &self.completed_operation_ids,
            production_authority: self.production_authority,
            external_effects: self.external_effects,
            promotion_eligible: self.promotion_eligible,
            production_caller: self.production_caller,
            production_writer: self.production_writer,
            effect_authority: self.effect_authority,
            operator_acceptance: self.operator_acceptance,
            promotion: self.promotion,
            g5_allowed: self.g5_allowed,
            execute_allowed: self.execute_allowed,
            governance_bypass: self.governance_bypass,
        })
        .map_err(|error| H8H9SupervisorError::Serialization(error.to_string()))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [STATE_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

fn operation_digest(
    agent_id: &str,
    owner_id: &str,
    source_release: &str,
    target_release: &str,
    expected_revision: u64,
    authority_epoch: u64,
    predecessor: &Sha256Digest,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    for value in [
        OPERATION_DOMAIN,
        agent_id.as_bytes(),
        owner_id.as_bytes(),
        source_release.as_bytes(),
        target_release.as_bytes(),
        predecessor.as_str().as_bytes(),
    ] {
        let len = u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes();
        hasher.update(len);
        hasher.update(value);
    }
    hasher.update(expected_revision.to_be_bytes());
    hasher.update(authority_epoch.to_be_bytes());
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn parse_digest(digest: &Sha256Digest, label: &'static str) -> Result<(), H8H9SupervisorError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map_err(|_| H8H9SupervisorError::Invalid(format!("H8/H9 {label} digest is malformed")))?;
    Ok(())
}

fn validate_release(value: &str) -> Result<(), H8H9SupervisorError> {
    if value.trim().is_empty()
        || value.len() > 256
        || value.as_bytes().contains(&0)
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(H8H9SupervisorError::Invalid(
            "H8/H9 release identity is malformed".to_string(),
        ));
    }
    Ok(())
}

pub type H8ShadowSupervisor = H8H9ShadowSupervisor;
pub type H9ShadowRollbackMachine = H8H9ShadowSupervisor;
pub type QualificationSupervisor = H8H9ShadowSupervisor;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rollback_cas_stale_owner_duplicate_and_power_loss_are_fail_closed() {
        let mut machine =
            H8H9ShadowSupervisor::new("agent-a", "owner-a", 1, "release-v2").expect("machine");
        let prepared = machine
            .prepare_rollback(0, 1, "owner-a", "release-v1")
            .expect("prepare");
        assert_eq!(prepared.status, QualificationReceiptStatus::Prepared);
        let operation = machine.pending_operation_id().cloned().expect("operation");
        assert_eq!(
            machine.commit_rollback(1, 1, "stale-owner", &operation, 1),
            Err(H8H9SupervisorError::StaleOwner)
        );
        assert_eq!(
            machine.commit_rollback(0, 1, "owner-a", &operation, 1),
            Err(H8H9SupervisorError::RevisionFence {
                expected: 0,
                actual: 1,
            })
        );
        assert_eq!(
            machine.commit_rollback(1, 0, "owner-a", &operation, 1),
            Err(H8H9SupervisorError::AuthorityEpochFence {
                expected: 0,
                actual: 1,
            })
        );
        let snapshot = machine.snapshot().expect("snapshot");
        let mut recovered = H8H9ShadowSupervisor::rehydrate(&snapshot).expect("rehydrate");
        let outcome = recovered
            .recover_after_power_loss(2, Some("release-v1"))
            .expect("recover target");
        assert!(matches!(outcome, H8H9RecoveryOutcome::Recovered(_)));
        assert_eq!(recovered.state().active_release, "release-v1");
        assert_eq!(
            recovered.commit_rollback(2, 2, "owner-a", &operation, 1),
            Err(H8H9SupervisorError::DuplicateCallback)
        );
    }

    #[test]
    fn owner_transfer_is_revision_and_owner_cas_bound() {
        let mut machine =
            H8H9ShadowSupervisor::new("agent-owner", "owner-a", 4, "release-v2").expect("machine");
        let receipt = machine
            .transfer_owner(0, 4, "owner-a", "owner-b")
            .expect("transfer");
        assert_eq!(receipt.operation, "owner_transfer");
        assert_eq!(machine.state().owner_id, "owner-b");
        assert_eq!(machine.revision(), 1);
        assert_eq!(
            machine.prepare_rollback(1, 4, "owner-a", "release-v1"),
            Err(H8H9SupervisorError::StaleOwner)
        );
        machine
            .prepare_rollback(1, 4, "owner-b", "release-v1")
            .expect("new owner prepare");
    }

    #[test]
    fn ambiguous_power_loss_requires_operator_and_does_not_promote() {
        let mut machine =
            H8H9ShadowSupervisor::new("agent-a", "owner-a", 1, "release-v2").expect("machine");
        machine
            .prepare_rollback(0, 1, "owner-a", "release-v1")
            .expect("prepare");
        let outcome = machine
            .recover_after_power_loss(2, Some("unknown-release"))
            .expect("recover");
        assert!(matches!(outcome, H8H9RecoveryOutcome::NeedsOperator(_)));
        assert_eq!(machine.state().phase, H8H9RollbackPhase::RecoveryRequired);
        assert!(!machine.state().production_authority);
        assert!(!machine.state().external_effects);
        assert!(!machine.state().promotion_eligible);
        assert!(!machine.state().production_caller);
        assert!(!machine.state().production_writer);
        assert!(!machine.state().effect_authority);
        assert!(!machine.state().operator_acceptance);
        assert!(!machine.state().promotion);
        assert!(!machine.state().g5_allowed);
        assert!(!machine.state().execute_allowed);
        assert!(!machine.state().governance_bypass);
    }
}
