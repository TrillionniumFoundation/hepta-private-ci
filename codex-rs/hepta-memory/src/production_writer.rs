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
use codex_hepta_operations::OperationIntentV1;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::CognitiveAccess;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CognitiveWriteReceipt;
use crate::ForgetMemoryDraft;
use crate::KgFactSetDraft;
use crate::LocalAdmission;
use crate::LocalLease;
use crate::LocalLeaseHeadDisposition;
use crate::LocalLeaseOutbox;
use crate::LocalLeaseOutboxError;
use crate::LocalOutcomeReceipt;
use crate::LocalOutcomeState;
use crate::LocalReconcileOutcome;
use crate::LocalReplayFinalization;
use crate::MemoryDraft;
use crate::MemoryRevisionDraft;
use crate::QueuedReceipt;
use crate::SourceDraft;
use crate::StableMemoryId;
use crate::local_lease_outbox::InheritedQueuedReceipt;
use crate::local_lease_outbox::dispatch_operation_digest;
#[cfg(test)]
use crate::local_lease_outbox::legacy_dispatch_operation_digest;
use crate::operation_claims;
use crate::operation_claims::DurableDispatchClaim;

/// Schema version of the externally-authorized H4 writer boundary.
pub const PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION: u32 = 1;
/// Stable provenance namespace for production writer receipts.
pub const PRODUCTION_DURABLE_WRITER_NAMESPACE: &str = "production_durable_writer";
pub const PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION: u32 = 1;
pub const PRODUCTION_COGNITIVE_MUTATION_NAMESPACE: &str = "production_cognitive_mutation";
const PRODUCTION_COGNITIVE_MUTATION_TOPIC: &str = "cognitive.store.semantic-mutation.v1";
/// The store opened by `CognitiveStore` must use this journal mode.
pub const PRODUCTION_DURABLE_WRITER_JOURNAL_MODE: &str = "wal";
/// SQLite `PRAGMA synchronous` value for FULL.
pub const PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL: i64 = 2;
/// Default owner-local lease held while one queued operation is being moved
/// from retryable/pre-dispatch state into the irreversible Indeterminate fence.
pub const PRODUCTION_DISPATCH_CLAIM_LEASE_MS: u64 = 30_000;

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
    #[error("production semantic mutation requires a retained live authority verifier")]
    LiveVerifierRequired,
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

    pub(crate) fn validate_for_agent(
        &self,
        agent_id: &AgentId,
    ) -> Result<(), ProductionWriterError> {
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

#[path = "production_cognitive_commit.rs"]
mod cognitive_commit;
#[path = "production_cognitive_digest.rs"]
mod cognitive_digest;

/// Opaque guard that linearizes one authority use against revocation.
///
/// A trusted verifier creates the guard only after atomically observing a
/// current grant. Revocation acknowledgement must wait for every issued guard
/// to drop. The owner holds this value across the complete SQLite mutation or
/// recovery publication boundary, so a check cannot become stale while the
/// caller waits for a lock, checkpoints a recovery image, or commits state.
pub struct ProductionAuthorityUseGuard {
    _guard: Box<dyn Send + 'static>,
}

impl ProductionAuthorityUseGuard {
    /// Wrap a verifier-owned guard whose `Drop` releases the verifier's live-use
    /// reservation. The verifier remains responsible for the actual
    /// revocation/currentness protocol; this constructor grants no authority.
    pub fn from_verified_use<G>(guard: G) -> Self
    where
        G: Send + 'static,
    {
        Self {
            _guard: Box::new(guard),
        }
    }
}

impl fmt::Debug for ProductionAuthorityUseGuard {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionAuthorityUseGuard")
            .finish_non_exhaustive()
    }
}

/// External verifier hook. Implementations should verify the signed grant,
/// scope, epoch, and opaque token before returning `Ok(())`.
///
/// `enter_use` is the production linearization boundary. A verifier that only
/// implements point-in-time `verify` remains usable for non-mutating
/// preflight/qualification, but cannot authorize a semantic mutation or
/// writable recovery publication.
///
/// The writer never treats a boolean field on the lease as authority and has
/// no built-in/self-signing implementation of this trait.
pub trait ProductionAuthorityVerifier: Send + Sync {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String>;

    fn enter_use(
        &self,
        _authority: &ProductionAuthorityLease,
        _expected_agent: &AgentId,
    ) -> Result<ProductionAuthorityUseGuard, String> {
        Err("authority verifier does not provide a linearized use guard".to_string())
    }
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

#[derive(Debug, thiserror::Error)]
pub enum ProductionCognitiveMutationError {
    #[error(transparent)]
    Authority(#[from] ProductionWriterError),
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error("production cognitive mutation already has a durable terminal result")]
    ObservedResult(Box<ProductionCognitiveMutationResultV1>),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProductionCognitiveMutationResultStateV1 {
    Queued,
    Indeterminate,
    Committed,
    Rejected,
    RolledBack,
}

impl ProductionCognitiveMutationResultStateV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Indeterminate => "indeterminate",
            Self::Committed => "committed",
            Self::Rejected => "rejected",
            Self::RolledBack => "rolled_back",
        }
    }
}

impl From<LocalOutcomeState> for ProductionCognitiveMutationResultStateV1 {
    fn from(value: LocalOutcomeState) -> Self {
        match value {
            LocalOutcomeState::Queued => Self::Queued,
            LocalOutcomeState::Indeterminate => Self::Indeterminate,
            LocalOutcomeState::Committed => Self::Committed,
            LocalOutcomeState::Rejected => Self::Rejected,
            LocalOutcomeState::RolledBack => Self::RolledBack,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionCognitiveMutationCommitV1 {
    pub schema_version: u32,
    pub namespace: String,
    pub operation_digest: Sha256Digest,
    pub write_digest: Sha256Digest,
    pub source_content_sha256: Sha256Digest,
    pub source_observed_at_unix_seconds: i64,
    pub memory_id: String,
    pub memory_revision: u64,
    pub source_id: String,
    pub source_revision: u64,
    pub projection_output_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ProductionCognitiveMutationResultV1 {
    pub schema_version: u32,
    pub namespace: String,
    pub state: ProductionCognitiveMutationResultStateV1,
    pub mutation_kind: String,
    pub operation_digest: Sha256Digest,
    pub input_payload_sha256: Sha256Digest,
    pub expected_predecessor_revision: Option<u64>,
    pub owner_agent_id: AgentId,
    pub authority_grant_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub lease_id: String,
    pub generation: u64,
    pub provenance_event_id: String,
    pub provenance_outbox_id: String,
    pub latest_event_id: String,
    pub latest_event_kind: String,
    pub latest_payload_json: String,
    pub commit: Option<ProductionCognitiveMutationCommitV1>,
    pub result_sha256: Sha256Digest,
    pub external_effect: bool,
}

impl ProductionCognitiveMutationResultV1 {
    #[must_use]
    pub fn compute_result_sha256(&self) -> Sha256Digest {
        production_cognitive_result_digest(self)
    }

    pub fn validate(&self) -> Result<(), ProductionWriterError> {
        let terminal_shape_valid = match self.state {
            ProductionCognitiveMutationResultStateV1::Committed => {
                self.commit.as_ref().is_some_and(|commit| {
                    self.latest_event_kind == "reconcile_committed"
                        && commit.schema_version == PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION
                        && commit.namespace == PRODUCTION_COGNITIVE_MUTATION_NAMESPACE
                        && commit.operation_digest == self.operation_digest
                        && serde_json::to_string(commit)
                            .is_ok_and(|encoded| encoded == self.latest_payload_json)
                })
            }
            ProductionCognitiveMutationResultStateV1::Queued
            | ProductionCognitiveMutationResultStateV1::Indeterminate
            | ProductionCognitiveMutationResultStateV1::Rejected
            | ProductionCognitiveMutationResultStateV1::RolledBack => self.commit.is_none(),
        };
        let expected_operation = production_cognitive_operation_digest_parts(
            &self.authority_grant_digest,
            self.authority_epoch,
            self.owner_epoch,
            &self.lease_id,
            self.generation,
            &self.mutation_kind,
            &self.input_payload_sha256,
            self.expected_predecessor_revision,
        );
        if self.schema_version != PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION
            || self.namespace != PRODUCTION_COGNITIVE_MUTATION_NAMESPACE
            || self.external_effect
            || self.generation == 0
            || self.provenance_event_id.is_empty()
            || self.provenance_outbox_id.is_empty()
            || self.latest_event_id.is_empty()
            || !terminal_shape_valid
            || self.operation_digest != expected_operation
            || self.result_sha256 != self.compute_result_sha256()
        {
            return Err(ProductionWriterError::StaleReceipt);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ProductionCognitiveMutationReceiptV1 {
    pub schema_version: u32,
    pub namespace: String,
    pub mutation_kind: String,
    pub operation_digest: Sha256Digest,
    pub input_payload_sha256: Sha256Digest,
    pub source_content_sha256: Sha256Digest,
    pub source_observed_at_unix_seconds: i64,
    pub expected_predecessor_revision: Option<u64>,
    pub owner_agent_id: AgentId,
    pub authority_grant_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub lease_id: String,
    pub generation: u64,
    pub provenance_event_id: String,
    pub provenance_outbox_id: String,
    pub provenance_commit_event_id: String,
    pub write_digest: Sha256Digest,
    pub write: CognitiveWriteReceipt,
    pub receipt_sha256: Sha256Digest,
    pub external_effect: bool,
}

impl ProductionCognitiveMutationReceiptV1 {
    #[must_use]
    pub fn compute_receipt_sha256(&self) -> Sha256Digest {
        production_cognitive_receipt_digest(self)
    }

    pub fn validate(&self) -> Result<(), ProductionWriterError> {
        if self.schema_version != PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION
            || self.namespace != PRODUCTION_COGNITIVE_MUTATION_NAMESPACE
            || self.external_effect
            || self.write_digest != production_cognitive_write_digest(&self.write)?
            || self.receipt_sha256 != self.compute_receipt_sha256()
        {
            return Err(ProductionWriterError::StaleReceipt);
        }
        Ok(())
    }
}

pub type ProductionCognitiveMutationFuture<'a> = Pin<
    Box<
        dyn Future<
                Output = Result<
                    ProductionCognitiveMutationReceiptV1,
                    ProductionCognitiveMutationError,
                >,
            > + Send
            + 'a,
    >,
>;

mod production_cognitive_mutation_sealed {
    pub trait Sealed {}
}

/// Opaque production mutation capability. Consumers can request canonical
/// semantic mutations, but cannot open the durable owner, mint authority, or
/// manufacture a current-cut witness through this interface. The trait is
/// sealed: only this durable-owner crate can mint an implementation.
#[allow(private_bounds)]
pub trait ProductionCognitiveMutation:
    production_cognitive_mutation_sealed::Sealed + Send + Sync
{
    fn owner_agent_id(&self) -> &AgentId;

    fn remember_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        source: &'a SourceDraft,
        draft: &'a MemoryDraft,
        facts: &'a KgFactSetDraft,
    ) -> ProductionCognitiveMutationFuture<'a>;

    fn correct_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        memory_id: &'a StableMemoryId,
        expected_revision: u64,
        source: &'a SourceDraft,
        draft: &'a MemoryRevisionDraft,
        facts: &'a KgFactSetDraft,
    ) -> ProductionCognitiveMutationFuture<'a>;

    fn forget_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        memory_id: &'a StableMemoryId,
        expected_revision: u64,
        source: &'a SourceDraft,
        draft: &'a ForgetMemoryDraft,
    ) -> ProductionCognitiveMutationFuture<'a>;
}

/// Durable writer bound to one externally-authorized lease.
#[derive(Clone)]
pub struct ProductionDurableWriter {
    store: CognitiveStore,
    authority: ProductionAuthorityLease,
    lease: LocalLeaseOutbox,
    lease_id: Arc<str>,
    live_verifier: Option<Arc<dyn ProductionAuthorityVerifier>>,
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
                let previous_authority_epoch = head
                    .authority_epoch
                    .ok_or(ProductionWriterError::StaleReceipt)?;
                let previous_owner_epoch = head
                    .owner_epoch
                    .ok_or(ProductionWriterError::StaleReceipt)?;
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
            live_verifier: None,
            _writer_lock: writer_lock,
        })
    }

    /// Open a writer with a verifier retained for every final-use authority
    /// check. Production semantic mutation must use this constructor. The
    /// verifier must also support a linearized use guard; a point-in-time-only
    /// verifier cannot mint the semantic mutation capability.
    pub async fn open_with_live_verifier(
        store: CognitiveStore,
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: impl Into<String>,
        generation: u64,
    ) -> Result<Self, ProductionWriterError> {
        // Creating or taking over a durable lease already mutates the owner.
        // Reject a point-in-time-only verifier before that mutation, not after
        // Self::open has committed a lease that the caller cannot safely use.
        authority.validate_for_agent(store.owner_agent_id())?;
        let guard = verifier
            .enter_use(&authority, store.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)?;
        let lease_id = lease_id.into();
        let runtime = tokio::runtime::Handle::try_current()
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        tokio::task::spawn_blocking(move || {
            // The waiter may disappear during SQLx lease COMMIT. Retain the
            // external authority hold until that worker has actually answered.
            let outcome = runtime.block_on(async move {
                let retained_verifier = Arc::clone(&verifier);
                let mut writer =
                    Self::open(store, authority, verifier.as_ref(), lease_id, generation).await?;
                writer.live_verifier = Some(retained_verifier);
                writer.verify_authority().await?;
                Ok(writer)
            });
            drop(guard);
            outcome
        })
        .await
        .map_err(|error| ProductionWriterError::Durability(format!(
            "production writer admission task terminated; inspect the durable lease before retry: {error}"
        )))?
    }

    /// Revalidate the external authority immediately before a semantic owner
    /// mutation. Legacy qualification writers fail closed at this boundary.
    pub async fn verify_current_authority(&self) -> Result<(), ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        self.verify_authority().await
    }

