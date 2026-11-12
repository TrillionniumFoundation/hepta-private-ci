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
    ) -> io::Result<RegisteredGenerationPublication> {
        original_root()?;
        require_end(end)?;
        let initial = learning.profile.original_initial_data()?;
        let scope = learning.profile.require_cell_scope(&initial)?;
        let binding = PublicationRefusalBinding::from_original(&initial, &scope, &inputs, version)?;
        PublicationRefusal::enroll(
            Arc::clone(&inputs.current_directory),
            binding,
            inputs.mode,
            end,
            |refusal| {
                let enrolled = self.enroll_armed_generation_publication(
                    config,
                    registration,
                    owner,
                    learning,
                    inputs,
                    version,
                    refusal,
                )?;
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
