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
use codex_hepta_contracts::Sha256Digest;
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
use crate::QueuedReceipt;
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
        validate_text(&lease_id, "production lease id", 512)?;
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
            (LocalLeaseHeadDisposition::ExpiredActive, Some(_)) => {
                return Err(ProductionWriterError::AuthorityExpired {
                    deadline: authority.lease_expires_at_unix_seconds,
                });
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

    pub async fn status(
        &self,
        occurrence_key: impl Into<String>,
    ) -> Result<LocalOutcomeState, ProductionWriterError> {
        self.verify_authority().await?;
        Ok(self.lease.status(occurrence_key).await?)
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
        match outcome {
            ProductionTargetOutcome::Committed {
                receipt: target_receipt,
            } => {
                let applied = self
                    .apply(&receipt.occurrence_key, target_receipt.clone())
                    .await;
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
                let local = self.reject(&receipt.occurrence_key, &reason).await?;
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
            replayed,
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

/// Dispatcher that can only be used with an explicit target attachment.
#[derive(Clone)]
pub struct ProductionOutboxDispatcher {
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
        let second =
            ProductionDurableWriter::open(store.clone(), auth.clone(), &AllowVerifier, lease_id, 1)
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