    /// Mint the only production cognitive mutation capability. A legacy writer
    /// opened without a retained live verifier cannot obtain this capability.
    pub fn cognitive_mutation_capability(
        self: &Arc<Self>,
    ) -> Result<ProductionCognitiveMutationCapability, ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        Ok(ProductionCognitiveMutationCapability {
            writer: Arc::clone(self),
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

    /// Read-only owner identity exposed to host composition without leaking the
    /// raw mutable CognitiveStore capability across crate boundaries.
    pub fn owner_agent_id(&self) -> &AgentId {
        self.store.owner_agent_id()
    }

    /// Read-only database path for qualification/evidence tooling. This does
    /// not expose the mutable owner handle.
    pub fn database_path(&self) -> &std::path::Path {
        self.store.path()
    }

    /// Capture a read-only exact-cut witness for qualification/evidence. The
    /// returned digest is not write authority and still requires independent
    /// host authentication before a later writable recovery.
    pub async fn recovery_anchor(
        &self,
    ) -> Result<crate::CognitiveRecoveryAnchor, crate::CognitiveStoreError> {
        self.store.recovery_anchor().await
    }

    /// Inspect one semantic mutation by its stable operation digest. This is a
    /// read-only result query, not permission to replay the mutation. It remains
    /// available after response loss and after live authority revocation, while
    /// the local lease/fence rules still govern which historical occurrence a
    /// successor may observe.
    pub async fn cognitive_mutation_result(
        &self,
        operation_digest: &Sha256Digest,
    ) -> Result<Option<ProductionCognitiveMutationResultV1>, ProductionWriterError> {
        let occurrence_key = format!("cognitive-mutation:{}", operation_digest.as_str());
        let Some(observation) = self.lease.observe_occurrence(&occurrence_key).await? else {
            return Ok(None);
        };
        if observation.topic != PRODUCTION_COGNITIVE_MUTATION_TOPIC {
            return Err(production_cognitive_journal_corrupt(
                "semantic mutation occurrence has an unexpected topic",
            ));
        }
        let intent: ProductionCognitiveMutationIntentRecordV1 =
            serde_json::from_str(&observation.admission_payload_json).map_err(|error| {
                production_cognitive_journal_corrupt(format!(
                    "semantic mutation intent is not canonical JSON: {error}"
                ))
            })?;
        let expected_operation = production_cognitive_operation_digest_parts(
            &intent.authority_grant_digest,
            intent.authority_epoch,
            intent.owner_epoch,
            &intent.lease_id,
            intent.generation,
            &intent.mutation_kind,
            &intent.input_payload_sha256,
            intent.expected_predecessor_revision,
        );
        if intent.schema_version != PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION
            || intent.namespace != PRODUCTION_COGNITIVE_MUTATION_NAMESPACE
            || intent.operation_digest != *operation_digest
            || expected_operation != *operation_digest
            || intent.owner_agent_id != *self.store.owner_agent_id()
            || intent.lease_id != self.lease_id()
            || intent.generation == 0
            || observation.occurrence_key != occurrence_key
        {
            return Err(production_cognitive_journal_corrupt(
                "semantic mutation intent does not match its owner, lease, or operation digest",
            ));
        }
        let state = ProductionCognitiveMutationResultStateV1::from(observation.state);
        let commit = if state == ProductionCognitiveMutationResultStateV1::Committed {
            if observation.latest_event_kind != "reconcile_committed" {
                return Err(production_cognitive_journal_corrupt(
                    "committed semantic mutation lacks its committed event",
                ));
            }
            let commit: ProductionCognitiveMutationCommitV1 =
                serde_json::from_str(&observation.latest_payload_json).map_err(|error| {
                    production_cognitive_journal_corrupt(format!(
                        "semantic mutation commit is not canonical JSON: {error}"
                    ))
                })?;
            if commit.operation_digest != *operation_digest {
                return Err(production_cognitive_journal_corrupt(
                    "semantic mutation commit belongs to another operation",
                ));
            }
            Some(commit)
        } else {
            None
        };
        let mut result = ProductionCognitiveMutationResultV1 {
            schema_version: intent.schema_version,
            namespace: intent.namespace,
            state,
            mutation_kind: intent.mutation_kind,
            operation_digest: intent.operation_digest,
            input_payload_sha256: intent.input_payload_sha256,
            expected_predecessor_revision: intent.expected_predecessor_revision,
            owner_agent_id: intent.owner_agent_id,
            authority_grant_digest: intent.authority_grant_digest,
            authority_epoch: intent.authority_epoch,
            owner_epoch: intent.owner_epoch,
            lease_id: intent.lease_id,
            generation: intent.generation,
            provenance_event_id: observation.admission_event_id,
            provenance_outbox_id: observation.outbox_id,
            latest_event_id: observation.latest_event_id,
            latest_event_kind: observation.latest_event_kind,
            latest_payload_json: observation.latest_payload_json,
            commit,
            result_sha256: Sha256Digest::for_bytes(b"pending"),
            external_effect: false,
        };
        result.result_sha256 = result.compute_result_sha256();
        result.validate()?;
        Ok(Some(result))
    }

    pub(crate) fn store(&self) -> &CognitiveStore {
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

    /// Prepare a complete kernel operation and publish its outbox identity in
    /// the same durable SQLite transaction.
    pub async fn prepare_operation(
        &self,
        operation: OperationIntentV1,
        topic: impl Into<String>,
        payload_json: impl Into<String>,
    ) -> Result<ProductionQueuedReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        let topic = topic.into();
        let payload_json = payload_json.into();
        let admission = self
            .lease
            .admit_operation(operation, &topic, &payload_json)
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

    /// Derive the only FinalUseBinding accepted for this durable operation
    /// and destination. Grant signers should sign this value verbatim.
    pub async fn final_use_binding(
        &self,
        receipt: &ProductionQueuedReceipt,
        destination_id: &str,
    ) -> Result<FinalUseBinding, ProductionWriterError> {
        self.verify_authority().await?;
        self.validate_queued_receipt(receipt)?;
        let operation = self
            .lease
            .verify_operation_dispatch_binding(&receipt.occurrence_key, destination_id)
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
            operation_scope_sha256: operation.scope_sha256.clone(),
            operation_subject_id: operation.subject_id.clone(),
            operation_destination_id: operation.destination_id.clone(),
            operation_semantic_sha256: operation.operation_semantic_sha256.clone(),
            operation_policy_generation: operation.policy_generation,
            expected_predecessor_sha256: operation.expected_predecessor_sha256.clone(),
            operation_digest: operation_digest(&self.authority, receipt, &operation),
        };
        Ok(FinalUseBinding {
            subject_id: self.store.owner_agent_id().as_str().to_string(),
            destination_id: operation.destination_id,
            request_sha256: digest_bytes(&request.operation_digest)?,
            scope_sha256: digest_bytes(&operation.scope_sha256)?,
            payload_sha256: digest_bytes(&request.payload_sha256)?,
        })
    }

    /// Acquire the durable owner-local dispatch lease for one exact queued
    /// operation. This lease is retryable only before the one-shot
    /// Indeterminate/effect-entry fence is written.
    pub async fn claim_dispatch_lease(
        &self,
        receipt: &ProductionQueuedReceipt,
        lease_duration_ms: u64,
    ) -> Result<DurableDispatchClaim, ProductionWriterError> {
        self.verify_authority().await?;
        self.validate_queued_receipt(receipt)?;
        Ok(operation_claims::claim(
            &self.store,
            &receipt.occurrence_key,
            self.generation(),
            self.lease.fencing_token(),
            now_unix_ms()?,
            lease_duration_ms,
        )
        .await?)
    }

    /// Extend a live pre-dispatch claim. Renewal never makes an entered or
    /// indeterminate operation retryable.
    pub async fn renew_dispatch_claim(
        &self,
        claim: &DurableDispatchClaim,
        lease_duration_ms: u64,
    ) -> Result<DurableDispatchClaim, ProductionWriterError> {
        self.verify_authority().await?;
        if claim.owner_generation != self.generation()
            || claim.fencing_token != self.lease.fencing_token()
        {
            return Err(ProductionWriterError::StaleReceipt);
        }
        Ok(operation_claims::renew(&self.store, claim, now_unix_ms()?, lease_duration_ms).await?)
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
            .map(|receipt| {
                ProductionQueuedReceipt::from_inherited(&self.authority, self.generation(), receipt)
            })
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

    /// Discover and reconcile a bounded batch of operations whose latest
    /// durable source state is indeterminate. Discovery is destination-scoped
    /// and reconciliation calls only the target observer, never dispatch.
    pub async fn reconcile_target_batch<T>(
        &self,
        target: &T,
        limit: usize,
    ) -> Result<usize, ProductionWriterError>
    where
        T: FinalUseProductionOutboxTarget + ?Sized,
    {
        self.verify_authority().await?;
        if !(1..=256).contains(&limit) {
            return Err(ProductionWriterError::Invalid(
                "reconcile batch limit must be 1..=256".to_string(),
            ));
        }
        let operation_ids = sqlx::query_scalar::<_, String>(
            "SELECT o.operation_id
             FROM cognitive_operation_ledger o
             WHERE o.lease_id = ? AND o.destination_id = ?
               AND (
                   SELECT e.event_kind
                   FROM cognitive_local_events e
                   WHERE e.lease_id = o.lease_id
                     AND e.occurrence_key = o.operation_id
                   ORDER BY e.event_sequence DESC
                   LIMIT 1
               ) IN ('indeterminate', 'reconcile_still_indeterminate')
             ORDER BY o.prepared_at_unix_seconds, o.operation_id
             LIMIT ?",
        )
        .bind(self.lease_id())
        .bind(target.destination_id())
        .bind(i64::try_from(limit).map_err(|_| {
            ProductionWriterError::Invalid("reconcile batch limit overflow".to_string())
        })?)
        .fetch_all(&self.store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;

        let mut reconciled = 0_usize;
        for operation_id in operation_ids {
            let request = self
                .reconciliation_request(&operation_id, target.destination_id())
                .await?;
            match target.observe_terminal(&request).await {
                ProductionTerminalObservation::Applied { .. } => {
                    self.reconcile(&operation_id, LocalReconcileOutcome::Committed)
                        .await?;
                    reconciled += 1;
                }
                ProductionTerminalObservation::NotApplied { .. }
                | ProductionTerminalObservation::Quarantined { .. } => {
                    self.reconcile(&operation_id, LocalReconcileOutcome::Rejected)
                        .await?;
                    reconciled += 1;
                }
                ProductionTerminalObservation::Indeterminate { .. } => {
                    self.reconcile(&operation_id, LocalReconcileOutcome::StillIndeterminate)
                        .await?;
                    reconciled += 1;
                }
                ProductionTerminalObservation::Unavailable { .. } => {}
            }
        }
        Ok(reconciled)
    }

    async fn reconciliation_request(
        &self,
        occurrence_key: &str,
        destination_id: &str,
    ) -> Result<ProductionDispatchRequest, ProductionWriterError> {
        let operation = self
            .lease
            .verify_operation_dispatch_binding(occurrence_key, destination_id)
            .await
            .map_err(|error| match error {
                LocalLeaseOutboxError::StaleFence(_)
                | LocalLeaseOutboxError::IllegalTransition(_)
                | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
                other => ProductionWriterError::Local(other),
            })?;
        let (topic, payload_json, payload_sha256): (String, String, String) = sqlx::query_as(
            "SELECT topic, payload_json, payload_sha256
                 FROM cognitive_local_outbox
                 WHERE lease_id = ? AND occurrence_key = ?
                 LIMIT 1",
        )
        .bind(self.lease_id())
        .bind(occurrence_key)
        .fetch_optional(&self.store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?
        .ok_or_else(|| {
            ProductionWriterError::Durability(
                "indeterminate operation is missing its durable outbox row".to_string(),
            )
        })?;
        let payload_sha256 =
            Sha256Digest::parse(&payload_sha256).map_err(ProductionWriterError::Invalid)?;
        let operation_digest = dispatch_operation_digest(
            &self.authority.grant_digest,
            self.lease_id(),
            occurrence_key,
            &topic,
            &payload_sha256,
            &operation.operation_semantic_sha256,
            operation.expected_predecessor_sha256.as_ref(),
        );
        Ok(ProductionDispatchRequest {
            schema_version: PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
            namespace: PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
            lease_id: self.lease_id().to_string(),
            occurrence_key: occurrence_key.to_string(),
            topic,
            payload_json,
            payload_sha256,
            idempotency_key: occurrence_key.to_string(),
            operation_scope_sha256: operation.scope_sha256,
            operation_subject_id: operation.subject_id,
            operation_destination_id: operation.destination_id,
            operation_semantic_sha256: operation.operation_semantic_sha256,
            operation_policy_generation: operation.policy_generation,
            expected_predecessor_sha256: operation.expected_predecessor_sha256,
            operation_digest,
        })
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

    fn enter_authority_use(&self) -> Result<ProductionAuthorityUseGuard, ProductionWriterError> {
        self.authority
            .validate_for_agent(self.store.owner_agent_id())?;
        self.live_verifier
            .as_ref()
            .ok_or(ProductionWriterError::LiveVerifierRequired)?
            .enter_use(&self.authority, self.store.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)
    }

    async fn verify_authority(&self) -> Result<(), ProductionWriterError> {
        self.authority
            .validate_for_agent(self.store.owner_agent_id())?;
        if let Some(verifier) = &self.live_verifier {
            verifier
                .verify(&self.authority, self.store.owner_agent_id())
                .map_err(ProductionWriterError::AuthorityRejected)?;
        }
        verify_durable_store(&self.store).await?;
        self.lease.verify_current_hot_path().await?;
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

    #[cfg(test)]
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
            operation_scope_sha256: Sha256Digest::for_bytes(b"legacy-unbound-scope"),
            operation_subject_id: String::new(),
            operation_destination_id: String::new(),
            operation_semantic_sha256: receipt.payload_sha256.clone(),
            operation_policy_generation: 0,
            expected_predecessor_sha256: None,
            operation_digest: legacy_operation_digest(&self.authority, &receipt),
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
        let durable_operation = self
            .lease
            .verify_operation_dispatch_binding(&receipt.occurrence_key, target.destination_id())
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
            operation_scope_sha256: durable_operation.scope_sha256.clone(),
            operation_subject_id: durable_operation.subject_id.clone(),
            operation_destination_id: durable_operation.destination_id.clone(),
            operation_semantic_sha256: durable_operation.operation_semantic_sha256.clone(),
            operation_policy_generation: durable_operation.policy_generation,
            expected_predecessor_sha256: durable_operation.expected_predecessor_sha256.clone(),
            operation_digest: operation_digest(&self.authority, &receipt, &durable_operation),
        };
        verify_final_use_dispatch_binding(
            self.store.owner_agent_id(),
            target.destination_id(),
            &durable_operation.scope_sha256,
            &request,
            expected,
        )?;

        // Acquire the retryable owner-local lease first. This claim may be
        // renewed or taken over after expiry only while the operation has not
        // crossed the one-shot Indeterminate/effect-entry fence.
        let owner_claim = self
            .claim_dispatch_lease(&receipt, PRODUCTION_DISPATCH_CLAIM_LEASE_MS)
            .await?;

        // Now make the ambiguous external boundary durable. A crash from this
        // point onward reopens as Indeterminate and must reconcile; the
        // per-operation claim is no longer allowed to authorize a resend.
        let inherited_from_generation = receipt.inherited_from_generation;
        let dispatch_claim_event_id = match inherited_from_generation {
            Some(source_generation) => {
                self.lease
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
                    .await
            }
            None => {
                self.lease
                    .claim_dispatch(
                        &receipt.occurrence_key,
                        &self.authority.grant_digest,
                        &request.operation_digest,
                    )
                    .await
            }
        }
        .map_err(|error| match error {
            LocalLeaseOutboxError::StaleFence(_)
            | LocalLeaseOutboxError::IllegalTransition(_)
            | LocalLeaseOutboxError::CasConflict(_) => ProductionWriterError::StaleReceipt,
            other => ProductionWriterError::Local(other),
        })?
        .event_id;
        let entered_claim =
            operation_claims::mark_entered(&self.store, &owner_claim, now_unix_ms()?).await?;

        // Then consume the single-use grant and revalidate it immediately at
        // target entry. If either check fails before the adapter is entered we
        // know no external effect happened, so settle local state as Rejected.
        let token = match final_use.claim(signed, expected) {
            Ok(token) => token,
            Err(error) => {
                if self
                    .settle_pre_dispatch_rejection(
                        &receipt.occurrence_key,
                        inherited_from_generation.is_some(),
                        format!("final-use claim rejected: {error}"),
                    )
                    .await
                    .is_ok()
                {
                    let _ = operation_claims::mark_settled(
                        &self.store,
                        &entered_claim,
                        now_unix_ms().unwrap_or(1),
                    )
                    .await;
                }
                return Err(ProductionWriterError::FinalUse(error));
            }
        };
        let future = match final_use
            .with_verified_use(token, expected, || target.dispatch(request.clone()))
        {
            Ok(future) => future,
            Err(error) => {
                if self
                    .settle_pre_dispatch_rejection(
                        &receipt.occurrence_key,
                        inherited_from_generation.is_some(),
                        format!("final-use entry rejected: {error}"),
                    )
                    .await
                    .is_ok()
                {
                    let _ = operation_claims::mark_settled(
                        &self.store,
                        &entered_claim,
                        now_unix_ms().unwrap_or(1),
                    )
                    .await;
                }
                return Err(ProductionWriterError::FinalUse(error));
            }
        };
        let outcome = future.await;
        let settled = if inherited_from_generation.is_some() {
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
        };
        if let Ok(dispatch_receipt) = settled.as_ref()
            && dispatch_receipt.target_disposition != ProductionTargetDisposition::Indeterminate
        {
            // Local terminality is already durable at this point, so failure
            // to append the secondary claim-settled marker must not erase a
            // real destination result or make the operation retryable.
            let _ = operation_claims::mark_settled(
                &self.store,
                &entered_claim,
                now_unix_ms().unwrap_or(1),
            )
            .await;
        }
        settled
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
                    target_disposition: ProductionTargetDisposition::Committed,
                    target_receipt: Some(receipt),
                    target_reason: None,
                    local_event_id: local.event_id,
                    external_effect: true,
                })
            }
            ProductionTargetOutcome::NotApplied { reason } => {
                let local = self
                    .reconcile(occurrence_key, LocalReconcileOutcome::Rejected)
                    .await?;
                Ok(ProductionDispatchReceipt {
                    request,
                    state: LocalOutcomeState::Rejected,
                    target_disposition: ProductionTargetDisposition::NotApplied,
                    target_receipt: None,
                    target_reason: Some(reason),
                    local_event_id: local.event_id,
                    external_effect: false,
                })
            }
            ProductionTargetOutcome::Rejected { reason } => {
                let local = self
                    .reconcile(occurrence_key, LocalReconcileOutcome::Rejected)
                    .await?;
                Ok(ProductionDispatchReceipt {
                    request,
                    state: LocalOutcomeState::Rejected,
                    target_disposition: ProductionTargetDisposition::Rejected,
                    target_receipt: None,
                    target_reason: Some(reason),
                    local_event_id: local.event_id,
                    external_effect: false,
                })
            }
            ProductionTargetOutcome::Indeterminate { reason } => Ok(ProductionDispatchReceipt {
                request,
                state: LocalOutcomeState::Indeterminate,
                target_disposition: ProductionTargetDisposition::Indeterminate,
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
                        target_disposition: ProductionTargetDisposition::Committed,
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
            ProductionTargetOutcome::NotApplied { reason } => {
                let local = self.reject(occurrence_key, &reason).await?;
                Ok(ProductionDispatchReceipt {
                    request,
                    state: LocalOutcomeState::Rejected,
                    target_disposition: ProductionTargetDisposition::NotApplied,
                    target_receipt: None,
                    target_reason: Some(reason),
                    local_event_id: local.event_id,
                    external_effect: false,
                })
            }
            ProductionTargetOutcome::Rejected { reason } => {
                let local = self.reject(occurrence_key, &reason).await?;
                Ok(ProductionDispatchReceipt {
                    request,
                    state: LocalOutcomeState::Rejected,
                    target_disposition: ProductionTargetDisposition::Rejected,
                    target_receipt: None,
                    target_reason: Some(reason),
                    local_event_id: local.event_id,
                    external_effect: false,
                })
            }
            ProductionTargetOutcome::Indeterminate { reason } => Ok(ProductionDispatchReceipt {
                request,
                state: LocalOutcomeState::Indeterminate,
                target_disposition: ProductionTargetDisposition::Indeterminate,
                target_receipt: None,
                target_reason: Some(reason),
                local_event_id: dispatch_claim_event_id,
                external_effect: false,
            }),
        }
    }
}

/// Non-forgeable semantic write capability minted only by a live-verified
/// ProductionDurableWriter. Its fields are private and the public trait is
/// sealed, so downstream crates cannot substitute a raw-store implementation.
#[derive(Clone)]
pub struct ProductionCognitiveMutationCapability {
    writer: Arc<ProductionDurableWriter>,
}

impl production_cognitive_mutation_sealed::Sealed for ProductionCognitiveMutationCapability {}

impl ProductionCognitiveMutation for ProductionCognitiveMutationCapability {
    fn owner_agent_id(&self) -> &AgentId {
        self.writer.store().owner_agent_id()
    }

    fn remember_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        source: &'a SourceDraft,
        draft: &'a MemoryDraft,
        facts: &'a KgFactSetDraft,
    ) -> ProductionCognitiveMutationFuture<'a> {
        Box::pin(async move {
            self.writer.verify_current_authority().await?;
            // A replay is still a scoped read of a durable result. Reject a
            // foreign access context before the duplicate-observation path.
            self.writer.store().authorize(access, &source.scope)?;
            let prepared =
                self.prepare_semantic_mutation("remember", source, None, &(draft, facts))?;
            let mut transaction = self
                .writer
                .store()
                .pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            // Linearize external revocation only after acquiring the SQLite
            // writer lock. The guard remains alive through the commit, while
            // the local lease is revalidated inside this exact transaction.
            let _authority_use = self.writer.enter_authority_use()?;
            self.writer
                .lease
                .verify_current_hot_path_in_transaction(&mut transaction)
                .await
                .map_err(ProductionWriterError::from)?;
            let queued = match self
                .admit_prepared_mutation(&mut transaction, &prepared)
                .await
            {
                Ok(queued) => queued,
                Err(error) => {
                    transaction
                        .rollback()
                        .await
                        .map_err(crate::cognitive_store::unavailable)?;
                    if let Some(result) = self
                        .writer
                        .cognitive_mutation_result(&prepared.operation_digest)
                        .await?
                    {
                        return Err(ProductionCognitiveMutationError::ObservedResult(Box::new(
                            result,
                        )));
                    }
                    return Err(error);
                }
            };
            let write = self
                .writer
                .store()
                .remember_with_kg_tx(&mut transaction, access, source, draft, facts)
                .await?;
            let receipt = self
                .finish_prepared_mutation(&mut transaction, prepared, queued, write)
                .await?;
            // Validate before durability; invalid receipts must not describe a
            // mutation that already became visible. A use hold pins revocation,
            // not the grant's absolute expiry.
            receipt.validate()?;
            self.writer
                .authority
                .validate_for_agent(self.writer.store().owner_agent_id())?;
            cognitive_commit::commit(transaction, _authority_use, Arc::clone(&self.writer)).await?;
            Ok(receipt)
        })
    }

    fn correct_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        memory_id: &'a StableMemoryId,
        expected_revision: u64,
        source: &'a SourceDraft,
        draft: &'a MemoryRevisionDraft,
        facts: &'a KgFactSetDraft,
    ) -> ProductionCognitiveMutationFuture<'a> {
        Box::pin(async move {
            self.writer.verify_current_authority().await?;
            // A replay is still a scoped read of a durable result. Reject a
            // foreign access context before the duplicate-observation path.
            self.writer.store().authorize(access, &source.scope)?;
            let prepared = self.prepare_semantic_mutation(
                "correct",
                source,
                Some(expected_revision),
                &(memory_id.as_str(), draft, facts),
            )?;
            let mut transaction = self
                .writer
                .store()
                .pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            // Linearize external revocation only after acquiring the SQLite
            // writer lock. The guard remains alive through the commit, while
            // the local lease is revalidated inside this exact transaction.
            let _authority_use = self.writer.enter_authority_use()?;
            self.writer
                .lease
                .verify_current_hot_path_in_transaction(&mut transaction)
                .await
                .map_err(ProductionWriterError::from)?;
            let queued = match self
                .admit_prepared_mutation(&mut transaction, &prepared)
                .await
            {
                Ok(queued) => queued,
                Err(error) => {
                    transaction
                        .rollback()
                        .await
                        .map_err(crate::cognitive_store::unavailable)?;
                    if let Some(result) = self
                        .writer
                        .cognitive_mutation_result(&prepared.operation_digest)
                        .await?
                    {
                        return Err(ProductionCognitiveMutationError::ObservedResult(Box::new(
                            result,
                        )));
                    }
                    return Err(error);
                }
            };
            let write = self
                .writer
                .store()
                .correct_with_kg_tx(
                    &mut transaction,
                    access,
                    &crate::MemoryRevisionId {
                        memory_id: memory_id.clone(),
                        revision: expected_revision,
                    },
                    source,
                    draft,
                    facts,
                )
                .await?;
            let receipt = self
                .finish_prepared_mutation(&mut transaction, prepared, queued, write)
                .await?;
            // Validate before durability; invalid receipts must not describe a
            // mutation that already became visible. A use hold pins revocation,
            // not the grant's absolute expiry.
            receipt.validate()?;
            self.writer
                .authority
                .validate_for_agent(self.writer.store().owner_agent_id())?;
            cognitive_commit::commit(transaction, _authority_use, Arc::clone(&self.writer)).await?;
            Ok(receipt)
        })
    }

    fn forget_with_kg<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        memory_id: &'a StableMemoryId,
        expected_revision: u64,
        source: &'a SourceDraft,
        draft: &'a ForgetMemoryDraft,
    ) -> ProductionCognitiveMutationFuture<'a> {
        Box::pin(async move {
            self.writer.verify_current_authority().await?;
            // A replay is still a scoped read of a durable result. Reject a
            // foreign access context before the duplicate-observation path.
            self.writer.store().authorize(access, &source.scope)?;
            let prepared = self.prepare_semantic_mutation(
                "forget",
                source,
                Some(expected_revision),
                &(memory_id.as_str(), draft),
            )?;
            let mut transaction = self
                .writer
                .store()
                .pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            // Linearize external revocation only after acquiring the SQLite
            // writer lock. The guard remains alive through the commit, while
            // the local lease is revalidated inside this exact transaction.
            let _authority_use = self.writer.enter_authority_use()?;
            self.writer
                .lease
                .verify_current_hot_path_in_transaction(&mut transaction)
                .await
                .map_err(ProductionWriterError::from)?;
            let queued = match self
                .admit_prepared_mutation(&mut transaction, &prepared)
                .await
            {
                Ok(queued) => queued,
                Err(error) => {
                    transaction
                        .rollback()
                        .await
                        .map_err(crate::cognitive_store::unavailable)?;
                    if let Some(result) = self
                        .writer
                        .cognitive_mutation_result(&prepared.operation_digest)
                        .await?
                    {
                        return Err(ProductionCognitiveMutationError::ObservedResult(Box::new(
                            result,
                        )));
                    }
                    return Err(error);
                }
            };
            let write = self
                .writer
                .store()
                .forget_with_kg_tx(
                    &mut transaction,
                    access,
                    memory_id,
                    expected_revision,
                    source,
                    draft,
                )
                .await?;
            let receipt = self
                .finish_prepared_mutation(&mut transaction, prepared, queued, write)
                .await?;
            // Validate before durability; invalid receipts must not describe a
            // mutation that already became visible. A use hold pins revocation,
            // not the grant's absolute expiry.
            receipt.validate()?;
            self.writer
                .authority
                .validate_for_agent(self.writer.store().owner_agent_id())?;
            cognitive_commit::commit(transaction, _authority_use, Arc::clone(&self.writer)).await?;
            Ok(receipt)
        })
    }
}

