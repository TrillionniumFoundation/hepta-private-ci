//! Original B plus nonempty retention, read from the same consumed owners.
//!
//! This boundary does not run B, release holdout data, publish Qualification,
//! sign a receipt, create a model, select a version, or obtain FinalUse. Those
//! original producers and capabilities remain separate. No arbitrary provider,
//! callback, raw batch, or vector of claimed completed receipts is accepted.

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_types::Digest32;

use super::OriginalCellEvaluationQualificationErrorV1;
use super::binding as original;
#[path = "neuron_cell_evaluation_panel_binding.rs"]
mod binding;
#[path = "neuron_cell_evaluation_panel_contract.rs"]
mod contract;
#[path = "neuron_cell_evaluation_panel_member.rs"]
mod member;
pub use contract::OriginalCellEvaluationPanelMemberReadbackV1;
pub use contract::OriginalCellEvaluationPanelReadbackV1;
pub use contract::OriginalCellEvaluationPanelRegistrationV1;
pub use contract::OriginalCellEvaluationPanelTaskV1;
pub use member::OriginalCellEvaluationPanelMemberOwnersV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellEvaluationPanelErrorV1 {
    #[error("original evaluation panel binding: {0}")]
    Binding(&'static str),
    #[error("original evaluation panel is uncertain")]
    CommitUncertain,
    #[error("original evaluation panel member: {0}")]
    Qualification(#[from] OriginalCellEvaluationQualificationErrorV1),
    #[error("original evaluation panel physical Cell: {0}")]
    Cell(#[from] CellGenerationErrorV2),
    #[error("original evaluation panel cohort: {0}")]
    Cohort(#[from] crate::OriginalCircuitEvaluationProviderErrorV1),
}
type Error = OriginalCellEvaluationPanelErrorV1;

/// Own the original member capabilities. There is no writer/key extraction,
/// recovery effect, replace-member operation, or way to clear a failed read.
pub struct OriginalCellEvaluationPanelOwnerV1<
    C: AnchorWitnessStore,
    F: AnchorWitnessStore,
    X: AnchorWitnessStore,
    Q: AnchorWitnessStore,
> {
    registration: OriginalCellEvaluationPanelRegistrationV1,
    primary: OriginalCellEvaluationPanelMemberOwnersV1<C, F, X, Q>,
    retention: Vec<OriginalCellEvaluationPanelMemberOwnersV1<C, F, X, Q>>,
    bindings: Vec<Digest32>,
    retained: Option<OriginalCellEvaluationPanelReadbackV1>,
    fenced: bool,
}

impl<C: AnchorWitnessStore, F: AnchorWitnessStore, X: AnchorWitnessStore, Q: AnchorWitnessStore>
    OriginalCellEvaluationPanelOwnerV1<C, F, X, Q>
{
    /// Consume already-held original owners. This performs fixed-profile
    /// validation only; a successful constructor is not a CURRENT observation.
    pub fn from_original_owners(
        registration: OriginalCellEvaluationPanelRegistrationV1,
        primary: OriginalCellEvaluationPanelMemberOwnersV1<C, F, X, Q>,
        retention: Vec<OriginalCellEvaluationPanelMemberOwnersV1<C, F, X, Q>>,
    ) -> Result<Self, Error> {
        let bindings = Self::validate_original_members(&registration, &primary, &retention)?;
        Ok(Self {
            registration,
            primary,
            retention,
            bindings,
            retained: None,
            fenced: false,
        })
    }

    pub async fn read_current(&mut self) -> Result<OriginalCellEvaluationPanelReadbackV1, Error> {
        self.read_current_with_clock(original::now).await
    }

    async fn read_current_with_clock(
        &mut self,
        mut clock: impl FnMut() -> Result<u64, OriginalCellEvaluationQualificationErrorV1> + Send,
    ) -> Result<OriginalCellEvaluationPanelReadbackV1, Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        self.fenced = true;
        let result = self.read_original_panel(&mut clock).await;
        if result.is_ok() {
            self.fenced = false;
        }
        result
    }

    async fn read_original_panel(
        &mut self,
        clock: &mut (impl FnMut() -> Result<u64, OriginalCellEvaluationQualificationErrorV1> + Send),
    ) -> Result<OriginalCellEvaluationPanelReadbackV1, Error> {
        let started_at = clock()?;
        let before = self.read_members(clock).await?;
        let after = self.read_members(clock).await?;
        if before != after {
            return Err(Error::CommitUncertain);
        }
        self.require_observed_panel(&after)?;
        let current = clock()?;
        original::clock_time(started_at, current)?;
        self.primary.authenticate(&after[0], current)?;
        for (owner, observed) in self.retention.iter_mut().zip(after.iter().skip(1)) {
            owner.authenticate(observed, current)?;
        }
        let result = self.seal_observed_panel(after)?;
        if self
            .retained
            .as_ref()
            .is_some_and(|original| original != &result)
        {
            return Err(Error::CommitUncertain);
        }
        self.retained = Some(result.clone());
        // No physical or peer I/O follows the common fresh authentication.
        Ok(result)
    }

    async fn read_members(
        &mut self,
        clock: &mut (impl FnMut() -> Result<u64, OriginalCellEvaluationQualificationErrorV1> + Send),
    ) -> Result<Vec<OriginalCellEvaluationPanelMemberReadbackV1>, Error> {
        let mut results = Vec::with_capacity(self.retention.len() + 1);
        results.push(
            OriginalCellEvaluationPanelMemberOwnersV1::read_original(
                &mut self.primary,
                self.registration.primary(),
                clock,
            )
            .await?,
        );
        for (owner, task) in self.retention.iter_mut().zip(self.registration.retention()) {
            results.push(
                OriginalCellEvaluationPanelMemberOwnersV1::read_original(owner, task, clock)
                    .await?,
            );
        }
        Ok(results)
    }
}

#[cfg(test)]
#[path = "neuron_cell_evaluation_panel_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "neuron_cell_evaluation_panel_access_tests.rs"]
mod test_access;

#[path = "neuron_cell_evaluation_host.rs"]
mod host;
pub use host::OriginalCellEvaluationCommandClientV1;
pub use host::OriginalCellEvaluationCommandConnectionV1;
pub use host::OriginalCellEvaluationCommandErrorV1;
pub use host::OriginalCellEvaluationCommandReceiptV1;
pub use host::OriginalCellEvaluationHostV1;
