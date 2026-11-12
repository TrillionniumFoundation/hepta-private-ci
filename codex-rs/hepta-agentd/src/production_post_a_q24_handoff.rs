//! Hold the two original anonymous datagrams through historical preparation.
//! Only the actual Root late-install acknowledgement permits their consumption.

use super::*;

pub(in crate::production_launcher) struct PendingHandoffs {
    pub(super) learning: UnixDatagram,
    pub(super) model: UnixDatagram,
}

impl PendingHandoffs {
    pub(in crate::production_launcher) fn defer_for_original_profile(
        primary: &PrimaryInputs,
        learning: &mut Option<UnixDatagram>,
        model: &mut Option<UnixDatagram>,
    ) -> Result<Option<Self>, AgentdError> {
        if !matches!(primary, PrimaryInputs::PostAQ24 { .. }) {
            return Ok(None);
        }
        let learning = learning
            .take()
            .ok_or_else(|| refused("post-A learning handoff absent"))?;
        let model = model
            .take()
            .ok_or_else(|| refused("post-A model handoff absent"))?;
        Ok(Some(Self { learning, model }))
    }
}
