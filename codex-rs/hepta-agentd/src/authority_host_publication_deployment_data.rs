//! Versioned deployment data. This is not an owner format: every live owner,
//! signature, journal cut and CURRENT decision is revalidated by enrollment.

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationObserverConfigV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::path::PathBuf;

use crate::RootPublicationFinalUseConsumerV1;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DeploymentData {
    pub schema_version: u32,
    pub mode: Mode,
    pub current_directory: PathBuf,
    pub previous_journal: PathBuf,
    pub previous_witness: PathBuf,
    pub previous: ObserverData,
    pub target_journal: PathBuf,
    pub target_witness: PathBuf,
    pub artifact_root: PathBuf,
    pub owner_trust: OwnerTrustData,
    pub retained_current: CurrentData,
    pub storage_binding: [u8; 32],
    pub withdrawal_file: PathBuf,
    pub withdrawal: WithdrawalData,
    pub selector_trust: SelectorTrustData,
    pub consumer: RootPublicationFinalUseConsumerV1,
    pub consumer_state_root: PathBuf,
    pub issuer_keys: Vec<IssuerKeyData>,
    pub late_material: PathBuf,
    pub trigger: PathBuf,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Mode {
    Reserve,
    Recover,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LateMaterial {
    pub schema_version: u32,
    pub target: ObserverData,
    pub selection: SelectionData,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ObserverData {
    pub generation: CellGenerationConfigV2,
    pub journal_records: u64,
    pub witness_scope: [u8; 32],
    pub witness_objective: [u8; 32],
    pub witness_generation: u64,
    pub witness_records: usize,
}

impl ObserverData {
    pub(super) fn original_observer_config(&self) -> io::Result<CellGenerationObserverConfigV1> {
        Ok(CellGenerationObserverConfigV1 {
            generation: self.generation.clone(),
            journal_records: self.journal_records,
            witness_scope: JournalScope {
                scope_digest: Digest32::from_array(self.witness_scope),
                objective_digest: Digest32::from_array(self.witness_objective),
            },
            witness_generation: Generation::new(self.witness_generation)
                .map_err(io::Error::other)?,
            witness_records: self.witness_records,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignerData {
    pub id: String,
    pub verifying_key: [u8; 32],
    pub minimum_authority_epoch: u64,
    pub maximum_authority_epoch: u64,
    pub valid_from: u64,
    pub expires_at: u64,
    #[serde(deserialize_with = "required_option")]
    pub revoked_at: Option<u64>,
}

impl SignerData {
    fn owner_signer(&self) -> io::Result<TrustedArtifactSignerV1> {
        Ok(TrustedArtifactSignerV1 {
            signer_id: StableId::new(&self.id).map_err(io::Error::other)?,
            verifying_key: self.verifying_key,
            minimum_authority_epoch: self.minimum_authority_epoch,
            maximum_authority_epoch: self.maximum_authority_epoch,
            valid_from: self.valid_from,
            expires_at: self.expires_at,
            revoked_at: self.revoked_at,
        })
    }
    fn selector_signer(&self) -> io::Result<TrustedArtifactSelectorV1> {
        let signer = self.owner_signer()?;
        Ok(TrustedArtifactSelectorV1 {
            selector_id: signer.signer_id,
            verifying_key: signer.verifying_key,
            minimum_authority_epoch: signer.minimum_authority_epoch,
            maximum_authority_epoch: signer.maximum_authority_epoch,
            valid_from: signer.valid_from,
            expires_at: signer.expires_at,
            revoked_at: signer.revoked_at,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OwnerTrustData {
    pub registry_id: String,
    pub withdrawal_scope: [u8; 32],
    pub minimum_registry_generation: u64,
    pub genesis_predecessor: [u8; 32],
    pub minimum_authority_epoch: u64,
    pub writer_signers: Vec<SignerData>,
    pub head_signers: Vec<SignerData>,
}

impl OwnerTrustData {
    pub(super) fn original_owner_trust(&self) -> io::Result<ArtifactOwnerTrustV1> {
        Ok(ArtifactOwnerTrustV1 {
            registry_id: StableId::new(&self.registry_id).map_err(io::Error::other)?,
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope),
            minimum_registry_generation: Generation::new(self.minimum_registry_generation)
                .map_err(io::Error::other)?,
            genesis_predecessor_head_digest: Digest32::from_array(self.genesis_predecessor),
            minimum_authority_epoch: self.minimum_authority_epoch,
            writer_signers: self
                .writer_signers
                .iter()
                .map(SignerData::owner_signer)
                .collect::<io::Result<_>>()?,
            head_signers: self
                .head_signers
                .iter()
                .map(SignerData::owner_signer)
                .collect::<io::Result<_>>()?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelectorTrustData {
    pub registry_id: String,
    pub withdrawal_scope: [u8; 32],
    pub minimum_authority_epoch: u64,
    pub selectors: Vec<SignerData>,
}

impl SelectorTrustData {
    pub(super) fn original_selector(
        &self,
        owner: &ArtifactOwnerTrustV1,
    ) -> io::Result<ArtifactSelectionVerifierV1> {
        ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: StableId::new(&self.registry_id).map_err(io::Error::other)?,
                withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope),
                minimum_authority_epoch: self.minimum_authority_epoch,
                selectors: self
                    .selectors
                    .iter()
                    .map(SignerData::selector_signer)
                    .collect::<io::Result<_>>()?,
            },
            owner,
        )
        .map_err(io::Error::other)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CurrentData {
    pub withdrawal_scope: [u8; 32],
    pub binding: [u8; 32],
    pub registry_id: String,
    pub generation: u64,
    pub head: [u8; 32],
    pub predecessor: [u8; 32],
    pub authority_epoch: u64,
    pub signer_id: String,
    pub signing_key_digest: [u8; 32],
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: Vec<u8>,
}

impl CurrentData {
    pub(super) fn original_current(&self) -> io::Result<SignedCurrentArtifactHeadV1> {
        Ok(SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope),
            binding: Digest32::from_array(self.binding),
            witness: RegistryHeadWitnessV1 {
                registry_id: StableId::new(&self.registry_id).map_err(io::Error::other)?,
                generation: Generation::new(self.generation).map_err(io::Error::other)?,
                head_digest: Digest32::from_array(self.head),
                predecessor_head_digest: Digest32::from_array(self.predecessor),
                authority_epoch: self.authority_epoch,
                signer_id: StableId::new(&self.signer_id).map_err(io::Error::other)?,
                signing_key_digest: Digest32::from_array(self.signing_key_digest),
                issued_at: self.issued_at,
                expires_at: self.expires_at,
            },
            signature: self
                .signature
                .as_slice()
                .try_into()
                .map_err(|_| io::Error::other("original signature must have 64 bytes"))?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WithdrawalData {
    pub binding: [u8; 32],
    pub scope: [u8; 32],
    pub head: [u8; 32],
    pub file_digest: [u8; 32],
    pub records: usize,
    pub encoded_bytes: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct IssuerKeyData {
    pub key_id: String,
    pub verifying_key: [u8; 32],
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelectionData {
    pub selection_id: String,
    pub artifact_id: String,
    pub registry_id: String,
    pub withdrawal_scope_digest: [u8; 32],
    pub registry_head_digest: [u8; 32],
    pub current_witness_digest: [u8; 32],
    pub current_trust_digest: [u8; 32],
    pub artifact_kind: ModelKind,
    pub artifact_generation: u64,
    #[serde(deserialize_with = "required_option")]
    pub predecessor_id: Option<String>,
    pub content_digest: [u8; 32],
    pub objective_digest: [u8; 32],
    pub support_digest: [u8; 32],
    pub compatibility_digest: [u8; 32],
    pub encoded_size_bytes: u64,
    pub selector_id: String,
    pub selector_credential_digest: [u8; 32],
    pub signing_key_digest: [u8; 32],
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ModelKind {
    Model,
}

impl SelectionData {
    pub(super) fn original_selection(&self) -> io::Result<SignedArtifactSelectionV1> {
        Ok(SignedArtifactSelectionV1 {
            selection_id: StableId::new(&self.selection_id).map_err(io::Error::other)?,
            artifact_id: StableId::new(&self.artifact_id).map_err(io::Error::other)?,
            registry_id: StableId::new(&self.registry_id).map_err(io::Error::other)?,
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope_digest),
            registry_head_digest: Digest32::from_array(self.registry_head_digest),
            current_witness_digest: Digest32::from_array(self.current_witness_digest),
            current_trust_digest: Digest32::from_array(self.current_trust_digest),
            artifact_kind: ArtifactKind::Model,
            artifact_generation: Generation::new(self.artifact_generation)
                .map_err(io::Error::other)?,
            predecessor_id: self
                .predecessor_id
                .as_ref()
                .map(StableId::new)
                .transpose()
                .map_err(io::Error::other)?,
            content_digest: Digest32::from_array(self.content_digest),
            objective_digest: Digest32::from_array(self.objective_digest),
            support_digest: Digest32::from_array(self.support_digest),
            compatibility_digest: Digest32::from_array(self.compatibility_digest),
            encoded_size_bytes: self.encoded_size_bytes,
            selector_id: StableId::new(&self.selector_id).map_err(io::Error::other)?,
            selector_credential_digest: Digest32::from_array(self.selector_credential_digest),
            signing_key_digest: Digest32::from_array(self.signing_key_digest),
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            signature: self
                .signature
                .as_slice()
                .try_into()
                .map_err(|_| io::Error::other("original selection signature must have 64 bytes"))?,
        })
    }
}

fn required_option<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::deserialize(deserializer)
}

impl ObserverData {
    pub(super) fn from_original_observer(original: &CellGenerationObserverConfigV1) -> Self {
        Self {
            generation: original.generation.clone(),
            journal_records: original.journal_records,
            witness_scope: original.witness_scope.scope_digest.into_array(),
            witness_objective: original.witness_scope.objective_digest.into_array(),
            witness_generation: original.witness_generation.get(),
            witness_records: original.witness_records,
        }
    }
}

impl SelectionData {
    pub(super) fn from_original_selection(
        original: &SignedArtifactSelectionV1,
    ) -> io::Result<Self> {
        if original.artifact_kind != ArtifactKind::Model {
            return Err(io::Error::other(
                "Cell publication requires an actual Model selection",
            ));
        }
        let data = Self {
            selection_id: original.selection_id.to_string(),
            artifact_id: original.artifact_id.to_string(),
            registry_id: original.registry_id.to_string(),
            withdrawal_scope_digest: original.withdrawal_scope_digest.into_array(),
            registry_head_digest: original.registry_head_digest.into_array(),
            current_witness_digest: original.current_witness_digest.into_array(),
            current_trust_digest: original.current_trust_digest.into_array(),
            artifact_kind: ModelKind::Model,
            artifact_generation: original.artifact_generation.get(),
            predecessor_id: original.predecessor_id.as_ref().map(ToString::to_string),
            content_digest: original.content_digest.into_array(),
            objective_digest: original.objective_digest.into_array(),
            support_digest: original.support_digest.into_array(),
            compatibility_digest: original.compatibility_digest.into_array(),
            encoded_size_bytes: original.encoded_size_bytes,
            selector_id: original.selector_id.to_string(),
            selector_credential_digest: original.selector_credential_digest.into_array(),
            signing_key_digest: original.signing_key_digest.into_array(),
            authority_epoch: original.authority_epoch,
            issued_at: original.issued_at,
            expires_at: original.expires_at,
            signature: original.signature.to_vec(),
        };
        if data.original_selection()? != *original {
            return Err(io::Error::other(
                "original selection data changed during encoding",
            ));
        }
        Ok(data)
    }
}
