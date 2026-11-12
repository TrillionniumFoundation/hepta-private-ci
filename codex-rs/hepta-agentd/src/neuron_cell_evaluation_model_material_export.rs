//! Read only the original completed Evaluator/Panel, then export original
//! commitment bytes. No sink, provider release, signer or claim is reachable.
use codex_hepta_intelligence_eval::OriginalProductEvaluationExecutionEvidenceV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::Owners;
use super::super::TrainingOperation;
use super::super::TrainingRead;
use super::super::contract::Context;
use super::super::require_clock;
use super::Error;
use super::OriginalCellEvaluationModelMaterialV1;
use super::Receipt;
use crate::OriginalCellEvaluationPanelReadbackV1;
use super::codec::Body;
use super::codec::Member;
use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationRunnerV1;
use crate::OriginalCellEvaluationPanelMemberOwnersV1;
use crate::OriginalCellEvaluationPanelMemberReadbackV1;
use crate::OriginalCellEvaluationCohortCustodyV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use crate::learning_owner_evidence;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;

struct PendingExport {
    bytes: Vec<u8>,
    evaluation: Receipt,
    panel: OriginalCellEvaluationPanelReadbackV1,
    started_at: u64,
}
struct Exported {
    bytes: Vec<u8>,
    evaluation: Receipt,
    observed_at: u64,
}

impl Owners {
    /// A private single-channel transfer owns this real observation until its
    /// Finish. The original Owners remain fenced across all network/effects;
    /// no Owners mutex or native Trainer lane is held between frames.
    pub(super) async fn begin_model_material_transfer(
        &mut self,
        context: &Context,
    ) -> Result<(Vec<u8>, Option<TrainingOperation>), Error> {
        if self.fenced { return Err(Error::CommitUncertain); }
        self.fenced = true;
        let started_at = self.current_time()?;
        context.authenticate(started_at)?;
        let operation = self.begin_training_operation(context).await?;
        let training = match operation.as_ref() {
            Some(original) => TrainingRead::Operation(original),
            None => TrainingRead::Independent,
        };
        let pending = self.read_model_material_export(context, training).await?;
        // First export still has the complete physical Panel and both E
        // journal observations. Its bytes are provisional until actual Finish.
        let exported = self.finish_model_material_export(context, pending)?;
        Ok((exported.bytes, operation))
    }

    pub(super) async fn finish_model_material_transfer(
        &mut self,
        context: &Context,
        operation: Option<TrainingOperation>,
        expected: &[u8],
    ) -> Result<OriginalCellEvaluationModelMaterialV1, Error> {
        if !self.fenced { return Err(Error::CommitUncertain); }
        match (&operation, &self.shared_training) {
            (Some(original), Some(trainer)) => TrainingOperation::require_member(
                original, trainer, &self.panel.primary.qualification.config,
            )?,
            (None, None) => {},
            _ => return Err(Error::Binding("same original transfer Training profile")),
        }
        let training = match operation.as_ref() {
            Some(original) => TrainingRead::Operation(original),
            None => TrainingRead::Independent,
        };
        // Every original Cell/Product/Qualification/cohort journal is really
        // read again. The earlier body is never used as a CURRENT observation.
        let pending = self.read_model_material_export(context, training).await?;
        if let Some(original) = operation {
            TrainingOperation::finish(original).await?;
        }
        // The final physical E journal read and full nested fresh validation
        // follow the last actual T I/O, before any completion can be encoded.
        let exported = self.finish_model_material_export(context, pending)?;
        if exported.bytes.as_slice() != expected { return Err(Error::CommitUncertain); }
        let binding = Digest32::of_bytes(&exported.bytes);
        Ok(OriginalCellEvaluationModelMaterialV1 {
            context: context.clone(),
            evaluation: exported.evaluation,
            bytes: exported.bytes,
            binding,
            observed_at: exported.observed_at,
        })
    }

    async fn read_model_material_export(
        &mut self,
        context: &Context,
        training: TrainingRead<'_>,
    ) -> Result<PendingExport, Error> {
        let started_at = self.current_time()?;
        context.authenticate(started_at)?;
        let (evaluation, observed) = self
            .read_original_completion(context, super::super::wire::Action::Readback, training)
            .await?;
        let mut members = Vec::with_capacity(observed.retention().len() + 1);
        members.push(member(
            &self.panel.primary,
            observed.primary(),
            self.panel.bindings[0],
            started_at,
        )?);
        for ((owner, observed), binding) in self
            .panel
            .retention
            .iter()
            .zip(observed.retention())
            .zip(self.panel.bindings.iter().skip(1))
        {
            members.push(member(owner, observed, *binding, started_at)?);
        }
        let body = Body {
            context: super::wire::binding(context, &evaluation, started_at)?,
            panel: observed.binding(),
            snapshot: encode_original_owner_snapshot_v1(evaluation.snapshot())?,
            evaluation: learning_owner_evidence::encode(
                &learning_iteration_receipt_signing_bytes_v1(evaluation.receipt())?,
                evaluation.attestation(),
            )?,
            members,
        };
        let bytes = body.encode()?;
        // Full original snapshots remain bracketed by actual complete Panel
        // observations, with independent B and every nonempty retention member.
        let after = self.read_panel(training).await?;
        if after != observed { return Err(Error::CommitUncertain); }
        Ok(PendingExport {
            bytes, evaluation, panel: after, started_at,
        })
    }

