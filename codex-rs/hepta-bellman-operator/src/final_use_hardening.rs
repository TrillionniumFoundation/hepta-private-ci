//! Strict time fencing for the default final-use API.
//!
//! The underlying owner-bound implementation validates durable ledger,
//! authority, generation, stop and dataset currentness before and after fitting.
//! This wrapper additionally makes the capability issuance instant part of the
//! single-use token and treats the absolute deadline as an exclusive bound.
//! Consequently, a caller cannot move the trusted clock backwards after
//! capability issuance, and work observed exactly at the deadline fails closed.

use std::fmt;

use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use crate::budget::WorkControlV1;
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
            .finish_non_exhaustive()
    }
}

#[must_use = "the capability must be consumed by fit_world_model_final_use_v1"]
pub struct FinalUseWorldModelCapabilityV1<'a> {
    inner: final_use::FinalUseWorldModelCapabilityV1<'a>,
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
    let inner = final_use::issue_tabular_final_use_capability_v1(
        owner,
        receipt,
        freeze_evidence,
        row_evidence,
        request,
        fence,
        control,
        witness,
    )?;
    Ok(FinalUseTabularCapabilityV1 {
        inner,
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
    let inner = final_use::issue_world_model_final_use_capability_v1(
        owner,
        receipt,
        freeze_evidence,
        row_evidence,
        request,
        fence,
        control,
        witness,
    )?;
    Ok(FinalUseWorldModelCapabilityV1 {
        inner,
        issued_at_unix_micros,
        absolute_deadline_unix_micros,
    })
}

pub fn fit_tabular_final_use_v1(
    capability: FinalUseTabularCapabilityV1<'_>,
    use_witness: &FinalUseWitnessV1,
    publish_witness: &FinalUseWitnessV1,
) -> Result<FinalUseTabularCandidateV1, FinalUseErrorV1> {
    validate_capability_window(
        capability.issued_at_unix_micros,
        capability.absolute_deadline_unix_micros,
        use_witness.observed_at(),
        publish_witness.observed_at(),
    )?;
    final_use::fit_tabular_final_use_v1(capability.inner, use_witness, publish_witness)
}

pub fn fit_world_model_final_use_v1(
    capability: FinalUseWorldModelCapabilityV1<'_>,
    use_witness: &FinalUseWitnessV1,
    publish_witness: &FinalUseWitnessV1,
) -> Result<FinalUseWorldModelCandidateV1, FinalUseErrorV1> {
    validate_capability_window(
        capability.issued_at_unix_micros,
        capability.absolute_deadline_unix_micros,
        use_witness.observed_at(),
        publish_witness.observed_at(),
    )?;
    final_use::fit_world_model_final_use_v1(capability.inner, use_witness, publish_witness)
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
}
