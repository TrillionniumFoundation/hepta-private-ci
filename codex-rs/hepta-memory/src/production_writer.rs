//! Production durable writer/outbox capability.
//!
//! This module is the boundary between an externally-authorized supervisor
//! grant and the Agent-local durable journal. The older
//! `local_lease_outbox` API remains available for qualification and replay
//! tests; this wrapper refuses to open without an independently verified
//! authority lease and a WAL/FULL SQLite store. It does not invent a provider
//! or target effect: an embedding must explicitly attach a
//! `ProductionOutboxTarget` to dispatch a queued row.

use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::CognitiveStore;
use crate::LocalAdmission;
use crate::LocalLease;
use crate::LocalLeaseHeadDisposition;
use crate::LocalLeaseOutbox;
use crate::LocalLeaseOutboxError;
use crate::LocalOutcomeReceipt;
use crate::LocalOutcomeState;
use crate::LocalReplayFinalization;
use crate::LocalReconcileOutcome;
use crate::QueuedReceipt;
use crate::local_lease_outbox::InheritedQueuedReceipt;
use crate::local_lease_outbox::dispatch_operation_digest;

/// Schema version of the externally-authorized H4 writer boundary.
pub const PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION: u32 = 1;
/// Stable provenance namespace for production writer receipts.
pub const PRODUCTION_DURABLE_WRITER_NAMESPACE: &str = "production_durable_writer";
/// The store opened by `CognitiveStore` must use this journal mode.
pub const PRODUCTION_DURABLE_WRITER_JOURNAL_MODE: &str = "wal";
/// SQLite `PRAGMA synchronous` value for FULL.
pub const PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL: i64 = 2;

/// Errors returned by the production writer and dispatcher boundary.
#[derive(Debug, thiserror::Error)]
pub enum ProductionWriterError {
    #[error(transparent)]
    Local(#[from] LocalLeaseOutboxError),
    #[error("production authority rejected: {0}")]
    AuthorityRejected(String),
    #[error("production authority lease expired at {deadline}")]
    AuthorityExpired { deadline: u64 },
    #[error("production authority lease does not match Agent {0}")]
    AuthorityAgentMismatch(AgentId),
    #[error("production writer input is invalid: {0}")]
    Invalid(String),
    #[error("production writer durability precondition failed: {0}")]
    Durability(String),
    #[error("production writer receipt is stale or belongs to another authority")]
    StaleReceipt,
    #[error("production writer already has an active owner for this local lease")]
    WriterBusy,
    #[error("final-use authority rejected dispatch: {0}")]
    FinalUse(#[from] FinalUseError),
}

/// Opaque authority token supplied by an external grant verifier.
///
/// There is deliberately no seed/random/default constructor. The only public
/// constructor is named `from_verified_bytes`; callers are expected to obtain
/// the bytes from a supervisor/grant verifier. The token is never rendered or
/// serialized; only a one-way digest is used as the local SQLite fencing token.
#[derive(Clone, Eq, PartialEq)]
pub struct ProductionAuthorityToken(Arc<[u8]>);

impl ProductionAuthorityToken {
    pub fn from_verified_bytes(bytes: impl Into<Vec<u8>>) -> Result<Self, ProductionWriterError> {
        let bytes = bytes.into();
        if bytes.is_empty() || bytes.len() > 4096 || bytes.contains(&0) {
            return Err(ProductionWriterError::Invalid(
                "authority token must contain 1..=4096 non-NUL bytes".to_string(),
            ));
        }
        Ok(Self(Arc::from(bytes)))
    }

    fn fencing_digest(&self) -> Sha256Digest {
        let mut hasher = Sha256::new();
        hasher.update(b"hepta:production-authority-token:v1\0");
        hasher.update(self.0.as_ref());
        Sha256Digest::for_bytes(&hasher.finalize())
    }

    /// Bind the local fence to both the opaque verifier token and the exact
    /// signed grant it authorizes. Persisting only a token digest would let a
    /// lease be reopened under a different grant that reused the same
    /// token/epochs. The grant-bound digest makes that cross-grant reopen fail
    /// closed without adding a mutable column to the append-only lease journal.
    fn fencing_digest_for_grant(&self, grant_digest: &Sha256Digest) -> Sha256Digest {
        let mut hasher = Sha256::new();
        hasher.update(b"hepta:production-authority-token-grant:v2\0");
        hasher.update(grant_digest.as_str().as_bytes());
        hasher.update(self.0.as_ref());
        Sha256Digest::for_bytes(&hasher.finalize())
    }
}

impl fmt::Debug for ProductionAuthorityToken {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionAuthorityToken")
            .field("digest", &self.fencing_digest())
            .finish()
    }
}

/// Minimum externally supplied authority material needed by H4.
///
/// `grant_digest` identifies the signed supervisor/OPE grant. The opaque token
/// is supplied by that verifier and is not derived from a local seed. Epochs
/// and expiry are persisted in the lease chain and checked on each mutation.
#[derive(Clone, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionAuthorityLease {
    pub agent_id: AgentId,
    pub grant_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub lease_expires_at_unix_seconds: u64,
    #[serde(skip)]
    token: Option<ProductionAuthorityToken>,
}

impl fmt::Debug for ProductionAuthorityLease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionAuthorityLease")
            .field("agent_id", &self.agent_id)
            .field("grant_digest", &self.grant_digest)
            .field("authority_epoch", &self.authority_epoch)
            .field("owner_epoch", &self.owner_epoch)
            .field(
                "lease_expires_at_unix_seconds",
                &self.lease_expires_at_unix_seconds,
            )
            .field(
                "token",
                &self
                    .token
                    .as_ref()
                    .map(ProductionAuthorityToken::fencing_digest),
            )
            .finish()
    }
}

impl ProductionAuthorityLease {
    /// Construct lease material after an external verifier has checked the
    /// signed grant and supplied its opaque token. This performs shape checks
    /// only; `ProductionDurableWriter::open` still requires a verifier.
    pub fn from_verified_parts(
        agent_id: AgentId,
        grant_digest: Sha256Digest,
        authority_epoch: u64,
        owner_epoch: u64,
        lease_expires_at_unix_seconds: u64,
        token: ProductionAuthorityToken,
    ) -> Result<Self, ProductionWriterError> {
        if authority_epoch == 0 || owner_epoch == 0 {
            return Err(ProductionWriterError::Invalid(
                "authority and owner epochs must be non-zero".to_string(),
            ));
        }
        if lease_expires_at_unix_seconds == 0 {
            return Err(ProductionWriterError::Invalid(
                "authority lease expiry must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            agent_id,
            grant_digest,
            authority_epoch,
            owner_epoch,
            lease_expires_at_unix_seconds,
            token: Some(token),
        })
    }

    pub fn fencing_token_digest(&self) -> Result<Sha256Digest, ProductionWriterError> {
        self.token
            .as_ref()
            .map(|token| token.fencing_digest_for_grant(&self.grant_digest))
            .ok_or_else(|| {
                ProductionWriterError::AuthorityRejected(
                    "deserialized authority lease has no opaque token".to_string(),
                )
            })
    }

    pub fn is_expired_at(&self, now_unix_seconds: u64) -> bool {
        now_unix_seconds >= self.lease_expires_at_unix_seconds
    }

    fn validate_for_agent(&self, agent_id: &AgentId) -> Result<(), ProductionWriterError> {
        if &self.agent_id != agent_id {
            return Err(ProductionWriterError::AuthorityAgentMismatch(
                agent_id.clone(),
            ));
        }
        let now = now_unix_seconds()?;
        if self.is_expired_at(now) {
            return Err(ProductionWriterError::AuthorityExpired {
                deadline: self.lease_expires_at_unix_seconds,
            });
        }
        let _ = self.fencing_token_digest()?;
        Ok(())
    }
}

/// External verifier hook. Implementations should verify the signed grant,
/// scope, epoch, and opaque token before returning `Ok(())`.
///
/// The writer never treats a boolean field on the lease as authority and has
/// no built-in/self-signing implementation of this trait.
pub trait ProductionAuthorityVerifier: Send + Sync {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String>;
}

impl<F> ProductionAuthorityVerifier for F
where
    F: Fn(&ProductionAuthorityLease, &AgentId) -> Result<(), String> + Send + Sync,
{
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        self(authority, expected_agent)
    }
}

/// Durable writer bound to one externally-authorized lease.
#[derive(Clone)]
pub struct ProductionDurableWriter {
    store: CognitiveStore,
    authority: ProductionAuthorityLease,
    lease: LocalLeaseOutbox,
    lease_id: Arc<str>,
    // Retain the OS-level lock for the lifetime of the writer.  SQLite's
    // transaction lock serializes individual mutations, but it does not
    // establish the H4 single-writer boundary: two processes could otherwise
    // reopen the same active lease under the same grant and interleave
    // independent recovery decisions.  The lock is local qualification
    // plumbing only; it grants no authority and is released automatically on
    // process exit/drop.
    _writer_lock: Arc<DurableWriterLock>,
}

struct DurableWriterLock {
    _file: File,
    _path: PathBuf,
}

