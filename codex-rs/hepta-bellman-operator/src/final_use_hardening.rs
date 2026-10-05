//! Strict time and work fencing for the default final-use API.
//!
//! The underlying owner-bound implementation validates durable ledger,
//! authority, generation, stop and dataset currentness before and after fitting.
//! This wrapper additionally makes the trusted issuance instant and one
//! monotonic `FitContextV1` part of the single-use token. Consequently, resource
//! elapsed time starts when the capability is issued, survives worker dispatch,
//! and cannot be reset immediately before fitting.

use std::fmt;

use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use crate::budget::FitContextV1;
use crate::budget::WorkControlV1;
use crate::budget::with_fit_context_v1;
use crate::final_use;
use crate::final_use::FinalUseErrorV1;
use crate::final_use::FinalUseFenceV1;
use crate::final_use::FinalUseTabularCandidateV1;
use crate::final_use::FinalUseWitnessV1;
use crate::final_use::FinalUseWorldModelCandidateV1;
use crate::final_use::TabularTrainingRequestV1;
use crate::final_use::WorldModelTrainingRequestV1;

#[must_use = "the capability must be consumed by fit_tabular_final_use_v1"]
pub struct FinalUseTabularCapabilityV1<'a> {
    inner: final_use::FinalUseTabularCapabilityV1<'a>,
    fit_context: FitContextV1,
    issued_at_unix_micros: u64,
    absolute_deadline_unix_micros: u64,
}

impl fmt::Debug for FinalUseTabularCapabilityV1<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FinalUseTabularCapabilityV1")
            .field("issued_at_unix_micros", &self.issued_at_unix_micros)
            .field(
                "absolute_deadline_unix_micros",
                &self.absolute_deadline_unix_micros,
            )
            .field("work_elapsed_micros", &self.fit_context.elapsed_micros())
            .finish_non_exhaustive()
    }
}

#[must_use = "the capability must be consumed by fit_world_model_final_use_v1"]
pub struct FinalUseWorldModelCapabilityV1<'a> {
    inner: final_use::FinalUseWorldModelCapabilityV1<'a>,
    fit_context: FitContextV1,
    issued_at_unix_micros: u64,
    absolute_deadline_unix_micros: u64,
}

impl fmt::Debug for FinalUseWorldModelCapabilityV1<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FinalUseWorldModelCapabilityV1")
            .field("issued_at_unix_micros", &self.issued_at_unix_micros)
            .field(
                "absolute_deadline_unix_micros",
                &self.absolute_deadline_unix_micros,
            )
            .field("work_elapsed_micros", &self.fit_context.elapsed_micros())
            .finish_non_exhaustive()
    }
}

#[allow(clippy::too_many_arguments)]
pub fn issue_tabular_final_use_capability_v1<'a>(
    owner: &'a LedgerWriter,
    receipt: &DatasetSnapshotReceiptV3,
    freeze_evidence: &SignedLearningEvidenceV1,
    row_evidence: &SignedLearningEvidenceV1,
    request: TabularTrainingRequestV1,
    fence: FinalUseFenceV1,
    control: WorkControlV1,
    witness: &FinalUseWitnessV1,
) -> Result<FinalUseTabularCapabilityV1<'a>, FinalUseErrorV1> {
    let issued_at_unix_micros = witness.observed_at();
    let absolute_deadline_unix_micros = fence.deadline();
    validate_capability_window(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        issued_at_unix_micros,
        issued_at_unix_micros,
    )?;
    let fit_context = control.fit_context();
    validate_fit_currentness(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        &fit_context,
    )?;
    let mut inner = with_fit_context_v1(&fit_context, || {
        final_use::issue_tabular_final_use_capability_v1(
            owner,
            receipt,
            freeze_evidence,
            row_evidence,
            request,
            fence,
            control,
            witness,
        )
    })?;
    validate_fit_currentness(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        &fit_context,
    )?;
    let now = effective_now(
        issued_at_unix_micros,
        issued_at_unix_micros,
        fit_context.elapsed_micros(),
    )?;
    inner.revalidate_issued_at(witness, now)?;
    Ok(FinalUseTabularCapabilityV1 {
        inner,
        fit_context,
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
    })
}

