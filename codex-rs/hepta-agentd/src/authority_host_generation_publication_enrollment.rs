//! Root-only late enrollment from actual original capabilities, after the
//! original learning decision exists. Peer messages cannot supply these inputs.

use std::os::unix::fs::MetadataExt;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_neuron::CellGenerationObserverConfigV1;

use super::*;
use crate::AgentdGenerationSelectionFilesV1;
use crate::NeuronGenerationPredecessorCompletionV1;

/// The original non-Root journal and independent witness. These are retained
/// descriptors, not paths supplied by the daemon's publication request.
pub struct RootGenerationJournalInputsV1 {
    pub journal: File,
    pub witness: File,
    pub config: CellGenerationObserverConfigV1,
}

impl RootGenerationJournalInputsV1 {
    fn observe(self, consumer_uid: u32) -> io::Result<CellGenerationJournalObserverV1> {
        for file in [&self.journal, &self.witness] {
            let metadata = file.metadata()?;
            if !metadata.is_file()
                || metadata.nlink() != 1
                || ![0, consumer_uid].contains(&metadata.uid())
                || metadata.mode() & 0o077 != 0
            {
                return Err(io::Error::other(
                    "original private journal/witness custody required",
                ));
            }
        }
        CellGenerationJournalObserverV1::from_original_files(
            self.journal,
            self.witness,
            self.config,
        )
        .map_err(io::Error::other)
    }
}

/// Original artifact read-side registration and separately signed selection.
/// The Root host provides real trust and files; no opaque selection is decoded.
pub struct RootArtifactPublicationInputsV1 {
    pub root: PathBuf,
    pub trust: ArtifactOwnerTrustV1,
    pub retained_current: SignedCurrentArtifactHeadV1,
    pub storage_binding: Digest32,
    pub withdrawal_floor: DatasetWithdrawalRegistry,
    pub selector: ArtifactSelectionVerifierV1,
    pub signed_selection: SignedArtifactSelectionV1,
    pub files: AgentdGenerationSelectionFilesV1,
}

/// One of the existing original consumer slots. This cannot create a third
/// consumer, choose an issuer, replace its keyring, or mint a grant.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RootPublicationFinalUseConsumerV1 {
    Device,
    Notes,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RootGenerationPublicationModeV1 {
    Reserve,
    Recover,
}

/// Trusted Root deployment inputs. Original CURRENT must already exist. A
/// missing recovery record never falls back to reserving a new operation.
pub struct RootGenerationPublicationEnrollmentV1 {
    pub mode: RootGenerationPublicationModeV1,
    pub current_directory: Arc<RootAuthorityDirectory>,
    pub previous: RootGenerationJournalInputsV1,
    pub target: RootGenerationJournalInputsV1,
    pub artifacts: RootArtifactPublicationInputsV1,
    pub consumer: RootPublicationFinalUseConsumerV1,
    pub consumer_state_root: PathBuf,
    /// The exact original consumer's complete issuer keyring, including any
    /// retained rotation keys. It cannot be replaced by a current-key subset.
    pub issuer_keys: Vec<codex_hepta_contracts::FinalUseIssuerTrustKey>,
}

impl HostAuthorityService {
    pub(crate) fn enroll_generation_publication(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
        inputs: RootGenerationPublicationEnrollmentV1,
    ) -> io::Result<RegisteredGenerationPublication> {
        self.enroll_original_publication_body(config, registration, owner, learning, inputs, None)
    }