impl DurableWriterLock {
    fn acquire(store: &CognitiveStore, lease_id: &str) -> Result<Arc<Self>, ProductionWriterError> {
        let database_path = store.path();
        let parent = database_path.parent().ok_or_else(|| {
            ProductionWriterError::Durability(
                "cognitive database path has no parent for writer lock".to_string(),
            )
        })?;
        let canonical_parent = parent.canonicalize().map_err(|error| {
            ProductionWriterError::Durability(format!(
                "cannot canonicalize writer-lock parent {}: {error}",
                parent.display()
            ))
        })?;
        if canonical_parent != parent {
            return Err(ProductionWriterError::Durability(
                "writer-lock parent must be canonical".to_string(),
            ));
        }

        // Hash the lease id instead of placing caller text in a path.  The
        // database parent is already the private Agent-local root checked by
        // CognitiveStore, and retaining the file (rather than deleting it on
        // drop) prevents an inode-replacement race with another opener.
        let mut key = Vec::with_capacity(database_path.as_os_str().len() + lease_id.len() + 1);
        key.extend_from_slice(database_path.as_os_str().as_encoded_bytes());
        key.push(0);
        key.extend_from_slice(lease_id.as_bytes());
        let lock_digest = Sha256Digest::for_bytes(&key);
        let path = parent.join(format!(
            ".hepta-production-writer-{}.lock",
            lock_digest.as_str()
        ));
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&path)
            .map_err(|error| {
                ProductionWriterError::Durability(format!(
                    "cannot open writer lock {}: {error}",
                    path.display()
                ))
            })?;
        match file.try_lock() {
            Ok(()) => Ok(Arc::new(Self {
                _file: file,
                _path: path,
            })),
            Err(std::fs::TryLockError::WouldBlock) => Err(ProductionWriterError::WriterBusy),
            Err(std::fs::TryLockError::Error(error)) => Err(ProductionWriterError::Durability(
                format!("cannot acquire writer lock {}: {error}", path.display()),
            )),
        }
    }
}

impl fmt::Debug for ProductionDurableWriter {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionDurableWriter")
            .field("lease_id", &self.lease_id)
            .field("authority", &self.authority)
            .field("lease", &self.lease)
            .finish()
    }
}

impl ProductionDurableWriter {
    /// Open a writer only after external authority verification and a WAL/FULL
    /// durability check. Acquisition/reopen is CAS-protected by the
    /// append-only lease chain.
    pub async fn open<V>(
        store: CognitiveStore,
        authority: ProductionAuthorityLease,
        verifier: &V,
        lease_id: impl Into<String>,
        generation: u64,
    ) -> Result<Self, ProductionWriterError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        let lease_id = lease_id.into();
        validate_text(&lease_id, "production lease id", /*max_bytes*/ 512)?;
        verifier
            .verify(&authority, store.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)?;
        authority.validate_for_agent(store.owner_agent_id())?;
        verify_durable_store(&store).await?;
        let fencing_token = authority.fencing_token_digest()?.as_str().to_string();
        let binding = (
            authority.authority_epoch,
            authority.owner_epoch,
            authority.lease_expires_at_unix_seconds,
        );