    fn finish_model_material_export(
        &mut self,
        context: &Context,
        pending: PendingExport,
    ) -> Result<Exported, Error> {
        let PendingExport { bytes, evaluation, panel, started_at } = pending;
        let evaluation = self.finish_original_completion(
            context,
            super::super::wire::Action::Readback,
            evaluation,
            &panel,
            started_at,
        )?;
        let current = self.current_time()?;
        require_clock(started_at, current)?;
        self.authenticate_panel(&panel, current)?;
        super::verify::material(context, &evaluation, &bytes, current)?;
        Ok(Exported { bytes, evaluation, observed_at: current })
    }
}

fn member(
    owner: &OriginalCellEvaluationPanelMemberOwnersV1<
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
    >,
    observed: &OriginalCellEvaluationPanelMemberReadbackV1,
    binding: Digest32,
    current: u64,
) -> Result<Member, Error> {
    let config = &owner.qualification.config;
    let projection = CellEvaluationRunnerV1::original_model_commitments(
        &owner.runner,
        observed.evaluation(),
        observed.qualification(),
        &CellEvaluationQualificationRequestV1 {
            context: &config.context,
            evidence: &config.product_evidence,
            timing: ProductTimingEvidenceV1::Qualification,
            verifier: &config.verifier,
            now: current,
        },
    )
    .map_err(crate::OriginalCellEvaluationQualificationErrorV1::from)?;
    let (cohort, freeze_payload, freeze_evidence) =
        OriginalCellEvaluationCohortCustodyV1::original_model_commitment(
            &owner.cohort,
            &observed.cohort,
        )
        .map_err(crate::OriginalCellEvaluationPanelErrorV1::from)?;
    let execution: &OriginalProductEvaluationExecutionEvidenceV1 = observed.execution_evidence();
    let snapshots = [
        owner
            .candidate
            .snapshot()
            .map_err(crate::OriginalCellEvaluationPanelErrorV1::from)?,
        owner
            .fixed_expert
            .snapshot()
            .map_err(crate::OriginalCellEvaluationPanelErrorV1::from)?,
    ];
    let record = observed.qualification().comparison();
    for ((snapshot, arm), scope) in snapshots
        .iter()
        .zip([&record.candidate, &record.fixed_expert])
        .zip(&observed.scopes)
    {
        if snapshot
            .digest()
            .map_err(crate::OriginalCellEvaluationPanelErrorV1::from)?
            != arm.snapshot_digest
            || snapshot.manifest_digest
                != arm
                    .manifest
                    .digest()
                    .map_err(crate::OriginalCellEvaluationPanelErrorV1::from)?
            || &snapshot.scope != scope
        {
            return Err(Error::Binding("same original recorded Cell snapshot"));
        }
    }
    Ok(Member {
        binding,
        execution_namespace: config.execution_namespace,
        qualification_namespace: config.qualification_namespace,
        metrics: u32::try_from(observed.prepared.bundle.metrics.len())
            .map_err(|_| Error::Binding("original metric count"))?,
        record: serde_json::to_vec(observed.qualification().comparison())?,
        snapshots: serde_json::to_vec(&snapshots)?,
        holdout: projection.holdout().to_vec(),
        plan: projection.plan().to_vec(),
        request: projection.request().to_vec(),
        decision: projection.decision().to_vec(),
        qualification: projection.qualification().to_vec(),
        estimand: projection.estimand().to_vec(),
        roles: projection.roles().to_vec(),
        generator: learning_owner_evidence::encode(
            config
                .plan
                .product_plan()
                .frozen_plan
                .plan_digest
                .as_array(),
            &observed.product_evidence().generator_plan,
        )?,
        evaluator: learning_owner_evidence::encode(
            projection.evaluator_payload(),
            &observed.product_evidence().evaluator_bundle,
        )?,
        execution: learning_owner_evidence::encode(
            OriginalProductEvaluationExecutionEvidenceV1::signing_payload(execution),
            execution.attestation(),
        )?,
        execution_record: OriginalProductEvaluationExecutionEvidenceV1::original_record(execution)
            .to_vec(),
        cohort,
        freeze: learning_owner_evidence::encode(&freeze_payload, &freeze_evidence)?,
    })
}
