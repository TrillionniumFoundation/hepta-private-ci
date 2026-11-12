//! Original Root enrollment. Reserve persists only the exact deployment
//! profile; CURRENT preparation waits for the consumer's validated target.
//! Recovery opens the same retained profile and CURRENT without any mutation.

use super::*;

impl HostAuthorityService {
    pub(crate) fn enroll_generation_initial(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        deployment: &HostGenerationInitialDeploymentV1,
        inputs: RootGenerationInitialEnrollmentV1,
    ) -> io::Result<RegisteredGenerationInitial> {
        self.enroll_generation_initial_in_phase(
            config, registration, owner, deployment, inputs, None,
        )
    }

    pub(crate) fn enroll_generation_initial_in_phase(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        deployment: &HostGenerationInitialDeploymentV1,
        inputs: RootGenerationInitialEnrollmentV1,
        phase: Option<&Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>>,
    ) -> io::Result<RegisteredGenerationInitial> {
        original_root()?;
        let mut enrolled_result = None;
        self.with_initial_publication_context(config, registration, owner, |proof| {
            let _admission = phase.map(|gate| gate.enter_original_lane()).transpose()?;
            let profile_owner = format!(
                "generation-initial/{}",
                crate::neuron_generation_current::types::scope_digest(deployment.target.scope(),)
                    .map_err(io::Error::other)?,
            );
            let recovered = match inputs.mode {
                RootGenerationInitialModeV1::Reserve => None,
                RootGenerationInitialModeV1::Recover => {
                    let store = HostAuthorityFrontierStore::<InitialRecord>::open(
                        inputs.current_directory.clone(),
                        profile_owner.clone(),
                    )
                    .map_err(io::Error::other)?;
                    let record = store.load(&profile_owner).map_err(io::Error::other)?;
                    if record.fenced {
                        return Err(io::Error::other("original initial enrollment is fenced"));
                    }
                    Some((Arc::new(store), record))
                }
            };
            let retained_result = (|| -> io::Result<RegisteredGenerationInitial> {
                let actual = HostGenerationInitialDeploymentV1::new(
                    deployment.operation.clone(),
                    &inputs.target.config,
                )?;
                if &actual != deployment
                    || deployment.target.scope().agent_id != self.identity.agent_id.as_str()
                {
                    return Err(io::Error::other(
                        "original deployment target or agent differs",
                    ));
                }
                let pin = inputs::artifact_pin(&inputs.artifacts)?;
                let now = self
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms;
                let (artifacts, selected) =
                    inputs::open_artifacts(inputs.artifacts, config.peer_uid, now)?;
                let binding = crate::neuron_generation_initial::validate_initial_configuration(
                    &selected,
                    &inputs.target.config.generation,
                    inputs.target.config.journal_records,
                )
                .map_err(io::Error::other)?;
                if binding != deployment.target {
                    return Err(io::Error::other("original complete initial target differs"));
                }
                let target = inputs::open_target(inputs.target, config.peer_uid)?;
                let (prepared_head, prepared) =
                    crate::neuron_generation_current::initial_root::original_initial_description(
                        deployment.operation.clone(),
                        binding,
                        &selected,
                    )
                    .map_err(io::Error::other)?;
                let (consumer, local_consumer) = self.open_initial_consumer(
                    config,
                    inputs.consumer,
                    inputs.consumer_state_root,
                    inputs.issuer_keys,
                )?;
                let mut profile = InitialProfile {
                    purpose: PURPOSE.into(),
                    deployment: deployment.clone(),
                    writer: proof,
                    identity: crate::neuron_generation_process_identity_digest_v1(&self.identity)
                        .map_err(io::Error::other)?
                        .to_string(),
                    target_files: target.files_binding().to_string(),
                    artifacts: pin,
                    consumer_trust: Digest32::from_array(consumer.issuer_trust_digest())
                        .to_string(),
                    consumer_slot: inputs.consumer,
                    local_consumer,
                    prepared: prepared_head,
                    intent: prepared.intent_digest().to_string(),
                    selection: prepared.selection_observation_digest().to_string(),
                    final_use: prepared.final_use_binding().clone(),
                    binding: String::new(),
                };
                profile.binding = profile.digest()?;
                let current =
                    match inputs.mode {
                        RootGenerationInitialModeV1::Reserve => {
                            target
                                .require_original_unwritten()
                                .map_err(io::Error::other)?;
                            None
                        }
                        RootGenerationInitialModeV1::Recover => {
                            let current = NeuronGenerationCurrentOwnerV1::open(
                                inputs.current_directory.clone(),
                                deployment.target.scope(),
                            )
                            .map_err(io::Error::other)?;
                            let head = current.original_broker_head().map_err(io::Error::other)?;
                            crate::neuron_generation_current::initial_root::original_initial_record(
                        &profile.prepared, &head,
                    ).map_err(io::Error::other)?;
                            Some(current)
                        }
                    };
                if let Some(gate) = phase { gate.require_open()?; }
                let profile_store = match &recovered {
                    Some((store, record)) => {
                        if record.profile != profile {
                            return Err(io::Error::other(
                                "original entire initial profile differs",
                            ));
                        }
                        Arc::clone(store)
                    }
                    None => Arc::new(
                        HostAuthorityFrontierStore::initialize(
                            inputs.current_directory.clone(),
                            profile_owner.clone(),
                            InitialRecord {
                                profile: profile.clone(),
                                fenced: false,
                            },
                        )
                        .map_err(io::Error::other)?,
                    ),
                };
                let enrolled = RegisteredGenerationInitial {
                    profile,
                    mode: inputs.mode,
                    profile_store,
                    profile_owner: profile_owner.clone(),
                    root: inputs.current_directory,
                    current: Mutex::new(current),
                    target,
                    artifacts,
                    selected: Mutex::new(selected),
                    consumer,
                };
                enrolled.require_profile()?;
                enrolled.require_selection(
                    self.clock
                        .refresh_projection()
                        .map_err(io::Error::other)?
                        .observed_unix_ms,
                )?;
                // Read the same physical state again. A registered empty target is
                // not genesis, and a retained publication is never claimed again.
                let held = enrolled
                    .current
                    .try_lock()
                    .map_err(|_| io::Error::other("original initial CURRENT busy"))?;
                match held.as_ref() {
                    None => enrolled.require_target(/*fresh*/ true)?,
                    Some(current) => {
                        let head = current.original_broker_head().map_err(io::Error::other)?;
                        if let Some((signed, witness)) =
                            crate::neuron_generation_current::initial_root::original_initial_record(
                                &enrolled.profile.prepared,
                                &head,
                            )
                            .map_err(io::Error::other)?
                        {
                            if enrolled.verify_recorded_use(&signed, &witness)?
                                != self.issuer.revocations()?
                            {
                                return Err(io::Error::other(
                                    "retained initial revocations differ",
                                ));
                            }
                            enrolled.observe_published_target()?;
                        } else {
                            enrolled.require_target(/*fresh*/ false)?;
                        }
                    }
                }
                drop(held);
                if let Some(gate) = phase { gate.require_open()?; }
                Ok(enrolled)
            })();
            let enrolled = match retained_result {
                Ok(enrolled) => enrolled,
                Err(error) => {
                    if let Some((store, _)) = &recovered {
                        fence_initial_record(store, &profile_owner)?;
                    }
                    return Err(error);
                }
            };
            enrolled_result = Some(enrolled);
            Ok(())
        })?;
        enrolled_result.ok_or_else(|| io::Error::other("initial enrollment result missing"))
    }
}
