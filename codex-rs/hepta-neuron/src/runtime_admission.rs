//! Admission checks for the existing durable owner. A prepared operation is a
//! committed recovery obligation; current-use checks never rewrite its history.
use super::*;
use crate::AbstainReasonV1;
use crate::CalibrationExpiryPolicyV1;
use crate::CalibrationWindowDecisionV1;
use crate::DegradationReasonV1;
use crate::NeuronCommitDispositionV1;
use crate::SparseError;
use crate::sparse_tick;

/// Host-owned live checks. Implementations must use authenticated current owners
/// and enforce deadline/cancellation; a digest alone is not an admission grant.
pub trait NeuronAdmissionGuard {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronAdmissionError {
    Revoked,
    DeadlineExceeded,
    Cancelled,
    Unavailable,
    BindingMismatch,
}

struct MechanismOnly;
impl NeuronAdmissionGuard for MechanismOnly {
    fn check(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        _: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Ok(())
    }
}

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    /// Mechanism/qualification entry retaining the V1 state-advance/abstain
    /// policy. Product callers must use `tick_guarded`, not this legacy entry.
    pub fn tick(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        self.tick_with_policy(
            model,
            input,
            &mut MechanismOnly,
            CalibrationExpiryPolicyV1::StateAdvanceAbstainLegacy,
        )
    }

    /// Product entry: expired calibration and impossible fixed-size resource
    /// envelopes reject before model invocation and before any state mutation.
    /// Live admission is checked again before durable preparation and delivery.
    /// A historical result is reconciled before applying new-work-only checks;
    /// the original receipt is never recalibrated or rewritten on retry.
    pub fn tick_guarded(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        self.tick_with_policy(
            model,
            input,
            guard,
            CalibrationExpiryPolicyV1::RejectBeforeMutation,
        )
    }

    fn tick_with_policy(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
        expiry_policy: CalibrationExpiryPolicyV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        guard
            .check(&self.config, &input)
            .map_err(NeuronRuntimeError::Admission)?;
        self.validate_recovered_frontiers()?;
        let model_request = self.model_request(&input)?;
        let input_digest = model_request.input_digest;
        if let Some(stored) = self.operations.find_tick(&input.tick_id)? {
            if stored.input_digest != input_digest {
                return Err(NeuronRuntimeError::OperationConflict);
            }
            let output = self.reconcile_operation(stored)?;
            guard
                .check(&self.config, &input)
                .map_err(NeuronRuntimeError::Admission)?;
            return Ok(output);
        }
        if self.operations.pending()?.is_some() {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }

        self.journal.admit_new_tick(
            JournalScope {
                scope_digest: subject_scope_digest(&input.subject_id)?,
                objective_digest: input.objective_digest,
            },
            input.logical_sequence,
        )?;
        self.operations.admit_new_operation()?;
        let current = self.journal.current()?;
        let expected_checkpoint = current.map_or(Digest32::ZERO, SparseCheckpoint::digest);
        if input.checkpoint_digest != expected_checkpoint {
            return Err(NeuronRuntimeError::CheckpointMismatch);
        }
        let expected_anchor = current.map(|checkpoint| JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        });
        self.preflight_new_tick(&input, expiry_policy)?;
        self.witness.admit_new_anchor(expected_anchor)?;