        // Preserve the more specific stale-grant error for an active lease,
        // then acquire the lifetime writer lock before making any mutating
        // lease decision.  The second inspection closes the small race
        // between the preflight read and lock acquisition.
        let inspection = store.inspect_local_lease_head(&lease_id).await?;
        if let (LocalLeaseHeadDisposition::Active, Some(head)) =
            (inspection.disposition, inspection.head.as_ref())
            && (head.generation != generation
                || head.fencing_token != authority.fencing_token_digest()?.as_str()
                || head.authority_epoch != Some(binding.0)
                || head.owner_epoch != Some(binding.1)
                || head.lease_expires_at_unix_seconds != Some(binding.2))
        {
            return Err(ProductionWriterError::StaleReceipt);
        }
        let writer_lock = DurableWriterLock::acquire(&store, &lease_id)?;
        let inspection = store.inspect_local_lease_head(&lease_id).await?;
        let lease = match (inspection.disposition, inspection.head) {
            (LocalLeaseHeadDisposition::Missing, None) => store
                .acquire_host_bound_lease(
                    &lease_id,
                    binding.0,
                    binding.1,
                    generation,
                    fencing_token,
                    binding.2,
                )
                .await?
                .into_handle(),
            (LocalLeaseHeadDisposition::Active, Some(head)) => {
                if head.generation != generation
                    || head.fencing_token != authority.fencing_token_digest()?.as_str()
                    || head.authority_epoch != Some(binding.0)
                    || head.owner_epoch != Some(binding.1)
                    || head.lease_expires_at_unix_seconds != Some(binding.2)
                {
                    return Err(ProductionWriterError::StaleReceipt);
                }
                store
                    .reopen_host_bound_lease(head, binding.0, binding.1, binding.2)
                    .await?
            }
            (LocalLeaseHeadDisposition::ExpiredActive, Some(head)) => {
                // The new authority has already been independently verified
                // and is live. Close the exact expired predecessor first,
                // preserving its unresolved occurrences, then acquire the
                // successor generation through the append-only head CAS.
                // No outbox row is dispatched during takeover.
                let previous_authority_epoch =
                    head.authority_epoch.ok_or(ProductionWriterError::StaleReceipt)?;
                let previous_owner_epoch =
                    head.owner_epoch.ok_or(ProductionWriterError::StaleReceipt)?;
                let previous_expiry = head
                    .lease_expires_at_unix_seconds
                    .ok_or(ProductionWriterError::StaleReceipt)?;
                let expired = store
                    .reopen_host_bound_lease(
                        head,
                        previous_authority_epoch,
                        previous_owner_epoch,
                        previous_expiry,
                    )
                    .await?
                    .expire_lease()
                    .await?;
                store
                    .acquire_host_bound_lease_after_head(
                        &lease_id,
                        expired,
                        binding.0,
                        binding.1,
                        generation,
                        fencing_token,
                        binding.2,
                    )
                    .await?
                    .into_handle()
            }
            (
                LocalLeaseHeadDisposition::Released | LocalLeaseHeadDisposition::RolledBack,
                Some(head),
            ) => store
                .acquire_host_bound_lease_after_head(
                    &lease_id,
                    head,
                    binding.0,
                    binding.1,
                    generation,
                    fencing_token,
                    binding.2,
                )
                .await?
                .into_handle(),
            (LocalLeaseHeadDisposition::Missing, Some(_)) => {
                return Err(ProductionWriterError::StaleReceipt);
            }
            (_, None) => return Err(ProductionWriterError::StaleReceipt),
        };
        Ok(Self {
            store,
            authority,
            lease,
            lease_id: Arc::from(lease_id),
            _writer_lock: writer_lock,
        })
    }

    pub fn authority(&self) -> &ProductionAuthorityLease {
        &self.authority
    }

    pub fn lease_id(&self) -> &str {
        &self.lease_id
    }

    pub fn generation(&self) -> u64 {
        self.lease.generation()
    }

    pub fn store(&self) -> &CognitiveStore {
        &self.store
    }

    pub async fn admit(
        &self,
        occurrence_key: impl Into<String>,
        topic: impl Into<String>,
        payload_json: impl Into<String>,
    ) -> Result<ProductionQueuedReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        let occurrence_key = occurrence_key.into();
        let topic = topic.into();
        let payload_json = payload_json.into();
        let admission = self
            .lease
            .admit(&occurrence_key, &topic, &payload_json)
            .await?;
        let (receipt, replayed) = match admission {
            LocalAdmission::Queued(receipt) => (receipt, false),
            LocalAdmission::Replay(receipt) => (receipt, true),
        };
        ProductionQueuedReceipt::from_local(
            &self.authority,
            &topic,
            &payload_json,
            receipt,
            replayed,
        )
    }

    pub async fn recover(
        &self,
        occurrence_key: impl Into<String>,
    ) -> Result<ProductionRecoveryReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        let occurrence_key = occurrence_key.into();
        let result = self
            .lease
            .finalize_replayed_occurrence(&occurrence_key)
            .await?;
        Ok(ProductionRecoveryReceipt::from_local(
            &self.authority,
            self.lease_id(),
            &occurrence_key,
            result,
        ))
    }

    /// Recover one queued outbox row inherited from a terminal predecessor
    /// generation without creating another outbox identity.
    pub async fn recover_inherited_queued(
        &self,
        occurrence_key: impl Into<String>,
    ) -> Result<Option<ProductionQueuedReceipt>, ProductionWriterError> {
        self.verify_authority().await?;
        let occurrence_key = occurrence_key.into();
        self.lease
            .inherited_queued_receipt(&occurrence_key)
            .await?
            .map(|receipt| ProductionQueuedReceipt::from_inherited(&self.authority, self.generation(), receipt))
            .transpose()
    }

    pub async fn status(
        &self,
        occurrence_key: impl Into<String>,
    ) -> Result<LocalOutcomeState, ProductionWriterError> {
        self.verify_authority().await?;
        Ok(self.lease.status(occurrence_key).await?)
    }

    /// Reconcile an indeterminate occurrence under the current durable fence.
    ///
    /// The local journal permits this across an expired-owner handoff only
    /// after the predecessor fence is durably terminal. This method never
    /// dispatches a queued row.
    pub async fn reconcile(
        &self,
        occurrence_key: impl Into<String>,
        outcome: LocalReconcileOutcome,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        Ok(self.lease.reconcile(occurrence_key, outcome).await?.into())
    }

    pub async fn mark_indeterminate(
        &self,
        occurrence_key: impl Into<String>,
        reason: impl Into<String>,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        Ok(self
            .lease
            .mark_indeterminate(occurrence_key, reason)
            .await?
            .into())
    }

    pub async fn apply(
        &self,
        occurrence_key: impl Into<String>,
        receipt: impl Into<String>,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        Ok(self.lease.apply(occurrence_key, receipt).await?.into())
    }

    pub async fn reject(
        &self,
        occurrence_key: impl Into<String>,
        reason: impl Into<String>,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        Ok(self.lease.reject(occurrence_key, reason).await?.into())
    }

    pub async fn rollback_occurrence(
        &self,
        occurrence_key: impl Into<String>,
        reason: impl Into<String>,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        Ok(self
            .lease
            .rollback_occurrence(occurrence_key, reason)
            .await?
            .into())
    }

    pub async fn release(&self) -> Result<ProductionLeaseReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        let head = self.lease.release().await?;
        Ok(ProductionLeaseReceipt::new(
            &self.authority,
            head,
            "released",
        ))
    }

    pub async fn rollback_lease(&self) -> Result<ProductionLeaseReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        let head = self.lease.rollback_lease().await?;
        Ok(ProductionLeaseReceipt::new(
            &self.authority,
            head,
            "rolled_back",
        ))
    }

    async fn verify_authority(&self) -> Result<(), ProductionWriterError> {
        self.authority
            .validate_for_agent(self.store.owner_agent_id())?;
        verify_durable_store(&self.store).await?;
        self.lease.verify_current().await?;
        Ok(())
    }

    fn validate_queued_receipt(
        &self,
        receipt: &ProductionQueuedReceipt,
    ) -> Result<(), ProductionWriterError> {
        if receipt.schema_version != PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || receipt.namespace != PRODUCTION_DURABLE_WRITER_NAMESPACE
            || receipt.lease_id != self.lease_id()
            || receipt.owner_agent_id != *self.store.owner_agent_id()
            || receipt.authority_grant_digest != self.authority.grant_digest
            || receipt.authority_epoch != self.authority.authority_epoch
            || receipt.owner_epoch != self.authority.owner_epoch
            || receipt.generation != self.lease.generation()
            || receipt
                .inherited_from_generation
                .is_some_and(|source| source >= receipt.generation)
            || receipt.fencing_token_digest != self.authority.fencing_token_digest()?
        {
            return Err(ProductionWriterError::StaleReceipt);
        }
        if Sha256Digest::for_bytes(receipt.payload_json.as_bytes()) != receipt.payload_sha256 {
            return Err(ProductionWriterError::StaleReceipt);
        }
        Ok(())
    }

    async fn dispatch_target<T: ProductionOutboxTarget + ?Sized>(
        &self,
        target: &T,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        self.validate_queued_receipt(&receipt)?;
        self.lease
            .verify_queued_receipt_binding(
                &receipt.occurrence_key,
                &receipt.event_id,
                &receipt.outbox_id,
                &receipt.topic,
                &receipt.payload_json,
                &receipt.payload_sha256,
            )
            .await
            .map_err(|error| match error {
                LocalLeaseOutboxError::StaleFence(_)
                | LocalLeaseOutboxError::IllegalTransition(_)
                | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
                other => ProductionWriterError::Local(other),
            })?;
        let request = ProductionDispatchRequest {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
            lease_id: receipt.lease_id.clone(),
            occurrence_key: receipt.occurrence_key.clone(),
            topic: receipt.topic.clone(),
            payload_json: receipt.payload_json.clone(),
            payload_sha256: receipt.payload_sha256.clone(),
            idempotency_key: receipt.occurrence_key.clone(),
            operation_digest: operation_digest(&self.authority, &receipt),
        };
        // Persist a single-consumer dispatch claim before crossing the target
        // boundary.  A crash after the target observes this request can no
        // longer leave a replayable `Queued` row behind: reopen sees the
        // durable `Indeterminate` marker and must status/reconcile it.  The
        // strict claim also prevents two concurrent dispatchers that verified
        // the same immutable receipt from both calling the target.
        let dispatch_claim_event_id = self
            .lease
            .claim_dispatch(
                &receipt.occurrence_key,
                &self.authority.grant_digest,
                &request.operation_digest,
            )
            .await
            .map_err(|error| match error {
                LocalLeaseOutboxError::StaleFence(_)
                | LocalLeaseOutboxError::IllegalTransition(_)
                | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
                other => ProductionWriterError::Local(other),
            })?
            .event_id;
        let outcome = target.dispatch(request.clone()).await;
        self.settle_dispatch_outcome(
            request,
            &receipt.occurrence_key,
            dispatch_claim_event_id,
            outcome,
        )
        .await
    }

    async fn dispatch_final_use_target<T: FinalUseProductionOutboxTarget + ?Sized>(
        &self,
        final_use: &FinalUseAuthority,
        target: &T,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        self.validate_queued_receipt(&receipt)?;
        if receipt.inherited_from_generation.is_none() {
            self.lease
                .verify_queued_receipt_binding(
                    &receipt.occurrence_key,
                    &receipt.event_id,
                    &receipt.outbox_id,
                    &receipt.topic,
                    &receipt.payload_json,
                    &receipt.payload_sha256,
                )
                .await
                .map_err(|error| match error {
                    LocalLeaseOutboxError::StaleFence(_)
                    | LocalLeaseOutboxError::IllegalTransition(_)
                    | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
                    other => ProductionWriterError::Local(other),
                })?;
        }
        let request = ProductionDispatchRequest {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
            lease_id: receipt.lease_id.clone(),
            occurrence_key: receipt.occurrence_key.clone(),
            topic: receipt.topic.clone(),
            payload_json: receipt.payload_json.clone(),
            payload_sha256: receipt.payload_sha256.clone(),
            idempotency_key: receipt.occurrence_key.clone(),
            operation_digest: operation_digest(&self.authority, &receipt),
        };
        verify_final_use_dispatch_binding(
            self.store.owner_agent_id(),
            target.destination_id(),
            &request,
            expected,
        )?;

        // First make the ambiguous external boundary durable. A crash from
        // this point onward reopens as Indeterminate and must reconcile.
        let inherited_from_generation = receipt.inherited_from_generation;
        let dispatch_claim_event_id = match inherited_from_generation {
            Some(source_generation) => self
                .lease
                .claim_inherited_dispatch(
                    &receipt.occurrence_key,
                    &receipt.event_id,
                    &receipt.outbox_id,
                    source_generation,
                    &receipt.topic,
                    &receipt.payload_json,
                    &receipt.payload_sha256,
                    &self.authority.grant_digest,
                    &request.operation_digest,
                )
                .await,
            None => self
                .lease
                .claim_dispatch(
                    &receipt.occurrence_key,
                    &self.authority.grant_digest,
                    &request.operation_digest,
                )
                .await,
        }
        .map_err(|error| match error {
            LocalLeaseOutboxError::StaleFence(_)
            | LocalLeaseOutboxError::IllegalTransition(_)
            | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
            other => ProductionWriterError::Local(other),
        })?
        .event_id;

        // Then consume the single-use grant and revalidate it immediately at
        // target entry. If either check fails before the adapter is entered we
        // know no external effect happened, so settle local state as Rejected.
        let token = match final_use.claim(signed, expected) {
            Ok(token) => token,
            Err(error) => {
                let _ = self
                    .settle_pre_dispatch_rejection(
                        &receipt.occurrence_key,
                        inherited_from_generation.is_some(),
                        format!("final-use claim rejected: {error}"),
                    )
                    .await;
                return Err(ProductionWriterError::FinalUse(error));
            }
        };
        let future = match final_use.with_verified_use(token, expected, || {
            target.dispatch(request.clone())
        }) {
            Ok(future) => future,
            Err(error) => {
                let _ = self
                    .settle_pre_dispatch_rejection(
                        &receipt.occurrence_key,
                        inherited_from_generation.is_some(),
                        format!("final-use entry rejected: {error}"),
                    )
                    .await;
                return Err(ProductionWriterError::FinalUse(error));
            }
        };
        let outcome = future.await;
        if inherited_from_generation.is_some() {
            self.settle_inherited_dispatch_outcome(
                request,
                &receipt.occurrence_key,
                dispatch_claim_event_id,
                outcome,
            )
            .await
        } else {
            self.settle_dispatch_outcome(
                request,
                &receipt.occurrence_key,
                dispatch_claim_event_id,
                outcome,
            )
            .await
        }
    }

    async fn settle_pre_dispatch_rejection(
        &self,
        occurrence_key: &str,
        inherited: bool,
        reason: String,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        if inherited {
            self.reconcile(occurrence_key, LocalReconcileOutcome::Rejected)
                .await
        } else {
            self.reject(occurrence_key, reason).await
        }
    }

    async fn settle_inherited_dispatch_outcome(
        &self,
        request: ProductionDispatchRequest,
        occurrence_key: &str,
        dispatch_claim_event_id: String,
        outcome: ProductionTargetOutcome,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        match outcome {
            ProductionTargetOutcome::Committed { receipt } => {
                let local = self
                    .reconcile(occurrence_key, LocalReconcileOutcome::Committed)
                    .await?;
                Ok(ProductionDispatchReceipt {
                    request,
                    state: LocalOutcomeState::Committed,
                    target_receipt: Some(receipt),
                    target_reason: None,
                    local_event_id: local.event_id,
                    external_effect: true,
                })
            }
            ProductionTargetOutcome::Rejected { reason } => {
                let local = self
                    .reconcile(occurrence_key, LocalReconcileOutcome::Rejected)
                    .await?;
                Ok(ProductionDispatchReceipt {
                    request,
                    state: LocalOutcomeState::Rejected,
                    target_receipt: None,
                    target_reason: Some(reason),
                    local_event_id: local.event_id,
                    external_effect: false,
                })
            }
            ProductionTargetOutcome::Indeterminate { reason } => Ok(ProductionDispatchReceipt {
                request,
                state: LocalOutcomeState::Indeterminate,
                target_receipt: None,
                target_reason: Some(reason),
                local_event_id: dispatch_claim_event_id,
                external_effect: false,
            }),
        }
    }

    async fn settle_dispatch_outcome(
        &self,
        request: ProductionDispatchRequest,
        occurrence_key: &str,
        dispatch_claim_event_id: String,
        outcome: ProductionTargetOutcome,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        match outcome {
            ProductionTargetOutcome::Committed {
                receipt: target_receipt,
            } => {
                let applied = self.apply(occurrence_key, target_receipt.clone()).await;
                match applied {
                    Ok(local) => Ok(ProductionDispatchReceipt {
                        request,
                        state: LocalOutcomeState::Committed,
                        target_receipt: Some(target_receipt),
                        target_reason: None,
                        local_event_id: local.event_id,
                        external_effect: true,
                    }),
                    // The pre-dispatch claim already keeps this occurrence
                    // indeterminate if the target ACK cannot be journaled.
                    Err(error) => Err(error),
                }
            }
            ProductionTargetOutcome::Rejected { reason } => {
                let local = self.reject(occurrence_key, &reason).await?;
                Ok(ProductionDispatchReceipt {
                    request,
                    state: LocalOutcomeState::Rejected,
                    target_receipt: None,
                    target_reason: Some(reason),
                    local_event_id: local.event_id,
                    external_effect: false,
                })
            }
            ProductionTargetOutcome::Indeterminate { reason } => Ok(ProductionDispatchReceipt {
                request,
                state: LocalOutcomeState::Indeterminate,
                target_receipt: None,
                target_reason: Some(reason),
                local_event_id: dispatch_claim_event_id,
                external_effect: false,
            }),
        }
    }
}

