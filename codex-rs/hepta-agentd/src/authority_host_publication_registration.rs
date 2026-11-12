//! Select only immutable data from the already registered Root learning owner,
//! then arm before any live Root proof, primary or physical read. The complete
//! original writer context and its postchecks are inside the same durable arm.

use std::time::Instant;

use super::refusal::PublicationRefusalBinding;
use super::refusal::require_end;
use super::*;
use crate::authority_host_runtime::verify_pinned_process;

impl HostAuthorityService {
    pub(crate) fn enroll_generation_publication(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
        inputs: RootGenerationPublicationEnrollmentV1,
        version: PublicationVersion,
        end: Instant,
        successor: Option<Arc<crate::authority_host_runtime::RootOriginalSuccessorFilesV1>>,
    ) -> io::Result<RegisteredGenerationPublication> {
        original_root()?;
        require_end(end)?;
        let initial = learning.profile.original_initial_data()?;
        let scope = learning.profile.require_cell_scope(&initial)?;
        let binding = PublicationRefusalBinding::from_original(&initial, &scope, &inputs, version)?;
        let root = Arc::clone(&inputs.current_directory);
        let mode = inputs.mode;
        PublicationRefusal::enroll(
            Arc::clone(&inputs.current_directory),
            binding,
            inputs.mode,
            end,
            |refusal| {
                let mut enrolled = self.enroll_armed_generation_publication(
                    config,
                    registration,
                    owner,
                    learning,
                    inputs,
                    version,
                    refusal,
                )?;
                if let Some(files) = successor {
                    let retained = self.with_learning_profile(
                        config,
                        registration,
                        owner,
                        &learning.profile,
                        |initial, proof| {
                            if version != PublicationVersion::DurableV2
                                || enrolled.profile.initial != initial.head_digest.to_string()
                                || enrolled.profile.writer != proof
                                || enrolled.profile.identity
                                    != crate::neuron_generation_process_identity_digest_v1(
                                        &self.identity,
                                    )
                                    .map_err(io::Error::other)?
                                    .to_string()
                            {
                                return Err(io::Error::other(
                                    "original successor Root context differs",
                                ));
                            }
                            enrolled.require_profile()?;
                            RegisteredSuccessorData::enroll(
                                root,
                                &enrolled,
                                files,
                                mode,
                                config,
                                registration,
                                &self.identity,
                            )
                        },
                    )?;
                    if mode == RootGenerationPublicationModeV1::Reserve {
                        retained.require_baseline()?;
                    } else {
                        retained.require_exact()?;
                    }
                    enrolled.successor = Some(retained);
                }
                // The actual with_learning_profile call and all of its writer,
                // issuer, logind and pidfd postchecks returned before completion.
                enrolled.require_profile()?;
                verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
                require_end(end)?;
                let original = enrolled.reserved.clone();
                Ok((enrolled, original))
            },
        )
    }
}
