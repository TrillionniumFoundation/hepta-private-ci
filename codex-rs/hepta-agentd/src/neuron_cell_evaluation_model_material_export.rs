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
use super::codec::Body;
use super::codec::Member;
use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationRunnerV1;
use crate::OriginalCellEvaluationPanelMemberOwnersV1;
use crate::OriginalCellEvaluationPanelMemberReadbackV1;
use crate::OriginalCircuitEvaluationCohortReadbackV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use crate::learning_owner_evidence;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;

impl Owners {
    pub(super) async fn original_model_material(
        &mut self,
        context: &Context,
    ) -> Result<Vec<u8>, Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        let result = self.read_original_model_material(context).await;
        self.fence_result(result)
    }

    async fn read_original_model_material(
        &mut self,
        context: &Context,
    ) -> Result<Vec<u8>, Error> {
        let started_at = self.current_time()?;
        context.authenticate(started_at)?;
        let operation = self.begin_training_operation(context).await?;
        let training = match operation.as_ref() {
            Some(original) => TrainingRead::Operation(original),
            None => TrainingRead::Independent,
        };
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
        // The complete original snapshots were read between two actual Panel
        // CURRENT observations. Neither a cached scope nor its unsigned digest
        // can substitute for the snapshot committed by the signed arm record.
        let after = self.read_panel(training).await?;
        if after != observed {
            return Err(Error::CommitUncertain);
        }
        if let Some(original) = operation {
            TrainingOperation::finish(original).await?;
        }
        let evaluation = self.finish_original_completion(
            context,
            super::super::wire::Action::Readback,
            evaluation,
            &after,
            started_at,
        )?;
        let current = self.current_time()?;
        require_clock(started_at, current)?;
        self.authenticate_panel(&after, current)?;
        // Revalidate every complete original payload after all actual I/O and
        // projection work. These checks do not construct or deserialize seals.
        super::verify::material(context, &evaluation, &bytes, current)?;
        Ok(bytes)
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
        OriginalCircuitEvaluationCohortReadbackV1::original_model_commitment(
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
