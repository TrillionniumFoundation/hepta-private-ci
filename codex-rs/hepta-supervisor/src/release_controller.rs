//! Durable caller for independently signed release mutations. This module never signs grants.
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;
use tokio::time::Instant;
use tokio::time::sleep;

use crate::ControlStateDigest;
use crate::H7H89ProductionGrant;
use crate::H7H89ProductionTransition;
use crate::ProductionMutationReceipt;
use crate::ProductionMutationState;
use crate::ProductionMutationStatus;
use crate::SupervisorError;
use crate::SupervisordClient;
use crate::release_controller_store::JournalLock;
use crate::release_controller_store::bounded_error;
use crate::release_controller_store::read_bounded_regular_file;
use crate::release_controller_store::read_journal;
use crate::release_controller_store::validate_journal_path;
use crate::release_controller_store::validate_operation_id;
use crate::release_controller_store::write_journal;

pub const PRODUCTION_RELEASE_REQUEST_SCHEMA_VERSION: u32 = 1;
pub const PRODUCTION_RELEASE_JOURNAL_SCHEMA_VERSION: u32 = 1;
pub const MAX_PRODUCTION_RELEASE_REQUEST_BYTES: u64 = 256 * 1024;
pub const MAX_PRODUCTION_RELEASE_JOURNAL_BYTES: u64 = 256 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionReleaseRequestV1 {
    pub schema_version: u32,
    pub operation_id: String,
    pub agent_id: AgentId,
    pub grant: H7H89ProductionGrant,
    pub h7_envelope: H7SignedArtifactEnvelope,
}

