//! Explicit local-development host seam for compact rehydration reads.
//!
//! H12 exposes the pure read on `codex-hepta-memory`.  This module is the
//! deliberately unregistered extension-facing adapter for a host that wants
//! to ask that question at a concrete turn boundary.  It only returns a
//! typed observation.  It does not attach the observation to `ExtensionData`,
//! append a rehydration witness, write the KG, route a request, or invoke a
//! provider/effect.

use codex_extension_api::ExtensionData;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CompactCheckpoint;
use codex_hepta_memory::LocalCompactExecutor;
use codex_hepta_memory::LocalCompactExecutorError;
use codex_hepta_memory::LocalRehydrationRead;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

/// Schema version for the explicit host read envelope.
pub const LOCAL_REHYDRATION_HOST_SCHEMA_VERSION: u32 = 1;
/// The envelope is local-development metadata only.
pub const LOCAL_REHYDRATION_HOST_NAMESPACE: &str = "local_development_only";
/// A read cannot authorize an external effect.
pub const LOCAL_REHYDRATION_HOST_EXTERNAL_EFFECTS: bool = false;
/// A read cannot authorize a KG write.
pub const LOCAL_REHYDRATION_HOST_KG_WRITE_AUTHORITY: bool = false;
/// A read cannot authorize routing or provider use.
pub const LOCAL_REHYDRATION_HOST_ROUTING_AUTHORITY: bool = false;
pub const LOCAL_REHYDRATION_HOST_PROVIDER_EFFECTS: bool = false;
/// This adapter is not a production caller.
pub const LOCAL_REHYDRATION_HOST_PRODUCTION_CALLER: bool = false;

const BINDING_DOMAIN: &[u8] = b"hepta-memory:local-rehydration-host:v1";

/// Explicit host input for one turn-bound pure rehydration read.
///
/// The host owns the executor, operation identity, and checkpoint.  This
/// value has no constructor with side effects and is never installed into an
/// extension registry automatically.
#[derive(Debug)]
pub struct LocalRehydrationHostInput<'a> {
    pub turn_id: &'a str,
    pub operation_id: &'a str,
    pub checkpoint: &'a CompactCheckpoint,
    pub expected_revision: u64,
}

impl<'a> LocalRehydrationHostInput<'a> {
    pub fn new(
        turn_id: &'a str,
        operation_id: &'a str,
        checkpoint: &'a CompactCheckpoint,
        expected_revision: u64,
    ) -> Self {
        Self {
            turn_id,
            operation_id,
            checkpoint,
            expected_revision,
        }
    }
}

/// Stable errors for the host seam.  Executor errors are preserved rather
/// than converted into a successful or partial read.
#[derive(Debug)]
pub enum LocalRehydrationHostError {
    TurnBindingMismatch,
    Invalid(String),
    Executor(LocalCompactExecutorError),
}

impl std::fmt::Display for LocalRehydrationHostError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TurnBindingMismatch => {
                formatter.write_str("local rehydration host turn binding does not match")
            }
            Self::Invalid(detail) => {
                write!(formatter, "invalid local rehydration host input: {detail}")
            }
            Self::Executor(error) => write!(formatter, "local rehydration read failed: {error}"),
        }
    }
}

impl std::error::Error for LocalRehydrationHostError {}

impl From<LocalCompactExecutorError> for LocalRehydrationHostError {
    fn from(error: LocalCompactExecutorError) -> Self {
        Self::Executor(error)
    }
}

/// Result returned to an explicit host caller.
///
/// The full H12 read is returned so a local caller can inspect the typed
/// reconstruction plan.  The identity fields and binding digest make the
/// host/operation association explicit without retaining anything in the
/// turn store.  All authority booleans are fixed false and validated.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalRehydrationHostRead {
    pub schema_version: u32,
    pub namespace: String,
    pub turn_id_sha256: Sha256Digest,
    pub journal_id_sha256: Sha256Digest,
    pub operation_id_sha256: Sha256Digest,
    pub checkpoint_sha256: Sha256Digest,
    pub read: LocalRehydrationRead,
    pub read_sha256: Sha256Digest,
    pub binding_sha256: Sha256Digest,
    pub external_effects: bool,
    pub kg_write_authority: bool,
    pub routing_authority: bool,
    pub provider_effects: bool,
    pub production_caller: bool,
}