/// Queue receipt returned by the production writer. It carries enough data to
/// dispatch after a process restart without trusting mutable process state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionQueuedReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub lease_id: String,
    pub occurrence_key: String,
    pub event_id: String,
    pub outbox_id: String,
    pub owner_agent_id: AgentId,
    pub authority_grant_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token_digest: Sha256Digest,
    pub topic: String,
    pub payload_json: String,
    pub payload_sha256: Sha256Digest,
    /// Source generation for an immutable queued row adopted after its old
    /// owner fence became terminal. Absent for normal/current-generation rows.
    #[serde(default)]
    pub inherited_from_generation: Option<u64>,
    pub replayed: bool,
    /// Always false until an explicitly attached target returns committed.
    pub external_effect: bool,
}

impl ProductionQueuedReceipt {
    fn from_local(
        authority: &ProductionAuthorityLease,
        topic: &str,
        payload_json: &str,
        receipt: QueuedReceipt,
        replayed: bool,
    ) -> Result<Self, ProductionWriterError> {
        Ok(Self {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
            lease_id: receipt.lease_id,
            occurrence_key: receipt.occurrence_key,
            event_id: receipt.event_id,
            outbox_id: receipt.outbox_id,
            owner_agent_id: receipt.owner_agent_id,
            authority_grant_digest: authority.grant_digest.clone(),
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            generation: receipt.generation,
            fencing_token_digest: authority.fencing_token_digest()?,
            topic: topic.to_string(),
            payload_json: payload_json.to_string(),
            payload_sha256: receipt.payload_sha256,
            inherited_from_generation: None,
            replayed,
            external_effect: false,
        })
    }

    fn from_inherited(
        authority: &ProductionAuthorityLease,
        generation: u64,
        receipt: InheritedQueuedReceipt,
    ) -> Result<Self, ProductionWriterError> {
        Ok(Self {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
            lease_id: receipt.lease_id,
            occurrence_key: receipt.occurrence_key,
            event_id: receipt.event_id,
            outbox_id: receipt.outbox_id,
            owner_agent_id: receipt.owner_agent_id,
            authority_grant_digest: authority.grant_digest.clone(),
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            generation,
            fencing_token_digest: authority.fencing_token_digest()?,
            topic: receipt.topic,
            payload_json: receipt.payload_json,
            payload_sha256: receipt.payload_sha256,
            inherited_from_generation: Some(receipt.source_generation),
            replayed: true,
            external_effect: false,
        })
    }
}

/// Explicit host-to-provider dispatch request. The target must implement its
/// own idempotency/status contract; this seam never silently retries unknown
/// outcomes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionDispatchRequest {
    pub schema_version: u32,
    pub namespace: String,
    pub lease_id: String,
    pub occurrence_key: String,
    pub topic: String,
    pub payload_json: String,
    pub payload_sha256: Sha256Digest,
    pub idempotency_key: String,
    pub operation_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionTargetOutcome {
    Committed {
        receipt: String,
    },
    Rejected {
        reason: String,
    },
    /// Unknown/timeout/provider ambiguity must remain quarantined.
    Indeterminate {
        reason: String,
    },
}

pub type ProductionDispatchFuture<'a> =
    Pin<Box<dyn Future<Output = ProductionTargetOutcome> + Send + 'a>>;

pub trait ProductionOutboxTarget: Send + Sync {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a>;
}

/// Production target with a stable destination identity that can be bound into
/// a `FinalUseBinding`.
pub trait FinalUseProductionOutboxTarget: ProductionOutboxTarget {
    fn destination_id(&self) -> &str;
}

/// Legacy direct dispatcher retained only for in-crate qualification tests.
/// Product composition must use `ProductionFinalUseOutboxDispatcher`.
#[derive(Clone)]
pub(crate) struct ProductionOutboxDispatcher {
    target: Arc<dyn ProductionOutboxTarget>,
}

impl fmt::Debug for ProductionOutboxDispatcher {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionOutboxDispatcher")
            .finish_non_exhaustive()
    }
}

impl ProductionOutboxDispatcher {
    pub fn attach(target: Arc<dyn ProductionOutboxTarget>) -> Self {
        Self { target }
    }

    pub async fn dispatch(
        &self,
        writer: &ProductionDurableWriter,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        writer.dispatch_target(self.target.as_ref(), receipt).await
    }
}

/// Production dispatcher that consumes a kernel-owned final-use grant exactly
/// at the attached destination boundary.
#[derive(Clone)]
pub struct ProductionFinalUseOutboxDispatcher {
    final_use: FinalUseAuthority,
    target: Arc<dyn FinalUseProductionOutboxTarget>,
}

impl fmt::Debug for ProductionFinalUseOutboxDispatcher {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionFinalUseOutboxDispatcher")
            .field("destination_id", &self.target.destination_id())
            .finish_non_exhaustive()
    }
}

impl ProductionFinalUseOutboxDispatcher {
    pub fn attach(
        final_use: FinalUseAuthority,
        target: Arc<dyn FinalUseProductionOutboxTarget>,
    ) -> Self {
        Self { final_use, target }
    }

