//! The only deferred transition into actual native and Generator owners.
//! Dataset and both complete signatures come from the original readback,
//! followed by live Source capture before any original writer initialization.
use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::Origin;
use super::OriginalCellQ24TrainingBootstrapCustodyV1;
use super::OriginalCellQ24TrainingBootstrapOwnerV1;
use super::OriginalCellQ24TrainingCommandErrorV1;
use super::OriginalCellQ24TrainingCommandOwnerV1;
use super::super::OriginalCellQ24TrainingCommandContextV1;
use super::super::wire;
use crate::CellQ24TrainingOwnerV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialSourceConnectionV1;
use crate::OriginalCellQ24RemoteTrainingSourceOwnersV1;
use crate::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::OriginalCellQ24TrainingSigningConfigV1;
use crate::OriginalCellQ24TrainingSourceConfigV1;
use crate::OriginalCellQ24TrainingStageV1;
use crate::SourceBoundCellQ24TrainingStageV1;
use crate::capture_original_remote_cell_q24_training_source_v1;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>
{
    pub(super) fn actual_context(
        &self,
        cut: &OriginalCellQ24MaterialCommandReceiptV1,
        request: &wire::Request,
        next_request_id: u64,
        started_at: u64,
    ) -> Result<OriginalCellQ24TrainingCommandContextV1, Error> {
        let initial = &self.config.material.initial;
        let snapshot = cut.snapshot();
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
            .map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        if snapshot.request != initial.request || snapshot.owners != initial.owners
            || snapshot.receipts.len() != 2 || cut.attestations().len() != 2
            || coordinator.next_stage() != Some(LearningIterationStageV1::Training)
        {
            return Err(Error::Binding("actual original two-receipt Dataset cut"));
        }
        let context = OriginalCellQ24TrainingCommandContextV1 {
            dataset: snapshot.clone(), scope: self.config.material.scope.clone(),
            verifier: self.config.material.verifier.clone(),
        };
        request.require_context(&context, context.binding()?, next_request_id)?;
        self.require_fresh_cut(cut, started_at)?;
        Ok(context)
    }

    pub(super) fn require_fresh_cut(
        &self,
        cut: &OriginalCellQ24MaterialCommandReceiptV1,
        started_at: u64,
    ) -> Result<(), Error> {
        let at = OriginalCellQ24DatasetCommandReadbackV1::verify_original_cut(&self.dataset, cut)?;
        OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(&self.dataset, &self.config.material)?;
        if at < started_at || matches!(self.origin, Origin::Fresh)
            && at >= self.config.material.initial.request.envelope.expiry_unix_seconds
        {
            return Err(Error::Binding("Trainer bootstrap clock or new-work deadline"));
        }
        self.config.material.verifier.require_signer_binding(
            LearningEvidenceRoleV1::Generator, &self.config.generator, at,
        ).map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
        Ok(())
    }

    pub(super) async fn build_original_owner(
        &self,
        custody: OriginalCellQ24TrainingBootstrapCustodyV1<TW, RW>,
        context: OriginalCellQ24TrainingCommandContextV1,
        cut: OriginalCellQ24MaterialCommandReceiptV1,
        started_at: u64,
    ) -> Result<Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>, Error> {
        let source_config = OriginalCellQ24TrainingSourceConfigV1 {
            dataset: cut.snapshot().clone(),
            scope: self.config.material.scope.clone(), rule: self.config.material.rule,
            optimizer: self.config.optimizer,
            freeze_plan: self.config.material.freeze_plan.clone(),
            freeze_evidence: self.config.material.freeze_evidence.clone(),
            experience_evidence: cut.attestations()[0].clone(),
            dataset_evidence: cut.attestations()[1].clone(),
            verifier: self.config.material.verifier.clone(),
        };
        let OriginalCellQ24TrainingBootstrapCustodyV1 {
            native_file, native_witness, receipt_file, receipt_witness,
            generator_key, baseline, material_source, experience, dataset,
        } = custody;
        let material = OriginalCellQ24MaterialSourceConnectionV1::bind_original_dataset(
            material_source, source_config.clone(),
        )?;
        let source = capture_original_remote_cell_q24_training_source_v1(
            OriginalCellQ24RemoteTrainingSourceOwnersV1 { material, baseline, experience, dataset },
            source_config,
        ).await?;
        self.require_fresh_cut(&cut, started_at)?;
        let signing = OriginalCellQ24TrainingSigningConfigV1 {
            dataset: context.dataset.clone(), scope: context.scope.clone(),
            signer: self.config.generator.clone(), verifier: context.verifier.clone(),
            maximum_signature_lifetime_seconds: self.config.maximum_signature_lifetime_seconds,
        };
        let origin = self.origin;
        let original_dataset = Arc::clone(&self.dataset);
        let material_config = self.config.material.clone();
        let original_cut = cut.clone();
        let (native, receipts) = tokio::task::spawn_blocking(move || {
            // Queueing the blocking lane may take time. Check the exact retained
            // signatures and registered Generator again before writer creation.
            let at = OriginalCellQ24DatasetCommandReadbackV1::verify_original_cut(
                &original_dataset, &original_cut,
            )?;
            OriginalCellQ24DatasetCommandReadbackV1::require_initial_context(
                &original_dataset, &material_config,
            )?;
            if at < started_at || matches!(origin, Origin::Fresh)
                && at >= material_config.initial.request.envelope.expiry_unix_seconds
            {
                return Err(Error::Binding("Trainer writer bootstrap clock or deadline"));
            }
            signing.verifier.require_signer_binding(
                LearningEvidenceRoleV1::Generator, &signing.signer, at,
            ).map_err(OriginalCellQ24TrainingCommandErrorV1::from)?;
            let native = match origin {
                Origin::Fresh => CellQ24TrainingOwnerV1::create_from_original_source(
                    native_file, native_witness, source,
                )?,
                Origin::Recovered => CellQ24TrainingOwnerV1::recover_from_original_source(
                    native_file, native_witness, source,
                )?,
            };
            let receipts = match origin {
                Origin::Fresh => OriginalCellQ24TrainingReceiptOwnerV1::create(
                    receipt_file, receipt_witness, signing, generator_key,
                )?,
                Origin::Recovered => OriginalCellQ24TrainingReceiptOwnerV1::recover(
                    receipt_file, receipt_witness, signing, generator_key,
                )?,
            };
            Ok::<_, Error>((native, receipts))
        }).await.map_err(|_| Error::Uncertain)??;
        let original = OriginalCellQ24TrainingStageV1::from_original_owners(native, receipts).await?;
        let stage = Arc::new(SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?);
        let owner = match self.origin {
            Origin::Fresh => OriginalCellQ24TrainingCommandOwnerV1::from_original_stage(
                stage, context, Arc::clone(&self.cancellation),
            ).await?,
            Origin::Recovered => OriginalCellQ24TrainingCommandOwnerV1::recover_original_stage(
                stage, context, Arc::clone(&self.cancellation),
            ).await?,
        };
        self.require_fresh_cut(&cut, started_at)?;
        Ok(Arc::new(owner))
    }
}