impl LocalRehydrationHostRead {
    /// Revalidates the immutable envelope and its authority boundary.
    pub fn validate(&self) -> Result<(), LocalRehydrationHostError> {
        if self.schema_version != LOCAL_REHYDRATION_HOST_SCHEMA_VERSION
            || self.namespace != LOCAL_REHYDRATION_HOST_NAMESPACE
        {
            return Err(LocalRehydrationHostError::Invalid(
                "unsupported schema or namespace".to_string(),
            ));
        }
        if self.external_effects
            || self.kg_write_authority
            || self.routing_authority
            || self.provider_effects
            || self.production_caller
        {
            return Err(LocalRehydrationHostError::Invalid(
                "host read crosses the local-development authority boundary".to_string(),
            ));
        }
        self.read
            .plan
            .namespace
            .eq(LOCAL_REHYDRATION_HOST_NAMESPACE)
            .then_some(())
            .ok_or_else(|| {
                LocalRehydrationHostError::Invalid(
                    "rehydration plan is outside local-development namespace".to_string(),
                )
            })?;
        if self.read.checkpoint_sha256 != self.checkpoint_sha256 {
            return Err(LocalRehydrationHostError::Invalid(
                "read/checkpoint digest mismatch".to_string(),
            ));
        }
        if self.read_sha256 != read_digest(&self.read)? {
            return Err(LocalRehydrationHostError::Invalid(
                "host read digest mismatch".to_string(),
            ));
        }
        if self.binding_sha256
            != binding_digest(
                &self.turn_id_sha256,
                &self.journal_id_sha256,
                &self.operation_id_sha256,
                &self.checkpoint_sha256,
                &self.read_sha256,
            )
        {
            return Err(LocalRehydrationHostError::Invalid(
                "host binding digest mismatch".to_string(),
            ));
        }
        Ok(())
    }

    pub fn is_local_read_only(&self) -> bool {
        self.namespace == LOCAL_REHYDRATION_HOST_NAMESPACE
            && !self.external_effects
            && !self.kg_write_authority
            && !self.routing_authority
            && !self.provider_effects
            && !self.production_caller
    }
}

/// Calls H12's pure read from an explicit host turn seam.
///
/// `turn_store` is read only: this function does not insert a result or any
/// witness into it.  Hosts must call this function explicitly; the extension
/// `install` function intentionally does not register it as a contributor.
pub async fn read_local_rehydration_for_turn(
    turn_store: &ExtensionData,
    executor: &LocalCompactExecutor,
    input: LocalRehydrationHostInput<'_>,
) -> Result<LocalRehydrationHostRead, LocalRehydrationHostError> {
    validate_text(input.turn_id, "turn id", /*max_bytes*/ 256)?;
    validate_text(input.operation_id, "operation id", /*max_bytes*/ 512)?;
    if input.turn_id != turn_store.level_id() {
        return Err(LocalRehydrationHostError::TurnBindingMismatch);
    }
    let read = executor
        .read_rehydration(
            input.operation_id,
            input.checkpoint,
            input.expected_revision,
        )
        .await?;
    let turn_id_sha256 = identity_digest(b"turn", input.turn_id);
    let journal_id_sha256 = identity_digest(b"journal", executor.journal_id());
    let operation_id_sha256 = identity_digest(b"operation", input.operation_id);
    let output = LocalRehydrationHostRead {
        schema_version: LOCAL_REHYDRATION_HOST_SCHEMA_VERSION,
        namespace: LOCAL_REHYDRATION_HOST_NAMESPACE.to_string(),
        turn_id_sha256,
        journal_id_sha256,
        operation_id_sha256,
        checkpoint_sha256: read.checkpoint_sha256.clone(),
        read_sha256: read_digest(&read)?,
        read,
        binding_sha256: Sha256Digest::for_bytes(b"pending"),
        external_effects: LOCAL_REHYDRATION_HOST_EXTERNAL_EFFECTS,
        kg_write_authority: LOCAL_REHYDRATION_HOST_KG_WRITE_AUTHORITY,
        routing_authority: LOCAL_REHYDRATION_HOST_ROUTING_AUTHORITY,
        provider_effects: LOCAL_REHYDRATION_HOST_PROVIDER_EFFECTS,
        production_caller: LOCAL_REHYDRATION_HOST_PRODUCTION_CALLER,
    };
    let mut output = output;
    output.binding_sha256 = binding_digest(
        &output.turn_id_sha256,
        &output.journal_id_sha256,
        &output.operation_id_sha256,
        &output.checkpoint_sha256,
        &output.read_sha256,
    );
    output.validate()?;
    Ok(output)
}

