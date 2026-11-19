//! First B admission: actual Training signature, native candidate/baseline
//! execution, complete frozen cost plan, then a current Root challenge. No
//! heldout labels or outcome rows are read by this phase.

use super::super::admission::OriginalBAuthorities;
use super::super::benchmark;
use super::*;
use crate::learning_owner_evidence;
use crate::neuron_cell_evaluation::OriginalCellEvaluationObserversV1;
use crate::root_independent_b_candidate_notice::CandidateNotice;
use crate::root_independent_b_protocol::PreparedPlanData;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;

impl OriginalRootIndependentBEvaluationFilesV1 {
    pub(in super::super) fn prepare_original_candidate<T>(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        frame_end: Instant,
        training_head: Digest32,
        attestation: &SignedLearningEvidenceV1,
        training_work: &crate::cell_composed_q24::OriginalQ24TrainingWorkDataV1,
        action: impl FnOnce(PreparedPlanData) -> io::Result<T>,
    ) -> io::Result<(T, CandidateNotice)> {
        let end = self.end.min(frame_end);
        // Keep both real SH locks through the durable Ready CAS, not just the
        // inner Root callback. No native borrow can release these descriptors.
        let mut cell_locks = None;
        OriginalBRecord::inspect(&self.record, end, |enrollment| {
            let mut state = self
                .state
                .try_lock()
                .map_err(|_| io::Error::other("original B native owners busy"))?;
            let files = &mut state.files;
            let (value, notice, training, protocol, authorities, saved_plan) = service
                .with_learning_profile(
                    config,
                    registration,
                    owner,
                    &self.profile,
                    |actual, _proof| {
                        owner_alive(owner, end)?;
                        if actual != self.initial
                            || self.backend.frozen_scope_binding()
                                != Some(self.profile.require_cell_scope(&actual)?.binding())
                        {
                            return Err(io::Error::other("original B learning context differs"));
                        }
                        let scope = self.profile.require_cell_scope(&actual)?;
                        let training = self
                            .backend
                            .restore(&actual.request)
                            .map_err(io::Error::other)?
                            .ok_or_else(|| {
                                io::Error::other("original Training checkpoint absent")
                            })?;
                        scope
                            .validate_snapshot(&training)
                            .map_err(io::Error::other)?;
                        if training_prefix(&training)? != training
                            || training.head_digest != training_head
                            || training.request != actual.request
                            || training.owners != actual.owners
                        {
                            return Err(io::Error::other(
                                "B preparation requires the actual current Training cut",
                            ));
                        }
                        let now = service.original_learning_unix_seconds()?;
                        require_files(files, enrollment, now)?;
                        let (protocol, authorities) = files.admitted_protocol(&actual, now)?;
                        let signed = require_training(&authorities, &training, attestation, now)?;
                        if enrollment
                            .original_training_attestation
                            .as_ref()
                            .is_some_and(|old| old != &signed)
                            || enrollment
                                .realized_training_head
                                .is_some_and(|old| old != training_head.into_array())
                        {
                            return Err(io::Error::other("original B Training signature changed"));
                        }
                        if enrollment
                            .original_training_work
                            .as_ref()
                            .is_some_and(|old| old != training_work)
                        {
                            return Err(io::Error::other("original native Training work changed"));
                        }
                        enrollment.original_training_work = Some(training_work.clone());
                        benchmark::prepare_original_cells(
                            files, enrollment, &training, &protocol, end,
                        )?;
                        cell_locks = Some((
                            files.candidate.lock_original()?,
                            files.fixed_expert.lock_original()?,
                        ));
                        let observers = OriginalCellEvaluationObserversV1::from_original_observers(
                            files.candidate.observer()?,
                            files.candidate.manifest().clone(),
                            files.fixed_expert.observer()?,
                            files.fixed_expert.manifest().clone(),
                        )
                        .map_err(io::Error::other)?;
                        let actual_work =
                            benchmark::read_original_b_training_work(files, enrollment, &training)?;
                        let (comparison, candidate_temporal, baseline_temporal) =
                            protocol.plans(&training, &actual_work)?;
                        let plan = observers
                            .freeze_original_learning_plan(
                                comparison,
                                &candidate_temporal,
                                &baseline_temporal,
                                training.request.evaluation_profile,
                            )
                            .map_err(io::Error::other)?;
                        let plan_digest = plan.product_plan().frozen_plan.plan_digest;
                        if enrollment
                            .realized_plan
                            .is_some_and(|old| old != plan_digest.into_array())
                        {
                            return Err(io::Error::other("original B frozen plan changed"));
                        }
                        let data = PreparedPlanData {
                            initial: actual.head_digest.to_string(),
                            scope: scope.binding().to_string(),
                            training_head: training_head.to_string(),
                            candidate_bundle: Digest32::from_array(
                                plan.record().candidate.manifest.bundle_digest,
                            )
                            .to_string(),
                            profile: training.request.evaluation_profile.to_string(),
                            plan_digest: plan_digest.to_string(),
                            comparison_digest: Digest32::of_bytes(
                                &serde_json::to_vec(plan.record()).map_err(io::Error::other)?,
                            )
                            .to_string(),
                            expires_at_seconds: enrollment.expires_at_seconds,
                            training_work_digest: training_work
                                .digest()
                                .map_err(io::Error::other)?
                                .to_string(),
                        };
                        let notice = CandidateNotice::from_original_training(
                            self.original_binding(),
                            &training,
                            data.clone(),
                            enrollment.registered_at_seconds,
                        )?;
                        if let Some(source) = &enrollment.admitted_source {
                            source.require_original(files)?;
                        }
                        let value = action(data);
                        observers
                            .require_original_plan(&plan)
                            .map_err(io::Error::other)?;
                        benchmark::require_original_cells(files, enrollment, &training, &protocol)?;
                        if self
                            .backend
                            .restore(&actual.request)
                            .map_err(io::Error::other)?
                            .as_ref()
                            != Some(&training)
                        {
                            return Err(io::Error::other(
                                "original Training cut changed during B preparation",
                            ));
                        }
                        enrollment.realized_training_head = Some(training_head.into_array());
                        enrollment.realized_plan = Some(plan_digest.into_array());
                        enrollment.original_training_attestation = Some(signed);
                        Ok((value?, notice, training, protocol, authorities, plan))
                    },
                )?;
            owner_alive(owner, end)?;
            let now = service.original_learning_unix_seconds()?;
            require_files(files, enrollment, now)?;
            require_training(&authorities, &training, attestation, now)?;
            benchmark::require_original_cells(files, enrollment, &training, &protocol)?;
            let observers = OriginalCellEvaluationObserversV1::from_original_observers(
                files.candidate.observer()?,
                files.candidate.manifest().clone(),
                files.fixed_expert.observer()?,
                files.fixed_expert.manifest().clone(),
            )
            .map_err(io::Error::other)?;
            observers
                .require_original_plan(&saved_plan)
                .map_err(io::Error::other)?;
            if self
                .backend
                .restore(&self.initial.request)
                .map_err(io::Error::other)?
                .as_ref()
                != Some(&training)
                || cell_locks.is_none()
            {
                return Err(io::Error::other("original B postcontext differs"));
            }
            owner_alive(owner, end)?;
            if let Some(source) = &enrollment.admitted_source {
                source.require_original(files)?;
            }
            Ok((value, notice))
        })
    }
}

