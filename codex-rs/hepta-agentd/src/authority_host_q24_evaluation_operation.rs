//! One original Root operation, including a synchronous Model callback. The
//! learning backend is the same Arc captured from actual registration. A wire
//! signature is only data until verified against that backend's Training cut.

use super::super::outputs::OriginalBResultMode;
use super::*;
use crate::learning_owner_evidence;

enum Operation<'a> {
    Complete {
        training: &'a SignedLearningEvidenceV1,
        plan: &'a SignedLearningEvidenceV1,
    },
    Readback,
}

impl OriginalRootIndependentBEvaluationFilesV1 {
    pub(crate) fn complete_from_original_training<T>(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        frame_end: Instant,
        training_head: Digest32,
        attestation: &SignedLearningEvidenceV1,
        plan_attestation: &SignedLearningEvidenceV1,
        action: impl for<'a> FnOnce(OriginalRootBEvaluationBorrowV1<'a>) -> io::Result<T>,
    ) -> io::Result<T> {
        self.with_operation(
            service,
            config,
            registration,
            owner,
            frame_end,
            training_head,
            Operation::Complete {
                training: attestation,
                plan: plan_attestation,
            },
            action,
        )
    }

    pub(crate) fn with_original_completed_evaluation<T>(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        frame_end: Instant,
        training_head: Digest32,
        action: impl for<'a> FnOnce(OriginalRootBEvaluationBorrowV1<'a>) -> io::Result<T>,
    ) -> io::Result<T> {
        self.with_operation(
            service,
            config,
            registration,
            owner,
            frame_end,
            training_head,
            Operation::Readback,
            action,
        )
    }

    fn with_operation<T>(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        frame_end: Instant,
        training_head: Digest32,
        operation: Operation<'_>,
        action: impl for<'a> FnOnce(OriginalRootBEvaluationBorrowV1<'a>) -> io::Result<T>,
    ) -> io::Result<T> {
        let end = self.end.min(frame_end);
        let mut cell_locks = None;
        self.record.inspect(end, |enrollment| {
            let mut state = self.state.try_lock().map_err(|_| io::Error::other("original B native owners are busy"))?;
            let OriginalBState { files, execution } = &mut *state;
            // Retained outside the callback, through the Root postchecks and
            // final physical readback; no borrowed observer can release them.
            let (value, completed, before, authorities) = service.with_learning_profile(
                config, registration, owner, &self.profile, |actual, proof| {
                    owner_alive(owner, end)?;
                    if actual != self.initial || self.backend.frozen_scope_binding()
                        != Some(self.profile.require_cell_scope(&actual)?.binding())
                    { return Err(io::Error::other("original B learning capability changed")); }
                    let scope = self.profile.require_cell_scope(&actual)?;
                    let before = self.backend.restore(&actual.request).map_err(io::Error::other)?
                        .ok_or_else(|| io::Error::other("original Root learning checkpoint is vacant"))?;
                    scope.validate_snapshot(&before).map_err(io::Error::other)?;
                    let training = training_prefix(&before)?;
                    if training.head_digest != training_head || training.request != actual.request || training.owners != actual.owners {
                        return Err(io::Error::other("original B Training cut differs"));
                    }
                    let now = service.original_learning_unix_seconds()?;
                    require_files(files, enrollment, now)?;
                    let (protocol, authorities) = files.admitted_protocol(&actual, now)?;
                    super::super::benchmark::restore_original_cells(files, enrollment, &training, &protocol)?;
                    if let Operation::Complete { plan, .. } = &operation {
                        super::prepare::retain_original_plan_statement(files, enrollment, &training, &authorities, plan, now)?;
                    }
                    cell_locks = Some((files.candidate.lock_original()?, files.fixed_expert.lock_original()?));
                    let attestation = match &operation {
                        Operation::Complete { training: original, .. } => (*original).clone(),
                        Operation::Readback => {
                            let encoded = enrollment.original_training_attestation.as_ref()
                                .ok_or_else(|| io::Error::other("original B Training attestation was never retained"))?;
                            learning_owner_evidence::decode(encoded).map_err(io::Error::other)?.1
                        }
                    };
                    let mode = if enrollment.completed_receipt.is_some() {
                        OriginalBResultMode::Readback
                    } else {
                        if !matches!(operation, Operation::Complete { .. }) || before != training {
                            return Err(io::Error::other("original B first execution requires the current Training cut"));
                        }
                        OriginalBResultMode::Complete
                    };
                    if execution.is_none() {
                        *execution = Some(OriginalBExecution::open(files, enrollment, &training, &protocol, &authorities, now)?);
                    }
                    let native = execution.as_mut().ok_or_else(|| io::Error::other("original B native owners are absent"))?;
                    if let Some(heads) = &enrollment.heads {
                        if &native.original_heads(Digest32::from_array(enrollment.namespace))? != heads
                            || native.output_images(files)? != enrollment.output_images
                        { return Err(io::Error::other("original B retained output differs")); }
                    }
                    let clock = || service.original_learning_unix_seconds();
                    let completed = native.perform(files, enrollment, &training, &attestation, &protocol, &authorities, &clock, mode)?;
                    let value = action(OriginalRootBEvaluationBorrowV1 {
                        initial: &actual, writer_proof: &proof,
                        actual: native, completed: &completed, verifier: &authorities.verifier,
                        not_send: PhantomData,
                    });
                    // Re-read even when the trusted callback returned an error.
                    let after = native.perform(files, enrollment, &training, &attestation, &protocol, &authorities, &clock, OriginalBResultMode::Readback)?;
                    if after.receipt != completed.receipt || after.attestation != completed.attestation
                        || after.execution != completed.execution || after.qualification != completed.qualification
                        || self.backend.restore(&actual.request).map_err(io::Error::other)?.as_ref() != Some(&before)
                    { return Err(io::Error::other("original B changed across the synchronous Root callback")); }
                    Ok((value?, after, before, authorities))
                },
            )?;
            // These are deliberately after with_learning_profile has returned.
            owner_alive(owner, end)?;
            let now = service.original_learning_unix_seconds()?;
            require_files(files, enrollment, now)?;
            if self.backend.restore(&self.initial.request).map_err(io::Error::other)?.as_ref() != Some(&before) {
                return Err(io::Error::other("original Root checkpoint changed after B context"));
            }
            let native = execution.as_mut().ok_or_else(|| io::Error::other("original B owners disappeared"))?;
            native.observers.require_original_plan(&native.plan).map_err(io::Error::other)?;
            let (protocol, _) = files.admitted_protocol(&self.initial, now)?;
            super::super::benchmark::require_original_cells(files, enrollment, &completed.training, &protocol)?;
            if enrollment.heads.as_ref() != Some(&native.original_heads(Digest32::from_array(enrollment.namespace))?)
                || enrollment.output_images != native.output_images(files)?
            { return Err(io::Error::other("original B changed after Root context")); }
            enrollment.released_source.as_ref().ok_or_else(|| io::Error::other("original B release absent"))?.require_original(files)?;
            let training = completed.training.receipts.last().ok_or_else(|| io::Error::other("original Training receipt missing"))?;
            for (role, signed, receipt) in [
                (codex_hepta_learning_ledger::LearningEvidenceRoleV1::Generator, &completed.training_attestation, training),
                (codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator, &completed.attestation, &completed.receipt),
            ] {
                authorities.verifier.verify(role, signed,
                    &codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1(receipt).map_err(io::Error::other)?, now)
                    .map_err(io::Error::other)?;
            }
            if cell_locks.is_none() { return Err(io::Error::other("original B Cell locks were never acquired")); }
            owner_alive(owner, end)?;
            Ok(value)
        })
    }
}