    pub(crate) fn enroll_original_publication_body(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
        inputs: RootGenerationPublicationEnrollmentV1,
        phase: Option<&crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext<'_>>,
    ) -> io::Result<RegisteredGenerationPublication> {
        original_root()?;
        self.with_learning_profile(
            config,
            registration,
            owner,
            &learning.profile,
            |initial, proof| {
                let _admission = phase
                    .map(|context| {
                        let admission = context.gate.enter_original_lane()?;
                        context.require_before_enrollment()?;
                        Ok::<_, io::Error>(admission)
                    })
                    .transpose()?;
                let scope = learning.profile.require_cell_scope(&initial)?;
                let actual = learning
                    .backend
                    .restore(&initial.request)
                    .map_err(io::Error::other)?
                    .ok_or_else(|| io::Error::other("actual Root decision checkpoint required"))?;
                scope.validate_snapshot(&actual).map_err(io::Error::other)?;
                let mut replay =
                    codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::new(
                        actual.request.clone(),
                        actual.owners.clone(),
                    )
                    .map_err(io::Error::other)?;
                let mut decision = None;
                for receipt in &actual.receipts {
                    replay
                        .record(receipt.clone(), receipt.observed_unix_seconds)
                        .map_err(io::Error::other)?;
                    if let Ok(cut) = crate::cell_q24_publication_driver::validation::Decision::new(
                        replay.snapshot().clone(),
                    ) {
                        if decision.is_some() {
                            return Err(io::Error::other(
                                "ambiguous original publication decision",
                            ));
                        }
                        decision = Some(cut);
                    }
                }
                let decision = decision
                    .ok_or_else(|| io::Error::other("original publication decision missing"))?;
                decision
                    .require_root_publication()
                    .map_err(io::Error::other)?;
                if inputs.artifacts.signed_selection.artifact_kind
                    != codex_hepta_learning_artifacts::ArtifactKind::Model
                    || inputs.artifacts.signed_selection.artifact_id != decision.bundle.artifact_id
                    || inputs.artifacts.signed_selection.artifact_generation
                        != decision.bundle.generation
                {
                    return Err(io::Error::other(
                        "original selection artifact identity differs from Root decision",
                    ));
                }
                let profile_owner = format!(
                    "generation-publication/{}",
                    Digest32::of_bytes(decision.operation.as_str().as_bytes(),)
                );
                let recovered = if inputs.mode == RootGenerationPublicationModeV1::Recover {
                    let store = HostAuthorityFrontierStore::<PublicationRecord>::open(
                        inputs.current_directory.clone(),
                        profile_owner.clone(),
                    )
                    .map_err(io::Error::other)?;
                    let record = store.load(&profile_owner).map_err(io::Error::other)?;
                    if record.fenced {
                        return Err(io::Error::other("original publication permanently fenced"));
                    }
                    Some((store, record))
                } else {
                    None
                };
                let artifact_pin = ArtifactRegistrationPin {
                    root: inputs.artifacts.root.clone(),
                    trust: codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1::new(
                        inputs.artifacts.trust.clone(),
                    )
                    .map_err(io::Error::other)?
                    .trust_digest()
                    .to_string(),
                    storage: inputs.artifacts.storage_binding.to_string(),
                    retained_current: Digest32::of_parts(&[
                        b"hepta.root.publication.artifact-floor.v1\0",
                        &inputs.artifacts.retained_current.signing_bytes(),
                        &inputs.artifacts.retained_current.signature,
                    ])
                    .to_string(),
                    withdrawal_floor: Digest32::of_parts(&[
                        b"hepta.root.publication.withdrawal-floor.v1\0",
                        inputs
                            .artifacts
                            .withdrawal_floor
                            .scope_digest()
                            .ok_or_else(|| io::Error::other("original withdrawal scope missing"))?
                            .as_array(),
                        inputs.artifacts.withdrawal_floor.head_digest().as_array(),
                    ])
                    .to_string(),
                    selection: Digest32::of_parts(&[
                        b"hepta.root.publication.independent-selection.v1\0",
                        &inputs.artifacts.signed_selection.signing_bytes(),
                        &inputs.artifacts.signed_selection.signature,
                    ])
                    .to_string(),
                    selector_trust: inputs.artifacts.selector.trust_digest().to_string(),
                };
                if let Some((_, record)) = &recovered
                    && (record.profile.artifacts != artifact_pin
                        || record.profile.decision != decision.snapshot.head_digest.to_string()
                        || record.profile.initial != initial.head_digest.to_string()
                        || record.profile.scope != scope.binding().to_string()
                        || record.profile.writer != proof)
                {
                    return Err(io::Error::other("original recovery configuration differs"));
                }

                if inputs.mode == RootGenerationPublicationModeV1::Reserve
                    && decision.snapshot != actual
                {
                    return Err(io::Error::other(
                        "fresh enrollment requires the exact current decision cut",
                    ));
                }
                let now = self
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms;
                if inputs.mode == RootGenerationPublicationModeV1::Reserve
                    && now / 1000 >= initial.request.envelope.expiry_unix_seconds
                {
                    return Err(io::Error::other(
                        "expired original work cannot reserve publication",
                    ));
                }
                crate::cell_composed_q24::validate_manifest(
                    &initial.request.selected_bundle,
                    &inputs.previous.config.generation.manifest,
                )
                .map_err(io::Error::other)?;
                let observed_artifacts = (|| -> io::Result<_> {
                    let artifacts = LearningArtifactReadViewV1::open_original(
                        inputs.artifacts.root,
                        config.peer_uid,
                        inputs.artifacts.trust,
                        inputs.artifacts.retained_current,
                        now,
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
                        now,
                    )
                    .map_err(io::Error::other)?;
                    Ok((artifacts, selected))
                })();
                let (artifacts, selected) = match observed_artifacts {
                    Ok(value) => value,
                    Err(error) => {
                        if let Some((store, _)) = &recovered {
                            fence_record(store, &profile_owner)?;
                        }
                        return Err(error);
                    }
                };
                if let Some((store, record)) = &recovered
                    && selected.observation().digest().into_array()
                        != record.profile.intent.selection
                {
                    fence_record(store, &profile_owner)?;
                    return Err(io::Error::other(
                        "original enrolled selection frontier changed",
                    ));
                }
                crate::cell_composed_q24::validate_manifest(&decision.bundle, selected.manifest())
                    .map_err(io::Error::other)?;
                if inputs.target.config.generation.manifest != *selected.manifest() {
                    return Err(io::Error::other(
                        "target complete manifest differs from actual selection",
                    ));
                }
                let previous = inputs.previous.observe(config.peer_uid)?;
                let target = inputs.target.observe(config.peer_uid)?;
                let old = previous.observe().map_err(io::Error::other)?;
                let from = previous.owner_binding();
                let to = target.owner_binding();
                if !old.is_drained()
                    || from.scope().agent_id != initial.request.agent_id.as_str()
                    || from.scope().cell_id != initial.request.cell_id.as_str()
                    || from.scope().run_id != initial.request.source_run_id.as_str()
                    || Digest32::from_array(from.scope().principal_digest).to_string()
                        != initial.request.principal_id.as_str()
                    || crate::neuron_generation_current::types::scope_digest(from.scope())
                        .map_err(io::Error::other)?
                        != crate::neuron_generation_current::types::scope_digest(to.scope())
                            .map_err(io::Error::other)?
                    || from.scope().run_id == to.scope().run_id
                    || from.task_digest() == to.task_digest()
                    || from.generation().checked_add(1) != Some(to.generation())
                    || from.writer_epoch().checked_add(1) != Some(to.writer_epoch())
                    || decision.adopts() != (from.manifest_digest() != to.manifest_digest())
                {
                    return Err(io::Error::other(
                        "actual original learning predecessor/target differs",
                    ));
                }
                let intent = UpdateIntent {
                    operation_id: decision.operation.to_string(),
                    supersedes: None,
                    previous: from.clone(),
                    previous_checkpoint: old.observation().owner_checkpoint().into_array(),
                    previous_observation: old.observation().digest().map_err(io::Error::other)?,
                    target: to.clone(),
                    genesis_checkpoint: to.genesis_checkpoint().into_array(),
                    selection: selected.observation().digest().into_array(),
                    completion: if decision.adopts() {
                        NeuronGenerationPredecessorCompletionV1::OwnerDrained
                    } else {
                        NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
                    },
                };
                if let Some(context) = phase {
                    context.require_before_enrollment()?;
                }
                let current = NeuronGenerationCurrentOwnerV1::open(
                    inputs.current_directory.clone(),
                    from.scope(),
                )
                .map_err(io::Error::other)?;
                let control = current.original_broker_head().map_err(io::Error::other)?;
                if inputs.mode == RootGenerationPublicationModeV1::Reserve
                    && (control.current != *from || control.prepared.is_some())
                {
                    return Err(io::Error::other(
                        "fresh Root enrollment requires unprepared original CURRENT",
                    ));
                }
                if control.current != *from && control.current != *to
                    || control
                        .prepared
                        .as_ref()
                        .is_some_and(|value| value != &intent)
                {
                    return Err(io::Error::other(
                        "original CURRENT belongs to another operation",
                    ));
                }
                if control.current == *to {
                    if control
                        .published
                        .as_ref()
                        .is_none_or(|record| record.intent != intent)
                    {
                        return Err(io::Error::other(
                            "published target has no original exact record",
                        ));
                    }
                    target.observe().map_err(io::Error::other)?;
                } else {
                    target
                        .require_original_unwritten_or_genesis()
                        .map_err(io::Error::other)?;
                }
                let slots = config
                    .consumers
                    .as_ref()
                    .ok_or_else(|| io::Error::other("original consumer slots required"))?;
                if self.consumers.is_none() {
                    return Err(io::Error::other(
                        "same Root original consumer owners required",
                    ));
                }
                let (slot, name) = match inputs.consumer {
                    RootPublicationFinalUseConsumerV1::Device => (&slots.device, "device"),
                    RootPublicationFinalUseConsumerV1::Notes => (&slots.notes, "notes"),
                };
                let key = self.issuer.trust_key()?;
                if slot.owner_id != key.key_id
                    || slot.owner_id != config.signer_id
                    || !inputs.issuer_keys.contains(&key)
                {
                    return Err(io::Error::other("original canonical signer differs"));
                }
                let local = std::fs::symlink_metadata(&inputs.consumer_state_root)?;
                if !inputs.consumer_state_root.is_absolute()
                    || inputs.consumer_state_root.canonicalize()? != inputs.consumer_state_root
                    || !local.is_dir()
                    || local.uid() != config.peer_uid
                    || local.gid() != config.peer_gid
                    || local.mode() & 0o7777 != 0o700
                {
                    return Err(io::Error::other(
                        "original private consumer parent required",
                    ));
                }
                let local_consumer = inputs.consumer_state_root.join(name);
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
                {
                    return Err(io::Error::other(
                        "original consumer observer binding differs",
                    ));
                }
                let mut profile = PublicationProfile {
                    purpose: PURPOSE.into(),
                    learning_operation: initial.request.operation_id.to_string(),
                    initial: initial.head_digest.to_string(),
                    scope: scope.binding().to_string(),
                    writer: proof,
                    identity: crate::neuron_generation_process_identity_digest_v1(&self.identity)
                        .map_err(io::Error::other)?
                        .to_string(),
                    decision: decision.snapshot.head_digest.to_string(),
                    previous_files: previous.files_binding().to_string(),
                    target_files: target.files_binding().to_string(),
                    artifacts: artifact_pin,
                    consumer_trust: Digest32::from_array(consumer.issuer_trust_digest())
                        .to_string(),
                    consumer_slot: inputs.consumer,
                    local_consumer,
                    intent,
                    binding: String::new(),
                };
                profile.binding = profile.digest()?;
                if let Some(context) = phase {
                    context.require_before_enrollment()?;
                }
                let profile_store = match recovered {
                    Some((store, record)) => {
                        if record.profile != profile {
                            fence_record(&store, &profile_owner)?;
                            return Err(io::Error::other(
                                "original complete publication profile differs",
                            ));
                        }
                        store
                    }
                    None => HostAuthorityFrontierStore::initialize(
                        inputs.current_directory,
                        profile_owner.clone(),
                        PublicationRecord {
                            profile: profile.clone(),
                            fenced: false,
                        },
                    )
                    .map_err(io::Error::other)?,
                };
                let enrolled = RegisteredGenerationPublication {
                    profile,
                    profile_store,
                    profile_owner,
                    decision: decision.snapshot,
                    current,
                    previous,
                    target,
                    artifacts,
                    selected: Mutex::new(selected),
                    consumer,
                };
                enrolled.require_profile()?;
                enrolled.require_history(learning, &scope)?;
                enrolled.require_previous()?;
                enrolled.require_selection(
                    self.clock
                        .refresh_projection()
                        .map_err(io::Error::other)?
                        .observed_unix_ms,
                )?;
                if let Some(context) = phase {
                    context.require_original(&enrolled)?;
                }
                Ok(enrolled)
            },
        )
    }
}

