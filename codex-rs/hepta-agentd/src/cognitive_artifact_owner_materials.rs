//! Raw material for the original artifact writer. No keys, verified admissions
//! or authority tokens are decoded here; the native owners reconstruct them.

use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_learning_artifacts as artifacts;
use serde::Deserialize;

use crate::cognitive_process_bootstrap::FileAccess;
use crate::cognitive_process_bootstrap::open_bounded_regular;
use crate::cognitive_process_current::CognitiveCurrentOwnerDescriptorV1;
use crate::cognitive_process_current::require_external_canonical_path;
use crate::cognitive_process_wire::Digest;
use crate::cognitive_process_wire::Id;
use crate::cognitive_process_wire::Signature;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CognitiveArtifactOwnerMaterialsV1 {
    agent_id: AgentId,
    current: CognitiveCurrentOwnerDescriptorV1,
    writer_lease: WriterLeaseRaw,
    withdrawal_snapshot: WithdrawalSnapshotRaw,
    storage_binding: Digest,
}

impl CognitiveArtifactOwnerMaterialsV1 {
    pub(super) fn open(
        self,
        fleet: &FleetRegistry,
        now: u64,
    ) -> Result<artifacts::LearningArtifactOwnerService> {
        let snapshot = fleet.load()?;
        let record = snapshot
            .agent(&self.agent_id)
            .context("artifact subject is not registered")?;
        for owned in [
            record.layout.home_root(),
            record.layout.run_root(),
            record.manifest.workspace.as_path(),
        ] {
            for path in [&self.current.root, &self.withdrawal_snapshot.path] {
                require_external_canonical_path(path, owned, path == &self.current.root)?;
            }
        }
        // Ordinary publication reopens an existing owner. Its durable withdrawal
        // frontier rejects older input across CLI invocations and crash recovery.
        for name in [
            "writer",
            "transactions",
            "payloads",
            "registries",
            "witnesses",
            "heads",
        ] {
            require_external_canonical_path(
                &self.current.root.join(name),
                record.layout.home_root(),
                /*directory*/ true,
            )?;
        }
        require_external_canonical_path(
            &self.current.root.join("writer/owner.lock"),
            record.layout.home_root(),
            /*directory*/ false,
        )?;
        let raw = self.withdrawal_snapshot;
        let withdrawals = artifacts::read_dataset_withdrawal_snapshot(
            open_bounded_regular(&raw.path, 8 * 1024 * 1024, FileAccess::Read)?,
            artifacts::DatasetWithdrawalSnapshotReceiptV1 {
                binding: raw.binding.into(),
                scope_digest: raw.scope_digest.into(),
                head_digest: raw.head_digest.into(),
                file_digest: raw.file_digest.into(),
                records: raw.records,
                encoded_bytes: raw.encoded_bytes,
            },
        )?;
        Ok(artifacts::LearningArtifactOwnerService::open(
            artifacts::LearningArtifactOwnerServiceConfigV1 {
                root: self.current.root,
                trust: self.current.trust.native()?,
                writer_lease: self.writer_lease.into(),
                required_current_head: Some(self.current.required_current_head.native()?),
                withdrawal_registry: withdrawals,
                storage_binding: self.storage_binding.into(),
                now,
            },
        )?)
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct WithdrawalSnapshotRaw {
    path: PathBuf,
    binding: Digest,
    scope_digest: Digest,
    head_digest: Digest,
    file_digest: Digest,
    records: usize,
    encoded_bytes: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct WriterLeaseRaw {
    lease_id: Id,
    producer_id: Id,
    registry_id: Id,
    withdrawal_scope_digest: Digest,
    signer_id: Id,
    signing_key_digest: Digest,
    authority_epoch: u64,
    lease_generation: u64,
    issued_at: u64,
    expires_at: u64,
    signature_hex: Signature,
}

impl From<WriterLeaseRaw> for artifacts::SignedArtifactWriterLeaseV1 {
    fn from(raw: WriterLeaseRaw) -> Self {
        Self {
            lease_id: raw.lease_id.into(),
            producer_id: raw.producer_id.into(),
            registry_id: raw.registry_id.into(),
            withdrawal_scope_digest: raw.withdrawal_scope_digest.into(),
            signer_id: raw.signer_id.into(),
            signing_key_digest: raw.signing_key_digest.into(),
            authority_epoch: raw.authority_epoch,
            lease_generation: raw.lease_generation,
            issued_at: raw.issued_at,
            expires_at: raw.expires_at,
            signature: raw.signature_hex.into(),
        }
    }
}