#[allow(clippy::too_many_arguments)]
pub fn issue_world_model_final_use_capability_v1<'a>(
    owner: &'a LedgerWriter,
    receipt: &DatasetSnapshotReceiptV3,
    freeze_evidence: &SignedLearningEvidenceV1,
    row_evidence: &SignedLearningEvidenceV1,
    request: WorldModelTrainingRequestV1,
    fence: FinalUseFenceV1,
    control: WorkControlV1,
    witness: &FinalUseWitnessV1,
) -> Result<FinalUseWorldModelCapabilityV1<'a>, FinalUseErrorV1> {
    let issued_at_unix_micros = witness.observed_at();
    let absolute_deadline_unix_micros = fence.deadline();
    validate_capability_window(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        issued_at_unix_micros,
        issued_at_unix_micros,
    )?;
    let fit_context = control.fit_context();
    validate_fit_currentness(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        &fit_context,
    )?;
    let mut inner = with_fit_context_v1(&fit_context, || {
        final_use::issue_world_model_final_use_capability_v1(
            owner,
            receipt,
            freeze_evidence,
            row_evidence,
            request,
            fence,
            control,
            witness,
        )
    })?;
    validate_fit_currentness(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        &fit_context,
    )?;
    let now = effective_now(
        issued_at_unix_micros,
        issued_at_unix_micros,
        fit_context.elapsed_micros(),
    )?;
    inner.revalidate_issued_at(witness, now)?;
    Ok(FinalUseWorldModelCapabilityV1 {
        inner,
        fit_context,
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
    })
}

pub fn fit_tabular_final_use_v1(
    capability: FinalUseTabularCapabilityV1<'_>,
    use_witness: &FinalUseWitnessV1,
    publish_witness: &FinalUseWitnessV1,
) -> Result<FinalUseTabularCandidateV1, FinalUseErrorV1> {
    let FinalUseTabularCapabilityV1 {
        inner,
        fit_context,
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
    } = capability;
    validate_capability_window(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        use_witness.observed_at(),
        publish_witness.observed_at(),
    )?;
    validate_fit_currentness(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        &fit_context,
    )?;
    let candidate = with_fit_context_v1(&fit_context, || {
        final_use::fit_tabular_final_use_v1(inner, use_witness, publish_witness, |observed_at| {
            effective_now(
                issued_at_unix_micros,
                observed_at,
                fit_context.elapsed_micros(),
            )
        })
    })?;
    // The host witnesses are supplied before this synchronous call. Their
    // timestamps cannot stand in for time actually spent dispatching/fitting.
    validate_fit_currentness(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        &fit_context,
    )?;
    Ok(candidate)
}

pub fn fit_world_model_final_use_v1(
    capability: FinalUseWorldModelCapabilityV1<'_>,
    use_witness: &FinalUseWitnessV1,
    publish_witness: &FinalUseWitnessV1,
) -> Result<FinalUseWorldModelCandidateV1, FinalUseErrorV1> {
    let FinalUseWorldModelCapabilityV1 {
        inner,
        fit_context,
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
    } = capability;
    validate_capability_window(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        use_witness.observed_at(),
        publish_witness.observed_at(),
    )?;
    validate_fit_currentness(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        &fit_context,
    )?;
    let candidate = with_fit_context_v1(&fit_context, || {
        final_use::fit_world_model_final_use_v1(
            inner,
            use_witness,
            publish_witness,
            |observed_at| {
                effective_now(
                    issued_at_unix_micros,
                    observed_at,
                    fit_context.elapsed_micros(),
                )
            },
        )
    })?;
    // The host witnesses are supplied before this synchronous call. Their
    // timestamps cannot stand in for time actually spent dispatching/fitting.
    validate_fit_currentness(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        &fit_context,
    )?;
    Ok(candidate)
}

fn validate_capability_window(
    issued_at_unix_micros: u64,
    absolute_deadline_unix_micros: u64,
    use_observed_at_unix_micros: u64,
    publish_observed_at_unix_micros: u64,
) -> Result<(), FinalUseErrorV1> {
    if use_observed_at_unix_micros < issued_at_unix_micros
        || publish_observed_at_unix_micros < use_observed_at_unix_micros
    {
        return Err(FinalUseErrorV1::ClockRegression);
    }
    if issued_at_unix_micros >= absolute_deadline_unix_micros
        || use_observed_at_unix_micros >= absolute_deadline_unix_micros
        || publish_observed_at_unix_micros >= absolute_deadline_unix_micros
    {
        return Err(FinalUseErrorV1::DeadlineExceeded);
    }
    Ok(())
}