struct PreparedProductionCognitiveMutation {
    mutation_kind: String,
    operation_digest: Sha256Digest,
    input_payload_sha256: Sha256Digest,
    source_content_sha256: Sha256Digest,
    source_observed_at_unix_seconds: i64,
    expected_predecessor_revision: Option<u64>,
    occurrence_key: String,
    intent_json: String,
}

impl ProductionCognitiveMutationCapability {
    pub fn remember_operation_digest(
        &self,
        source: &SourceDraft,
        draft: &MemoryDraft,
        facts: &KgFactSetDraft,
    ) -> Result<Sha256Digest, ProductionCognitiveMutationError> {
        Ok(self
            .prepare_semantic_mutation("remember", source, None, &(draft, facts))?
            .operation_digest)
    }

    pub fn correct_operation_digest(
        &self,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &MemoryRevisionDraft,
        facts: &KgFactSetDraft,
    ) -> Result<Sha256Digest, ProductionCognitiveMutationError> {
        Ok(self
            .prepare_semantic_mutation(
                "correct",
                source,
                Some(expected_revision),
                &(memory_id.as_str(), draft, facts),
            )?
            .operation_digest)
    }

    pub fn forget_operation_digest(
        &self,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &ForgetMemoryDraft,
    ) -> Result<Sha256Digest, ProductionCognitiveMutationError> {
        Ok(self
            .prepare_semantic_mutation(
                "forget",
                source,
                Some(expected_revision),
                &(memory_id.as_str(), draft),
            )?
            .operation_digest)
    }

