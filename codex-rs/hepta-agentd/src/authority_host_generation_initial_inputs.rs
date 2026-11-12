//! Root-only original inputs. The independent selection and original readonly
//! descriptors are fixed before the consumer can send any initial request.

use super::*;
use codex_hepta_contracts::FinalUseFrontier;
use std::os::unix::fs::MetadataExt;

/// Reserve never opens or overwrites an existing initial CURRENT. Recover
/// opens only retained state and serves readback; it cannot Prepare or Publish.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RootGenerationInitialModeV1 {
    Reserve,
    Recover,
}

pub struct RootGenerationInitialEnrollmentV1 {
    pub mode: RootGenerationInitialModeV1,
    pub current_directory: Arc<RootAuthorityDirectory>,
    pub target: crate::RootGenerationJournalInputsV1,
    pub artifacts: crate::RootArtifactPublicationInputsV1,
    pub consumer: crate::RootPublicationFinalUseConsumerV1,
    pub consumer_state_root: PathBuf,
    pub issuer_keys: Vec<codex_hepta_contracts::FinalUseIssuerTrustKey>,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ArtifactPin {
    root: PathBuf,
    trust: String,
    storage: String,
    retained_current: String,
    withdrawal_floor: String,
    selection: String,
    selector_trust: String,
}

pub(super) fn artifact_pin(
    inputs: &crate::RootArtifactPublicationInputsV1,
) -> io::Result<ArtifactPin> {
    let artifact_pin = ArtifactPin {
        root: inputs.root.clone(),
        trust: codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1::new(inputs.trust.clone())
            .map_err(io::Error::other)?
            .trust_digest()
            .to_string(),
        storage: inputs.storage_binding.to_string(),
        retained_current: Digest32::of_parts(&[
            b"hepta.root.publication.artifact-floor.v1\0",
            &inputs.retained_current.signing_bytes(),
            &inputs.retained_current.signature,
        ])
        .to_string(),
        withdrawal_floor: Digest32::of_parts(&[
            b"hepta.root.publication.withdrawal-floor.v1\0",
            inputs
                .withdrawal_floor
                .scope_digest()
                .ok_or_else(|| io::Error::other("original withdrawal scope missing"))?
                .as_array(),
            inputs.withdrawal_floor.head_digest().as_array(),
        ])
        .to_string(),
        selection: Digest32::of_parts(&[
            b"hepta.root.publication.independent-selection.v1\0",
            &inputs.signed_selection.signing_bytes(),
            &inputs.signed_selection.signature,
        ])
        .to_string(),
        selector_trust: inputs.selector.trust_digest().to_string(),
    };

    Ok(artifact_pin)
}

pub(super) fn open_artifacts(
    inputs: crate::RootArtifactPublicationInputsV1,
    consumer_uid: u32,
    now: u64,
) -> io::Result<(LearningArtifactReadViewV1, AgentdSelectedGenerationV1)> {
    let artifacts = LearningArtifactReadViewV1::open_original(
        inputs.root,
        consumer_uid,
        inputs.trust,
        inputs.retained_current,
        now,
    )
    .map_err(io::Error::other)?
    .with_original_withdrawal_floor(inputs.storage_binding, inputs.withdrawal_floor)
    .map_err(io::Error::other)?;
    let selected = AgentdSelectedGenerationV1::load_from_original_artifacts(
        &artifacts,
        inputs.selector,
        inputs.signed_selection,
        inputs.files,
        now,
    )
    .map_err(io::Error::other)?;
    Ok((artifacts, selected))
}

pub(super) fn open_target(
    inputs: crate::RootGenerationJournalInputsV1,
    consumer_uid: u32,
) -> io::Result<CellGenerationJournalObserverV1> {
    for file in [&inputs.journal, &inputs.witness] {
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || ![0, consumer_uid].contains(&metadata.uid())
            || metadata.mode() & 0o077 != 0
        {
            return Err(io::Error::other("original private target custody required"));
        }
    }
    CellGenerationJournalObserverV1::from_original_files(
        inputs.journal,
        inputs.witness,
        inputs.config,
    )
    .map_err(io::Error::other)
}

impl HostAuthorityService {
    pub(super) fn open_initial_consumer(
        &self,
        config: &HostAuthorityServiceConfig,
        consumer_slot: crate::RootPublicationFinalUseConsumerV1,
        local_root: PathBuf,
        issuer_keys: Vec<codex_hepta_contracts::FinalUseIssuerTrustKey>,
    ) -> io::Result<(RootFinalUseObserverV1, PathBuf)> {
        let slots = config
            .consumers
            .as_ref()
            .ok_or_else(|| io::Error::other("original consumer slots required"))?;
        if self.consumers.is_none() {
            return Err(io::Error::other(
                "same Root original consumer owners required",
            ));
        }
        let (slot, name) = match consumer_slot {
            crate::RootPublicationFinalUseConsumerV1::Device => (&slots.device, "device"),
            crate::RootPublicationFinalUseConsumerV1::Notes => (&slots.notes, "notes"),
        };
        let key = self.issuer.trust_key()?;
        if slot.owner_id != key.key_id
            || slot.owner_id != config.signer_id
            || !issuer_keys.contains(&key)
        {
            return Err(io::Error::other(
                "original canonical initial signer differs",
            ));
        }
        let local = std::fs::symlink_metadata(&local_root)?;
        if !local_root.is_absolute()
            || local_root.canonicalize()? != local_root
            || !local.is_dir()
            || local.uid() != config.peer_uid
            || local.gid() != config.peer_gid
            || local.mode() & 0o7777 != 0o700
        {
            return Err(io::Error::other(
                "original private consumer parent required",
            ));
        }
        let path = local_root.join(name);
        let frontier: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>> = Arc::new(
            HostAuthorityFrontierStore::<FinalUseFrontier>::open(
                RootAuthorityDirectory::open(&slot.state_dir).map_err(io::Error::other)?,
                slot.owner_id.clone(),
            )
            .map_err(io::Error::other)?,
        );
        let consumer = RootFinalUseObserverV1::open_original(
            &path,
            config.peer_uid,
            key.key_id,
            issuer_keys,
            frontier,
        )
        .map_err(io::Error::other)?;
        if consumer.consumer_uid() != config.peer_uid || consumer.signer_id() != slot.owner_id {
            return Err(io::Error::other("original initial consumer differs"));
        }
        Ok((consumer, path))
    }
}
