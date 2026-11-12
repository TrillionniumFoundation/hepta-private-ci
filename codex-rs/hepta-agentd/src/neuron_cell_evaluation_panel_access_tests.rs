//! Explicit synthetic B time only; production always obtains SystemTime.
//! This access never replaces the original Qualification/Trainer clock.
use super::*;

impl<C: AnchorWitnessStore, F: AnchorWitnessStore, X: AnchorWitnessStore, Q: AnchorWitnessStore>
    OriginalCellEvaluationPanelOwnerV1<C, F, X, Q>
{
    pub(crate) async fn fixture_current(
        &mut self,
        at: u64,
    ) -> Result<OriginalCellEvaluationPanelReadbackV1, Error> {
        self.read_current_with_clock(|| Ok(at), TrainingRead::Independent)
            .await
    }

    pub(crate) fn fixture_cohort_bytes(&mut self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = Vec::new();
        bytes.extend(self.primary.cohort.fixture_bytes()?);
        for member in &mut self.retention {
            bytes.extend(member.cohort.fixture_bytes()?);
        }
        Ok(bytes)
    }
}
