//! The concrete original owners behind one already-completed panel member.
use std::sync::Arc;

use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_intelligence_eval::revalidate_product_qualification_v1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationScopeV2;
use codex_hepta_types::Digest32;

use super::super::OriginalCellEvaluationQualificationErrorV1;
use super::super::OriginalCellEvaluationQualificationOwnerV1;
use super::super::OriginalCellEvaluationQualificationSourcesV1;
use super::super::training_read_proof::OriginalPanelTrainingReadV1;
use super::Error;
use super::OriginalCellEvaluationPanelMemberReadbackV1;
use super::OriginalCellEvaluationPanelTaskV1;
use super::original;
use crate::CellEvaluationJournalsV1;
use crate::CellEvaluationRunnerV1;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCellEvaluationExecutionStoreV1;
use crate::OriginalCircuitEvaluationCohortReadbackV1;

/// These are existing original capabilities, moved once into the panel. The
/// panel exposes no callback, signature producer, file path or member getter.
/// Existing guarded Cells retain their original Current/revocation verifier.
pub struct OriginalCellEvaluationPanelMemberOwnersV1<
    C: AnchorWitnessStore,
    F: AnchorWitnessStore,
    X: AnchorWitnessStore,
    Q: AnchorWitnessStore,
> {
    pub qualification: OriginalCellEvaluationQualificationOwnerV1<Q>,
    pub runner: CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    pub candidate: CellGenerationJournalV2<C>,
    pub fixed_expert: CellGenerationJournalV2<F>,
    pub candidate_plan: TemporalEvaluationPlan,
    pub baseline_plan: TemporalEvaluationPlan,
    pub executions: OriginalCellEvaluationExecutionStoreV1<X>,
    pub trainer: Arc<LearningIterationEvidenceClientV1>,
    pub cohort: OriginalCircuitEvaluationCohortReadbackV1,
}

impl<C: AnchorWitnessStore, F: AnchorWitnessStore, X: AnchorWitnessStore, Q: AnchorWitnessStore>
    OriginalCellEvaluationPanelMemberOwnersV1<C, F, X, Q>
{
    pub(super) async fn read_original(
        &mut self,
        task: &OriginalCellEvaluationPanelTaskV1,
        clock: &mut (impl FnMut() -> Result<u64, OriginalCellEvaluationQualificationErrorV1> + Send),
        training: &mut OriginalPanelTrainingReadV1<'_>,
    ) -> Result<OriginalCellEvaluationPanelMemberReadbackV1, Error> {
        // The original Qualification owns its internal SystemTime checks.
        // The panel's final common clock reauthenticates every window later.
        let started_at = original::now()?;
        let cohort_before =
            OriginalCircuitEvaluationCohortReadbackV1::read_current(&mut self.cohort)?;
        let before = self.read_cells()?;
        let mut sources = OriginalCellEvaluationQualificationSourcesV1 {
            runner: &mut self.runner,
            journals: CellEvaluationJournalsV1 {
                candidate: &self.candidate,
                fixed_expert: &self.fixed_expert,
            },
            candidate_plan: &self.candidate_plan,
            baseline_plan: &self.baseline_plan,
            executions: &mut self.executions,
            trainer: self.trainer.as_ref(),
        };
        let bytes = self.qualification.completed_bytes()?;
        let prepared = OriginalCellEvaluationQualificationSourcesV1::prepare_with_training(
            &mut sources,
            &self.qualification.config,
            started_at,
            training,
        )
        .await?;
        let qualification =
            OriginalCellEvaluationQualificationOwnerV1::finish_readback_with_training(
                &mut self.qualification,
                &mut sources,
                &prepared,
                &bytes,
                started_at,
                /*new_publication*/ false,
                training,
            )
            .await?;
        drop(sources);
        let after = self.read_cells()?;
        let cohort_after =
            OriginalCircuitEvaluationCohortReadbackV1::read_current(&mut self.cohort)?;
        if before != after || cohort_before != cohort_after {
            return Err(Error::CommitUncertain);
        }
        let observed = OriginalCellEvaluationPanelMemberReadbackV1 {
            task: task.clone(),
            prepared,
            qualification,
            product_evidence: self.qualification.config.product_evidence.clone(),
            execution_evidence: self.qualification.config.execution_evidence.clone(),
            cells: after.0,
            scopes: after.1,
            cohort: cohort_after,
        };
        let current = clock()?;
        original::clock_time(started_at, current)?;
        self.authenticate(&observed, current)?;
        Ok(observed)
    }

    fn read_cells(&mut self) -> Result<([Digest32; 2], [CellGenerationScopeV2; 2]), Error> {
        let candidate = CellGenerationJournalV2::read_current_checkpoint(&mut self.candidate)?;
        let fixed_expert =
            CellGenerationJournalV2::read_current_checkpoint(&mut self.fixed_expert)?;
        let record = self.qualification.config.plan.record();
        if candidate != record.candidate.journal_cut
            || fixed_expert != record.fixed_expert.journal_cut
        {
            return Err(Error::Binding("same original physical evaluation Cells"));
        }
        let candidate_scope = self.candidate.snapshot()?.scope.clone();
        let baseline_scope = self.fixed_expert.snapshot()?.scope.clone();
        let source_run = self
            .qualification
            .config
            .training
            .request
            .source_run_id
            .as_str();
        if candidate_scope.run_id == source_run || baseline_scope.run_id == source_run {
            return Err(Error::Binding(
                "evaluation task must differ from original A",
            ));
        }
        Ok(([candidate, fixed_expert], [candidate_scope, baseline_scope]))
    }

    pub(super) fn authenticate(
        &mut self,
        observed: &OriginalCellEvaluationPanelMemberReadbackV1,
        current: u64,
    ) -> Result<(), Error> {
        OriginalCircuitEvaluationCohortReadbackV1::authenticate_current(
            &mut self.cohort,
            &observed.cohort,
            current,
        )?;
        let config = &self.qualification.config;
        if observed.product_evidence != config.product_evidence
            || observed.execution_evidence != config.execution_evidence
            || observed.qualification.comparison() != config.plan.record()
        {
            return Err(Error::Binding("exact original panel member evidence"));
        }
        original::authenticate(config, &observed.prepared, current)?;
        let decision = revalidate_product_qualification_v1(
            observed.qualification.product(),
            observed.prepared.bundle.clone(),
            config.plan.product_plan().metric_roles.clone(),
            &config.product_evidence,
            ProductTimingEvidenceV1::Qualification,
            &config.verifier,
            current,
        )
        .map_err(OriginalCellEvaluationQualificationErrorV1::from)?;
        if observed.qualification.product().decision != decision {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }
}