    fn prepare_semantic_mutation<T: Serialize + ?Sized>(
        &self,
        mutation_kind: &str,
        source: &SourceDraft,
        expected_predecessor_revision: Option<u64>,
        semantic_input: &T,
    ) -> Result<PreparedProductionCognitiveMutation, ProductionCognitiveMutationError> {
        let input_payload_sha256 =
            production_cognitive_input_digest(mutation_kind, source, semantic_input)?;
        let source_content_sha256 = Sha256Digest::for_bytes(&source.content);
        let operation_digest = production_cognitive_operation_digest(
            &self.writer,
            mutation_kind,
            &input_payload_sha256,
            expected_predecessor_revision,
        );
        let occurrence_key = format!("cognitive-mutation:{}", operation_digest.as_str());
        let intent_json = serde_json::to_string(&ProductionCognitiveMutationIntentJournalV1 {
            schema_version: PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION,
            namespace: PRODUCTION_COGNITIVE_MUTATION_NAMESPACE,
            mutation_kind,
            operation_digest: &operation_digest,
            input_payload_sha256: &input_payload_sha256,
            expected_predecessor_revision,
            authority_grant_digest: &self.writer.authority.grant_digest,
            authority_epoch: self.writer.authority.authority_epoch,
            owner_epoch: self.writer.authority.owner_epoch,
            lease_id: self.writer.lease_id(),
            generation: self.writer.generation(),
            owner_agent_id: self.writer.store().owner_agent_id().as_str(),
        })
        .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
        Ok(PreparedProductionCognitiveMutation {
            mutation_kind: mutation_kind.to_string(),
            operation_digest,
            input_payload_sha256,
            source_content_sha256,
            source_observed_at_unix_seconds: source.observed_at_unix_seconds,
            expected_predecessor_revision,
            occurrence_key,
            intent_json,
        })
    }