fn validate_text(
    value: &str,
    label: &str,
    max_bytes: usize,
) -> Result<(), LocalRehydrationHostError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(LocalRehydrationHostError::Invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn identity_digest(kind: &[u8], value: &str) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, BINDING_DOMAIN);
    hash_part(&mut hasher, kind);
    hash_part(&mut hasher, value.as_bytes());
    Sha256Digest::for_bytes(&hasher.finalize())
}

fn binding_digest(
    turn_id: &Sha256Digest,
    journal_id: &Sha256Digest,
    operation_id: &Sha256Digest,
    checkpoint: &Sha256Digest,
    read: &Sha256Digest,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, BINDING_DOMAIN);
    for digest in [turn_id, journal_id, operation_id, checkpoint, read] {
        hash_part(&mut hasher, digest.as_str().as_bytes());
    }
    Sha256Digest::for_bytes(&hasher.finalize())
}

fn read_digest(read: &LocalRehydrationRead) -> Result<Sha256Digest, LocalRehydrationHostError> {
    let encoded = serde_json::to_vec(read).map_err(|error| {
        LocalRehydrationHostError::Invalid(format!("cannot encode rehydration read: {error}"))
    })?;
    Ok(Sha256Digest::for_bytes(&encoded))
}

fn hash_part(hasher: &mut Sha256, value: &[u8]) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value);
}

#[cfg(test)]
mod tests {
    use std::fs;

    use codex_extension_api::ExtensionData;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::CompactCheckpoint;
    use codex_hepta_memory::CompactFence;
    use codex_hepta_memory::CompactLease;
    use codex_hepta_memory::CompactLossReport;
    use codex_hepta_memory::CompactParentSnapshot;
    use codex_hepta_memory::CompactSummaryReceipt;
    use codex_hepta_memory::RehydrationStatus;
    use codex_hepta_memory::checkpoint_digest;
    use codex_hepta_paths::HeptaFleetRoot;
    use tempfile::TempDir;

    use super::*;

    fn checkpoint(fence: CompactFence) -> CompactCheckpoint {
        CompactCheckpoint::new(
            "ctxcp:h13",
            CompactLease::from_snapshot(
                CompactParentSnapshot::new(
                    "ctx:h13",
                    1,
                    2,
                    3,
                    Sha256Digest::for_bytes(b"state"),
                    fence,
                )
                .expect("parent"),
            ),
            Vec::new(),
            CompactSummaryReceipt::new(
                Sha256Digest::for_bytes(b"summary"),
                Sha256Digest::for_bytes(b"model"),
                Sha256Digest::for_bytes(b"policy"),
            ),
            CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss"),
            0,
        )
        .expect("checkpoint")
    }

    async fn opened_store(temp: &TempDir) -> CognitiveStore {
        let fleet_root = temp.path().join("fleet");
        fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet");
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000913").expect("owner");
        CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .expect("store")
    }

