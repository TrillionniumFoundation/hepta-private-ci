//! Canonical production facade for durable compaction checkpoints.
//!
//! The lower-level SQLite owner remains an implementation detail. External
//! callers can publish only a sealed `VerifiedCompactionPublicationV1` that was
//! reconstructed against a root-authenticated trust manifest. Reopen performs
//! the same cryptographic and semantic verification before returning a
//! checkpoint to a product caller.

use std::collections::BTreeMap;
use std::time::Instant;

use codex_hepta_types::{Digest32, StableId};

use crate::archive_codec::{Decoder, Encoder, Wire, WireError};
use crate::durable::{
    CompactionArtifactImagesV1, DurableCompactionBundleV1, DurableCompactionDisposition,
    DurableCompactionError, DurableCompactionOutboxEventV1,
    DurableCompactionPublicationReceiptV1, DurableCompactionStoreV1,
    DurableCompactionTrustSetV1,
};
use crate::{
    CompactionAdmissionErrorV1, CompactionNonceBindingV1, CompactionPublicationRequestV1,
    CompactionTrustRoleV1, CompactionTrustedPrincipalV1, VerifiedCompactionPublicationV1,
    VerifiedCompactionTrustRegistryV1,
};

pub const MEMORY_CHECKPOINT_COORDINATOR_CALLER_V2: &str =
    "memory.checkpoint-coordinator.v2";

const FULL_ARCHIVE_DOMAIN: &[u8] = b"hepta.compaction.publication-archive.v1\0";
const COMPACT_ARCHIVE_DOMAIN: &[u8] =
    b"hepta.compaction.durable-publication-archive.v2\0";