    pub async fn dispatch(
        &self,
        writer: &ProductionDurableWriter,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, ProductionWriterError> {
        writer
            .dispatch_final_use_target(
                &self.final_use,
                self.target.as_ref(),
                signed,
                expected,
                receipt,
            )
            .await
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionDispatchReceipt {
    pub request: ProductionDispatchRequest,
    pub state: LocalOutcomeState,
    pub target_receipt: Option<String>,
    /// Provider-side reason is returned verbatim for status/reconcile
    /// qualification. It is not an authority receipt; committed outcomes
    /// leave this field absent.
    #[serde(default)]
    pub target_reason: Option<String>,
    pub local_event_id: String,
    pub external_effect: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionOutcomeReceipt {
    pub lease_id: String,
    pub occurrence_key: String,
    pub state: LocalOutcomeState,
    pub event_id: String,
    pub external_effect: bool,
}

impl From<LocalOutcomeReceipt> for ProductionOutcomeReceipt {
    fn from(value: LocalOutcomeReceipt) -> Self {
        Self {
            lease_id: value.lease_id,
            occurrence_key: value.occurrence_key,
            state: value.state,
            event_id: value.event_id,
            external_effect: false,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionLeaseReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub lease_id: String,
    pub owner_agent_id: AgentId,
    pub generation: u64,
    pub authority_grant_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub state: String,
    pub lease_head_digest: Sha256Digest,
    pub external_effect: bool,
}

impl ProductionLeaseReceipt {
    fn new(authority: &ProductionAuthorityLease, head: LocalLease, state: &str) -> Self {
        Self {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
            lease_id: head.lease_id,
            owner_agent_id: head.owner_agent_id,
            generation: head.generation,
            authority_grant_digest: authority.grant_digest.clone(),
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            state: state.to_string(),
            lease_head_digest: head.lease_sha256,
            external_effect: false,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionRecoveryReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub lease_id: String,
    pub authority_grant_digest: Sha256Digest,
    pub state: String,
    pub occurrence_key: Option<String>,
    pub external_effect: bool,
    /// A SIGKILL/crash probe is not a physical power-loss proof.
    pub physical_power_loss_claim: bool,
}

impl ProductionRecoveryReceipt {
    fn from_local(
        authority: &ProductionAuthorityLease,
        lease_id: &str,
        requested_occurrence_key: &str,
        result: LocalReplayFinalization,
    ) -> Self {
        let (state, occurrence_key) = match result {
            LocalReplayFinalization::NotAdmitted => (
                "not_admitted".to_string(),
                Some(requested_occurrence_key.to_string()),
            ),
            LocalReplayFinalization::Queued(receipt) => {
                ("queued".to_string(), Some(receipt.occurrence_key))
            }
            LocalReplayFinalization::Released { outcome, .. } => (
                format!(
                    "released_{}",
                    match outcome {
                        LocalOutcomeState::Queued => "queued",
                        LocalOutcomeState::Indeterminate => "indeterminate",
                        LocalOutcomeState::Committed => "committed",
                        LocalOutcomeState::Rejected => "rejected",
                        LocalOutcomeState::RolledBack => "rolled_back",
                    }
                ),
                Some(requested_occurrence_key.to_string()),
            ),
        };
        Self {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
            lease_id: lease_id.to_string(),
            authority_grant_digest: authority.grant_digest.clone(),
            state,
            occurrence_key,
            external_effect: false,
            physical_power_loss_claim: false,
        }
    }
}

fn verify_final_use_dispatch_binding(
    owner: &AgentId,
    destination_id: &str,
    request: &ProductionDispatchRequest,
    expected: &FinalUseBinding,
) -> Result<(), ProductionWriterError> {
    if expected.subject_id != owner.as_str()
        || expected.destination_id != destination_id
        || expected.payload_sha256 != digest_bytes(&request.payload_sha256)?
        || expected.request_sha256 != digest_bytes(&request.operation_digest)?
    {
        return Err(ProductionWriterError::FinalUse(
            FinalUseError::BindingMismatch,
        ));
    }
    Ok(())
}

fn digest_bytes(digest: &Sha256Digest) -> Result<[u8; 32], ProductionWriterError> {
    let source = digest.as_str().as_bytes();
    if source.len() != 64 {
        return Err(ProductionWriterError::Invalid(
            "internal SHA-256 digest length is invalid".to_string(),
        ));
    }
    let mut output = [0_u8; 32];
    for (index, byte) in output.iter_mut().enumerate() {
        let high = decode_hex(source[index * 2]).ok_or_else(|| {
            ProductionWriterError::Invalid("internal SHA-256 digest is invalid".to_string())
        })?;
        let low = decode_hex(source[index * 2 + 1]).ok_or_else(|| {
            ProductionWriterError::Invalid("internal SHA-256 digest is invalid".to_string())
        })?;
        *byte = (high << 4) | low;
    }
    Ok(output)
}

fn decode_hex(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        _ => None,
    }
}

fn operation_digest(
    authority: &ProductionAuthorityLease,
    receipt: &ProductionQueuedReceipt,
) -> Sha256Digest {
    dispatch_operation_digest(
        &authority.grant_digest,
        &receipt.lease_id,
        &receipt.occurrence_key,
        &receipt.topic,
        &receipt.payload_sha256,
    )
}

async fn verify_durable_store(store: &CognitiveStore) -> Result<(), ProductionWriterError> {
    let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(&store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
    let synchronous: i64 = sqlx::query_scalar("PRAGMA synchronous")
        .fetch_one(&store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
    if !journal_mode.eq_ignore_ascii_case(PRODUCTION_DURABLE_WRITER_JOURNAL_MODE)
        || synchronous != PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL
    {
        return Err(ProductionWriterError::Durability(format!(
            "required journal_mode=WAL and synchronous=FULL, observed mode={journal_mode:?} synchronous={synchronous}"
        )));
    }
    Ok(())
}

fn validate_text(value: &str, label: &str, max_bytes: usize) -> Result<(), ProductionWriterError> {
    if value.is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(ProductionWriterError::Invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn now_unix_seconds() -> Result<u64, ProductionWriterError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|error| ProductionWriterError::Invalid(format!("system clock failed: {error}")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    use std::time::Duration;
    use tempfile::TempDir;
    use tokio::time::sleep;
    use tokio::time::timeout;

    const OWNER: u8 = 222;

    fn agent_id(number: u8) -> AgentId {
        AgentId::parse(format!("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c{number:02x}")).unwrap()
    }

    async fn store(temp: &TempDir) -> CognitiveStore {
        let fleet_root = temp.path().join("fleet");
        std::fs::create_dir_all(&fleet_root).unwrap();
        let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().unwrap()).unwrap();
        CognitiveStore::open(&fleet.layout().agent(&agent_id(OWNER)))
            .await
            .unwrap()
    }

    fn authority(agent: AgentId) -> ProductionAuthorityLease {
        ProductionAuthorityLease::from_verified_parts(
            agent,
            Sha256Digest::for_bytes(b"signed-grant"),
            9,
            4,
            now_unix_seconds().unwrap() + 3_600,
            ProductionAuthorityToken::from_verified_bytes(b"opaque-supervisor-token".to_vec())
                .unwrap(),
        )
        .unwrap()
    }

    struct Target {
        calls: AtomicUsize,
        outcome: ProductionTargetOutcome,
    }

    struct AllowVerifier;

    impl ProductionAuthorityVerifier for AllowVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            Ok(())
        }
    }

    struct DenyVerifier;

    impl ProductionAuthorityVerifier for DenyVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            Err("no independent grant".to_string())
        }
    }

    impl ProductionOutboxTarget for Target {
        fn dispatch<'a>(
            &'a self,
            _request: ProductionDispatchRequest,
        ) -> ProductionDispatchFuture<'a> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            let outcome = self.outcome.clone();
            Box::pin(async move { outcome })
        }
    }

    struct PanicAfterSendTarget {
        calls: Arc<AtomicUsize>,
    }

    impl ProductionOutboxTarget for PanicAfterSendTarget {
        fn dispatch<'a>(
            &'a self,
            _request: ProductionDispatchRequest,
        ) -> ProductionDispatchFuture<'a> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Box::pin(async { panic!("qualification target crashed after send") })
        }
    }

    struct SlowTarget {
        calls: Arc<AtomicUsize>,
    }

    impl ProductionOutboxTarget for SlowTarget {
        fn dispatch<'a>(
            &'a self,
            _request: ProductionDispatchRequest,
        ) -> ProductionDispatchFuture<'a> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Box::pin(async move {
                sleep(Duration::from_millis(100)).await;
                ProductionTargetOutcome::Indeterminate {
                    reason: "qualification target timeout".to_string(),
                }
            })
        }
    }

    #[tokio::test]
    async fn production_writer_requires_verifier_and_records_commit() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let denied = ProductionDurableWriter::open(
            store.clone(),
            auth.clone(),
            &DenyVerifier,
            "production:h4:test",
            1,
        )
        .await
        .unwrap_err();
        assert!(matches!(
            denied,
            ProductionWriterError::AuthorityRejected(_)
        ));

        let writer =
            ProductionDurableWriter::open(store, auth, &AllowVerifier, "production:h4:test", 1)
                .await
                .unwrap();
        let queued = writer
            .admit("occurrence:1", "memory.write", "{\"x\":1}")
            .await
            .unwrap();
        assert!(!queued.external_effect);
        let target = Arc::new(Target {
            calls: AtomicUsize::new(0),
            outcome: ProductionTargetOutcome::Committed {
                receipt: "provider-ack-1".to_string(),
            },
        });
        let dispatcher = ProductionOutboxDispatcher::attach(target.clone());
        let dispatched = dispatcher.dispatch(&writer, queued).await.unwrap();
        assert_eq!(dispatched.state, LocalOutcomeState::Committed);
        assert!(dispatched.external_effect);
        assert_eq!(target.calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn unknown_target_outcome_is_indeterminate_and_replay_is_durable() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let writer =
            ProductionDurableWriter::open(store, auth, &AllowVerifier, "production:h4:unknown", 1)
                .await
                .unwrap();
        let queued = writer
            .admit("occurrence:unknown", "memory.write", "payload")
            .await
            .unwrap();
        let target = Arc::new(Target {
            calls: AtomicUsize::new(0),
            outcome: ProductionTargetOutcome::Indeterminate {
                reason: "timeout".to_string(),
            },
        });
        let receipt = ProductionOutboxDispatcher::attach(target)
            .dispatch(&writer, queued)
            .await
            .unwrap();
        assert_eq!(receipt.state, LocalOutcomeState::Indeterminate);
        assert_eq!(receipt.target_reason.as_deref(), Some("timeout"));
        assert!(!receipt.external_effect);
        assert_eq!(
            writer.status("occurrence:unknown").await.unwrap(),
            LocalOutcomeState::Indeterminate
        );
        let recovery = writer.recover("occurrence:unknown").await.unwrap();
        assert!(recovery.state.starts_with("released_"));
        assert!(!recovery.physical_power_loss_claim);
    }

    #[tokio::test]
    async fn recovery_does_not_release_production_lease_with_peer_pending() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let writer = ProductionDurableWriter::open(
            store,
            auth,
            &AllowVerifier,
            "production:h4:recovery-peer",
            1,
        )
        .await
        .unwrap();
        writer
            .admit(
                "occurrence:recovery-indeterminate",
                "memory.write",
                "payload-a",
            )
            .await
            .unwrap();
        writer
            .admit("occurrence:recovery-queued", "memory.write", "payload-b")
            .await
            .unwrap();
        writer
            .mark_indeterminate(
                "occurrence:recovery-indeterminate",
                "target-may-have-committed",
            )
            .await
            .unwrap();

        let error = writer
            .recover("occurrence:recovery-indeterminate")
            .await
            .expect_err("peer queued intent must block replay release");
        assert!(matches!(
            error,
            ProductionWriterError::Local(LocalLeaseOutboxError::IllegalTransition(ref message))
                if message.contains("occurrence:recovery-queued")
        ));
        assert_eq!(
            writer.status("occurrence:recovery-queued").await.unwrap(),
            LocalOutcomeState::Queued
        );

        writer
            .rollback_occurrence("occurrence:recovery-queued", "operator-revoked")
            .await
            .unwrap();
        let recovery = writer
            .recover("occurrence:recovery-indeterminate")
            .await
            .unwrap();
        assert_eq!(recovery.state, "released_indeterminate");
        assert!(!recovery.external_effect);
    }

    #[tokio::test]
    async fn forged_queue_receipt_cannot_substitute_provider_payload_or_topic() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let writer = ProductionDurableWriter::open(
            store,
            auth,
            &AllowVerifier,
            "production:h4:receipt-binding",
            1,
        )
        .await
        .unwrap();
        let queued = writer
            .admit("occurrence:binding", "memory.write", "{\"x\":1}")
            .await
            .unwrap();
        let mut forged = queued.clone();
        forged.topic = "different.topic".to_string();
        forged.payload_json = "{\"x\":2}".to_string();
        forged.payload_sha256 = Sha256Digest::for_bytes(forged.payload_json.as_bytes());
        let target = Arc::new(Target {
            calls: AtomicUsize::new(0),
            outcome: ProductionTargetOutcome::Committed {
                receipt: "must-not-be-called".to_string(),
            },
        });
        let result = ProductionOutboxDispatcher::attach(target.clone())
            .dispatch(&writer, forged)
            .await;
        assert!(matches!(result, Err(ProductionWriterError::StaleReceipt)));
        assert_eq!(target.calls.load(Ordering::SeqCst), 0);
        assert_eq!(
            writer.status("occurrence:binding").await.unwrap(),
            LocalOutcomeState::Queued
        );
    }

    #[tokio::test]
    async fn dispatch_claim_rejects_unbound_or_malformed_operation_digest() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let writer = ProductionDurableWriter::open(
            store,
            auth,
            &AllowVerifier,
            "production:h4:claim-binding",
            1,
        )
        .await
        .unwrap();
        let queued = writer
            .admit("occurrence:claim-binding", "memory.write", "payload")
            .await
            .unwrap();
        let malformed: Sha256Digest = serde_json::from_str("\"not-a-sha256\"").unwrap();
        let malformed_result = writer
            .lease
            .claim_dispatch(
                &queued.occurrence_key,
                &writer.authority.grant_digest,
                &malformed,
            )
            .await;
        assert!(matches!(
            malformed_result,
            Err(LocalLeaseOutboxError::Invalid(_))
        ));
        assert_eq!(
            writer.status("occurrence:claim-binding").await.unwrap(),
            LocalOutcomeState::Queued
        );

        let unbound = Sha256Digest::for_bytes(b"different-operation");
        let unbound_result = writer
            .lease
            .claim_dispatch(
                &queued.occurrence_key,
                &writer.authority.grant_digest,
                &unbound,
            )
            .await;
        assert!(matches!(
            unbound_result,
            Err(LocalLeaseOutboxError::StaleFence(_))
        ));
        assert_eq!(
            writer.status("occurrence:claim-binding").await.unwrap(),
            LocalOutcomeState::Queued
        );

        let expected = operation_digest(&writer.authority, &queued);
        let claim = writer
            .lease
            .claim_dispatch(
                &queued.occurrence_key,
                &writer.authority.grant_digest,
                &expected,
            )
            .await
            .unwrap();
        assert_eq!(claim.state, LocalOutcomeState::Indeterminate);
        assert_eq!(
            writer.status("occurrence:claim-binding").await.unwrap(),
            LocalOutcomeState::Indeterminate
        );
    }

    #[tokio::test]
    async fn restart_reopens_exact_bound_lease_and_replays_queue() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let writer = ProductionDurableWriter::open(
            store.clone(),
            auth.clone(),
            &AllowVerifier,
            "production:h4:restart",
            1,
        )
        .await
        .unwrap();
        let queued = writer
            .admit("occurrence:restart", "memory.write", "payload")
            .await
            .unwrap();
        drop(writer);
        let reopened =
            ProductionDurableWriter::open(store, auth, &AllowVerifier, "production:h4:restart", 1)
                .await
                .unwrap();
        let replay = reopened
            .admit("occurrence:restart", "memory.write", "payload")
            .await
            .unwrap();
        assert!(replay.replayed);
        assert_eq!(replay.event_id, queued.event_id);
        assert_eq!(replay.outbox_id, queued.outbox_id);
    }

    #[tokio::test]
    async fn second_writer_open_is_rejected_until_first_owner_drops() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let lease_id = "production:h4:single-writer";
        let first =
            ProductionDurableWriter::open(store.clone(), auth.clone(), &AllowVerifier, lease_id, 1)
                .await
                .unwrap();
        first
            .admit("occurrence:single-writer", "memory.write", "payload")
            .await
            .unwrap();

        // A second process/handle with the same exact authority must not
        // silently become a co-owner merely because SQLite serializes each
        // individual transaction.  The writer lock is held for the lifetime
        // of `first`, so the failed open must not append a successor lease.
        // Reopen through the ordinary path as well: on Windows the first store
        // was opened through the OS verbatim spelling. Both must share a lock.
        let native_fleet = AbsolutePathBuf::from_absolute_path(temp.path().join("fleet"))
            .unwrap()
            .canonicalize()
            .unwrap();
        let second_store = CognitiveStore::open(
            &HeptaFleetRoot::parse(native_fleet.into_path_buf())
                .unwrap()
                .layout()
                .agent(store.owner_agent_id()),
        )
        .await
        .unwrap();
        assert!(store.is_same_local_store(&second_store));
        let second =
            ProductionDurableWriter::open(second_store, auth.clone(), &AllowVerifier, lease_id, 1)
                .await;
        assert!(matches!(second, Err(ProductionWriterError::WriterBusy)));
        let head = store.inspect_local_lease_head(lease_id).await.unwrap();
        assert_eq!(head.disposition, LocalLeaseHeadDisposition::Active);
        assert_eq!(head.head.unwrap().lease_sequence, 1);

        // A normal close releases the OS lock, while the append-only lease
        // remains replayable for the next owner handle.
        drop(first);
        let reopened = ProductionDurableWriter::open(store, auth, &AllowVerifier, lease_id, 1)
            .await
            .unwrap();
        let replay = reopened
            .admit("occurrence:single-writer", "memory.write", "payload")
            .await
            .unwrap();
        assert!(replay.replayed);
    }

    #[tokio::test]
    async fn crash_after_target_send_reopens_as_indeterminate_and_cannot_redispatch() {
        let temp = TempDir::new().unwrap();
        let initial_store = store(&temp).await;
        let owner = initial_store.owner_agent_id().clone();
        let auth = authority(owner);
        let writer = ProductionDurableWriter::open(
            initial_store.clone(),
            auth.clone(),
            &AllowVerifier,
            "production:h4:dispatch-crash",
            1,
        )
        .await
        .unwrap();
        let queued = writer
            .admit("occurrence:dispatch-crash", "memory.write", "payload")
            .await
            .unwrap();
        let retry_receipt = queued.clone();
        let calls = Arc::new(AtomicUsize::new(0));
        let target = Arc::new(PanicAfterSendTarget {
            calls: calls.clone(),
        });
        let dispatcher = ProductionOutboxDispatcher::attach(target.clone());
        let task = tokio::spawn(async move { dispatcher.dispatch(&writer, queued).await });
        let join_error = timeout(Duration::from_secs(5), task)
            .await
            .expect("crash-after-send fixture must not hang")
            .unwrap_err();
        assert!(join_error.is_panic());
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        drop(initial_store);

        let reopened_store = store(&temp).await;
        let reopened = ProductionDurableWriter::open(
            reopened_store,
            auth,
            &AllowVerifier,
            "production:h4:dispatch-crash",
            1,
        )
        .await
        .unwrap();
        assert_eq!(
            reopened.status("occurrence:dispatch-crash").await.unwrap(),
            LocalOutcomeState::Indeterminate
        );
        let retry = ProductionOutboxDispatcher::attach(target);
        let result = retry.dispatch(&reopened, retry_receipt).await;
        assert!(matches!(result, Err(ProductionWriterError::StaleReceipt)));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        let recovery = reopened.recover("occurrence:dispatch-crash").await.unwrap();
        assert_eq!(recovery.state, "released_indeterminate");
        assert!(!recovery.external_effect);
    }

    #[tokio::test]
    async fn concurrent_dispatchers_have_one_durable_claim_and_one_target_call() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let writer = ProductionDurableWriter::open(
            store,
            auth,
            &AllowVerifier,
            "production:h4:dispatch-race",
            1,
        )
        .await
        .unwrap();
        let queued = writer
            .admit("occurrence:dispatch-race", "memory.write", "payload")
            .await
            .unwrap();
        let calls = Arc::new(AtomicUsize::new(0));
        let target = Arc::new(SlowTarget {
            calls: calls.clone(),
        });
        let dispatcher = ProductionOutboxDispatcher::attach(target);
        let (first, second) = timeout(Duration::from_secs(5), async {
            tokio::join!(
                dispatcher.dispatch(&writer, queued.clone()),
                dispatcher.dispatch(&writer, queued),
            )
        })
        .await
        .expect("concurrent dispatch claim fixture must not hang");
        let first_ok = matches!(
            &first,
            Ok(receipt) if receipt.state == LocalOutcomeState::Indeterminate
        );
        let second_ok = matches!(
            &second,
            Ok(receipt) if receipt.state == LocalOutcomeState::Indeterminate
        );
        let first_stale = matches!(&first, Err(ProductionWriterError::StaleReceipt));
        let second_stale = matches!(&second, Err(ProductionWriterError::StaleReceipt));
        assert!(
            (first_ok && second_stale) || (second_ok && first_stale),
            "expected one successful claim and one stale receipt, first={first:?} second={second:?}"
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn active_lease_cannot_reopen_under_a_different_grant_with_same_token() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let original = authority(owner.clone());
        let writer = ProductionDurableWriter::open(
            store.clone(),
            original.clone(),
            &AllowVerifier,
            "production:h4:grant-binding",
            1,
        )
        .await
        .unwrap();
        writer
            .admit("occurrence:grant-binding", "memory.write", "payload")
            .await
            .unwrap();

        // A verifier may receive a fresh grant while an old active lease is
        // still present. Reusing the same opaque token/epochs must not make
        // the old append-only lease look valid for that new grant.
        let rebound = ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(b"different-signed-grant"),
            original.authority_epoch,
            original.owner_epoch,
            original.lease_expires_at_unix_seconds,
            ProductionAuthorityToken::from_verified_bytes(b"opaque-supervisor-token".to_vec())
                .unwrap(),
        )
        .unwrap();
        let result = ProductionDurableWriter::open(
            store.clone(),
            rebound,
            &AllowVerifier,
            "production:h4:grant-binding",
            1,
        )
        .await;
        assert!(matches!(result, Err(ProductionWriterError::StaleReceipt)));
        let head = store
            .inspect_local_lease_head("production:h4:grant-binding")
            .await
            .unwrap();
        assert_eq!(head.disposition, LocalLeaseHeadDisposition::Active);
        assert_eq!(
            head.head.unwrap().fencing_token,
            original.fencing_token_digest().unwrap().as_str()
        );
    }

    #[tokio::test]
    async fn expired_or_rebound_authority_cannot_open_a_writer() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let expired = ProductionAuthorityLease::from_verified_parts(
            owner.clone(),
            Sha256Digest::for_bytes(b"expired-grant"),
            9,
            4,
            now_unix_seconds().unwrap().saturating_sub(1),
            ProductionAuthorityToken::from_verified_bytes(b"expired-token".to_vec()).unwrap(),
        )
        .unwrap();
        let expired_result = ProductionDurableWriter::open(
            store.clone(),
            expired,
            &AllowVerifier,
            "production:h4:expired-open",
            1,
        )
        .await;
        assert!(matches!(
            expired_result,
            Err(ProductionWriterError::AuthorityExpired { .. })
        ));
        assert_eq!(
            store
                .inspect_local_lease_head("production:h4:expired-open")
                .await
                .unwrap()
                .disposition,
            LocalLeaseHeadDisposition::Missing,
            "an expired authority must not create a lease while opening"
        );

        let original = authority(owner.clone());
        let lease_id = "production:h4:reopen-binding";
        let writer = ProductionDurableWriter::open(
            store.clone(),
            original.clone(),
            &AllowVerifier,
            lease_id,
            1,
        )
        .await
        .unwrap();
        writer
            .admit("occurrence:reopen-binding", "memory.write", "payload")
            .await
            .unwrap();

        // An active lease cannot be reopened under a changed owner epoch,
        // even when the Agent and grant verifier are otherwise valid. The
        // successor must first observe/release the exact current head.
        let rebound = ProductionAuthorityLease::from_verified_parts(
            owner,
            original.grant_digest.clone(),
            original.authority_epoch,
            original.owner_epoch + 1,
            original.lease_expires_at_unix_seconds,
            ProductionAuthorityToken::from_verified_bytes(b"opaque-supervisor-token".to_vec())
                .unwrap(),
        )
        .unwrap();
        let rebound_result =
            ProductionDurableWriter::open(store.clone(), rebound, &AllowVerifier, lease_id, 1)
                .await;
        assert!(matches!(
            rebound_result,
            Err(ProductionWriterError::StaleReceipt)
        ));
        let head = store.inspect_local_lease_head(lease_id).await.unwrap();
        assert_eq!(head.disposition, LocalLeaseHeadDisposition::Active);
        assert_eq!(head.head.unwrap().owner_epoch, Some(original.owner_epoch));
    }
}