fn validate_fit_currentness(
    issued_at_unix_micros: u64,
    absolute_deadline_unix_micros: u64,
    fit_context: &FitContextV1,
) -> Result<(), FinalUseErrorV1> {
    if fit_context.control().is_cancelled() {
        return Err(FinalUseErrorV1::Stopped);
    }
    validate_elapsed_deadline(
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
        fit_context.elapsed_micros(),
    )
}

fn validate_elapsed_deadline(
    issued_at_unix_micros: u64,
    absolute_deadline_unix_micros: u64,
    elapsed_micros: u64,
) -> Result<(), FinalUseErrorV1> {
    let current_time = effective_now(issued_at_unix_micros, issued_at_unix_micros, elapsed_micros)?;
    if current_time >= absolute_deadline_unix_micros {
        return Err(FinalUseErrorV1::DeadlineExceeded);
    }
    Ok(())
}

// Advance only the time used to validate owner/evidence windows. The host's
// identity and generation witnesses are never rewritten as refreshed evidence.
fn effective_now(issued_at: u64, observed_at: u64, elapsed: u64) -> Result<u64, FinalUseErrorV1> {
    issued_at
        .checked_add(elapsed)
        .map(|now| now.max(observed_at))
        .ok_or(FinalUseErrorV1::DeadlineExceeded)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn final_use_window_is_strictly_before_deadline() {
        assert!(validate_capability_window(10, 20, 10, 19).is_ok());
    }

    #[test]
    fn capability_issue_at_deadline_fails_closed() {
        assert!(matches!(
            validate_capability_window(20, 20, 20, 20),
            Err(FinalUseErrorV1::DeadlineExceeded)
        ));
    }

    #[test]
    fn use_at_deadline_fails_closed() {
        assert!(matches!(
            validate_capability_window(10, 20, 20, 20),
            Err(FinalUseErrorV1::DeadlineExceeded)
        ));
    }

    #[test]
    fn use_before_capability_issue_is_clock_regression() {
        assert!(matches!(
            validate_capability_window(10, 20, 9, 11),
            Err(FinalUseErrorV1::ClockRegression)
        ));
    }

    #[test]
    fn publish_before_use_is_clock_regression() {
        assert!(matches!(
            validate_capability_window(10, 20, 15, 14),
            Err(FinalUseErrorV1::ClockRegression)
        ));
    }

    #[test]
    fn cancellation_at_publication_guard_rejects_completed_work() {
        let control = WorkControlV1::new();
        let context = control.fit_context();
        assert!(validate_fit_currentness(10, 10_000_000, &context).is_ok());
        control.cancel();
        assert!(matches!(
            validate_fit_currentness(10, 10_000_000, &context),
            Err(FinalUseErrorV1::Stopped)
        ));
    }

    #[test]
    fn elapsed_deadline_boundary_and_overflow_fail_closed() {
        assert!(validate_elapsed_deadline(10, 20, 9).is_ok());
        assert!(matches!(
            validate_elapsed_deadline(10, 20, 10),
            Err(FinalUseErrorV1::DeadlineExceeded)
        ));
        assert!(matches!(
            validate_elapsed_deadline(u64::MAX - 1, u64::MAX, 2),
            Err(FinalUseErrorV1::DeadlineExceeded)
        ));
    }

    #[test]
    fn effective_now_preserves_later_host_time_and_rejects_overflow() {
        assert_eq!(effective_now(10, 12, 15).unwrap(), 25);
        assert_eq!(effective_now(10, 30, 15).unwrap(), 30);
        assert!(matches!(
            effective_now(u64::MAX - 1, u64::MAX, 2),
            Err(FinalUseErrorV1::DeadlineExceeded)
        ));
    }

    #[test]
    fn monotonic_fit_context_elapsed_time_cannot_reset() {
        let context = WorkControlV1::new().fit_context();
        let before = context.elapsed_micros();
        std::thread::sleep(std::time::Duration::from_millis(2));
        let after = context.elapsed_micros();
        assert!(after > before);
        // Static timestamps still look current, but real dispatch elapsed time
        // has crossed this absolute deadline and cannot publish a candidate.
        assert!(validate_capability_window(10, 20, 10, 10).is_ok());
        assert!(matches!(
            validate_elapsed_deadline(10, 20, after),
            Err(FinalUseErrorV1::DeadlineExceeded)
        ));
        with_fit_context_v1(&context, || {
            assert!(context.elapsed_micros() >= after);
        });
    }
}