    async fn admit_prepared_mutation(
        &self,
        transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
        prepared: &PreparedProductionCognitiveMutation,
    ) -> Result<QueuedReceipt, ProductionCognitiveMutationError> {
        let admission = self
            .writer
            .lease
            .admit_in_transaction(
                transaction,
                prepared.occurrence_key.clone(),
                PRODUCTION_COGNITIVE_MUTATION_TOPIC.to_string(),
                prepared.intent_json.clone(),
            )
            .await
            .map_err(ProductionWriterError::from)?;
        Ok(match admission {
            LocalAdmission::Queued(receipt) | LocalAdmission::Replay(receipt) => receipt,
        })
    }

    async fn finish_prepared_mutation(
        &self,
        transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
        prepared: PreparedProductionCognitiveMutation,
        queued: QueuedReceipt,
        write: CognitiveWriteReceipt,
    ) -> Result<ProductionCognitiveMutationReceiptV1, ProductionCognitiveMutationError> {
        let write_digest = production_cognitive_write_digest(&write)?;
        let commit = ProductionCognitiveMutationCommitV1 {
            schema_version: PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION,
            namespace: PRODUCTION_COGNITIVE_MUTATION_NAMESPACE.to_string(),
            operation_digest: prepared.operation_digest.clone(),
            write_digest: write_digest.clone(),
            source_content_sha256: prepared.source_content_sha256.clone(),
            source_observed_at_unix_seconds: prepared.source_observed_at_unix_seconds,
            memory_id: write.memory.id.memory_id.as_str().to_string(),
            memory_revision: write.memory.id.revision,
            source_id: write.source.source_id.as_str().to_string(),
            source_revision: write.source.revision,
            projection_output_sha256: write.projection.output_sha256.clone(),
        };
        let commit_json = serde_json::to_string(&commit)
            .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
        let terminal = self
            .writer
            .lease
            .apply_in_transaction(transaction, prepared.occurrence_key, commit_json)
            .await
            .map_err(ProductionWriterError::from)?;

        let mut receipt = ProductionCognitiveMutationReceiptV1 {
            schema_version: PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION,
            namespace: PRODUCTION_COGNITIVE_MUTATION_NAMESPACE.to_string(),
            mutation_kind: prepared.mutation_kind,
            operation_digest: prepared.operation_digest,
            input_payload_sha256: prepared.input_payload_sha256,
            source_content_sha256: prepared.source_content_sha256,
            source_observed_at_unix_seconds: prepared.source_observed_at_unix_seconds,
            expected_predecessor_revision: prepared.expected_predecessor_revision,
            owner_agent_id: self.writer.store().owner_agent_id().clone(),
            authority_grant_digest: self.writer.authority.grant_digest.clone(),
            authority_epoch: self.writer.authority.authority_epoch,
            owner_epoch: self.writer.authority.owner_epoch,
            lease_id: self.writer.lease_id().to_string(),
            generation: self.writer.generation(),
            provenance_event_id: queued.event_id,
            provenance_outbox_id: queued.outbox_id,
            provenance_commit_event_id: terminal.event_id,
            write_digest,
            write,
            receipt_sha256: Sha256Digest::for_bytes(b"pending"),
            external_effect: false,
        };
        receipt.receipt_sha256 = receipt.compute_receipt_sha256();
        Ok(receipt)
    }
}

#[derive(Serialize)]
struct ProductionCognitiveMutationIntentJournalV1<'a> {
    schema_version: u32,
    namespace: &'static str,
    mutation_kind: &'a str,
    operation_digest: &'a Sha256Digest,
    input_payload_sha256: &'a Sha256Digest,
    expected_predecessor_revision: Option<u64>,
    authority_grant_digest: &'a Sha256Digest,
    authority_epoch: u64,
    owner_epoch: u64,
    lease_id: &'a str,
    generation: u64,
    owner_agent_id: &'a str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProductionCognitiveMutationIntentRecordV1 {
    schema_version: u32,
    namespace: String,
    mutation_kind: String,
    operation_digest: Sha256Digest,
    input_payload_sha256: Sha256Digest,
    expected_predecessor_revision: Option<u64>,
    authority_grant_digest: Sha256Digest,
    authority_epoch: u64,
    owner_epoch: u64,
    lease_id: String,
    generation: u64,
    owner_agent_id: AgentId,
}

fn production_cognitive_input_digest<T: Serialize + ?Sized>(
    mutation_kind: &str,
    source: &SourceDraft,
    semantic_input: &T,
) -> Result<Sha256Digest, ProductionWriterError> {
    if source.content.is_empty() || source.content.len() > crate::cognitive_model::MAX_SOURCE_BYTES
    {
        return Err(ProductionWriterError::Invalid(
            "production cognitive source content exceeds its owner bound".to_string(),
        ));
    }
    cognitive_digest::input_digest(&(mutation_kind, source, semantic_input))
}

fn production_cognitive_operation_digest(
    writer: &ProductionDurableWriter,
    mutation_kind: &str,
    input_payload_sha256: &Sha256Digest,
    expected_predecessor_revision: Option<u64>,
) -> Sha256Digest {
    production_cognitive_operation_digest_parts(
        &writer.authority.grant_digest,
        writer.authority.authority_epoch,
        writer.authority.owner_epoch,
        writer.lease_id(),
        writer.generation(),
        mutation_kind,
        input_payload_sha256,
        expected_predecessor_revision,
    )
}

#[allow(clippy::too_many_arguments)]
fn production_cognitive_operation_digest_parts(
    authority_grant_digest: &Sha256Digest,
    authority_epoch: u64,
    owner_epoch: u64,
    lease_id: &str,
    generation: u64,
    mutation_kind: &str,
    input_payload_sha256: &Sha256Digest,
    expected_predecessor_revision: Option<u64>,
) -> Sha256Digest {
    let predecessor = expected_predecessor_revision
        .map(u64::to_be_bytes)
        .unwrap_or([0; 8]);
    digest_framed(
        b"hepta:production-cognitive-mutation-operation:v1",
        &[
            authority_grant_digest.as_str().as_bytes(),
            &authority_epoch.to_be_bytes(),
            &owner_epoch.to_be_bytes(),
            lease_id.as_bytes(),
            &generation.to_be_bytes(),
            mutation_kind.as_bytes(),
            input_payload_sha256.as_str().as_bytes(),
            &predecessor,
        ],
    )
}

fn production_cognitive_journal_corrupt(message: impl Into<String>) -> ProductionWriterError {
    ProductionWriterError::Local(LocalLeaseOutboxError::Corrupt(message.into()))
}

fn production_cognitive_write_digest(
    write: &CognitiveWriteReceipt,
) -> Result<Sha256Digest, ProductionWriterError> {
    let bytes = serde_json::to_vec(write)
        .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
    Ok(digest_framed(
        b"hepta:production-cognitive-mutation-write:v1",
        &[&bytes],
    ))
}

fn production_cognitive_result_digest(
    result: &ProductionCognitiveMutationResultV1,
) -> Sha256Digest {
    let predecessor = result
        .expected_predecessor_revision
        .map(u64::to_be_bytes)
        .unwrap_or([0; 8]);
    let mut parts = vec![
        result.schema_version.to_be_bytes().to_vec(),
        result.namespace.as_bytes().to_vec(),
        result.state.as_str().as_bytes().to_vec(),
        result.mutation_kind.as_bytes().to_vec(),
        result.operation_digest.as_str().as_bytes().to_vec(),
        result.input_payload_sha256.as_str().as_bytes().to_vec(),
        predecessor.to_vec(),
        result.owner_agent_id.as_str().as_bytes().to_vec(),
        result.authority_grant_digest.as_str().as_bytes().to_vec(),
        result.authority_epoch.to_be_bytes().to_vec(),
        result.owner_epoch.to_be_bytes().to_vec(),
        result.lease_id.as_bytes().to_vec(),
        result.generation.to_be_bytes().to_vec(),
        result.provenance_event_id.as_bytes().to_vec(),
        result.provenance_outbox_id.as_bytes().to_vec(),
        result.latest_event_id.as_bytes().to_vec(),
        result.latest_event_kind.as_bytes().to_vec(),
        result.latest_payload_json.as_bytes().to_vec(),
        vec![u8::from(result.external_effect)],
    ];
    match &result.commit {
        Some(commit) => {
            parts.push(vec![1]);
            parts.push(commit.schema_version.to_be_bytes().to_vec());
            parts.push(commit.namespace.as_bytes().to_vec());
            parts.push(commit.operation_digest.as_str().as_bytes().to_vec());
            parts.push(commit.write_digest.as_str().as_bytes().to_vec());
            parts.push(commit.source_content_sha256.as_str().as_bytes().to_vec());
            parts.push(
                commit
                    .source_observed_at_unix_seconds
                    .to_be_bytes()
                    .to_vec(),
            );
            parts.push(commit.memory_id.as_bytes().to_vec());
            parts.push(commit.memory_revision.to_be_bytes().to_vec());
            parts.push(commit.source_id.as_bytes().to_vec());
            parts.push(commit.source_revision.to_be_bytes().to_vec());
            parts.push(commit.projection_output_sha256.as_str().as_bytes().to_vec());
        }
        None => parts.push(vec![0]),
    }
    let slices = parts.iter().map(Vec::as_slice).collect::<Vec<_>>();
    digest_framed(b"hepta:production-cognitive-mutation-result:v1", &slices)
}

