//! Recovery metadata is part of the independently selected immutable payload.
//! It carries source identities, never Memory content or reusable authority.

use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::DatasetSnapshotV2;
use codex_hepta_memory::SharedExperienceUseV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::SharedTerminalCellError;

type Result<T> = std::result::Result<T, SharedTerminalCellError>;
const MAX_BUNDLE_BYTES: usize = 4 * 1024 * 1024;
const MAX_DATASET_RECORDS: usize = 4096;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Bundle {
    version: u32,
    trust_distribution_digest: String,
    policy_id: String,
    policy_revision: u64,
    source_support: String,
    artifact_id: String,
    producer_id: String,
    generation: u64,
    artifact_digest: String,
    objective_digest: String,
    sensor_core_digest: String,
    training_profile_digest: String,
    dataset: Dataset,
    model: Vec<u8>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Dataset {
    snapshot_id: String,
    ledger_head_digest: String,
    objective_digest: String,
    eligible_frontier: u64,
    outcome_watermark: u64,
    source_record_digests: Vec<String>,
    pending_outcomes: u32,
    censored_outcomes: u32,
    dataset_digest: String,
    producer_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
    correction_cut_digest: String,
    revocation_cut_digest: String,
    inclusion_policy_digest: String,
}

pub(crate) struct RecoveredTerminal {
    pub(crate) trust_distribution_digest: Digest32,
    pub(crate) policy_id: Sha256Digest,
    pub(crate) policy_revision: u64,
    pub(crate) source_support: Sha256Digest,
    pub(crate) dataset: DatasetSnapshotReceiptV3,
    pub(crate) loaded: LoadedTabularOperatorV1,
}

pub(crate) fn encode(
    artifact: &TabularOperatorArtifactV1,
    data: &DatasetSnapshotReceiptV3,
    source: &SharedExperienceUseV1,
    trust_distribution_digest: Digest32,
) -> Result<Vec<u8>> {
    if data.snapshot.source_record_digests.len() > MAX_DATASET_RECORDS
        || trust_distribution_digest.is_zero()
    {
        return Err(SharedTerminalCellError::Binding("recovery dataset bound"));
    }
    let s = &data.snapshot;
    let p = &data.producer;
    let bundle = Bundle {
        // V1 did not bind the ledger trust epoch. It cannot be silently accepted
        // under a different authority. Migrate only by independently publishing
        // and selecting a newly trained V2 bundle.
        version: 2,
        trust_distribution_digest: trust_distribution_digest.to_string(),
        policy_id: source.policy_id().as_str().to_owned(),
        policy_revision: source.policy_revision(),
        source_support: source.source_support_digest().as_str().to_owned(),
        artifact_id: artifact.artifact_id.to_string(),
        producer_id: artifact.producer_id.to_string(),
        generation: artifact.generation.get(),
        artifact_digest: artifact.artifact_digest.to_string(),
        objective_digest: artifact.objective_digest.to_string(),
        sensor_core_digest: artifact.sensor_core_digest.to_string(),
        training_profile_digest: artifact.training_profile_digest.to_string(),
        dataset: Dataset {
            snapshot_id: s.snapshot_id.to_string(),
            ledger_head_digest: s.ledger_head_digest.to_string(),
            objective_digest: s.objective_digest.to_string(),
            eligible_frontier: s.eligible_frontier,
            outcome_watermark: s.outcome_watermark,
            source_record_digests: s
                .source_record_digests
                .iter()
                .map(ToString::to_string)
                .collect(),
            pending_outcomes: s.pending_outcomes,
            censored_outcomes: s.censored_outcomes,
            dataset_digest: s.dataset_digest.to_string(),
            producer_id: p.principal_id.to_string(),
            credential_chain_digest: p.credential_chain_digest.to_string(),
            signing_key_digest: p.signing_key_digest.to_string(),
            scope_digest: p.scope_digest.to_string(),
            authority_epoch: p.authority_epoch,
            authenticated_at: p.authenticated_at,
            expires_at: p.expires_at,
            correction_cut_digest: data.correction_cut_digest.to_string(),
            revocation_cut_digest: data.revocation_cut_digest.to_string(),
            inclusion_policy_digest: data.inclusion_policy_digest.to_string(),
        },
        model: encode_tabular_payload_v1(artifact)
            .map_err(|_| SharedTerminalCellError::Binding("artifact encoding"))?,
    };
    let bytes = serde_json::to_vec(&bundle)
        .map_err(|_| SharedTerminalCellError::Binding("recovery encoding"))?;
    if bytes.len() > MAX_BUNDLE_BYTES {
        return Err(SharedTerminalCellError::Binding("recovery payload bound"));
    }
    Ok(bytes)
}

/// The caller must authenticate the complete bundle through the live artifact
/// owner first. The inner model pin is not independent selection authority.
pub(crate) fn decode(
    bytes: &[u8],
    manifest: &ArtifactManifest,
    admitted: &codex_hepta_learning_artifacts::ValidatedArtifactManifestV2,
) -> Result<RecoveredTerminal> {
    if bytes.len() > MAX_BUNDLE_BYTES
        || bytes.len() as u64 != manifest.encoded_size_bytes
        || Digest32::of_bytes(bytes) != manifest.content_digest
    {
        return Err(SharedTerminalCellError::Binding(
            "recovery payload bound or digest",
        ));
    }
    let b: Bundle = serde_json::from_slice(bytes)
        .map_err(|_| SharedTerminalCellError::Binding("recovery encoding"))?;
    if b.version != 2
        || b.policy_revision == 0
        || b.dataset.source_record_digests.len() > MAX_DATASET_RECORDS
        || serde_json::to_vec(&b)
            .map_err(|_| SharedTerminalCellError::Binding("recovery encoding"))?
            != bytes
    {
        return Err(SharedTerminalCellError::Binding(
            "recovery version or canonical form",
        ));
    }
    let d = b.dataset;
    let dataset = DatasetSnapshotReceiptV3 {
        snapshot: DatasetSnapshotV2 {
            snapshot_id: id(d.snapshot_id)?,
            ledger_head_digest: digest(&d.ledger_head_digest)?,
            objective_digest: digest(&d.objective_digest)?,
            eligible_frontier: d.eligible_frontier,
            outcome_watermark: d.outcome_watermark,
            source_record_digests: d
                .source_record_digests
                .iter()
                .map(|s| digest(s))
                .collect::<Result<_>>()?,
            pending_outcomes: d.pending_outcomes,
            censored_outcomes: d.censored_outcomes,
            dataset_digest: digest(&d.dataset_digest)?,
            authority: AuthorityPosture::DENY_ALL,
        },
        producer: AuthenticatedPrincipalV1 {
            principal_id: id(d.producer_id)?,
            credential_chain_digest: digest(&d.credential_chain_digest)?,
            signing_key_digest: digest(&d.signing_key_digest)?,
            scope_digest: digest(&d.scope_digest)?,
            authority_epoch: d.authority_epoch,
            authenticated_at: d.authenticated_at,
            expires_at: d.expires_at,
        },
        correction_cut_digest: digest(&d.correction_cut_digest)?,
        revocation_cut_digest: digest(&d.revocation_cut_digest)?,
        inclusion_policy_digest: digest(&d.inclusion_policy_digest)?,
    };
    let generation = Generation::new(b.generation)
        .map_err(|_| SharedTerminalCellError::Binding("recovery generation"))?;
    let pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&b.model),
        artifact_digest: digest(&b.artifact_digest)?,
        objective_digest: digest(&b.objective_digest)?,
        dataset_digest: dataset.snapshot.dataset_digest,
        sensor_core_digest: digest(&b.sensor_core_digest)?,
        training_profile_digest: digest(&b.training_profile_digest)?,
        generation,
    };
    if manifest.kind != codex_hepta_learning_artifacts::ArtifactKind::Policy
        || manifest.artifact_id.as_str() != b.artifact_id
        || manifest.producer_id.as_str() != b.producer_id
        || manifest.generation != generation
        || manifest.objective_digest != pin.objective_digest
        || manifest.compatibility_digest != pin.training_profile_digest
        || dataset.snapshot.objective_digest != pin.objective_digest
    {
        return Err(SharedTerminalCellError::Binding("recovery manifest"));
    }
    let full = &admitted.manifest;
    if admitted.manifest_digest != manifest.support_digest
        || full.provenance_mode != codex_hepta_learning_artifacts::ProvenanceModeV1::DatasetDerived
        || full.source_dataset_digests.as_slice() != [pin.dataset_digest]
        || !full.lineage_digests.contains(&pin.artifact_digest)
    {
        return Err(SharedTerminalCellError::Binding(
            "authoritative manifest lineage",
        ));
    }
    let loaded = LoadedTabularOperatorV1::from_pinned_payload(&b.model, &pin)
        .map_err(|_| SharedTerminalCellError::Binding("recovery model pin"))?;
    if loaded.artifact_id() != &manifest.artifact_id
        || loaded.producer_id() != &manifest.producer_id
    {
        return Err(SharedTerminalCellError::Binding("recovery model identity"));
    }
    let trust_distribution_digest = digest(&b.trust_distribution_digest)?;
    if trust_distribution_digest.is_zero() {
        return Err(SharedTerminalCellError::Binding("recovery trust identity"));
    }
    Ok(RecoveredTerminal {
        trust_distribution_digest,
        policy_id: Sha256Digest::parse(b.policy_id)
            .map_err(|_| SharedTerminalCellError::Binding("recovery policy"))?,
        policy_revision: b.policy_revision,
        source_support: Sha256Digest::parse(b.source_support)
            .map_err(|_| SharedTerminalCellError::Binding("recovery source"))?,
        dataset,
        loaded,
    })
}

fn digest(value: &str) -> Result<Digest32> {
    value
        .parse()
        .map_err(|_| SharedTerminalCellError::Binding("recovery digest"))
}

fn id(value: String) -> Result<StableId> {
    StableId::new(value).map_err(|_| SharedTerminalCellError::Binding("recovery identity"))
}
