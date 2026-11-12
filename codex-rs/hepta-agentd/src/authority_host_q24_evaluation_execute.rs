//! Original native execution and qualification. Only actual native receipts
//! reach the signing journals; uncertainty is never an ineligible decision.

use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::AuthorityPosture;

use super::super::outputs::OriginalBResultMode;
use super::super::provider::OriginalBProvider;
use super::*;
use crate::CellEvaluationQualificationRequestV1;
use crate::learning_owner_evidence;

impl OriginalBExecution {
    pub(in super::super) fn perform(
        &mut self,
        files: &OriginalBInputs,
        enrollment: &mut OriginalBEnrollment,
        training: &LearningIterationSnapshotV1,
        training_attestation: &SignedLearningEvidenceV1,
        protocol: &OriginalBProtocolData,
        authorities: &OriginalBAuthorities,
        clock: &dyn Fn() -> io::Result<u64>,
        mode: OriginalBResultMode,
    ) -> io::Result<OriginalBCompleted> {
        let original_training = training
            .receipts
            .last()
            .filter(|receipt| receipt.observation.stage() == LearningIterationStageV1::Training)
            .ok_or_else(|| io::Error::other("original B Training predecessor is absent"))?;
        let training_payload = learning_iteration_receipt_signing_bytes_v1(original_training)
            .map_err(io::Error::other)?;
        let generator = authorities
            .verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                training_attestation,
                &training_payload,
                clock()?,
            )
            .map_err(io::Error::other)?;
        if generator.principal() != &authorities.generator.principal
            || generator.controller_id() != &authorities.generator.controller_id
            || original_training.actor_id != training.owners.trainer
        {
            return Err(io::Error::other("original B Trainer authority differs"));
        }
        let training_bytes =
            learning_owner_evidence::encode(&training_payload, training_attestation)
                .map_err(io::Error::other)?;
        if enrollment
            .original_training_attestation
            .as_ref()
            .is_some_and(|old| old != &training_bytes)
        {
            return Err(io::Error::other("original B Training attestation changed"));
        }
        let generator_plan = authorities.require_statement(
            &files.realized_plan_statement,
            LearningEvidenceRoleV1::Generator,
            self.plan.product_plan().frozen_plan.plan_digest.as_array(),
            clock()?,
        )?;
        let plan_bytes = learning_owner_evidence::encode(
            self.plan.product_plan().frozen_plan.plan_digest.as_array(),
            &generator_plan,
        )
        .map_err(io::Error::other)?;
        let plan_statement = Digest32::of_bytes(&plan_bytes);
        if enrollment
            .realized_plan_statement
            .is_some_and(|old| old != plan_statement.into_array())
        {
            return Err(io::Error::other("original B plan signature changed"));
        }
        files
            .realized_plan_statement
            .require_digest(plan_statement, 65_536)?;
        if let Some(released) = &enrollment.released_source {
            released.require_original(files)?;
        }
        self.observers
            .require_original_plan(&self.plan)
            .map_err(io::Error::other)?;
        let now = || clock().map_err(|_| ProductProviderErrorV1::Indeterminate);
        let request = ProductEvaluationExecutionRequestV1 {
            plan: self.plan.product_plan(),
            candidate_plan: &self.candidate_plan,
            baseline_plan: &self.baseline_plan,
            evaluator: &authorities.evaluator.principal,
            verifier: &authorities.verifier,
            clock: &now,
        };
        let execution = match mode {
            OriginalBResultMode::Complete => {
                if enrollment.completed_receipt.is_some() || enrollment.released_source.is_some() {
                    return Err(io::Error::other("original B completion must use readback"));
                }
                let admitted = enrollment.admitted_source.as_ref().ok_or_else(|| {
                    io::Error::other("original independent B signed source has not been admitted")
                })?;
                admitted.require_original(files)?;
                let mut provider = OriginalBProvider::new(
                    files,
                    authorities,
                    &self.plan,
                    Digest32::from_array(enrollment.namespace),
                    protocol.unit_profile(),
                    enrollment.registered_at_seconds,
                    clock,
                    admitted,
                );
                let execution = self
                    .observers
                    .evaluate_original(
                        &mut self.runner,
                        &self.plan,
                        &request,
                        &mut provider,
                        &mut self.executions,
                        &mut self.attestor,
                    )
                    .map_err(io::Error::other)?;
                enrollment.released_source = Some(provider.into_original_release()?);
                execution
            }
            OriginalBResultMode::Readback => {
                if enrollment.completed_receipt.is_none() || enrollment.released_source.is_none() {
                    return Err(io::Error::other(
                        "original B completion is absent or uncertain",
                    ));
                }
                self.observers
                    .read_original_execution(
                        &mut self.runner,
                        &self.plan,
                        &request,
                        &mut self.executions,
                    )
                    .map_err(io::Error::other)?
            }
        };
        let context = protocol.qualification_context(authorities);
        let bundle = self
            .runner
            .qualification_bundle(&execution, &context)
            .map_err(io::Error::other)?;
        let payload =
            evaluation_signing_payload_v2(&bundle, &self.plan.product_plan().metric_roles)
                .map_err(io::Error::other)?;
        let issued_at = clock()?;
        let expires_at = issued_at
            .checked_add(files.maximum_signature_lifetime_seconds)
            .ok_or_else(|| io::Error::other("original B signature end overflow"))?
            .min(enrollment.expires_at_seconds);
        let evaluator_bundle = self.qualification.original_signature(
            &payload,
            authorities,
            &self.signing,
            issued_at,
            expires_at,
            mode,
        )?;
        let evidence = SignedEvaluationEvidenceV1 {
            generator_plan,
            evaluator_bundle,
        };
        let verified_at = clock()?;
        let qualification = self
            .runner
            .qualify_and_persist(
                &execution,
                CellEvaluationQualificationRequestV1 {
                    context: &context,
                    evidence: &evidence,
                    timing: ProductTimingEvidenceV1::Qualification,
                    verifier: &authorities.verifier,
                    now: verified_at,
                },
                &mut OriginalBSink {
                    journal: &mut self.publication,
                    execution: execution.temporal().execution_digest,
                    mode,
                },
            )
            .map_err(io::Error::other)?;
        let prepare = |now| {
            crate::prepare_cell_learning_evaluation_v1(
                &self.runner,
                training,
                &execution,
                &qualification,
                &CellEvaluationQualificationRequestV1 {
                    context: &context,
                    evidence: &evidence,
                    timing: ProductTimingEvidenceV1::Qualification,
                    verifier: &authorities.verifier,
                    now,
                },
            )
            .map_err(io::Error::other)
        };
        let receipt = prepare(verified_at)?;
        let receipt_payload =
            learning_iteration_receipt_signing_bytes_v1(&receipt).map_err(io::Error::other)?;
        let attestation = self.receipt.original_signature(
            &receipt_payload,
            authorities,
            &self.signing,
            clock()?,
            expires_at,
            mode,
        )?;
        let verified_at = clock()?;
        let evaluator = authorities
            .verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &attestation,
                &receipt_payload,
                verified_at,
            )
            .map_err(io::Error::other)?;
        let generator = authorities
            .verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                training_attestation,
                &training_payload,
                verified_at,
            )
            .map_err(io::Error::other)?;
        verify_signed_actor_separation(&generator, &evaluator, verified_at)
            .map_err(io::Error::other)?;
        if prepare(verified_at)? != receipt {
            return Err(io::Error::other(
                "original B qualification changed after signing",
            ));
        }
        self.observers
            .require_original_plan(&self.plan)
            .map_err(io::Error::other)?;
        files
            .realized_plan_statement
            .require_digest(plan_statement, 65_536)?;
        enrollment
            .released_source
            .as_ref()
            .ok_or_else(|| io::Error::other("original B release absent"))?
            .require_original(files)?;
        enrollment.realized_training_head = Some(training.head_digest.into_array());
        enrollment.realized_plan = Some(
            self.plan
                .product_plan()
                .frozen_plan
                .plan_digest
                .into_array(),
        );
        enrollment.realized_plan_statement = Some(plan_statement.into_array());
        enrollment.original_training_attestation = Some(training_bytes);
        let receipt_digest = Digest32::of_bytes(&receipt_payload);
        if enrollment
            .completed_receipt
            .is_some_and(|old| old != receipt_digest.into_array())
        {
            return Err(io::Error::other("original B receipt changed"));
        }
        enrollment.completed_receipt = Some(receipt_digest.into_array());
        enrollment.heads = Some(self.original_heads(Digest32::from_array(enrollment.namespace))?);
        enrollment.output_images = self.output_images(files)?;
        files.require_original_files()?;
        Ok(OriginalBCompleted {
            training: training.clone(),
            training_attestation: training_attestation.clone(),
            execution,
            qualification,
            context,
            evidence,
            receipt,
            attestation,
            verified_at,
        })
    }
}

struct OriginalBSink<'a> {
    journal: &'a mut OriginalBJournal,
    execution: Digest32,
    mode: OriginalBResultMode,
}

impl ProductQualificationEvidenceSinkV1 for OriginalBSink<'_> {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        if execution != self.execution
            || execution.is_zero()
            || decision.authentication_digest.is_zero()
            || decision.decision.evidence_digest.is_zero()
            || decision.decision.authority != AuthorityPosture::DENY_ALL
        {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        let bytes = [
            b"hepta.root.independent-b.qualification-publication.v1\0".as_slice(),
            execution.as_array(),
            decision.authentication_digest.as_array(),
            decision.trust_digest.as_array(),
            decision.decision.evidence_digest.as_array(),
        ]
        .concat();
        self.journal
            .original_bytes(&bytes, self.mode)
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        Ok(Digest32::of_bytes(&bytes))
    }
}