        let started = Instant::now();
        let model_output = model.execute(&model_request)?;
        validate_model_output(&self.config, &model_output)?;
        let native_tick = SparseTick {
            scope_digest: subject_scope_digest(&input.subject_id)?,
            objective_digest: input.objective_digest,
            ndu_digest: input.ndu_snapshot_digest,
            body_digest: body_digest(&self.config, &input),
            input_digest,
            sequence: input.logical_sequence,
            monotonic_micros: input.monotonic_time_micros,
            drive_q24: model_output.drive_q24.clone(),
            prediction_q24: model_output.prediction_q24.clone(),
        };
        let (checkpoint, sparse_receipt) =
            sparse_tick(&self.native, &native_tick, self.journal.current()?)
                .map_err(JournalError::Mechanism)?;
        let output = self.build_output(
            &input.tick_id,
            &model_output,
            &checkpoint,
            &sparse_receipt,
            started,
        )?;
        let next_anchor = JournalAnchor {
            sequence: input.logical_sequence,
            checkpoint_digest: sparse_receipt.checkpoint_after,
        };
        let prepared = PreparedNeuronOperationV1::new(
            input_digest,
            input.tick_id.clone(),
            expected_anchor,
            next_anchor,
            native_tick,
            output,
        )?;
        guard
            .check(&self.config, &input)
            .map_err(NeuronRuntimeError::Admission)?;
        self.operations.prepare(prepared.clone())?;
        let output = self.reconcile_operation(prepared)?;
        guard
            .check(&self.config, &input)
            .map_err(NeuronRuntimeError::Admission)?;
        Ok(output)
    }

    fn preflight_new_tick(
        &self,
        input: &NeuronTickInputV1,
        expiry_policy: CalibrationExpiryPolicyV1,
    ) -> Result<(), NeuronRuntimeError> {
        if self.operations.latest()?.is_some_and(|previous| {
            input.monotonic_time_micros <= previous.sparse_tick.monotonic_micros
        }) {
            return Err(JournalError::Mechanism(SparseError::Clock).into());
        }
        let calibration = &self.config.calibration;
        let decision = expiry_policy
            .decide(
                input.logical_sequence,
                calibration.valid_from_sequence,
                calibration.expires_after_sequence,
            )
            .map_err(|_| NeuronRuntimeError::InvalidCalibration)?;
        if decision == CalibrationWindowDecisionV1::RejectNoUpdate {
            return Err(NeuronRuntimeError::CalibrationExpired);
        }
        if expiry_policy == CalibrationExpiryPolicyV1::RejectBeforeMutation {
            // V1 has five same-width vectors. This is the exact existing
            // bounded_encoded_bytes profile, not an estimate of model memory
            // or a claim about operation-WAL/witness physical amplification.
            let bound = 6 * std::mem::size_of::<Digest32>()
                + 7 * std::mem::size_of::<u64>()
                + 5 * self.config.state_width * std::mem::size_of::<i64>();
            let checkpoint_bytes =
                u64::try_from(bound).map_err(|_| NeuronRuntimeError::Arithmetic)?;
            let journal_bytes = u64::try_from(304 + 16 * self.config.state_width)
                .map_err(|_| NeuronRuntimeError::Arithmetic)?;
            if checkpoint_bytes > self.config.resource_envelope.checkpoint_bytes
                || write_amplification(journal_bytes, checkpoint_bytes)?
                    > self.config.resource_envelope.write_amplification_ppm
            {
                return Err(NeuronRuntimeError::InvalidConfig);
            }
        }
        Ok(())
    }

    /// Read a versioned disposition derived only from the immutable complete
    /// stored result and frozen configuration. This does not rewrite V1 bytes,
    /// perform inference, grant authority, or report post-commit I/O as measured
    /// latency. A degraded commit remains committed and must not be retried as
    /// an unexecuted tick.
    pub fn query_committed_disposition(
        &mut self,
        tick_id: &codex_hepta_types::StableId,
        input_digest: Digest32,
    ) -> Result<Option<NeuronCommitDispositionV1>, NeuronRuntimeError> {
        let Some(output) = self.query_result(tick_id, input_digest)? else {
            return Ok(None);
        };
        let record = self
            .operations
            .find_tick(tick_id)?
            .ok_or(NeuronRuntimeError::CheckpointMismatch)?;
        let profile = &self.config.calibration;
        let tick = &output.tick;
        let mut abstention = Vec::new();
        if record.sparse_tick.sequence < profile.valid_from_sequence
            || record.sparse_tick.sequence > profile.expires_after_sequence
        {
            abstention.push(AbstainReasonV1::CalibrationExpiredLegacy);
        } else {
            for (condition, reason) in [
                (tick.confidence_ppm < profile.minimum_confidence_ppm, AbstainReasonV1::LowConfidence),
                (tick.ood_ppm > profile.maximum_ood_ppm, AbstainReasonV1::OutOfDomain),
                (tick.sparsity_ppm < profile.minimum_active_ppm, AbstainReasonV1::SparseCollapse),
                (tick.sparsity_ppm > profile.maximum_active_ppm, AbstainReasonV1::DenseCollapse),
                (tick.resource_receipt.saturation_count > profile.maximum_projection_count, AbstainReasonV1::ProjectionLimit),
            ] {
                if condition {
                    abstention.push(reason);
                }
            }
        }
        let resource = &tick.resource_receipt;
        let envelope = &self.config.resource_envelope;
        let mut degradation = Vec::new();
        for (condition, reason) in [
            (resource.execution_micros > envelope.p99_latency_micros, DegradationReasonV1::LatencyEnvelope),
            (resource.transient_allocation_bytes > envelope.transient_allocation_bytes, DegradationReasonV1::AllocationEnvelope),
            (resource.checkpoint_bytes > envelope.checkpoint_bytes, DegradationReasonV1::CheckpointEnvelope),
            (resource.write_amplification_ppm > envelope.write_amplification_ppm, DegradationReasonV1::WriteAmplificationEnvelope),
        ] {
            if condition {
                degradation.push(reason);
            }
        }
        let disposition = if !degradation.is_empty() {
            NeuronCommitDispositionV1::degraded(degradation, abstention)
        } else if !abstention.is_empty() {
            NeuronCommitDispositionV1::abstained(abstention)
        } else {
            Ok(NeuronCommitDispositionV1::CommittedReady)
        };
        disposition.map(Some).map_err(|_| NeuronRuntimeError::InvalidInput)
    }
}

#[cfg(test)]
#[path = "runtime_admission_tests.rs"]
mod tests;
