//! Resource rejection precedes plan copies and observer-signature verification.

use super::trust_window_tests::sign_until_at;
use super::trust_window_tests::tabular_request;
use super::trust_window_tests::world_request_until;
use super::*;

fn fence_and_witness(
    receipt: &DatasetSnapshotReceiptV3,
) -> (crate::FinalUseFenceV1, crate::FinalUseWitnessV1) {
    let generation = Generation::new(1).unwrap();
    (
        crate::FinalUseFenceV1::new(
            receipt.snapshot.ledger_head_digest,
            receipt.snapshot.eligible_frontier,
            generation,
            /*expected_authority_epoch*/ 7,
            /*expected_stop_epoch*/ 3,
            /*absolute_deadline_unix_micros*/ 120_000_000,
        )
        .unwrap(),
        crate::FinalUseWitnessV1::new(
            /*observed_at_unix_micros*/ 50_000_000,
            receipt.snapshot.ledger_head_digest,
            receipt.snapshot.eligible_frontier,
            generation,
            /*authority_epoch*/ 7,
            /*stop_epoch*/ 3,
            /*stop_requested*/ false,
        )
        .unwrap(),
    )
}

#[test]
fn tabular_tiny_byte_budget_rejects_before_invalid_observer_signature() {
    let fixture = Fixture::with_candidates_and_expiry(
        vec![id("action"), id("abstain")],
        /*expires_at*/ 90_000_000,
    );
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, /*seed*/ 3, /*expires_at*/ 95_000_000);
    let (_, mut rows) = tabular_request(&fixture, &receipt);
    rows.signature = [0; 64];
    let mut budget = crate::OperatorResourceBudgetV1::qualification_default();
    budget.max_estimated_bytes = 1;
    let profile = crate::TrainingProfileV1::new(
        hash("objective"),
        hash("sensors"),
        receipt.snapshot.eligible_frontier,
        /*minimum_samples_per_cell*/ 1,
        FixedQ32::ONE,
        budget,
    )
    .unwrap();
    let input = plan(&receipt);
    let request = crate::TabularTrainingRequestV1::new(
        input.artifact_id,
        input.producer_id,
        input.generation,
        profile,
        input.sensor_ids,
        input.action_ids,
        input.samples,
    )
    .unwrap();
    let (fence, witness) = fence_and_witness(&receipt);
    assert!(matches!(
        crate::issue_tabular_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &rows,
            request,
            fence,
            crate::WorkControlV1::new(),
            &witness
        ),
        Err(crate::FinalUseErrorV1::Work(
            crate::OperatorWorkErrorV1::ResourceExhausted {
                resource: crate::OperatorResourceKindV1::EstimatedBytes,
                limit: 1,
                ..
            }
        ))
    ));
}

#[test]
fn world_tiny_operation_budget_rejects_before_invalid_observer_signature() {
    let fixture = Fixture::with_candidates_and_expiry(
        vec![id("action"), id("abstain")],
        /*expires_at*/ 90_000_000,
    );
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, /*seed*/ 3, /*expires_at*/ 95_000_000);
    let (_, mut rows) = world_request_until(
        &fixture, &receipt, /*retained_until*/ 96_000_000, /*expires_at*/ 97_000_000,
    );
    rows.signature = [0; 64];
    let mut budget = crate::OperatorResourceBudgetV1::qualification_default();
    budget.max_operations = 1;
    let profile = crate::WorldModelProfileV1::new(
        hash("objective"),
        hash("sensors"),
        receipt.snapshot.eligible_frontier,
        /*minimum_support*/ 1,
        FixedQ32::ONE,
        FixedQ32::ONE,
        ProbabilityQ32::ONE,
        FixedQ32::ONE,
        budget,
    )
    .unwrap();
    let samples = receipt
        .snapshot
        .source_record_digests
        .iter()
        .enumerate()
        .map(|(index, evidence)| WorldModelSampleV1 {
            sample_id: id(&format!("row-{index}")),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: id("next-state"),
            outcome: FixedQ32::ZERO,
            evidence_digest: *evidence,
        })
        .collect();
    let request = crate::WorldModelTrainingRequestV1::new(
        id("world-model"),
        Generation::new(1).unwrap(),
        profile,
        fixture.owner.verifier().trust_digest(),
        hash("registry"),
        hash("train-window"),
        hash("holdout-window"),
        hash("future-window"),
        /*predecessor_model_digest*/ None,
        FixedQ32::ZERO,
        FixedQ32::ZERO,
        ProbabilityQ32::ZERO,
        FixedQ32::ZERO,
        hash("change-point"),
        /*retained_until*/ 96_000_000,
        /*expires_at*/ 97_000_000,
        samples,
    )
    .unwrap();
    let (fence, witness) = fence_and_witness(&receipt);
    assert!(matches!(
        crate::issue_world_model_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &rows,
            request,
            fence,
            crate::WorkControlV1::new(),
            &witness
        ),
        Err(crate::FinalUseErrorV1::Work(
            crate::OperatorWorkErrorV1::ResourceExhausted {
                resource: crate::OperatorResourceKindV1::Operations,
                required: 2,
                limit: 1
            }
        ))
    ));
}