#[cfg(test)]
mod takeover_regression_tests {
    use super::*;
    use codex_hepta_paths::HeptaFleetRoot;
    use std::time::Duration;
    use tempfile::TempDir;
    use tokio::time::sleep;

    fn test_agent() -> AgentId {
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cfe").expect("agent")
    }

    struct TakeoverAllowVerifier;

    impl ProductionAuthorityVerifier for TakeoverAllowVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            Ok(())
        }
    }

    async fn test_store(temp: &TempDir) -> CognitiveStore {
        let fleet_root = temp.path().join("fleet-takeover");
        std::fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet"))
            .expect("fleet");
        CognitiveStore::open(&fleet.layout().agent(&test_agent()))
            .await
            .expect("store")
    }

    fn authority_for(
        owner: AgentId,
        grant: &[u8],
        authority_epoch: u64,
        owner_epoch: u64,
        expiry: u64,
        token: &[u8],
    ) -> ProductionAuthorityLease {
        ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(grant),
            authority_epoch,
            owner_epoch,
            expiry,
            ProductionAuthorityToken::from_verified_bytes(token.to_vec()).expect("token"),
        )
        .expect("authority")
    }

    #[tokio::test]
    async fn expired_active_writer_is_terminalized_and_successor_reconciles_unknown_effect() {
        let temp = TempDir::new().expect("temp");
        let store = test_store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let old_expiry = now_unix_seconds().expect("clock") + 2;
        let old_authority =
            authority_for(owner.clone(), b"grant-old", 9, 40, old_expiry, b"token-old");
        let old = ProductionDurableWriter::open(
            store.clone(),
            old_authority,
            &TakeoverAllowVerifier,
            "production:h4:takeover",
            1,
        )
        .await
        .expect("old writer");
        old.admit("occurrence:takeover", "destination.write", "{\"value\":1}")
            .await
            .expect("admission");
        old.mark_indeterminate("occurrence:takeover", "ack-lost")
            .await
            .expect("indeterminate");
        drop(old);

        sleep(Duration::from_millis(2_100)).await;

        let new_authority = authority_for(
            owner,
            b"grant-new",
            9,
            41,
            now_unix_seconds().expect("clock") + 3_600,
            b"token-new",
        );
        let successor = ProductionDurableWriter::open(
            store,
            new_authority,
            &TakeoverAllowVerifier,
            "production:h4:takeover",
            2,
        )
        .await
        .expect("successor writer");
        assert_eq!(successor.generation(), 2);
        assert_eq!(
            successor
                .status("occurrence:takeover")
                .await
                .expect("inherited status"),
            LocalOutcomeState::Indeterminate
        );

        let settled = successor
            .reconcile(
                "occurrence:takeover",
                LocalReconcileOutcome::Committed,
            )
            .await
            .expect("successor reconciliation");
        assert_eq!(settled.state, LocalOutcomeState::Committed);
        assert_eq!(
            successor
                .status("occurrence:takeover")
                .await
                .expect("terminal status"),
            LocalOutcomeState::Committed
        );
    }
}