pub(super) fn require_training(
    authorities: &OriginalBAuthorities,
    training: &LearningIterationSnapshotV1,
    attestation: &SignedLearningEvidenceV1,
    now: u64,
) -> io::Result<Vec<u8>> {
    let receipt = training
        .receipts
        .last()
        .filter(|r| r.observation.stage() == LearningIterationStageV1::Training)
        .ok_or_else(|| io::Error::other("original Training receipt missing"))?;
    let payload = learning_iteration_receipt_signing_bytes_v1(receipt).map_err(io::Error::other)?;
    let generator = authorities
        .verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            attestation,
            &payload,
            now,
        )
        .map_err(io::Error::other)?;
    if generator.principal() != &authorities.generator.principal
        || generator.controller_id() != &authorities.generator.controller_id
        || receipt.actor_id != training.owners.trainer
    {
        return Err(io::Error::other("original B Generator differs"));
    }
    learning_owner_evidence::encode(&payload, attestation).map_err(io::Error::other)
}

pub(super) fn retain_original_plan_statement(
    files: &OriginalBInputs,
    enrollment: &OriginalBEnrollment,
    training: &LearningIterationSnapshotV1,
    authorities: &OriginalBAuthorities,
    statement: &SignedLearningEvidenceV1,
    now: u64,
) -> io::Result<()> {
    let plan = enrollment
        .realized_plan
        .ok_or_else(|| io::Error::other("original B plan was not prepared"))?;
    if enrollment.realized_training_head != Some(training.head_digest.into_array())
        || enrollment.cell_images.is_none()
    {
        return Err(io::Error::other("original B candidate preparation differs"));
    }
    let generator = authorities
        .verifier
        .verify(LearningEvidenceRoleV1::Generator, statement, &plan, now)
        .map_err(io::Error::other)?;
    if generator.principal() != &authorities.generator.principal
        || generator.controller_id() != &authorities.generator.controller_id
    {
        return Err(io::Error::other("original B plan Generator differs"));
    }
    let bytes = learning_owner_evidence::encode(&plan, statement).map_err(io::Error::other)?;
    let digest = Digest32::of_bytes(&bytes);
    if enrollment
        .realized_plan_statement
        .is_some_and(|old| old != digest.into_array())
    {
        return Err(io::Error::other("original B plan signature changed"));
    }
    files
        .realized_plan_statement
        .write_original_plan_once(&bytes)?;
    files
        .realized_plan_statement
        .require_digest(digest, 65_536)?;
    Ok(())
}