impl ProductionReleaseRequestV1 {
    pub fn validate(&self) -> Result<(), ProductionReleaseControllerError> {
        if self.schema_version != PRODUCTION_RELEASE_REQUEST_SCHEMA_VERSION {
            return Err(ProductionReleaseControllerError::Invalid(
                "unsupported production release request schema".to_string(),
            ));
        }
        validate_operation_id(&self.operation_id)?;
        if self.agent_id.as_str() != self.grant.agent_id {
            return Err(ProductionReleaseControllerError::Invalid(
                "request Agent does not match the production grant".to_string(),
            ));
        }
        if self.grant.h7_envelope_sha256 != self.h7_envelope.envelope_sha256
            || self.grant.artifact_sha256 != self.h7_envelope.artifact_sha256
        {
            return Err(ProductionReleaseControllerError::Invalid(
                "production grant does not bind the supplied H7 envelope".to_string(),
            ));
        }
        let transition_matches = matches!(
            (self.grant.transition, self.h7_envelope.transition),
            (
                H7H89ProductionTransition::Upgrade,
                codex_hepta_memory::H7SignedArtifactTransition::Reload
            ) | (
                H7H89ProductionTransition::Rollback,
                codex_hepta_memory::H7SignedArtifactTransition::Rollback
            )
        );
        if !transition_matches {
            return Err(ProductionReleaseControllerError::Invalid(
                "production grant transition does not bind the H7 transition".to_string(),
            ));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, ProductionReleaseControllerError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self)?;
        if bytes.len() as u64 > MAX_PRODUCTION_RELEASE_REQUEST_BYTES {
            return Err(ProductionReleaseControllerError::Invalid(
                "production release request exceeds the size bound".to_string(),
            ));
        }
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProductionReleaseCallerStatusV1 {
    Prepared,
    Accepted,
    Committed,
    RolledBack,
    RecoveryRequired,
    Aborted,
    Indeterminate,
}

impl ProductionReleaseCallerStatusV1 {
    #[must_use]
    pub const fn terminal(self) -> bool {
        matches!(self, Self::Committed | Self::RolledBack | Self::Aborted)
    }

    #[must_use]
    pub const fn replay_forbidden(self) -> bool {
        true
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionReleaseJournalV1 {
    pub schema_version: u32,
    pub operation_id: String,
    pub request_sha256: Sha256Digest,
    pub grant_sha256: Sha256Digest,
    pub agent_id: AgentId,
    pub transition: H7H89ProductionTransition,
    pub status: ProductionReleaseCallerStatusV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub accepted_state_digest: Option<ControlStateDigest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub accepted_receipt: Option<ProductionMutationReceipt>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub production_state: Option<ProductionMutationState>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_error: Option<String>,
    pub journal_sha256: Sha256Digest,
}

impl ProductionReleaseJournalV1 {
    fn prepared(request: &ProductionReleaseRequestV1, request_sha256: Sha256Digest) -> Self {
        Self {
            schema_version: PRODUCTION_RELEASE_JOURNAL_SCHEMA_VERSION,
            operation_id: request.operation_id.clone(),
            request_sha256,
            grant_sha256: request.grant.grant_sha256.clone(),
            agent_id: request.agent_id.clone(),
            transition: request.grant.transition,
            status: ProductionReleaseCallerStatusV1::Prepared,
            accepted_state_digest: None,
            accepted_receipt: None,
            production_state: None,
            last_error: None,
            journal_sha256: Sha256Digest::for_bytes(b"pending"),
        }
    }

    pub(crate) fn digest(&self) -> Result<Sha256Digest, ProductionReleaseControllerError> {
        let mut canonical = self.clone();
        canonical.journal_sha256 = Sha256Digest::for_bytes(b"pending");
        let mut bytes = b"hepta-supervisor:release-caller-journal:v1".to_vec();
        bytes.extend(serde_json::to_vec(&canonical)?);
        Ok(Sha256Digest::for_bytes(&bytes))
    }

    fn validate_request(
        &self,
        request: &ProductionReleaseRequestV1,
        request_sha256: &Sha256Digest,
    ) -> Result<(), ProductionReleaseControllerError> {
        if self.journal_sha256 != self.digest()?
            || self.schema_version != PRODUCTION_RELEASE_JOURNAL_SCHEMA_VERSION
            || self.operation_id != request.operation_id
            || &self.request_sha256 != request_sha256
            || self.grant_sha256 != request.grant.grant_sha256
            || self.agent_id != request.agent_id
            || self.transition != request.grant.transition
        {
            return Err(ProductionReleaseControllerError::Conflict(
                "existing caller journal belongs to different operation semantics".to_string(),
            ));
        }
        if self
            .accepted_receipt
            .as_ref()
            .is_some_and(|receipt| !receipt_matches(request, receipt))
        {
            return Err(ProductionReleaseControllerError::Conflict(
                "caller receipt binding mismatch".to_string(),
            ));
        }
        if self.status.terminal()
            && !self.production_state.as_ref().is_some_and(|state| {
                receipt_matches(request, &state.receipt)
                    && caller_status(state.receipt.status) == self.status
            })
        {
            return Err(ProductionReleaseControllerError::Conflict(
                "terminal journal has no matching owner witness".to_string(),
            ));
        }
        Ok(())
    }

    fn observe(
        &mut self,
        request: &ProductionReleaseRequestV1,
        state: ProductionMutationState,
    ) -> Result<(), ProductionReleaseControllerError> {
        if !receipt_matches(request, &state.receipt) {
            return Err(ProductionReleaseControllerError::Conflict(
                "supervisor production status belongs to different operation semantics".to_string(),
            ));
        }
        self.accepted_receipt = Some(state.receipt.clone());
        self.status = caller_status(state.receipt.status);
        self.production_state = Some(state);
        self.last_error = None;
        Ok(())
    }

    fn mark_indeterminate(&mut self, error: impl ToString) {
        self.status = ProductionReleaseCallerStatusV1::Indeterminate;
        self.last_error = Some(bounded_error(error.to_string()));
    }
}

pub struct ProductionReleaseController {
    client: SupervisordClient,
    journal_path: PathBuf,
}

impl ProductionReleaseController {
    pub fn new(
        client: SupervisordClient,
        journal_path: PathBuf,
    ) -> Result<Self, ProductionReleaseControllerError> {
        let journal_path = validate_journal_path(&journal_path)?;
        Ok(Self {
            client,
            journal_path,
        })
    }

    pub async fn dispatch(
        &self,
        request: &ProductionReleaseRequestV1,
        wait_timeout: Duration,
    ) -> Result<ProductionReleaseJournalV1, ProductionReleaseControllerError> {
        if wait_timeout > Duration::from_secs(3_600) {
            return Err(ProductionReleaseControllerError::Invalid(
                "wait exceeds one hour".to_string(),
            ));
        }
        let _lock = JournalLock::acquire(&self.journal_path)?;
        let request_sha256 = request.digest()?;
        if let Some(existing) = read_journal(&self.journal_path)? {
            existing.validate_request(request, &request_sha256)?;
            return self.recover_locked(request, existing, wait_timeout).await;
        }

        let context = self
            .client
            .production_mutation_context(request.agent_id.clone())
            .await?;
        if context.control_revision != request.grant.expected_control_revision
            || context.authority_epoch != request.grant.authority_epoch
        {
            return Err(ProductionReleaseControllerError::Conflict(
                "current signing context differs from grant".to_string(),
            ));
        }
        let snapshot = context.agent;
        validate_admission_snapshot(request, &snapshot)?;
        let mut journal = ProductionReleaseJournalV1::prepared(request, request_sha256);
        write_journal(&self.journal_path, &mut journal)?;

        let accepted = match request.grant.transition {
            H7H89ProductionTransition::Upgrade => {
                self.client
                    .signed_upgrade(
                        snapshot.control_fence,
                        request.grant.clone(),
                        request.h7_envelope.clone(),
                    )
                    .await
            }
            H7H89ProductionTransition::Rollback => {
                self.client
                    .signed_rollback(
                        snapshot.control_fence,
                        request.grant.clone(),
                        request.h7_envelope.clone(),
                    )
                    .await
            }
        };

        match accepted {
            Ok(accepted) => {
                let Some(receipt) = accepted.production_receipt else {
                    journal
                        .mark_indeterminate("signed supervisor RPC returned no production receipt");
                    write_journal(&self.journal_path, &mut journal)?;
                    return Ok(journal);
                };
                if !receipt_matches(request, &receipt) {
                    journal
                        .mark_indeterminate("signed supervisor RPC returned a mismatched receipt");
                    write_journal(&self.journal_path, &mut journal)?;
                    return Ok(journal);
                }
                journal.status = ProductionReleaseCallerStatusV1::Accepted;
                journal.accepted_state_digest = Some(accepted.accepted_state_digest);
                journal.accepted_receipt = Some(receipt);
                write_journal(&self.journal_path, &mut journal)?;
            }
            Err(error) => {
                journal.mark_indeterminate(&error);
                write_journal(&self.journal_path, &mut journal)?;
                return self.recover_locked(request, journal, wait_timeout).await;
            }
        }
        self.recover_locked(request, journal, wait_timeout).await
    }

    pub async fn recover(
        &self,
        request: &ProductionReleaseRequestV1,
        wait_timeout: Duration,
    ) -> Result<ProductionReleaseJournalV1, ProductionReleaseControllerError> {
        if wait_timeout > Duration::from_secs(3_600) {
            return Err(ProductionReleaseControllerError::Invalid(
                "wait exceeds one hour".to_string(),
            ));
        }
        let _lock = JournalLock::acquire(&self.journal_path)?;
        let request_sha256 = request.digest()?;
        let journal = read_journal(&self.journal_path)?.ok_or_else(|| {
            ProductionReleaseControllerError::Invalid(
                "production release recovery requires an existing journal".to_string(),
            )
        })?;
        journal.validate_request(request, &request_sha256)?;
        self.recover_locked(request, journal, wait_timeout).await
    }

    pub fn read_status(
        &self,
        request: &ProductionReleaseRequestV1,
    ) -> Result<ProductionReleaseJournalV1, ProductionReleaseControllerError> {
        let _lock = JournalLock::acquire(&self.journal_path)?;
        let request_sha256 = request.digest()?;
        let journal = read_journal(&self.journal_path)?.ok_or_else(|| {
            ProductionReleaseControllerError::Invalid(
                "production release journal does not exist".to_string(),
            )
        })?;
        journal.validate_request(request, &request_sha256)?;
        Ok(journal)
    }

    async fn recover_locked(
        &self,
        request: &ProductionReleaseRequestV1,
        mut journal: ProductionReleaseJournalV1,
        wait_timeout: Duration,
    ) -> Result<ProductionReleaseJournalV1, ProductionReleaseControllerError> {
        if journal.status.terminal() {
            return Ok(journal);
        }
        if wait_timeout > Duration::from_secs(3_600) {
            return Err(ProductionReleaseControllerError::Invalid(
                "wait exceeds one hour".to_string(),
            ));
        }
        let deadline = Instant::now().checked_add(wait_timeout).ok_or_else(|| {
            ProductionReleaseControllerError::Invalid("wait deadline overflow".to_string())
        })?;
        loop {
            match self
                .client
                .production_mutation_lookup(
                    request.agent_id.clone(),
                    request.grant.grant_sha256.clone(),
                )
                .await
            {
                Ok(Some(state)) => {
                    let unchanged = journal.production_state.as_ref() == Some(&state)
                        && journal.last_error.is_none();
                    if let Err(error) = journal.observe(request, state) {
                        journal.mark_indeterminate(&error);
                        write_journal(&self.journal_path, &mut journal)?;
                        return Ok(journal);
                    }
                    if !unchanged {
                        write_journal(&self.journal_path, &mut journal)?;
                    }
                    if journal.status.terminal()
                        || journal.status == ProductionReleaseCallerStatusV1::RecoveryRequired
                        || wait_timeout.is_zero()
                    {
                        return Ok(journal);
                    }
                }
                Ok(None) => {
                    journal.mark_indeterminate(
                        "supervisor has no durable production mutation witness; replay is forbidden",
                    );
                    write_journal(&self.journal_path, &mut journal)?;
                    return Ok(journal);
                }
                Err(error) => {
                    journal.mark_indeterminate(error);
                    write_journal(&self.journal_path, &mut journal)?;
                    return Ok(journal);
                }
            }
            if Instant::now() >= deadline {
                return Ok(journal);
            }
            sleep(
                Duration::from_millis(100).min(deadline.saturating_duration_since(Instant::now())),
            )
            .await;
        }
    }
}

#[derive(Debug, Error)]
pub enum ProductionReleaseControllerError {
    #[error("invalid production release controller input: {0}")]
    Invalid(String),
    #[error("production release controller conflict: {0}")]
    Conflict(String),
    #[error("production release controller is already running")]
    Busy,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
    #[error(transparent)]
    Supervisor(#[from] SupervisorError),
}

pub fn read_production_release_request(
    path: &Path,
) -> Result<ProductionReleaseRequestV1, ProductionReleaseControllerError> {
    let bytes = read_bounded_regular_file(path, MAX_PRODUCTION_RELEASE_REQUEST_BYTES)?;
    let request: ProductionReleaseRequestV1 = serde_json::from_slice(&bytes)?;
    request.validate()?;
    Ok(request)
}

fn validate_admission_snapshot(
    request: &ProductionReleaseRequestV1,
    snapshot: &crate::SupervisordAgentStatus,
) -> Result<(), ProductionReleaseControllerError> {
    if snapshot.agent_id != request.agent_id
        || snapshot.lifecycle_generation != request.grant.expected_lifecycle_generation
        || snapshot
            .current_release
            .as_ref()
            .map(ToString::to_string)
            .as_deref()
            != Some(request.grant.source_release.as_str())
        || snapshot.release_change_pending
    {
        return Err(ProductionReleaseControllerError::Conflict(
            "current supervisor snapshot does not satisfy the signed grant fences".to_string(),
        ));
    }
    if request.grant.transition == H7H89ProductionTransition::Rollback
        && snapshot
            .previous_release
            .as_ref()
            .map(ToString::to_string)
            .as_deref()
            != Some(request.grant.target_release.as_str())
    {
        return Err(ProductionReleaseControllerError::Conflict(
            "signed rollback target is not the current predecessor".to_string(),
        ));
    }
    Ok(())
}

fn receipt_matches(
    request: &ProductionReleaseRequestV1,
    receipt: &ProductionMutationReceipt,
) -> bool {
    receipt.grant_sha256 == request.grant.grant_sha256
        && receipt.agent_id == request.agent_id.as_str()
        && receipt.transition == request.grant.transition
        && receipt.source_release == request.grant.source_release
        && receipt.target_release == request.grant.target_release
        && request.grant.expected_control_revision.checked_add(1) == Some(receipt.control_revision)
}

fn caller_status(status: ProductionMutationStatus) -> ProductionReleaseCallerStatusV1 {
    match status {
        ProductionMutationStatus::Queued => ProductionReleaseCallerStatusV1::Accepted,
        ProductionMutationStatus::Committed => ProductionReleaseCallerStatusV1::Committed,
        ProductionMutationStatus::RolledBack => ProductionReleaseCallerStatusV1::RolledBack,
        ProductionMutationStatus::RecoveryRequired => {
            ProductionReleaseCallerStatusV1::RecoveryRequired
        }
        ProductionMutationStatus::Aborted => ProductionReleaseCallerStatusV1::Aborted,
    }
}

#[cfg(test)]
#[path = "release_controller_tests.rs"]
mod tests;
