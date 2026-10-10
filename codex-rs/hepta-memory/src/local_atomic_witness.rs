//! Explicit local-development lease/compact witness writer.
//!
//! H16 intentionally stopped at a read-only observer.  This module is the
//! smallest write-capable step after that observer: it takes one
//! `BEGIN IMMEDIATE` transaction, verifies the current Agent-local lease and
//! both local journal chains, verifies the compact fence and checkpoint
//! binding, and appends at most one `Rehydrated` compact event.  The lease is
//! not released here; the host lifecycle owner must make that decision in a
//! separate, explicit policy step.
//!
//! The writer is local-development-only.  It never writes KG/projection rows,
//! dispatches an outbox, invokes a provider, or claims an external effect.
//! Lease authority/owner epochs and the expiry deadline are persisted and
//! checked inside the same transaction as the compact witness append.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CompactCheckpoint;
use crate::CompactPersistenceAppend;
use crate::LocalCompactExecutor;
use crate::LocalCompactExecutorError;
use crate::LocalLeaseOutbox;
use crate::LocalLeaseOutboxError;
use crate::checkpoint_digest;

/// Schema version for the explicit local atomic witness writer receipt.
pub const LOCAL_ATOMIC_WITNESS_SCHEMA_VERSION: u32 = 1;
/// All rows written by this seam remain in the local-development namespace.
pub const LOCAL_ATOMIC_WITNESS_NAMESPACE: &str = "local_development_only";
/// The writer has no external-effect capability.
pub const LOCAL_ATOMIC_WITNESS_EXTERNAL_EFFECTS: bool = false;
/// The writer has no KG/projection authority.
pub const LOCAL_ATOMIC_WITNESS_KG_WRITE_AUTHORITY: bool = false;
/// No callback or lifecycle contributor is installed by this module.
pub const LOCAL_ATOMIC_WITNESS_LIFECYCLE_REGISTERED: bool = false;
/// Lease authority/owner epochs are persisted and checked by the writer.
pub const LOCAL_ATOMIC_WITNESS_LEASE_EPOCH_BOUND: bool = true;
/// The lease expiry deadline is persisted and checked by the writer.
pub const LOCAL_ATOMIC_WITNESS_LEASE_EXPIRY_BOUND: bool = true;

// Keep identity fields on the same framing/domain as the H14/H15 runtime
// envelope so a host can cross-check a writer receipt against its observed
// read plan.  Lease epochs and expiry are independently persisted in the
// schema-bound lease row and are checked again in the writer transaction.
const REHYDRATION_RUNTIME_BINDING_DOMAIN: &[u8] = b"hepta-memory:local-rehydration-runtime:v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalAtomicWitnessFault {
    /// Abort after inserting the compact event but before committing the
    /// transaction.  The caller can verify that no compact row remains.
    AfterWitnessInsertBeforeCommit,
}

