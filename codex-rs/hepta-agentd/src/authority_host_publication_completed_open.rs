//! Read-side construction under an already Armed first-publication proof.
//! No enrollment, reservation, writer, grant or signature is produced here.

use std::os::unix::fs::MetadataExt;
use std::path::Path;

use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;

use super::*;

impl<'a> OriginalCompletedPublicationReadV1<'a> {
    pub(crate) fn open_existing(
        proof: &'a OriginalPublicationHistoryProofV1<'a>,
        service: &'a HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        root_path: &Path,
        inputs: RootGenerationPublicationEnrollmentV1,
        files: Arc<crate::authority_host_runtime::RootOriginalSuccessorFilesV1>,
        mode: OriginalCompletedPublicationModeV1,
        end: Instant,
    ) -> io::Result<Self> {
        original_root()?;
        refusal::require_end(end)?;
        let profile = proof.original_profile()?;
        let profile_owner = format!(
            "{}/{}",
            PublicationVersion::DurableV2.owner_prefix(),
            Digest32::of_bytes(profile.intent.operation_id.as_bytes())
        );
        let profile_pin = OriginalControlRecord::open(root_path, &profile_owner)?;
        let profile_store = HostAuthorityFrontierStore::<PublicationRecord>::open(
            Arc::clone(&inputs.current_directory),
            profile_owner.clone(),
        )
        .map_err(io::Error::other)?;
        let current_owner = format!(
            "cell-generation/{}",
            crate::neuron_generation_current::types::scope_digest(profile.intent.previous.scope())
                .map_err(io::Error::other)?
        );
        let current_pin = OriginalControlRecord::open(root_path, &current_owner)?;
        let current = HostAuthorityFrontierStore::<CurrentHead>::open(
            Arc::clone(&inputs.current_directory),
            current_owner.clone(),
        )
        .map_err(io::Error::other)?;
        let pin = artifact_pin(&inputs.artifacts)?;
        if pin != profile.artifacts || inputs.consumer != profile.consumer_slot {
            return Err(io::Error::other(
                "original completed publication inputs differ",
            ));
        }
        let at = proof.verified_at_unix_ms();
        let artifacts = LearningArtifactReadViewV1::open_original(
            inputs.artifacts.root,
            config.peer_uid,
            inputs.artifacts.trust,
            inputs.artifacts.retained_current,
            at,
        )
        .map_err(io::Error::other)?
        .with_original_withdrawal_floor(
            inputs.artifacts.storage_binding,
            inputs.artifacts.withdrawal_floor,
        )
        .map_err(io::Error::other)?;
        let selected = AgentdSelectedGenerationV1::load_from_original_artifacts(
            &artifacts,
            inputs.artifacts.selector,
            inputs.artifacts.signed_selection,
            inputs.artifacts.files,
            at,
        )
        .map_err(io::Error::other)?;
        if inputs.target.config.generation.manifest != *selected.manifest() {
            return Err(io::Error::other(
                "completed target manifest differs from original selection",
            ));
        }
        let previous = inputs.previous.observe(config.peer_uid)?;
        let target = inputs.target.observe(config.peer_uid)?;
        let slots = config
            .consumers
            .as_ref()
            .ok_or_else(|| io::Error::other("actual original consumer configuration missing"))?;
        let (slot, name) = match inputs.consumer {
            RootPublicationFinalUseConsumerV1::Device => (&slots.device, "device"),
            RootPublicationFinalUseConsumerV1::Notes => (&slots.notes, "notes"),
        };
        let key = service.issuer.trust_key()?;
        let local = std::fs::symlink_metadata(&inputs.consumer_state_root)?;
        let local_consumer = inputs.consumer_state_root.join(name);
        if service.consumers.is_none()
            || slot.owner_id != key.key_id
            || slot.owner_id != config.signer_id
            || !inputs.issuer_keys.contains(&key)
            || !inputs.consumer_state_root.is_absolute()
            || inputs.consumer_state_root.canonicalize()? != inputs.consumer_state_root
            || !local.is_dir()
            || local.uid() != config.peer_uid
            || local.gid() != config.peer_gid
            || local.mode() & 0o7777 != 0o700
            || local_consumer != profile.local_consumer
        {
            return Err(io::Error::other(
                "actual completed consumer custody differs",
            ));
        }
        let consumer_pin = OriginalControlRecord::open(&slot.state_dir, &slot.owner_id)?;
        let frontier: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>> = Arc::new(
            HostAuthorityFrontierStore::<FinalUseFrontier>::open(
                RootAuthorityDirectory::open(&slot.state_dir).map_err(io::Error::other)?,
                slot.owner_id.clone(),
            )
            .map_err(io::Error::other)?,
        );
        let consumer = RootFinalUseObserverV1::open_original(
            &local_consumer,
            config.peer_uid,
            key.key_id,
            inputs.issuer_keys,
            frontier,
        )
        .map_err(io::Error::other)?;
        if consumer.consumer_uid() != config.peer_uid
            || consumer.signer_id() != slot.owner_id
            || Digest32::from_array(consumer.issuer_trust_digest()).to_string()
                != profile.consumer_trust
        {
            return Err(io::Error::other(
                "original completed consumer keyring differs",
            ));
        }
        let successor = match mode {
            OriginalCompletedPublicationModeV1::AcceptedPublication => None,
            OriginalCompletedPublicationModeV1::CaptureRetired
            | OriginalCompletedPublicationModeV1::ReadFinalized => {
                Some(RegisteredSuccessorData::open_completed_history(
                    inputs.current_directory,
                    root_path,
                    proof,
                    files,
                    config.peer_uid,
                    config.peer_gid,
                )?)
            }
        };
        let mut held = Self {
            proof,
            service,
            mode,
            end,
            profile_store,
            profile_owner,
            profile_pin,
            current,
            current_owner,
            current_pin,
            previous,
            target,
            original_target: None,
            artifacts,
            selected,
            consumer,
            consumer_pin,
            successor,
            phase: ReadPhase::AwaitingContext,
        };
        held.require_physical()?;
        Ok(held)
    }
}

fn artifact_pin(inputs: &RootArtifactPublicationInputsV1) -> io::Result<ArtifactRegistrationPin> {
    Ok(ArtifactRegistrationPin {
        root: inputs.root.clone(),
        trust: ArtifactOwnerVerifierV1::new(inputs.trust.clone())
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
    })
}
