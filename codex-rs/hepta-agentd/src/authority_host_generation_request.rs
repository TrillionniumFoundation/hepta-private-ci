//! Exact initial-publication request data for the existing authorization path.
//! This preview opens no CURRENT, writes no target and creates no grant or
//! Prepared value. The later original prepare/publication rechecks everything.

use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_neuron::AnchorWitnessStore;

use super::HostAuthorityService;
use super::invalid;
use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_initial::validate_initial_target;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

impl HostAuthorityService {
    pub(crate) fn read_original_initial_request<W: AnchorWitnessStore>(
        &self,
        selected: &AgentdSelectedGenerationV1,
        target: &AgentdGenerationUpdateTargetV1<W>,
        request: &AgentdGenerationUpdateRequestV1,
        end: Instant,
    ) -> Result<FinalUseBinding, AgentdError> {
        // SAFETY: these process-identity calls have no pointer arguments.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0
            || Instant::now() >= end || self.resident_store_root.is_none()
        {
            return Err(invalid("original Root initial request is unavailable"));
        }
        let registry = self.root_registry.as_ref().ok_or_else(|| {
            invalid("original initial request requires the retained Root Registry")
        })?;
        let binding = NeuronGenerationCurrentOwnerV1::original_initial_publication_binding(
            request.operation_id.clone(), validate_initial_target(selected, target)?, selected,
        )?;
        if target.config.initial.scope.agent_id != self.identity.agent_id.as_str()
            || binding.subject_id != self.identity.agent_id.as_str()
            || binding.destination_id != "agentd.cell-generation.initialize"
        {
            return Err(invalid("initial request differs from the registered original identity"));
        }
        let expected = AuthorityLeaseBinding {
            principal_id: binding.subject_id.clone(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
        };
        let lease = self.issuer.with_live_lease(|lease| {
            if lease.binding != expected || Instant::now() >= end
                || self.clock.now_unix_ms().map_err(std::io::Error::other)?
                    >= lease.expires_at_unix_ms
            {
                return Err(std::io::Error::other("original initial request lease differs or expired"));
            }
            Ok(lease.clone())
        })?;
        let retained = registry.verifier().read_lease(&lease.lease_id).map_err(invalid)?;
        if retained.as_ref().map(|record| &record.lease) != Some(&lease)
            || self.clock.now_unix_ms().map_err(invalid)? >= lease.expires_at_unix_ms
            || Instant::now() >= end
        {
            return Err(invalid("original initial request lease changed or ended"));
        }
        Ok(binding)
    }
}
