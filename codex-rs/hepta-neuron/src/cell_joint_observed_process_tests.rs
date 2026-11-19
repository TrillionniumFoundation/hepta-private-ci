//! Observed-profile admission failures retain the actual deadline disposition.

use super::*;
use crate::JointGenerationCommandV2;
use crate::JointGenerationDeliveryContractV2;
use crate::JointGenerationInputV2;
use pretty_assertions::assert_eq;

fn observed_harness(now_micros: u64) -> TestResult<Harness> {
    let mut harness = Harness::new(/*weights_bytes*/ 128, Arc::new(move || now_micros))?;
    harness.manifest.profile = JointGenerationProcessWorkerV1::OBSERVED_PROFILE.into();
    harness.manifest.input_schema = JointGenerationProcessWorkerV1::observed_input_schema_digest();
    harness.manifest.state_schema = JointGenerationProcessWorkerV1::observed_state_schema_digest();
    harness.manifest.output_schema =
        JointGenerationProcessWorkerV1::observed_output_schema_digest();
    harness.request.predecessor.manifest_digest = harness.manifest.digest()?;
    harness.request.deadline_micros = 100;
    harness.request.input = serde_json::to_vec(&JointGenerationInputV2 {
        public_digest: harness.worker.public_digest,
        delivery: JointGenerationDeliveryContractV2 {
            required_mask: 8,
            optional_mask: 1,
            budget_total_micros: 99,
            task_deadline_micros: 100,
        },
        command: JointGenerationCommandV2::Init {
            seed: 17,
            sampler: JointGenerationSamplerV1::Mean,
        },
    })?;
    Ok(harness)
}

#[test]
fn expired_observed_request_records_deadline_without_launching_child() -> TestResult {
    let harness = observed_harness(/*now_micros*/ 100)?;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(
        proposal.disposition,
        CellGenerationDispositionV2::DeadlineExceeded
    );
    assert_eq!(proposal.successor_state, harness.request.predecessor.state);
    assert!(proposal.output_delta.is_empty());
    assert_eq!(proposal.cost.entries().len(), 1);
    let entry = &proposal.cost.entries()[0];
    assert_eq!(entry.outcome, CellCostOutcomeV2::Cancelled);
    assert_eq!(entry.stage, CellCostStageV2::Codec);
    assert!(entry.metrics.wall_micros.is_some());
    assert_eq!(entry.metrics.cpu_micros, None);
    Ok(())
}

#[test]
fn shortened_observed_request_budget_is_rejected_before_launch() -> TestResult {
    let mut harness = observed_harness(/*now_micros*/ 10)?;
    harness.request.deadline_micros = 99;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Rejected);
    assert_eq!(proposal.successor_state, harness.request.predecessor.state);
    assert!(proposal.output_delta.is_empty());
    assert_eq!(proposal.cost.entries().len(), 1);
    assert_eq!(
        proposal.cost.entries()[0].outcome,
        CellCostOutcomeV2::Rejected
    );
    Ok(())
}
