//! Explicit retirement belongs to the original publication host. A read-only
//! Cell/Observer handle cannot acquire this durable version mutation capability.

use super::*;

impl PublishedCircuitFeatureTaskV1 {
    /// The genuine CJoined owner supplies its retained actual task here.
    /// Root Intent authorizes only this purpose shutdown, not C completion.
    pub(crate) fn retire_original_root_current_after_intent(
        &self,
        intent: &crate::same_actor_q24_deployment::OriginalRootRetirementIntent,
        identity: &AgentdIdentity,
        gate: &Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        let mut closing = crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop::new(gate);
        intent.require_original_origin(identity, gate)?;
        if self.0.source.scope.agent_id.as_str() != identity.agent_id.as_str()
            || !matches!(&self.0.publication, Publication::Update { .. })
        {
            return Err(invalid("retirement requires the actual published C task"));
        }
        // C's genuine drain and join already happened. Keep its real journal
        // locked and retained; never try to recreate that fact by a new read.
        let _original = self.0.original.try_lock().map_err(invalid)?;
        LiveGenerationCurrent::retire_original_current_purpose(
            &self.0.current, intent, identity, gate,
        )?;
        intent.require_original_origin(identity, gate)?;
        closing.disarm();
        Ok(())
    }

    /// Close this exact original task only after actual source and private Cell
    /// completion. Durable drain is never a manufactured model STOP.
    pub fn drain_completed_task<CW: AnchorWitnessStore, SW: AnchorWitnessStore>(
        &self,
        cell: &PublishedCircuitCellOwnerV1<CW>,
        source: &CircuitTaskSourceReadbackV1<SW>,
        identity: &AgentdIdentity,
    ) -> Result<PublishedCircuitFeatureCompletionV1, AgentdError> {
        if !Arc::ptr_eq(&self.0, &cell.task.0) {
            return Err(invalid("Feature retirement belongs to a different owner"));
        }
        let before = source
            .read_run_publication(identity, &self.source().scope.run_id)
            .map_err(invalid)?;
        let receipt = cell.committed(&before)?;
        if source
            .read_run_publication(identity, &self.source().scope.run_id)
            .map_err(invalid)?
            != before
        {
            return Err(invalid("original Feature source changed before drain"));
        }
        let mut original = self.0.original.lock().map_err(invalid)?;
        original.require_current()?;
        original.drain()?;
        if !original.is_drained()? {
            return Err(invalid("original task drain is uncertain"));
        }
        drop(original);
        if source
            .read_run_publication(identity, &self.source().scope.run_id)
            .map_err(invalid)?
            != before
        {
            return Err(invalid("original Feature source changed across drain"));
        }
        self.require_current()?;
        Ok(PublishedCircuitFeatureCompletionV1 {
            binding: self.0.publication.target().clone(),
            manifest: self.0.manifest.clone(),
            source: before,
            receipt,
        })
    }
}
