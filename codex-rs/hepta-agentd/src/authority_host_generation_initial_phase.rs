//! Same-service validation of the actual published and drained A cut before
//! a durable phase claim. Business completion and its accepted Outcome remain
//! the original daemon Prepared/retained-source join's separate obligation.

use super::*;
use crate::HostAuthorityLearningProfileV1;
use crate::same_actor_q24_phase_record::OriginalPhaseRecord;
use crate::same_actor_q24_phase_record::PhaseClaim;

/// Captured inside the same Root while the original Initial owner is held.
/// The caller must complete the original join and drop that owner before any
/// successor CURRENT open. This data does not attest a terminal business Outcome.
pub(crate) struct OriginalSameActorPhaseClaim {
    root: Arc<RootAuthorityDirectory>,
    head: CurrentHead,
    files: String,
    owner: CellGenerationOwnerBindingV1,
    checkpoint: [u8; 32],
    observation: [u8; 32],
    consumer_slot: crate::RootPublicationFinalUseConsumerV1,
    consumer_trust: String,
    local_consumer: PathBuf,
}

pub(crate) struct OriginalSameActorPhaseA {
    pub(crate) previous: CellGenerationJournalObserverV1,
    pub(crate) root: Arc<RootAuthorityDirectory>,
    pub(crate) head: CurrentHead,
    pub(crate) files: String,
    pub(crate) owner: CellGenerationOwnerBindingV1,
    pub(crate) checkpoint: [u8; 32],
    pub(crate) observation: [u8; 32],
    pub(crate) consumer_slot: crate::RootPublicationFinalUseConsumerV1,
    pub(crate) consumer_trust: String,
    pub(crate) local_consumer: PathBuf,
}

impl HostAuthorityService {
    pub(crate) fn claim_same_actor_phase_after_original_a(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        original: &RegisteredGenerationInitial,
        profile: &HostAuthorityLearningProfileV1,
        record: &mut OriginalPhaseRecord,
        gate: &Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    ) -> io::Result<OriginalSameActorPhaseClaim> {
        let mut captured = None;
        self.with_learning_profile(config, registration, owner_pidfd, profile, |initial, proof| {
            let _admission = gate.enter_original_lane()?;
            let scope = profile.require_cell_scope(&initial)?;
            if original.mode != RootGenerationInitialModeV1::Reserve
                || record.identity()?.initial != original.profile.deployment
                || record.identity()?.writer != proof
                || original.profile.writer != proof
                || record.identity()?.identity != original.profile.identity
            {
                return Err(io::Error::other("original same-session A registration differs"));
            }
            original.require_profile()?;
            let now = self.clock.refresh_projection().map_err(io::Error::other)?
                .observed_unix_ms;
            original.require_selection(now)?;
            {
                let selected: std::sync::MutexGuard<'_, AgentdSelectedGenerationV1> =
                    original.selected.try_lock()
                        .map_err(|_| io::Error::other("original A selection busy"))?;
                crate::cell_composed_q24::validate_manifest(
                    &initial.request.selected_bundle, selected.manifest(),
                ).map_err(io::Error::other)?;
            }
            let observed = original.target.observe().map_err(io::Error::other)?;
            let binding = original.target.owner_binding();
            if !observed.is_drained()
                || binding != &original.profile.deployment.target
                || binding.scope().agent_id != initial.request.agent_id.as_str()
                || binding.scope().cell_id != initial.request.cell_id.as_str()
                || binding.scope().run_id != initial.request.source_run_id.as_str()
                || Digest32::from_array(binding.scope().principal_digest).to_string()
                    != initial.request.principal_id.as_str()
            {
                return Err(io::Error::other("actual same-actor A drain and source required"));
            }
            let current: std::sync::MutexGuard<'_, Option<NeuronGenerationCurrentOwnerV1>> =
                original.current.try_lock()
                    .map_err(|_| io::Error::other("original A CURRENT busy"))?;
            let head = current.as_ref()
                .ok_or_else(|| io::Error::other("original A CURRENT was not published"))?
                .original_broker_head().map_err(io::Error::other)?;
            let (signed, witness) =
                crate::neuron_generation_current::initial_root::original_initial_record(
                    &original.profile.prepared, &head,
                ).map_err(io::Error::other)?
                    .ok_or_else(|| io::Error::other("original A initial use is unconsumed"))?;
            let revocations = self.issuer.revocations()?;
            if head.current != *binding
                || original.verify_recorded_use(&signed, &witness)? != revocations
            {
                return Err(io::Error::other("original A publication or retained use differs"));
            }
            let claim = PhaseClaim {
                learning_profile: serde_json::to_string(profile).map_err(io::Error::other)?,
                initial_learning_head: initial.head_digest.to_string(),
                scope: scope.binding().to_string(),
                initial_publication: original.profile.binding.clone(),
                current_head: head_digest(&Some(head.clone()))?,
                source_files: original.target.files_binding().to_string(),
                source_binding: binding.clone(),
                source_checkpoint: observed.observation().owner_checkpoint().to_string(),
                source_observation: Digest32::from_array(
                    observed.observation().digest().map_err(io::Error::other)?,
                ).to_string(),
            };
            // This durable claim precedes every Learning/Model namespace.
            // Any uncertainty consumes the record's in-memory expected value.
            gate.require_open()?;
            record.claim_before_namespaces(claim)?;
            gate.require_open()?;
            if original.target.observe().map_err(io::Error::other)? != observed
                || original.target.files_binding().to_string() != original.profile.target_files
                || current.as_ref()
                    .ok_or_else(|| io::Error::other("original A CURRENT disappeared"))?
                    .original_broker_head().map_err(io::Error::other)? != head
                || original.verify_recorded_use(&signed, &witness)? != revocations
            {
                return Err(io::Error::other("original A changed during phase claim"));
            }
            original.require_profile()?;
            original.require_selection(
                self.clock.refresh_projection().map_err(io::Error::other)?.observed_unix_ms,
            )?;
            gate.require_open()?;
            captured = Some(OriginalSameActorPhaseClaim {
                root: Arc::clone(&original.root),
                head,
                files: original.target.files_binding().to_string(),
                owner: binding.clone(),
                checkpoint: observed.observation().owner_checkpoint().into_array(),
                observation: observed.observation().digest().map_err(io::Error::other)?,
                consumer_slot: original.profile.consumer_slot,
                consumer_trust: original.profile.consumer_trust.clone(),
                local_consumer: original.profile.local_consumer.clone(),
            });
            Ok(())
        })?;
        captured.ok_or_else(|| io::Error::other("original A phase claim capture missing"))
    }
}

