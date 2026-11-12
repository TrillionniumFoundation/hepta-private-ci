//! Private clock for synthetic B admission/measurement fixtures only. The
//! production readback entry point has no caller-provided clock.
use super::*;
use pretty_assertions::assert_eq;

impl OriginalCircuitEvaluationCohortReadbackV1 {
    pub(crate) fn fixture_at(mut self, at: u64) -> Self {
        self.fixture_clock = Some(at);
        self
    }

    pub(crate) fn fixture_current(&mut self, at: u64) -> Result<OriginalCircuitEvaluationCohortCurrentV1, Error> {
        self.read_current_with_clock(|| Ok(at))
    }

    pub(crate) fn fixture_bytes(&mut self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok(self.original.owners.ledger.qualification_file_bytes(/*maximum_bytes*/ 8 * 1024 * 1024)?)
    }

    pub(crate) fn fixture_cold(
        original: OriginalCircuitEvaluationCohortV1,
        plan: CellEvaluationPlanV1,
        at: u64,
    ) -> Result<Self, Error> {
        binding::require_plan(&original, &plan)?;
        let mut owner = Self::retaining(original, plan).fixture_at(at);
        assert_eq!(owner.last, None);
        owner.read_current()?;
        Ok(owner)
    }
}