impl HostAuthorityService {
    pub(crate) fn enroll_generation_publication_for_phase(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
        inputs: RootGenerationPublicationEnrollmentV1,
        phase: &crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext<'_>,
    ) -> io::Result<RegisteredGenerationPublication> {
        phase.gate.require_open()?;
        phase.record.require_scoped()?;
        if inputs.mode != RootGenerationPublicationModeV1::Reserve
            || !Arc::ptr_eq(&inputs.current_directory, &phase.original.root)
            || inputs.consumer != phase.original.consumer_slot
        {
            return Err(io::Error::other(
                "same-actor phase requires its original CURRENT and consumer",
            ));
        }
        // These duplicate only the original read descriptors. The original
        // enrollment below still consumes and checks the supplied files.
        let previous = RootGenerationJournalInputsV1 {
            journal: inputs.previous.journal.try_clone()?,
            witness: inputs.previous.witness.try_clone()?,
            config: inputs.previous.config.clone(),
        }
        .observe(config.peer_uid)?;
        let observed = previous.observe().map_err(io::Error::other)?;
        if previous.files_binding().to_string() != phase.original.files
            || previous.owner_binding() != &phase.original.owner
            || !observed.is_drained()
            || observed.observation().owner_checkpoint().into_array() != phase.original.checkpoint
            || observed.observation().digest().map_err(io::Error::other)?
                != phase.original.observation
        {
            return Err(io::Error::other(
                "same-actor phase predecessor changed before enrollment",
            ));
        }
        phase.gate.require_open()?;
        let slot = self.enroll_original_publication_body(
            config,
            registration,
            owner,
            learning,
            inputs,
            Some(phase),
        )?;
        self.with_learning_profile(
            config,
            registration,
            owner,
            &learning.profile,
            |_initial, _proof| {
                phase.require_original(&slot)?;
                if slot
                    .current
                    .original_broker_head()
                    .map_err(io::Error::other)?
                    != phase.original.head
                {
                    return Err(io::Error::other(
                        "same-actor phase CURRENT changed after the original A claim",
                    ));
                }
                if previous.observe().map_err(io::Error::other)? != observed {
                    return Err(io::Error::other(
                        "same-actor phase predecessor changed during enrollment",
                    ));
                }
                phase.require_original(&slot)
            },
        )?;
        Ok(slot)
    }
}