#[derive(Debug, thiserror::Error)]
pub enum CompactionCoordinatorErrorV2 {
    #[error(transparent)]
    Durable(#[from] DurableCompactionError),
    #[error(transparent)]
    Admission(#[from] CompactionAdmissionErrorV1),
    #[error("invalid compaction coordinator input: {0}")]
    Invalid(&'static str),
    #[error("durable compaction publication is corrupt: {0}")]
    Corrupt(&'static str),
}

/// Per-operation measurements for a successful publication.
///
/// Estimated work fields are deliberately named as estimates. The end-to-end
/// clock starts when the public coordinator entrypoint is invoked; the durable
/// clock covers only the store publication call.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CompactionPublicationMetricsV2 {
    pub payload_bytes: u64,
    pub durable_archive_bytes: u64,
    pub estimated_clone_bytes: u64,
    pub estimated_content_hashes: u32,
    pub durable_publish_latency_micros: u64,
    pub end_to_end_latency_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPublicationReceiptV2 {
    pub schema_version: u32,
    pub caller: String,
    pub owner_id: String,
    pub idempotency_key: String,
    pub scope_id: String,
    pub purpose_id: String,
    pub generation: u64,
    pub checkpoint_digest: Digest32,
    pub publication_digest: Digest32,
    pub outbox_event_id: Digest32,
    pub disposition: DurableCompactionDisposition,
    pub metrics: CompactionPublicationMetricsV2,
}

/// Per-operation measurements for a successful cryptographic reopen.
///
/// Normal reopen verifies the selected immutable objects and current trust. A
/// database-wide integrity scan and stale-claim reconciliation are explicit
/// startup/operator operations and are intentionally excluded from this path.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CompactionReopenMetricsV2 {
    pub payload_bytes: u64,
    pub durable_archive_bytes: u64,
    pub estimated_content_hashes: u32,
    pub reconstruction_latency_micros: u64,
    pub end_to_end_latency_micros: u64,
}

#[derive(Clone, Debug)]
pub struct VerifiedCompactionSelectionV2 {
    owner_id: String,
    scope_id: String,
    purpose_id: String,
    generation: u64,
    checkpoint_digest: Digest32,
    publication_digest: Digest32,
    fell_back_from_revoked_head: bool,
    metrics: CompactionReopenMetricsV2,
    publication: VerifiedCompactionPublicationV1,
}

impl VerifiedCompactionSelectionV2 {
    #[must_use]
    pub fn owner_id(&self) -> &str {
        &self.owner_id
    }

    #[must_use]
    pub fn scope_id(&self) -> &str {
        &self.scope_id
    }

    #[must_use]
    pub fn purpose_id(&self) -> &str {
        &self.purpose_id
    }

    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub fn checkpoint_digest(&self) -> Digest32 {
        self.checkpoint_digest
    }

    #[must_use]
    pub fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }

    #[must_use]
    pub fn fell_back_from_revoked_head(&self) -> bool {
        self.fell_back_from_revoked_head
    }

    #[must_use]
    pub fn metrics(&self) -> CompactionReopenMetricsV2 {
        self.metrics
    }

    #[must_use]
    pub fn publication(&self) -> &VerifiedCompactionPublicationV1 {
        &self.publication
    }
}

/// The only public durable owner for compaction checkpoints.
///
/// `manifest_chain` is ordered oldest to newest. Each manifest is verified
/// against the same out-of-band root pin and every successor is checked against
/// its exact predecessor. The final manifest must be current at `now`.
#[derive(Clone)]
pub struct MemoryCheckpointCoordinatorV2 {
    store: DurableCompactionStoreV1,
    pinned_root_key: [u8; 32],
    registries: BTreeMap<String, VerifiedCompactionTrustRegistryV1>,
    active_registry_digest: Digest32,
}

impl MemoryCheckpointCoordinatorV2 {
    pub async fn open(
        database_url: &str,
        owner_id: &str,
        pinned_root_key: [u8; 32],
        manifest_bytes: &[u8],
        now_unix_seconds: u64,
    ) -> Result<Self, CompactionCoordinatorErrorV2> {
        Self::open_with_manifest_chain(
            database_url,
            owner_id,
            pinned_root_key,
            &[manifest_bytes.to_vec()],
            now_unix_seconds,
        )
        .await
    }

    pub async fn open_with_manifest_chain(
        database_url: &str,
        owner_id: &str,
        pinned_root_key: [u8; 32],
        manifest_chain: &[Vec<u8>],
        now_unix_seconds: u64,
    ) -> Result<Self, CompactionCoordinatorErrorV2> {
        if manifest_chain.is_empty() {
            return Err(CompactionCoordinatorErrorV2::Invalid(
                "at least one signed trust manifest is required",
            ));
        }
        let mut registries = BTreeMap::new();
        let mut previous: Option<VerifiedCompactionTrustRegistryV1> = None;
        for manifest in manifest_chain {
            let registry =
                VerifiedCompactionTrustRegistryV1::verify(pinned_root_key, manifest)?;
            if registry.owner_id().as_str() != owner_id {
                return Err(CompactionCoordinatorErrorV2::Invalid(
                    "trust manifest owner differs from the durable owner",
                ));
            }
            if let Some(prior) = &previous {
                registry.validate_successor_of(prior)?;
            } else if registry.manifest().sequence != 1
                || registry.manifest().predecessor_manifest_digest.is_some()
            {
                return Err(CompactionCoordinatorErrorV2::Invalid(
                    "manifest chain must begin with the root generation",
                ));
            }
            registries.insert(registry.manifest_digest().to_string(), registry.clone());
            previous = Some(registry);
        }
        let active = previous.ok_or(CompactionCoordinatorErrorV2::Invalid(
            "signed trust manifest chain is empty",
        ))?;
        active.validate_current_at(now_unix_seconds)?;
        let active_registry_digest = active.manifest_digest();
        let store = DurableCompactionStoreV1::open(database_url, owner_id).await?;
        Ok(Self {
            store,
            pinned_root_key,
            registries,
            active_registry_digest,
        })
    }

    #[must_use]
    pub fn owner_id(&self) -> &str {
        self.store.owner_id()
    }

    #[must_use]
    pub fn active_registry_digest(&self) -> Digest32 {
        self.active_registry_digest
    }

    pub fn install_successor_manifest(
        &mut self,
        manifest_bytes: &[u8],
        now_unix_seconds: u64,
    ) -> Result<Digest32, CompactionCoordinatorErrorV2> {
        let current = self.active_registry()?;
        let successor =
            VerifiedCompactionTrustRegistryV1::verify(self.pinned_root_key, manifest_bytes)?;
        successor.validate_successor_of(current)?;
        successor.validate_current_at(now_unix_seconds)?;
        let digest = successor.manifest_digest();
        self.registries.insert(digest.to_string(), successor);
        self.active_registry_digest = digest;
        Ok(digest)
    }

    pub async fn publish_verified_checkpoint(
        &self,
        idempotency_key: &str,
        publication: &VerifiedCompactionPublicationV1,
        retain_source_until_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<CompactionPublicationReceiptV2, CompactionCoordinatorErrorV2> {
        let request_started = Instant::now();
        let registry = self.active_registry()?;
        registry.validate_current_at(now_unix_seconds)?;
        if publication.owner_id() != registry.owner_id()
            || publication.root_key_digest() != registry.root_key_digest()
            || publication.registry_digest() != registry.manifest_digest()
        {
            return Err(CompactionCoordinatorErrorV2::Invalid(
                "publication owner, root or active manifest substitution",
            ));
        }
        publication.readmit_current_trust(registry, now_unix_seconds)?;
        if retain_source_until_unix_seconds < publication.accepted_at_unix_seconds() {
            return Err(CompactionCoordinatorErrorV2::Invalid(
                "source-retention deadline precedes publication acceptance",
            ));
        }

        let selector = principal_for(
            registry,
            publication.nonce_bindings(),
            CompactionTrustRoleV1::RetentionSelector,
        )?;
        let generator = principal_for(
            registry,
            publication.nonce_bindings(),
            CompactionTrustRoleV1::SemanticGenerator,
        )?;
        let tokenizer = principal_for(
            registry,
            publication.nonce_bindings(),
            CompactionTrustRoleV1::Tokenizer,
        )?;
        let evaluator = principal_for(
            registry,
            publication.nonce_bindings(),
            CompactionTrustRoleV1::Evaluator,
        )?;
        let selection_binding = binding_for(
            publication.nonce_bindings(),
            CompactionTrustRoleV1::RetentionSelector,
        )?;
        let generation_binding = binding_for(
            publication.nonce_bindings(),
            CompactionTrustRoleV1::SemanticGenerator,
        )?;

        let durable_archive = compact_archive(publication.archive(), publication)?;
        let candidate_digest = publication.candidate().candidate_digest();
        let evaluation_digest = publication.proof().evaluation_receipt_digest;
        let checkpoint_digest = publication.candidate().checkpoint().checkpoint_digest;
        let images = CompactionArtifactImagesV1 {
            candidate_image: candidate_digest.to_string().into_bytes(),
            evaluation_image: evaluation_digest.to_string().into_bytes(),
            proof_image: durable_archive.clone(),
            checkpoint_image: checkpoint_digest.to_string().into_bytes(),
        };
        let bundle = DurableCompactionBundleV1::from_verified(
            self.owner_id(),
            idempotency_key,
            publication.candidate(),
            publication.proof().clone(),
            selection_binding.receipt_digest,
            generation_binding.receipt_digest,
            DurableCompactionTrustSetV1 {
                selector: selector.enrollment.clone(),
                generator: generator.enrollment.clone(),
                tokenizer: tokenizer.enrollment.clone(),
                evaluator: evaluator.enrollment.clone(),
            },
            images,
            retain_source_until_unix_seconds,
        )?;

        let durable_started = Instant::now();
        let receipt = self.store.publish(&bundle, now_unix_seconds).await?;
        let durable_publish_latency_micros =
            saturating_micros(durable_started.elapsed().as_micros());
        let payload_bytes = u64::try_from(
            publication.candidate().semantic_payload().payload.len(),
        )
        .unwrap_or(u64::MAX);
        let archive_bytes = u64::try_from(durable_archive.len()).unwrap_or(u64::MAX);
        Ok(wrap_receipt(
            receipt,
            CompactionPublicationMetricsV2 {
                payload_bytes,
                durable_archive_bytes: archive_bytes,
                estimated_clone_bytes: payload_bytes.saturating_add(archive_bytes),
                estimated_content_hashes: 5,
                durable_publish_latency_micros,
                end_to_end_latency_micros: saturating_micros(
                    request_started.elapsed().as_micros(),
                ),
            },
        ))
    }

    pub async fn recover_current_checkpoint(
        &self,
        scope_id: &str,
        purpose_id: &str,
        now_unix_seconds: u64,
    ) -> Result<Option<VerifiedCompactionSelectionV2>, CompactionCoordinatorErrorV2> {
        let request_started = Instant::now();
        let Some(selection) = self.store.select_current(scope_id, purpose_id).await? else {
            return Ok(None);
        };
        let reconstruction_started = Instant::now();
        let archive = expand_archive(&selection.proof_image, &selection.payload)?;
        let archive_registry_digest =
            registry_digest_from_compact_archive(&selection.proof_image)?;
        let historical_registry = self
            .registries
            .get(&archive_registry_digest.to_string())
            .ok_or(CompactionCoordinatorErrorV2::Corrupt(
                "historical signed manifest was not supplied at reopen",
            ))?;
        let publication = VerifiedCompactionPublicationV1::reopen(
            &archive,
            &selection.payload,
            historical_registry,
        )?;
        publication.readmit_current_trust(self.active_registry()?, now_unix_seconds)?;

        let checkpoint = publication.candidate().checkpoint();
        if publication.owner_id().as_str() != selection.owner_id
            || checkpoint.source_snapshot.vector.scope_id.as_str() != selection.scope_id
            || checkpoint.source_snapshot.vector.purpose_id.as_str() != selection.purpose_id
            || checkpoint.generation.get() != selection.generation
            || checkpoint.checkpoint_digest != selection.checkpoint_digest
            || checkpoint.predecessor_digest != selection.predecessor_checkpoint_digest
            || checkpoint.source_snapshot.vector_digest != selection.source_snapshot_digest
            || checkpoint.source_memory_snapshot_digest
                != selection.source_memory_snapshot_digest
            || publication.candidate().candidate_digest() != selection.candidate_digest
            || checkpoint.payload_digest != selection.payload_digest
            || publication.proof().proof.proof_digest != selection.proof_digest
        {
            return Err(CompactionCoordinatorErrorV2::Corrupt(
                "reopened publication differs from durable checkpoint metadata",
            ));
        }

        let metrics = CompactionReopenMetricsV2 {
            payload_bytes: u64::try_from(selection.payload.len()).unwrap_or(u64::MAX),
            durable_archive_bytes: u64::try_from(selection.proof_image.len())
                .unwrap_or(u64::MAX),
            estimated_content_hashes: 4,
            reconstruction_latency_micros: saturating_micros(
                reconstruction_started.elapsed().as_micros(),
            ),
            end_to_end_latency_micros: saturating_micros(
                request_started.elapsed().as_micros(),
            ),
        };
        Ok(Some(VerifiedCompactionSelectionV2 {
            owner_id: selection.owner_id,
            scope_id: selection.scope_id,
            purpose_id: selection.purpose_id,
            generation: selection.generation,
            checkpoint_digest: selection.checkpoint_digest,
            publication_digest: selection.publication_digest,
            fell_back_from_revoked_head: selection.fell_back_from_revoked_head,
            metrics,
            publication,
        }))
    }

    pub async fn revoke_checkpoint(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<Digest32, CompactionCoordinatorErrorV2> {
        Ok(self
            .store
            .revoke_checkpoint(
                checkpoint_digest,
                reason_digest,
                revoked_at_unix_seconds,
            )
            .await?)
    }

    pub async fn claim_next_outbox(
        &self,
        now_unix_seconds: u64,
        claim_token: &str,
    ) -> Result<Option<DurableCompactionOutboxEventV1>, CompactionCoordinatorErrorV2> {
        Ok(self
            .store
            .claim_next_outbox(now_unix_seconds, claim_token)
            .await?)
    }

    pub async fn complete_outbox(
        &self,
        event: &DurableCompactionOutboxEventV1,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        Ok(self
            .store
            .complete_outbox(event, delivered_at_unix_seconds)
            .await?)
    }

    pub async fn reconcile_claims(
        &self,
        retry_at_unix_seconds: u64,
    ) -> Result<u64, CompactionCoordinatorErrorV2> {
        Ok(self.store.reconcile_claims(retry_at_unix_seconds).await?)
    }

    pub async fn verify_integrity(&self) -> Result<(), CompactionCoordinatorErrorV2> {
        Ok(self.store.verify_integrity().await?)
    }

    fn active_registry(
        &self,
    ) -> Result<&VerifiedCompactionTrustRegistryV1, CompactionCoordinatorErrorV2> {
        self.registries
            .get(&self.active_registry_digest.to_string())
            .ok_or(CompactionCoordinatorErrorV2::Corrupt(
                "active signed trust manifest is absent",
            ))
    }
}

fn wrap_receipt(
    receipt: DurableCompactionPublicationReceiptV1,
    metrics: CompactionPublicationMetricsV2,
) -> CompactionPublicationReceiptV2 {
    CompactionPublicationReceiptV2 {
        schema_version: 2,
        caller: MEMORY_CHECKPOINT_COORDINATOR_CALLER_V2.to_string(),
        owner_id: receipt.owner_id,
        idempotency_key: receipt.idempotency_key,
        scope_id: receipt.scope_id,
        purpose_id: receipt.purpose_id,
        generation: receipt.generation,
        checkpoint_digest: receipt.checkpoint_digest,
        publication_digest: receipt.publication_digest,
        outbox_event_id: receipt.outbox_event_id,
        disposition: receipt.disposition,
        metrics,
    }
}

fn principal_for<'a>(
    registry: &'a VerifiedCompactionTrustRegistryV1,
    bindings: &[CompactionNonceBindingV1; 4],
    role: CompactionTrustRoleV1,
) -> Result<&'a CompactionTrustedPrincipalV1, CompactionCoordinatorErrorV2> {
    let binding = binding_for(bindings, role)?;
    Ok(registry.lookup(role, &binding.key_id, binding.trust_epoch)?)
}

fn binding_for(
    bindings: &[CompactionNonceBindingV1; 4],
    role: CompactionTrustRoleV1,
) -> Result<&CompactionNonceBindingV1, CompactionCoordinatorErrorV2> {
    bindings
        .iter()
        .find(|binding| binding.role == role)
        .ok_or(CompactionCoordinatorErrorV2::Corrupt(
            "verified publication lacks one required trust role",
        ))
}

struct ArchiveParts {
    owner_id: StableId,
    root_key_digest: Digest32,
    registry_digest: Digest32,
    accepted_at_unix_seconds: u64,
    request: CompactionPublicationRequestV1,
    request_digest: Digest32,
    candidate_digest: Digest32,
    checkpoint_digest: Digest32,
    proof_digest: Digest32,
}

fn compact_archive(
    archive: &[u8],
    publication: &VerifiedCompactionPublicationV1,
) -> Result<Vec<u8>, CompactionCoordinatorErrorV2> {
    let mut parts = decode_archive(archive, FULL_ARCHIVE_DOMAIN)?;
    if parts.owner_id != *publication.owner_id()
        || parts.root_key_digest != publication.root_key_digest()
        || parts.registry_digest != publication.registry_digest()
        || parts.accepted_at_unix_seconds != publication.accepted_at_unix_seconds()
        || parts.request_digest != publication.request_digest()
        || parts.candidate_digest != publication.candidate().candidate_digest()
        || parts.checkpoint_digest
            != publication.candidate().checkpoint().checkpoint_digest
        || parts.proof_digest != publication.proof().proof.proof_digest
    {
        return Err(CompactionCoordinatorErrorV2::Corrupt(
            "verified archive fields differ from the sealed publication",
        ));
    }
    parts.request.evidence.semantic_payload.payload.clear();
    encode_archive(&parts, COMPACT_ARCHIVE_DOMAIN)
}

fn expand_archive(
    compact_archive: &[u8],
    payload: &[u8],
) -> Result<Vec<u8>, CompactionCoordinatorErrorV2> {
    let mut parts = decode_archive(compact_archive, COMPACT_ARCHIVE_DOMAIN)?;
    if !parts.request.evidence.semantic_payload.payload.is_empty() {
        return Err(CompactionCoordinatorErrorV2::Corrupt(
            "durable metadata archive unexpectedly embeds payload bytes",
        ));
    }
    if Digest32::of_bytes(payload) != parts.request.evidence.semantic_payload.payload_digest {
        return Err(CompactionCoordinatorErrorV2::Corrupt(
            "durable payload differs from the archived request digest",
        ));
    }
    parts.request.evidence.semantic_payload.payload = payload.to_vec();
    encode_archive(&parts, FULL_ARCHIVE_DOMAIN)
}

fn registry_digest_from_compact_archive(
    compact_archive: &[u8],
) -> Result<Digest32, CompactionCoordinatorErrorV2> {
    Ok(decode_archive(compact_archive, COMPACT_ARCHIVE_DOMAIN)?.registry_digest)
}

fn decode_archive(
    bytes: &[u8],
    domain: &[u8],
) -> Result<ArchiveParts, CompactionCoordinatorErrorV2> {
    let mut input = Decoder::new(bytes, domain).map_err(encoding_error)?;
    if u32::read(&mut input).map_err(encoding_error)? != 1 {
        return Err(CompactionCoordinatorErrorV2::Corrupt(
            "unsupported publication archive schema",
        ));
    }
    let parts = ArchiveParts {
        owner_id: StableId::read(&mut input).map_err(encoding_error)?,
        root_key_digest: Digest32::read(&mut input).map_err(encoding_error)?,
        registry_digest: Digest32::read(&mut input).map_err(encoding_error)?,
        accepted_at_unix_seconds: u64::read(&mut input).map_err(encoding_error)?,
        request: CompactionPublicationRequestV1::read(&mut input).map_err(encoding_error)?,
        request_digest: Digest32::read(&mut input).map_err(encoding_error)?,
        candidate_digest: Digest32::read(&mut input).map_err(encoding_error)?,
        checkpoint_digest: Digest32::read(&mut input).map_err(encoding_error)?,
        proof_digest: Digest32::read(&mut input).map_err(encoding_error)?,
    };
    input.finish().map_err(encoding_error)?;
    Ok(parts)
}

fn encode_archive(
    parts: &ArchiveParts,
    domain: &[u8],
) -> Result<Vec<u8>, CompactionCoordinatorErrorV2> {
    let mut output = Encoder::new(domain).map_err(encoding_error)?;
    1_u32.write(&mut output).map_err(encoding_error)?;
    parts.owner_id.write(&mut output).map_err(encoding_error)?;
    parts
        .root_key_digest
        .write(&mut output)
        .map_err(encoding_error)?;
    parts
        .registry_digest
        .write(&mut output)
        .map_err(encoding_error)?;
    parts
        .accepted_at_unix_seconds
        .write(&mut output)
        .map_err(encoding_error)?;
    parts.request.write(&mut output).map_err(encoding_error)?;
    parts
        .request_digest
        .write(&mut output)
        .map_err(encoding_error)?;
    parts
        .candidate_digest
        .write(&mut output)
        .map_err(encoding_error)?;
    parts
        .checkpoint_digest
        .write(&mut output)
        .map_err(encoding_error)?;
    parts
        .proof_digest
        .write(&mut output)
        .map_err(encoding_error)?;
    Ok(output.finish())
}

fn encoding_error(error: WireError) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Corrupt(error.0)
}

fn saturating_micros(value: u128) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}