    fn fence() -> CompactFence {
        CompactFence::new(3, 4, 5, "h13-fence").expect("fence")
    }

    #[tokio::test]
    async fn explicit_host_read_is_pure_and_unregistered() {
        let temp = TempDir::new().expect("temp");
        let store = opened_store(&temp).await;
        let current_fence = fence();
        let checkpoint = checkpoint(current_fence.clone());
        let current = checkpoint.lease.snapshot.clone();
        let executor = store
            .open_local_compact_executor("journal:h13", current_fence)
            .await
            .expect("executor");
        executor
            .append_intent("op:h13", &checkpoint, &current)
            .await
            .expect("intent");
        let digest = checkpoint_digest(&checkpoint).expect("digest");
        executor
            .commit_checkpoint("op:h13", &digest)
            .await
            .expect("commit");
        let turn_store = ExtensionData::new("turn:h13");
        let before = executor.snapshot().await.expect("before");
        let view = read_local_rehydration_for_turn(
            &turn_store,
            &executor,
            LocalRehydrationHostInput::new("turn:h13", "op:h13", &checkpoint, 0),
        )
        .await
        .expect("host read");
        assert_eq!(view.read.plan.status, RehydrationStatus::NotStarted);
        assert!(view.read.witness.is_none());
        assert!(view.is_local_read_only());
        view.validate().expect("valid envelope");
        let mut tampered = view.clone();
        tampered.read.plan.status = RehydrationStatus::Complete;
        assert!(tampered.validate().is_err());
        assert_eq!(executor.snapshot().await.expect("after"), before);
        assert!(turn_store.get::<LocalRehydrationHostRead>().is_none());
    }

    #[tokio::test]
    async fn explicit_host_read_observes_existing_witness_without_writing() {
        let temp = TempDir::new().expect("temp");
        let store = opened_store(&temp).await;
        let current_fence = fence();
        let checkpoint = checkpoint(current_fence.clone());
        let current = checkpoint.lease.snapshot.clone();
        let executor = store
            .open_local_compact_executor("journal:h13-complete", current_fence)
            .await
            .expect("executor");
        executor
            .append_intent("op:h13-complete", &checkpoint, &current)
            .await
            .expect("intent");
        let digest = checkpoint_digest(&checkpoint).expect("digest");
        executor
            .commit_checkpoint("op:h13-complete", &digest)
            .await
            .expect("commit");
        executor
            .rehydrate("op:h13-complete", &checkpoint, 0)
            .await
            .expect("explicit witness");
        let before = executor.snapshot().await.expect("before");
        let turn_store = ExtensionData::new("turn:h13-complete");
        let view = read_local_rehydration_for_turn(
            &turn_store,
            &executor,
            LocalRehydrationHostInput::new("turn:h13-complete", "op:h13-complete", &checkpoint, 0),
        )
        .await
        .expect("host read");
        assert_eq!(view.read.plan.status, RehydrationStatus::Complete);
        assert!(view.read.witness.is_some());
        assert_eq!(executor.snapshot().await.expect("after"), before);
    }

    #[tokio::test]
    async fn host_turn_mismatch_fails_before_executor_read() {
        let temp = TempDir::new().expect("temp");
        let store = opened_store(&temp).await;
        let current_fence = fence();
        let checkpoint = checkpoint(current_fence.clone());
        let executor = store
            .open_local_compact_executor("journal:h13-mismatch", current_fence)
            .await
            .expect("executor");
        let before = executor.snapshot().await.expect("before");
        let turn_store = ExtensionData::new("turn:actual");
        let error = read_local_rehydration_for_turn(
            &turn_store,
            &executor,
            LocalRehydrationHostInput::new("turn:other", "op:h13-mismatch", &checkpoint, 0),
        )
        .await
        .expect_err("mismatch");
        assert!(matches!(
            error,
            LocalRehydrationHostError::TurnBindingMismatch
        ));
        assert_eq!(executor.snapshot().await.expect("after"), before);
    }
}