#[derive(Debug, Error)]
pub enum LocalAtomicWitnessError {
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error(transparent)]
    Lease(#[from] LocalLeaseOutboxError),
    #[error(transparent)]
    Compact(#[from] LocalCompactExecutorError),
    #[error("invalid local atomic witness input: {0}")]
    Invalid(String),
    #[error("local atomic witness fence mismatch: {0}")]
    FenceMismatch(String),
    #[error("local atomic witness transaction was rolled back: {0}")]
    TransactionAborted(String),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalRehydrationWitnessReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub journal_id: String,
    pub operation_id: String,
    pub checkpoint_sha256: Sha256Digest,
    pub expected_revision: u64,
    pub witness_sequence: u64,
    pub lease_id_sha256: Sha256Digest,
    pub fencing_token_sha256: Sha256Digest,
    pub generation: u64,
    pub replayed: bool,
    pub external_effect: bool,
    pub kg_write_authority: bool,
    pub lifecycle_registered: bool,
    pub lease_epoch_bound: bool,
    pub lease_expiry_bound: bool,
}

impl LocalRehydrationWitnessReceipt {
    pub fn validate(&self) -> Result<(), LocalAtomicWitnessError> {
        if self.schema_version != LOCAL_ATOMIC_WITNESS_SCHEMA_VERSION
            || self.namespace != LOCAL_ATOMIC_WITNESS_NAMESPACE
        {
            return Err(LocalAtomicWitnessError::Invalid(
                "unsupported schema or namespace".to_string(),
            ));
        }
        if self.external_effect || self.kg_write_authority || self.lifecycle_registered {
            return Err(LocalAtomicWitnessError::Invalid(
                "witness receipt crosses the local-development boundary".to_string(),
            ));
        }
        if !self.lease_epoch_bound || !self.lease_expiry_bound {
            return Err(LocalAtomicWitnessError::Invalid(
                "witness receipt is missing schema-bound lease authority".to_string(),
            ));
        }
        if self.journal_id.trim().is_empty()
            || self.operation_id.trim().is_empty()
            || self.witness_sequence == 0
            || self.generation == 0
        {
            return Err(LocalAtomicWitnessError::Invalid(
                "witness receipt contains an invalid identity or sequence".to_string(),
            ));
        }
        validate_text(&self.journal_id, "journal id", /*max_bytes*/ 512)?;
        validate_text(&self.operation_id, "operation id", /*max_bytes*/ 512)?;
        for (label, digest) in [
            ("checkpoint digest", &self.checkpoint_sha256),
            ("lease identity digest", &self.lease_id_sha256),
            ("fencing-token identity digest", &self.fencing_token_sha256),
        ] {
            Sha256Digest::parse(digest.as_str().to_string()).map_err(|_| {
                LocalAtomicWitnessError::Invalid(format!(
                    "{label} must be a lowercase SHA-256 digest"
                ))
            })?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalRehydrationWitnessWrite {
    Appended(LocalRehydrationWitnessReceipt),
    Replay(LocalRehydrationWitnessReceipt),
}

impl LocalRehydrationWitnessWrite {
    pub fn receipt(&self) -> &LocalRehydrationWitnessReceipt {
        match self {
            Self::Appended(receipt) | Self::Replay(receipt) => receipt,
        }
    }

    pub fn is_replay(&self) -> bool {
        matches!(self, Self::Replay(_))
    }
}

/// Atomically append the local rehydration witness under the current lease
/// and compact fence.  The operation is explicit and bounded: no lifecycle
/// callback or background retry is installed, and the lease remains active
/// for the host owner to close or reconcile deliberately.
pub async fn write_local_rehydration_witness(
    lease: &LocalLeaseOutbox,
    executor: &LocalCompactExecutor,
    operation_id: impl Into<String>,
    checkpoint: &CompactCheckpoint,
    expected_revision: u64,
) -> Result<LocalRehydrationWitnessWrite, LocalAtomicWitnessError> {
    write_local_rehydration_witness_inner(
        lease,
        executor,
        operation_id.into(),
        checkpoint,
        expected_revision,
        /*fault*/ None,
    )
    .await
}

/// Fault-injection variant used by the local qualification tests.  It is
/// intentionally kept in the public local-only API so the transaction
/// rollback claim remains directly reproducible by a host harness.
pub async fn write_local_rehydration_witness_with_fault(
    lease: &LocalLeaseOutbox,
    executor: &LocalCompactExecutor,
    operation_id: impl Into<String>,
    checkpoint: &CompactCheckpoint,
    expected_revision: u64,
    fault: LocalAtomicWitnessFault,
) -> Result<LocalRehydrationWitnessWrite, LocalAtomicWitnessError> {
    write_local_rehydration_witness_inner(
        lease,
        executor,
        operation_id.into(),
        checkpoint,
        expected_revision,
        Some(fault),
    )
    .await
}

async fn write_local_rehydration_witness_inner(
    lease: &LocalLeaseOutbox,
    executor: &LocalCompactExecutor,
    operation_id: String,
    checkpoint: &CompactCheckpoint,
    expected_revision: u64,
    fault: Option<LocalAtomicWitnessFault>,
) -> Result<LocalRehydrationWitnessWrite, LocalAtomicWitnessError> {
    validate_text(&operation_id, "operation id", /*max_bytes*/ 512)?;
    checkpoint
        .rehydration_plan(expected_revision)
        .map_err(|error| LocalAtomicWitnessError::Invalid(error.to_string()))?;
    if !lease.store().is_same_local_store(executor.store()) {
        return Err(LocalAtomicWitnessError::Invalid(
            "lease and compact executor belong to different local stores".to_string(),
        ));
    }
    let fence = executor.fence();
    let compact_binding = executor.lease_binding().ok_or_else(|| {
        LocalAtomicWitnessError::FenceMismatch(
            "schema-bound lease/head binding is required for witness writes".to_string(),
        )
    })?;
    let lease_binding = lease.binding().ok_or_else(|| {
        LocalAtomicWitnessError::FenceMismatch(
            "explicit authority/owner/expiry lease binding is required for witness writes"
                .to_string(),
        )
    })?;
    if compact_binding.lease_id != lease.lease_id()
        || compact_binding.authority_epoch != lease_binding.authority_epoch
        || compact_binding.owner_epoch != lease_binding.owner_epoch
        || compact_binding.lease_expires_at_unix_seconds
            != lease_binding.lease_expires_at_unix_seconds
    {
        return Err(LocalAtomicWitnessError::FenceMismatch(
            "lease and compact schema bindings do not match".to_string(),
        ));
    }
    if lease.generation() != fence.generation || lease.fencing_token() != fence.fencing_token {
        return Err(LocalAtomicWitnessError::FenceMismatch(
            "lease generation/token does not match compact fence".to_string(),
        ));
    }
    if checkpoint.lease.snapshot.fence != *fence {
        return Err(LocalAtomicWitnessError::FenceMismatch(
            "checkpoint fence does not match compact executor fence".to_string(),
        ));
    }

    let store = lease.store();
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    let current_lease = lease
        .verify_current_in_transaction(&mut transaction)
        .await?;
    if current_lease.generation != fence.generation
        || current_lease.fencing_token != fence.fencing_token
        || current_lease.authority_epoch != Some(compact_binding.authority_epoch)
        || current_lease.owner_epoch != Some(compact_binding.owner_epoch)
        || current_lease.lease_expires_at_unix_seconds
            != Some(compact_binding.lease_expires_at_unix_seconds)
        || current_lease.lease_sha256 != compact_binding.lease_head_sha256
    {
        return Err(LocalAtomicWitnessError::FenceMismatch(
            "current lease head changed before witness append".to_string(),
        ));
    }

    let mut journal = executor.load_journal(&mut transaction).await?;
    let checkpoint_sha256 = checkpoint_digest(checkpoint)
        .map_err(LocalCompactExecutorError::from)
        .map_err(LocalAtomicWitnessError::from)?;
    let before = journal.entries().len();
    let append = journal
        .record_rehydration(&operation_id, &checkpoint_sha256, expected_revision)
        .map_err(LocalCompactExecutorError::from)
        .map_err(LocalAtomicWitnessError::from)?;
    for entry in &journal.entries()[before..] {
        executor.insert_event(&mut transaction, entry).await?;
    }
    if fault == Some(LocalAtomicWitnessFault::AfterWitnessInsertBeforeCommit)
        && before != journal.entries().len()
    {
        return Err(LocalAtomicWitnessError::TransactionAborted(
            "fault injected after compact witness insert".to_string(),
        ));
    }
    let witness = journal.rehydration(&operation_id).cloned().ok_or_else(|| {
        LocalAtomicWitnessError::Invalid(
            "compact journal accepted witness but returned none".to_string(),
        )
    })?;
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;

    let receipt = LocalRehydrationWitnessReceipt {
        schema_version: LOCAL_ATOMIC_WITNESS_SCHEMA_VERSION,
        namespace: LOCAL_ATOMIC_WITNESS_NAMESPACE.to_string(),
        journal_id: executor.journal_id().to_string(),
        operation_id,
        checkpoint_sha256,
        expected_revision,
        witness_sequence: witness.sequence,
        lease_id_sha256: identity_digest(b"lease", lease.lease_id()),
        fencing_token_sha256: identity_digest(b"fencing-token", lease.fencing_token()),
        generation: fence.generation,
        replayed: matches!(append, CompactPersistenceAppend::Replay { .. }),
        external_effect: LOCAL_ATOMIC_WITNESS_EXTERNAL_EFFECTS,
        kg_write_authority: LOCAL_ATOMIC_WITNESS_KG_WRITE_AUTHORITY,
        lifecycle_registered: LOCAL_ATOMIC_WITNESS_LIFECYCLE_REGISTERED,
        lease_epoch_bound: LOCAL_ATOMIC_WITNESS_LEASE_EPOCH_BOUND,
        lease_expiry_bound: LOCAL_ATOMIC_WITNESS_LEASE_EXPIRY_BOUND,
    };
    receipt.validate()?;
    Ok(if receipt.replayed {
        LocalRehydrationWitnessWrite::Replay(receipt)
    } else {
        LocalRehydrationWitnessWrite::Appended(receipt)
    })
}

impl CognitiveStore {
    /// Convenience method for the explicit host owner.  It does not register
    /// a lifecycle callback or alter any production authority flag.
    pub async fn write_local_rehydration_witness(
        &self,
        lease: &LocalLeaseOutbox,
        executor: &LocalCompactExecutor,
        operation_id: impl Into<String>,
        checkpoint: &CompactCheckpoint,
        expected_revision: u64,
    ) -> Result<LocalRehydrationWitnessWrite, LocalAtomicWitnessError> {
        if !self.is_same_local_store(lease.store()) || !self.is_same_local_store(executor.store()) {
            return Err(LocalAtomicWitnessError::Invalid(
                "writer store does not match lease and compact executor".to_string(),
            ));
        }
        write_local_rehydration_witness(
            lease,
            executor,
            operation_id,
            checkpoint,
            expected_revision,
        )
        .await
    }
}

fn identity_digest(kind: &[u8], value: &str) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, REHYDRATION_RUNTIME_BINDING_DOMAIN);
    hash_part(&mut hasher, kind);
    hash_part(&mut hasher, value.as_bytes());
    Sha256Digest::for_bytes(&hasher.finalize())
}

fn hash_part(hasher: &mut Sha256, value: &[u8]) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value);
}

fn validate_text(
    value: &str,
    label: &str,
    max_bytes: usize,
) -> Result<(), LocalAtomicWitnessError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(LocalAtomicWitnessError::Invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}
