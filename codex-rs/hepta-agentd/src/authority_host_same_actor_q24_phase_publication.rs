//! The claimed original A pins for this same-actor publication lane.
//! The ordinary publication implementation still performs every original
//! decision, selection, CURRENT, retained-use and process check.

use std::io;
use std::sync::Arc;

use crate::authority_host_service::generation_initial::OriginalSameActorPhaseA;
use crate::authority_host_service::generation_publication::RegisteredGenerationPublication;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use crate::same_actor_q24_phase_record::OriginalPhaseRecord;

pub(crate) struct OriginalPhasePublicationContext<'a> {
    pub(crate) gate: &'a Arc<SameActorPhaseGate>,
    pub(crate) record: &'a OriginalPhaseRecord,
    pub(crate) original: &'a OriginalSameActorPhaseA,
}

impl OriginalPhasePublicationContext<'_> {
    pub(crate) fn require_before_enrollment(&self) -> std::io::Result<()> {
        self.gate.require_open()?;
        self.record.require_scoped()?;
        self.original.require_retained_predecessor()?;
        self.gate.require_open()?;
        Ok(())
    }

    pub(crate) fn require_original(
        &self,
        slot: &RegisteredGenerationPublication,
    ) -> io::Result<()> {
        self.gate.require_open()?;
        self.record.require_scoped()?;
        self.original.require_retained_predecessor()?;
        let profile = &slot.profile;
        if profile.intent.previous != self.original.owner
            || profile.previous_files != self.original.files
            || profile.intent.previous_checkpoint != self.original.checkpoint
            || profile.intent.previous_observation != self.original.observation
            || profile.consumer_slot != self.original.consumer_slot
            || profile.consumer_trust != self.original.consumer_trust
            || profile.local_consumer != self.original.local_consumer
        {
            return Err(io::Error::other(
                "same-actor publication replaced its original A or consumer",
            ));
        }
        self.gate.require_open().map(|_| ())
    }
}