impl RegisteredGenerationInitial {
    /// Release the actual original CURRENT owner, while retaining this SAME
    /// read-only journal/witness observer for every later phase comparison.
    pub(crate) fn retire_original_phase_slot(
        self,
        claim: OriginalSameActorPhaseClaim,
    ) -> io::Result<OriginalSameActorPhaseA> {
        if !Arc::ptr_eq(&self.root, &claim.root)
            || self.target.files_binding().to_string() != claim.files
            || self.target.owner_binding() != &claim.owner
            || self.profile.consumer_slot != claim.consumer_slot
            || self.profile.consumer_trust != claim.consumer_trust
            || self.profile.local_consumer != claim.local_consumer
        {
            return Err(io::Error::other("original Initial slot differs from its phase claim"));
        }
        self.require_profile()?;
        let observed = self.target.observe().map_err(io::Error::other)?;
        if !observed.is_drained()
            || observed.observation().owner_checkpoint().into_array() != claim.checkpoint
            || observed.observation().digest().map_err(io::Error::other)? != claim.observation
        {
            return Err(io::Error::other("original Initial cut changed before retirement"));
        }
        {
            let held = self.current.try_lock()
                .map_err(|_| io::Error::other("original Initial CURRENT busy before retirement"))?;
            if held.as_ref().ok_or_else(|| io::Error::other("original Initial CURRENT missing"))?
                .original_broker_head().map_err(io::Error::other)? != claim.head
            {
                return Err(io::Error::other("original Initial CURRENT changed before retirement"));
            }
        }
        let RegisteredGenerationInitial { current, target, .. } = self;
        drop(current);
        Ok(OriginalSameActorPhaseA {
            previous: target,
            root: claim.root,
            head: claim.head,
            files: claim.files,
            owner: claim.owner,
            checkpoint: claim.checkpoint,
            observation: claim.observation,
            consumer_slot: claim.consumer_slot,
            consumer_trust: claim.consumer_trust,
            local_consumer: claim.local_consumer,
        })
    }
}

impl OriginalSameActorPhaseA {
    pub(crate) fn require_retained_predecessor(&self) -> io::Result<()> {
        let observed = self.previous.observe().map_err(io::Error::other)?;
        if self.previous.files_binding().to_string() != self.files
            || self.previous.owner_binding() != &self.owner
            || !observed.is_drained()
            || observed.observation().owner_checkpoint().into_array() != self.checkpoint
            || observed.observation().digest().map_err(io::Error::other)? != self.observation
        {
            return Err(io::Error::other("retained original A journal/witness changed"));
        }
        Ok(())
    }
}