#[cfg(all(test, unix))]
mod final_use_dispatch_tests {
    use super::*;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_paths::HeptaFleetRoot;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    use tempfile::TempDir;

    fn agent() -> AgentId {
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cff").expect("agent")
    }

    async fn store(temp: &TempDir) -> CognitiveStore {
        let root = temp.path().join("fleet-final-use");
        std::fs::create_dir_all(&root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(root.canonicalize().expect("canonical root"))
            .expect("fleet root");
        CognitiveStore::open(&fleet.layout().agent(&agent()))
            .await
            .expect("store")
    }

    struct FinalUseVerifier;

    impl ProductionAuthorityVerifier for FinalUseVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            Ok(())
        }
    }

    #[derive(Debug)]
    struct CountingTarget {
        calls: AtomicUsize,
        destination: String,
    }

    impl CountingTarget {
        fn new(destination: &str) -> Self {
            Self {
                calls: AtomicUsize::new(0),
                destination: destination.to_string(),
            }
        }

        fn calls(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
    }

    impl ProductionOutboxTarget for CountingTarget {
        fn dispatch<'a>(
            &'a self,
            _request: ProductionDispatchRequest,
        ) -> ProductionDispatchFuture<'a> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Box::pin(async {
                ProductionTargetOutcome::Committed {
                    receipt: "target:committed".to_string(),
                }
            })
        }
    }

    impl FinalUseProductionOutboxTarget for CountingTarget {
        fn destination_id(&self) -> &str {
            &self.destination
        }
    }

    fn production_authority(owner: AgentId) -> ProductionAuthorityLease {
        ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(b"production-grant"),
            31,
            41,
            now_unix_seconds().expect("clock") + 3_600,
            ProductionAuthorityToken::from_verified_bytes(b"production-token".to_vec())
                .expect("token"),
        )
        .expect("authority")
    }

    fn signed_final_use(
        issuer: &SigningKey,
        binding: FinalUseBinding,
        grant_id: &str,
        nonce: [u8; 32],
    ) -> SignedFinalUseGrant {
        let now_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "final-use-owner".to_string(),
            authority_epoch: 71,
            grant_id: grant_id.to_string(),
            nonce,
            binding,
            not_before_unix_ms: now_ms.saturating_sub(1_000),
            expires_at_unix_ms: now_ms + 30_000,
        };
        let signature = issuer
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }

    #[tokio::test]
    async fn final_use_is_consumed_at_target_entry_and_binding_mismatch_never_calls_target() {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let writer = ProductionDurableWriter::open(
            store,
            production_authority(owner.clone()),
            &FinalUseVerifier,
            "production:h4:final-use",
            1,
        )
        .await
        .expect("writer");

        let authority_dir = temp.path().join("final-use-authority");
        std::fs::create_dir(&authority_dir).expect("authority dir");
        std::fs::set_permissions(
            &authority_dir,
            std::fs::Permissions::from_mode(0o700),
        )
        .expect("authority permissions");
        let issuer = SigningKey::from_bytes(&[83; 32]);
        let final_use = FinalUseAuthority::open_state_dir(
            &authority_dir,
            "final-use-owner".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 71,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("final-use authority");
        let target = Arc::new(CountingTarget::new("destination:cognitive-store"));
        let dispatcher =
            ProductionFinalUseOutboxDispatcher::attach(final_use.clone(), target.clone());

        let queued = writer
            .admit(
                "occurrence:final-use:1",
                "memory.write",
                "{\"fact\":\"one\"}",
            )
            .await
            .expect("queued");
        let binding = FinalUseBinding {
            subject_id: owner.as_str().to_string(),
            destination_id: target.destination_id().to_string(),
            request_sha256: digest_bytes(&operation_digest(writer.authority(), &queued))
                .expect("request digest"),
            scope_sha256: [7; 32],
            payload_sha256: digest_bytes(&queued.payload_sha256).expect("payload digest"),
        };
        let signed = signed_final_use(&issuer, binding.clone(), "final-use-good", [11; 32]);
        let dispatched = dispatcher
            .dispatch(&writer, &signed, &binding, queued)
            .await
            .expect("authorized dispatch");
        assert_eq!(dispatched.state, LocalOutcomeState::Committed);
        assert_eq!(target.calls(), 1);

        let queued_bad = writer
            .admit(
                "occurrence:final-use:2",
                "memory.write",
                "{\"fact\":\"two\"}",
            )
            .await
            .expect("second queued");
        let bad_binding = FinalUseBinding {
            subject_id: owner.as_str().to_string(),
            destination_id: "destination:substituted".to_string(),
            request_sha256: digest_bytes(&operation_digest(writer.authority(), &queued_bad))
                .expect("request digest"),
            scope_sha256: [8; 32],
            payload_sha256: digest_bytes(&queued_bad.payload_sha256).expect("payload digest"),
        };
        let bad_signed =
            signed_final_use(&issuer, bad_binding.clone(), "final-use-bad-destination", [12; 32]);
        assert!(matches!(
            dispatcher
                .dispatch(&writer, &bad_signed, &bad_binding, queued_bad.clone())
                .await,
            Err(ProductionWriterError::FinalUse(FinalUseError::BindingMismatch))
        ));
        assert_eq!(target.calls(), 1, "mismatched destination never enters target");
        assert_eq!(
            writer
                .status("occurrence:final-use:2")
                .await
                .expect("queued status"),
            LocalOutcomeState::Queued,
            "preflight binding rejection happens before durable dispatch claim"
        );

        // Preflight rejection did not consume the owner-signed nonce.
        let token = final_use
            .claim(&bad_signed, &bad_binding)
            .expect("nonce remains unused");
        drop(token);
    }

    #[tokio::test]
    async fn queued_identity_survives_owner_handoff_and_dispatches_once_under_new_final_use() {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let old = ProductionDurableWriter::open(
            store.clone(),
            production_authority(owner.clone()),
            &FinalUseVerifier,
            "production:h4:queued-handoff",
            1,
        )
        .await
        .expect("old writer");
        let queued = old
            .admit(
                "occurrence:queued-handoff",
                "memory.write",
                "{\"fact\":\"handoff\"}",
            )
            .await
            .expect("queued");
        assert_eq!(queued.inherited_from_generation, None);
        let expiry = old.authority().lease_expires_at_unix_seconds;
        old.lease
            .expire_lease_at_unix_seconds(expiry)
            .await
            .expect("explicit timeout terminalization");
        drop(old);

        let next_authority = ProductionAuthorityLease::from_verified_parts(
            owner.clone(),
            Sha256Digest::for_bytes(b"production-grant-next"),
            31,
            42,
            now_unix_seconds().expect("clock") + 7_200,
            ProductionAuthorityToken::from_verified_bytes(b"production-token-next".to_vec())
                .expect("token"),
        )
        .expect("next authority");
        let successor = ProductionDurableWriter::open(
            store,
            next_authority,
            &FinalUseVerifier,
            "production:h4:queued-handoff",
            2,
        )
        .await
        .expect("successor writer");
        let inherited = successor
            .recover_inherited_queued("occurrence:queued-handoff")
            .await
            .expect("recover inherited")
            .expect("queued predecessor row");
        assert_eq!(inherited.inherited_from_generation, Some(1));
        assert_eq!(inherited.event_id, queued.event_id);
        assert_eq!(inherited.outbox_id, queued.outbox_id);

        let authority_dir = temp.path().join("final-use-handoff");
        std::fs::create_dir(&authority_dir).expect("authority dir");
        std::fs::set_permissions(
            &authority_dir,
            std::fs::Permissions::from_mode(0o700),
        )
        .expect("authority permissions");
        let issuer = SigningKey::from_bytes(&[84; 32]);
        let final_use = FinalUseAuthority::open_state_dir(
            &authority_dir,
            "final-use-owner".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 71,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("final-use authority");
        let target = Arc::new(CountingTarget::new("destination:cognitive-store"));
        let dispatcher =
            ProductionFinalUseOutboxDispatcher::attach(final_use, target.clone());
        let binding = FinalUseBinding {
            subject_id: owner.as_str().to_string(),
            destination_id: target.destination_id().to_string(),
            request_sha256: digest_bytes(&operation_digest(successor.authority(), &inherited))
                .expect("request digest"),
            scope_sha256: [9; 32],
            payload_sha256: digest_bytes(&inherited.payload_sha256).expect("payload digest"),
        };
        let signed =
            signed_final_use(&issuer, binding.clone(), "final-use-handoff", [13; 32]);
        let result = dispatcher
            .dispatch(&successor, &signed, &binding, inherited)
            .await
            .expect("successor dispatch");
        assert_eq!(result.state, LocalOutcomeState::Committed);
        assert_eq!(target.calls(), 1);
        assert_eq!(
            successor
                .status("occurrence:queued-handoff")
                .await
                .expect("terminal status"),
            LocalOutcomeState::Committed
        );
        let counts = successor.lease.snapshot_counts().await.expect("counts");
        assert_eq!(counts.outbox_rows, 1, "handoff reuses one durable outbox identity");
    }
}