fn production_cognitive_receipt_digest(
    receipt: &ProductionCognitiveMutationReceiptV1,
) -> Sha256Digest {
    let predecessor = receipt
        .expected_predecessor_revision
        .map(u64::to_be_bytes)
        .unwrap_or([0; 8]);
    digest_framed(
        b"hepta:production-cognitive-mutation-receipt:v1",
        &[
            &receipt.schema_version.to_be_bytes(),
            receipt.namespace.as_bytes(),
            receipt.mutation_kind.as_bytes(),
            receipt.operation_digest.as_str().as_bytes(),
            receipt.input_payload_sha256.as_str().as_bytes(),
            receipt.source_content_sha256.as_str().as_bytes(),
            &receipt.source_observed_at_unix_seconds.to_be_bytes(),
            &predecessor,
            receipt.owner_agent_id.as_str().as_bytes(),
            receipt.authority_grant_digest.as_str().as_bytes(),
            &receipt.authority_epoch.to_be_bytes(),
            &receipt.owner_epoch.to_be_bytes(),
            receipt.lease_id.as_bytes(),
            &receipt.generation.to_be_bytes(),
            receipt.provenance_event_id.as_bytes(),
            receipt.provenance_outbox_id.as_bytes(),
            receipt.provenance_commit_event_id.as_bytes(),
            receipt.write_digest.as_str().as_bytes(),
        ],
    )
}

