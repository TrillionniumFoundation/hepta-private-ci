//! Borrowed checks for new namespaces inside the original writer witness.
//! This object owns no authority; every call still uses the same Root service.

use std::io;
use std::sync::Arc;

use crate::same_actor_q24_phase_gate::SameActorPhaseAdmission;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use crate::same_actor_q24_phase_record::OriginalPhaseRecord;

pub(crate) struct OriginalPhaseNamespaceContext<'a> {
    pub(crate) gate: &'a Arc<SameActorPhaseGate>,
    pub(crate) record: &'a OriginalPhaseRecord,
}

impl OriginalPhaseNamespaceContext<'_> {
    pub(crate) fn enter_claimed(&self) -> io::Result<SameActorPhaseAdmission> {
        let admission = self.gate.enter_original_lane()?;
        self.require_claimed()?;
        Ok(admission)
    }

    pub(crate) fn require_claimed(&self) -> io::Result<()> {
        self.gate.require_open()?;
        self.record.require_claimed()?;
        self.gate.require_open()?;
        Ok(())
    }
}