fn digest_framed(domain: &[u8], parts: &[&[u8]]) -> Sha256Digest {
    let mut bytes = Vec::new();
    for part in std::iter::once(domain).chain(parts.iter().copied()) {
        bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Sha256Digest::for_bytes(&bytes)
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
    /// Exact semantic fields needed by the destination to revalidate the
    /// durable OperationIntentV1 rather than trusting an opaque source digest.
    pub operation_scope_sha256: Sha256Digest,
    pub operation_subject_id: String,
    pub operation_destination_id: String,
    /// Canonical digest of the complete durable OperationIntentV1.
    pub operation_semantic_sha256: Sha256Digest,
    pub operation_policy_generation: u64,
    /// Destination-owned CAS expectation. The destination must compare this
    /// against its authoritative predecessor inside the apply transaction.
    pub expected_predecessor_sha256: Option<Sha256Digest>,
    /// Final-use request identity. Product dispatch binds the semantic digest
    /// and predecessor expectation in addition to the local outbox fields.
    pub operation_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionTargetOutcome {
    Committed {
        receipt: String,
    },
    /// The destination deterministically proved that the requested mutation
    /// was not applied (for example, predecessor/CAS mismatch).
    NotApplied {
        reason: String,
    },
    /// The request itself is invalid or unauthorized for this destination.
    Rejected {
        reason: String,
    },
    /// Unknown/timeout/provider ambiguity must remain quarantined.
    Indeterminate {
        reason: String,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProductionTargetDisposition {
    Committed,
    NotApplied,
    Rejected,
    Indeterminate,
}

pub type ProductionDispatchFuture<'a> =
    Pin<Box<dyn Future<Output = ProductionTargetOutcome> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionTerminalObservation {
    Applied { receipt: String },
    NotApplied { reason: String },
    Quarantined { reason: String },
    Indeterminate { reason: String },
    Unavailable { reason: String },
}

pub type ProductionTerminalObservationFuture<'a> =
    Pin<Box<dyn Future<Output = ProductionTerminalObservation> + Send + 'a>>;

pub trait ProductionOutboxTarget: Send + Sync {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a>;
}

/// Production target with a stable destination identity and an independent
/// terminal observer. The default observer is deliberately unavailable so a
/// target cannot accidentally turn transport acknowledgement into terminality.
pub trait FinalUseProductionOutboxTarget: ProductionOutboxTarget {
    fn destination_id(&self) -> &str;

    fn observe_terminal<'a>(
        &'a self,
        _request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async {
            ProductionTerminalObservation::Unavailable {
                reason: "target does not provide a terminal observer".to_string(),
            }
        })
    }
}

/// Legacy direct dispatcher retained only for in-crate qualification tests.
/// Product composition must use `ProductionFinalUseOutboxDispatcher`.
#[cfg(test)]
#[derive(Clone)]
pub(crate) struct ProductionOutboxDispatcher {
    target: Arc<dyn ProductionOutboxTarget>,
}

#[cfg(test)]
impl fmt::Debug for ProductionOutboxDispatcher {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionOutboxDispatcher")
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
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

    pub fn destination_id(&self) -> &str {
        self.target.destination_id()
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

    /// Reconcile a bounded batch of already-indeterminate operations through
    /// the destination-owned observer. This path never calls dispatch.
    pub async fn reconcile(
        &self,
        writer: &ProductionDurableWriter,
        limit: usize,
    ) -> Result<usize, ProductionWriterError> {
        writer
            .reconcile_target_batch(self.target.as_ref(), limit)
            .await
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProductionDispatchReceipt {
    pub request: ProductionDispatchRequest,
    pub state: LocalOutcomeState,
    pub target_disposition: ProductionTargetDisposition,
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
    scope_sha256: &Sha256Digest,
    request: &ProductionDispatchRequest,
    expected: &FinalUseBinding,
) -> Result<(), ProductionWriterError> {
    if expected.subject_id != owner.as_str()
        || expected.destination_id != destination_id
        || expected.scope_sha256 != digest_bytes(scope_sha256)?
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

#[cfg(test)]
fn legacy_operation_digest(
    authority: &ProductionAuthorityLease,
    receipt: &ProductionQueuedReceipt,
) -> Sha256Digest {
    legacy_dispatch_operation_digest(
        &authority.grant_digest,
        &receipt.lease_id,
        &receipt.occurrence_key,
        &receipt.topic,
        &receipt.payload_sha256,
    )
}

fn operation_digest(
    authority: &ProductionAuthorityLease,
    receipt: &ProductionQueuedReceipt,
    operation: &crate::local_lease_outbox::DurableOperationDispatchBinding,
) -> Sha256Digest {
    dispatch_operation_digest(
        &authority.grant_digest,
        &receipt.lease_id,
        &receipt.occurrence_key,
        &receipt.topic,
        &receipt.payload_sha256,
        &operation.operation_semantic_sha256,
        operation.expected_predecessor_sha256.as_ref(),
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

fn now_unix_ms() -> Result<u64, ProductionWriterError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| ProductionWriterError::Invalid(format!("system clock failed: {error}")))?
        .as_millis();
    u64::try_from(millis).map_err(|_| {
        ProductionWriterError::Invalid("system clock millisecond overflow".to_string())
    })
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
    use crate::CognitiveScope;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use std::sync::Condvar;
    use std::sync::Mutex;
    use std::sync::atomic::AtomicBool;
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

    pub(super) async fn store(temp: &TempDir) -> CognitiveStore {
        let fleet_root = temp.path().join("fleet");
        std::fs::create_dir_all(&fleet_root).unwrap();
        let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().unwrap()).unwrap();
        CognitiveStore::open(&fleet.layout().agent(&agent_id(OWNER)))
            .await
            .unwrap()
    }

    pub(super) fn authority(agent: AgentId) -> ProductionAuthorityLease {
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

    pub(super) struct AllowVerifier;

    impl ProductionAuthorityVerifier for AllowVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            Ok(())
        }

        fn enter_use(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<ProductionAuthorityUseGuard, String> {
            Ok(ProductionAuthorityUseGuard::from_verified_use(()))
        }
    }

    struct RevocableVerifier {
        revoked: Arc<AtomicBool>,
    }

    impl ProductionAuthorityVerifier for RevocableVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            if self.revoked.load(Ordering::SeqCst) {
                Err("grant revoked after writer open".to_string())
            } else {
                Ok(())
            }
        }

        fn enter_use(
            &self,
            authority: &ProductionAuthorityLease,
            expected_agent: &AgentId,
        ) -> Result<ProductionAuthorityUseGuard, String> {
            self.verify(authority, expected_agent)?;
            Ok(ProductionAuthorityUseGuard::from_verified_use(()))
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

    #[derive(Default)]
    struct LinearizedAuthorityState {
        revoked: bool,
        active_uses: usize,
        verify_calls: u64,
        pause_next_enter: bool,
        enter_paused: bool,
        release_enter: bool,
        revocation_requested: bool,
    }

    #[derive(Clone, Default)]
    struct LinearizedAuthorityVerifier {
        state: Arc<(Mutex<LinearizedAuthorityState>, Condvar)>,
    }

    struct LinearizedAuthorityUse {
        state: Arc<(Mutex<LinearizedAuthorityState>, Condvar)>,
    }

    impl Drop for LinearizedAuthorityUse {
        fn drop(&mut self) {
            let (lock, changed) = &*self.state;
            let mut state = lock.lock().expect("linearized authority state");
            state.active_uses = state
                .active_uses
                .checked_sub(1)
                .expect("authority use count is positive");
            changed.notify_all();
        }
    }

    impl LinearizedAuthorityVerifier {
        fn verify_calls(&self) -> u64 {
            self.state
                .0
                .lock()
                .expect("linearized authority state")
                .verify_calls
        }

        fn wait_for_verify_calls(&self, minimum: u64) {
            let (lock, changed) = &*self.state;
            let mut state = lock.lock().expect("linearized authority state");
            while state.verify_calls < minimum {
                state = changed
                    .wait(state)
                    .expect("linearized authority state after wait");
            }
        }

        fn pause_next_enter(&self) {
            let mut state = self.state.0.lock().expect("linearized authority state");
            state.pause_next_enter = true;
            state.release_enter = false;
        }

        fn wait_for_enter_pause(&self) {
            let (lock, changed) = &*self.state;
            let mut state = lock.lock().expect("linearized authority state");
            while !state.enter_paused {
                state = changed
                    .wait(state)
                    .expect("linearized authority state after wait");
            }
        }

        fn release_enter(&self) {
            let (lock, changed) = &*self.state;
            let mut state = lock.lock().expect("linearized authority state");
            state.release_enter = true;
            changed.notify_all();
        }

        fn wait_for_revocation_request(&self) {
            let (lock, changed) = &*self.state;
            let mut state = lock.lock().expect("linearized authority state");
            while !state.revocation_requested {
                state = changed
                    .wait(state)
                    .expect("linearized authority state after wait");
            }
        }

        fn revoke_and_wait(&self) {
            let (lock, changed) = &*self.state;
            let mut state = lock.lock().expect("linearized authority state");
            state.revoked = true;
            state.revocation_requested = true;
            changed.notify_all();
            while state.active_uses != 0 {
                state = changed
                    .wait(state)
                    .expect("linearized authority state after wait");
            }
        }
    }

    impl ProductionAuthorityVerifier for LinearizedAuthorityVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            let (lock, changed) = &*self.state;
            let mut state = lock
                .lock()
                .map_err(|_| "linearized authority state poisoned".to_string())?;
            state.verify_calls = state.verify_calls.saturating_add(1);
            changed.notify_all();
            if state.revoked {
                Err("linearized production authority revoked".to_string())
            } else {
                Ok(())
            }
        }

        fn enter_use(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<ProductionAuthorityUseGuard, String> {
            let (lock, changed) = &*self.state;
            let mut state = lock
                .lock()
                .map_err(|_| "linearized authority state poisoned".to_string())?;
            if state.revoked {
                return Err("linearized production authority revoked".to_string());
            }
            state.active_uses = state.active_uses.saturating_add(1);
            if state.pause_next_enter {
                state.pause_next_enter = false;
                state.enter_paused = true;
                changed.notify_all();
                while !state.release_enter {
                    state = changed
                        .wait(state)
                        .map_err(|_| "linearized authority state poisoned".to_string())?;
                }
                state.release_enter = false;
                state.enter_paused = false;
            }
            drop(state);
            Ok(ProductionAuthorityUseGuard::from_verified_use(
                LinearizedAuthorityUse {
                    state: Arc::clone(&self.state),
                },
            ))
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
    async fn semantic_capability_requires_retained_live_verifier() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner.clone());
        let lease_id = "production:h4:semantic-capability";

        let legacy = Arc::new(
            ProductionDurableWriter::open(store.clone(), auth.clone(), &AllowVerifier, lease_id, 1)
                .await
                .unwrap(),
        );
        assert!(matches!(
            legacy.cognitive_mutation_capability(),
            Err(ProductionWriterError::LiveVerifierRequired)
        ));
        drop(legacy);

        let live_verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(AllowVerifier);
        let live = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                auth,
                live_verifier,
                lease_id,
                1,
            )
            .await
            .unwrap(),
        );
        let capability = live
            .cognitive_mutation_capability()
            .expect("live-verified writer mints semantic capability");
        assert_eq!(capability.owner_agent_id(), &owner);
    }

    #[tokio::test]
    async fn post_open_revocation_blocks_semantic_use_dispatch_and_reconcile() {
        let temp = TempDir::new().unwrap();
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let auth = authority(owner);
        let revoked = Arc::new(AtomicBool::new(false));
        let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(RevocableVerifier {
            revoked: Arc::clone(&revoked),
        });
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                auth,
                verifier,
                "production:h4:post-open-revoke",
                1,
            )
            .await
            .unwrap(),
        );
        let queued = writer
            .admit("occurrence:post-open-revoke", "memory.write", "payload")
            .await
            .unwrap();

        revoked.store(true, Ordering::SeqCst);

        assert!(matches!(
            writer.verify_current_authority().await,
            Err(ProductionWriterError::AuthorityRejected(_))
        ));
        assert!(matches!(
            writer
                .admit("occurrence:post-open-revoke:new", "memory.write", "payload",)
                .await,
            Err(ProductionWriterError::AuthorityRejected(_))
        ));
        assert!(matches!(
            writer.recover("occurrence:post-open-revoke").await,
            Err(ProductionWriterError::AuthorityRejected(_))
        ));

        let target = Arc::new(Target {
            calls: AtomicUsize::new(0),
            outcome: ProductionTargetOutcome::Committed {
                receipt: "must-not-run-after-revoke".to_string(),
            },
        });
        let dispatcher = ProductionOutboxDispatcher::attach(target.clone());
        assert!(matches!(
            dispatcher.dispatch(&writer, queued).await,
            Err(ProductionWriterError::AuthorityRejected(_))
        ));
        assert_eq!(target.calls.load(Ordering::SeqCst), 0);
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn revocation_while_waiting_for_writer_lock_rejects_before_mutation() {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let verifier = Arc::new(LinearizedAuthorityVerifier::default());
        let live_verifier: Arc<dyn ProductionAuthorityVerifier> = verifier.clone();
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store.clone(),
                authority(owner.clone()),
                live_verifier,
                "production:h4:writer-lock-revoke",
                1,
            )
            .await
            .expect("writer"),
        );
        let capability = writer
            .cognitive_mutation_capability()
            .expect("semantic capability");
        let cut_before = writer.recovery_anchor().await.expect("cut before");
        let verify_calls = verifier.verify_calls();
        let blocker = store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .expect("writer-lock blocker");
        let now = i64::try_from(now_unix_seconds().expect("clock")).expect("clock range");
        let operation = tokio::spawn(async move {
            capability
                .remember_with_kg(
                    &CognitiveAccess::agent_private(owner),
                    &SourceDraft {
                        scope: CognitiveScope::AgentPrivate,
                        kind: crate::LedgerSourceKind::ExplicitMemoryDirective,
                        event_key: "writer-lock-revoke-source".to_string(),
                        content: b"writer-lock-revoke".to_vec(),
                        observed_at_unix_seconds: now,
                    },
                    &MemoryDraft {
                        stable_key: "writer-lock-revoke-memory".to_string(),
                        revision: MemoryRevisionDraft {
                            scope: CognitiveScope::AgentPrivate,
                            content: "writer-lock-revoke".to_string(),
                            verification: crate::MemoryVerification::Verified,
                            lifecycle: crate::MemoryLifecycleState::Active,
                            valid_from_unix_seconds: now,
                            valid_to_unix_seconds: None,
                            citations: Vec::new(),
                        },
                    },
                    &KgFactSetDraft::default(),
                )
                .await
        });
        verifier.wait_for_verify_calls(verify_calls.saturating_add(1));
        tokio::time::sleep(Duration::from_millis(25)).await;
        verifier.revoke_and_wait();
        blocker.rollback().await.expect("release writer lock");
        let error = operation
            .await
            .expect("mutation task")
            .expect_err("revoked mutation must fail");
        assert!(matches!(
            error,
            ProductionCognitiveMutationError::Authority(ProductionWriterError::AuthorityRejected(
                _
            ))
        ));
        assert_eq!(
            writer.recovery_anchor().await.expect("cut after"),
            cut_before,
            "revocation confirmed while the request waited for the writer lock must prevent every durable mutation"
        );
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn revocation_after_guard_entry_waits_for_the_authorized_commit() {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await;
        let owner = store.owner_agent_id().clone();
        let verifier = Arc::new(LinearizedAuthorityVerifier::default());
        let live_verifier: Arc<dyn ProductionAuthorityVerifier> = verifier.clone();
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                authority(owner.clone()),
                live_verifier,
                "production:h4:guarded-commit-revoke",
                1,
            )
            .await
            .expect("writer"),
        );
        let capability = writer
            .cognitive_mutation_capability()
            .expect("semantic capability");
        verifier.pause_next_enter();
        let now = i64::try_from(now_unix_seconds().expect("clock")).expect("clock range");
        let operation = tokio::spawn(async move {
            capability
                .remember_with_kg(
                    &CognitiveAccess::agent_private(owner),
                    &SourceDraft {
                        scope: CognitiveScope::AgentPrivate,
                        kind: crate::LedgerSourceKind::ExplicitMemoryDirective,
                        event_key: "guarded-commit-revoke-source".to_string(),
                        content: b"guarded-commit-revoke".to_vec(),
                        observed_at_unix_seconds: now,
                    },
                    &MemoryDraft {
                        stable_key: "guarded-commit-revoke-memory".to_string(),
                        revision: MemoryRevisionDraft {
                            scope: CognitiveScope::AgentPrivate,
                            content: "guarded-commit-revoke".to_string(),
                            verification: crate::MemoryVerification::Verified,
                            lifecycle: crate::MemoryLifecycleState::Active,
                            valid_from_unix_seconds: now,
                            valid_to_unix_seconds: None,
                            citations: Vec::new(),
                        },
                    },
                    &KgFactSetDraft::default(),
                )
                .await
        });
        verifier.wait_for_enter_pause();
        let revoke_verifier = Arc::clone(&verifier);
        let revocation = std::thread::spawn(move || revoke_verifier.revoke_and_wait());
        verifier.wait_for_revocation_request();
        assert!(
            !revocation.is_finished(),
            "revocation acknowledgement must wait for the active authority-use guard"
        );
        verifier.release_enter();
        let receipt = operation
            .await
            .expect("mutation task")
            .expect("guarded mutation commits before revocation acknowledgement");
        receipt.validate().expect("committed receipt");
        revocation.join().expect("revocation thread");
        assert!(matches!(
            writer.verify_current_authority().await,
            Err(ProductionWriterError::AuthorityRejected(_))
        ));
    }

    #[tokio::test]
    async fn semantic_response_loss_restart_rejects_duplicate_and_preserves_committed_cut() {
        let temp = TempDir::new().unwrap();
        let initial_store = store(&temp).await;
        let owner = initial_store.owner_agent_id().clone();
        let auth = authority(owner.clone());
        let lease_id = "production:h4:semantic-response-loss";
        let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(AllowVerifier);
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                initial_store.clone(),
                auth.clone(),
                Arc::clone(&verifier),
                lease_id,
                1,
            )
            .await
            .unwrap(),
        );
        let capability = writer
            .cognitive_mutation_capability()
            .expect("live verifier must mint semantic mutation capability");
        let access = CognitiveAccess::agent_private(owner);
        let now = i64::try_from(now_unix_seconds().unwrap()).unwrap();
        let content = "Committed semantic mutation survives response loss.";
        let source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: crate::LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "semantic-response-loss:1".to_string(),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: now,
        };
        let draft = MemoryDraft {
            stable_key: "semantic-response-loss-memory".to_string(),
            revision: MemoryRevisionDraft {
                scope: CognitiveScope::AgentPrivate,
                content: content.to_string(),
                verification: crate::MemoryVerification::Verified,
                lifecycle: crate::MemoryLifecycleState::Active,
                valid_from_unix_seconds: now,
                valid_to_unix_seconds: None,
                citations: Vec::new(),
            },
        };
        let facts = KgFactSetDraft::default();

        // Simulate a response that was durably committed but lost before the
        // caller could retain the returned receipt.
        let committed = capability
            .remember_with_kg(&access, &source, &draft, &facts)
            .await
            .expect("initial semantic mutation");
        committed.validate().expect("committed receipt");
        let occurrence_key = format!("cognitive-mutation:{}", committed.operation_digest.as_str());
        assert_eq!(
            writer.status(&occurrence_key).await.unwrap(),
            LocalOutcomeState::Committed
        );
        let committed_cut = writer.recovery_anchor().await.unwrap();

        drop(capability);
        drop(writer);
        drop(initial_store);

        // A process restart may repeat the exact semantic request. The durable
        // committed occurrence must stop that retry before a second Memory
        // revision/source/fact mutation is attempted.
        let reopened_store = store(&temp).await;
        let reopened_writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                reopened_store,
                auth,
                verifier,
                lease_id,
                1,
            )
            .await
            .unwrap(),
        );
        let reopened_capability = reopened_writer
            .cognitive_mutation_capability()
            .expect("reopened live writer capability");
        let retry = reopened_capability
            .remember_with_kg(&access, &source, &draft, &facts)
            .await;
        let observed = match retry {
            Err(ProductionCognitiveMutationError::ObservedResult(result)) => *result,
            other => panic!("duplicate semantic request must return its typed result: {other:?}"),
        };
        observed.validate().expect("observed durable result");
        assert_eq!(
            observed.state,
            ProductionCognitiveMutationResultStateV1::Committed
        );
        assert_eq!(observed.operation_digest, committed.operation_digest);
        assert_eq!(
            observed
                .commit
                .as_ref()
                .expect("committed write summary")
                .write_digest,
            committed.write_digest
        );
        assert_eq!(
            reopened_writer
                .cognitive_mutation_result(&committed.operation_digest)
                .await
                .expect("query durable result")
                .expect("committed durable result"),
            observed
        );
        assert_eq!(
            reopened_writer.status(&occurrence_key).await.unwrap(),
            LocalOutcomeState::Committed
        );
        assert_eq!(
            reopened_writer.recovery_anchor().await.unwrap(),
            committed_cut,
            "response-loss retry must not append a duplicate semantic revision"
        );
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

        let expected = legacy_operation_digest(&writer.authority, &queued);
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

        fn enter_use(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<ProductionAuthorityUseGuard, String> {
            Ok(ProductionAuthorityUseGuard::from_verified_use(()))
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
            .reconcile("occurrence:takeover", LocalReconcileOutcome::Committed)
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
    use codex_hepta_operations::OperationIntentV1;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    use tempfile::TempDir;

    type TestResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

    fn agent() -> TestResult<AgentId> {
        Ok(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cff")?)
    }

    async fn store(temp: &TempDir) -> TestResult<CognitiveStore> {
        let root = temp.path().join("fleet-final-use");
        std::fs::create_dir_all(&root)?;
        let fleet = HeptaFleetRoot::parse(root.canonicalize()?)?;
        Ok(CognitiveStore::open(&fleet.layout().agent(&agent()?)).await?)
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

        fn enter_use(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<ProductionAuthorityUseGuard, String> {
            Ok(ProductionAuthorityUseGuard::from_verified_use(()))
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

    fn bound_operation(
        owner: &AgentId,
        operation_id: &str,
        destination: &str,
        payload: &str,
    ) -> TestResult<OperationIntentV1> {
        Ok(OperationIntentV1::new(
            StableId::new(operation_id)?,
            StableId::new(owner.as_str())?,
            StableId::new(destination)?,
            Digest32::of_bytes(payload.as_bytes()),
            Digest32::of_bytes(b"scope:production-test"),
            codex_hepta_types::Generation::new(1)?,
            None,
        )?)
    }

    fn production_authority(owner: AgentId) -> TestResult<ProductionAuthorityLease> {
        Ok(ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(b"production-grant"),
            31,
            41,
            now_unix_seconds()? + 3_600,
            ProductionAuthorityToken::from_verified_bytes(b"production-token".to_vec())?,
        )?)
    }

    fn test_nonce(label: &str) -> TestResult<[u8; 32]> {
        let now_nanos = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let material = format!("{label}:{now_nanos}:{}", std::process::id());
        let digest = <sha2::Sha256 as sha2::Digest>::digest(material.as_bytes());
        Ok(digest.into())
    }

    fn signed_final_use(
        issuer: &SigningKey,
        binding: FinalUseBinding,
        grant_id: &str,
        nonce: [u8; 32],
    ) -> TestResult<SignedFinalUseGrant> {
        let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
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
        let signature = issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }

    #[tokio::test]
    async fn final_use_is_consumed_at_target_entry_and_binding_mismatch_never_calls_target()
    -> TestResult<()> {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await?;
        let owner = store.owner_agent_id().clone();
        let writer = ProductionDurableWriter::open(
            store,
            production_authority(owner.clone())?,
            &FinalUseVerifier,
            "production:h4:final-use",
            1,
        )
        .await
        .expect("writer");

        let authority_dir = temp.path().join("final-use-authority");
        std::fs::create_dir(&authority_dir).expect("authority dir");
        std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))
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

        let payload_one = "{\"fact\":\"one\"}";
        let queued = writer
            .prepare_operation(
                bound_operation(
                    &owner,
                    "occurrence:final-use:1",
                    target.destination_id(),
                    payload_one,
                )?,
                "memory.write",
                payload_one,
            )
            .await
            .expect("queued");
        let binding = writer
            .final_use_binding(&queued, target.destination_id())
            .await
            .expect("canonical final-use binding");
        let signed = signed_final_use(
            &issuer,
            binding.clone(),
            "final-use-good",
            test_nonce("final-use-good")?,
        )?;
        let dispatched = dispatcher
            .dispatch(&writer, &signed, &binding, queued)
            .await
            .expect("authorized dispatch");
        assert_eq!(dispatched.state, LocalOutcomeState::Committed);
        assert_eq!(target.calls(), 1);

        let payload_two = "{\"fact\":\"two\"}";
        let queued_bad = writer
            .prepare_operation(
                bound_operation(
                    &owner,
                    "occurrence:final-use:2",
                    target.destination_id(),
                    payload_two,
                )?,
                "memory.write",
                payload_two,
            )
            .await
            .expect("second queued");
        let mut bad_binding = writer
            .final_use_binding(&queued_bad, target.destination_id())
            .await
            .expect("canonical bad-case binding");
        bad_binding.destination_id = "destination:substituted".to_string();
        let bad_signed = signed_final_use(
            &issuer,
            bad_binding.clone(),
            "final-use-bad-destination",
            test_nonce("final-use-bad-destination")?,
        )?;
        assert!(matches!(
            dispatcher
                .dispatch(&writer, &bad_signed, &bad_binding, queued_bad.clone())
                .await,
            Err(ProductionWriterError::FinalUse(
                FinalUseError::BindingMismatch
            ))
        ));
        assert_eq!(
            target.calls(),
            1,
            "mismatched destination never enters target"
        );
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
        Ok(())
    }

    #[tokio::test]
    async fn durable_dispatch_claim_is_idempotent_and_renewable_before_entry() -> TestResult<()> {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await?;
        let owner = store.owner_agent_id().clone();
        let writer = ProductionDurableWriter::open(
            store,
            production_authority(owner.clone())?,
            &FinalUseVerifier,
            "production:h4:claim-lease",
            1,
        )
        .await
        .expect("writer");
        let payload = "{\"fact\":\"claim-lease\"}";
        let queued = writer
            .prepare_operation(
                bound_operation(
                    &owner,
                    "occurrence:claim-lease",
                    "destination:cognitive-store",
                    payload,
                )?,
                "memory.write",
                payload,
            )
            .await
            .expect("queued");

        let first = writer
            .claim_dispatch_lease(&queued, 1_000)
            .await
            .expect("first claim");
        let replay = writer
            .claim_dispatch_lease(&queued, 1_000)
            .await
            .expect("same-owner claim replay");
        assert_eq!(replay, first);

        let renewed = writer
            .renew_dispatch_claim(&first, 2_000)
            .await
            .expect("renewed claim");
        assert_eq!(renewed.attempt, 1);
        assert!(renewed.lease_expires_at_unix_ms > first.lease_expires_at_unix_ms);
        assert_ne!(renewed.claim_sha256, first.claim_sha256);
        Ok(())
    }

    #[tokio::test]
    async fn queued_identity_survives_owner_handoff_and_dispatches_once_under_new_final_use()
    -> TestResult<()> {
        let temp = TempDir::new().expect("temp");
        let store = store(&temp).await?;
        let owner = store.owner_agent_id().clone();
        let old = ProductionDurableWriter::open(
            store.clone(),
            production_authority(owner.clone())?,
            &FinalUseVerifier,
            "production:h4:queued-handoff",
            1,
        )
        .await
        .expect("old writer");
        let handoff_payload = "{\"fact\":\"handoff\"}";
        let queued = old
            .prepare_operation(
                bound_operation(
                    &owner,
                    "occurrence:queued-handoff",
                    "destination:cognitive-store",
                    handoff_payload,
                )?,
                "memory.write",
                handoff_payload,
            )
            .await
            .expect("queued");
        assert_eq!(queued.inherited_from_generation, None);
        let old_claim = old
            .claim_dispatch_lease(&queued, 1)
            .await
            .expect("old generation claim");
        assert_eq!(old_claim.attempt, 1);
        let expiry = old.authority().lease_expires_at_unix_seconds;
        old.lease
            .expire_lease_at_unix_seconds(expiry)
            .await
            .expect("explicit timeout terminalization");
        drop(old);
        tokio::time::sleep(std::time::Duration::from_millis(60)).await;

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
        std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))
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
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(final_use, target.clone());
        let binding = successor
            .final_use_binding(&inherited, target.destination_id())
            .await
            .expect("canonical handoff binding");
        let signed = signed_final_use(
            &issuer,
            binding.clone(),
            "final-use-handoff",
            test_nonce("final-use-handoff")?,
        )?;
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
        assert_eq!(
            counts.outbox_rows, 1,
            "handoff reuses one durable outbox identity"
        );
        let max_attempt: i64 = sqlx::query_scalar(
            "SELECT MAX(attempt) FROM cognitive_operation_dispatch_claims
             WHERE operation_id = 'occurrence:queued-handoff'",
        )
        .fetch_one(&successor.store.pool)
        .await
        .expect("claim attempt");
        assert_eq!(
            max_attempt, 2,
            "successor takeover must advance the durable dispatch attempt"
        );
        Ok(())
    }
}

#[cfg(test)]
#[path = "production_cognitive_results_tests.rs"]
mod cognitive_results_tests;
