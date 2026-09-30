//! Deterministic clock advancement across actual synchronous fit work.

use super::*;
use crate::final_use;
use std::cell::Cell;

fn fence_and_witness(
    receipt: &DatasetSnapshotReceiptV3,
) -> (crate::FinalUseFenceV1, crate::FinalUseWitnessV1) {
    let generation = Generation::new(1).unwrap();
    let fence = crate::FinalUseFenceV1::new(
        receipt.snapshot.ledger_head_digest,
        receipt.snapshot.eligible_frontier,
        generation,
        /*expected_authority_epoch*/ 7,
        /*expected_stop_epoch*/ 3,
        /*absolute_deadline_unix_micros*/ 80_000_000,
    )
    .unwrap();
    let witness = crate::FinalUseWitnessV1::new(
        /*observed_at_unix_micros*/ 50,
        receipt.snapshot.ledger_head_digest,
        receipt.snapshot.eligible_frontier,
        generation,
        /*authority_epoch*/ 7,
        /*stop_epoch*/ 3,
        /*stop_requested*/ false,
    )
    .unwrap();
    (fence, witness)
}

fn expiring_row(owner: &LedgerWriter, payload: &[u8]) -> SignedLearningEvidenceV1 {
    let mut row = sign(
        owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        payload,
    );
    row.expires_at = 55;
    row.signature = SigningKey::from_bytes(&[2; 32])
        .sign(&row.signing_bytes())
        .to_bytes();
    row
}

#[test]
fn tabular_row_evidence_expiring_during_fit_rejects_publication_before_deadline() {
    let fixture = Fixture::new();
    let (receipt, freeze) = fixture.dataset();
    let (fence, witness) = fence_and_witness(&receipt);
    let profile = crate::TrainingProfileV1::new(
        hash("objective"),
        hash("sensors"),
        receipt.snapshot.eligible_frontier,
        /*minimum_samples_per_cell*/ 1,
        FixedQ32::ONE,
        crate::OperatorResourceBudgetV1::qualification_default(),
    )
    .unwrap();
    let mut input = plan(&receipt);
    input.training_profile_digest = profile.digest();
    let row = expiring_row(
        &fixture.owner,
        &tabular_training_signing_payload_v2(&input, &receipt, &fixture.owner).unwrap(),
    );
    for publish_now in [50, 56] {
        let request = crate::TabularTrainingRequestV1::new(
            input.artifact_id.clone(),
            input.producer_id.clone(),
            input.generation,
            profile.clone(),
            input.sensor_ids.clone(),
            input.action_ids.clone(),
            input.samples.clone(),
        )
        .unwrap();
        let capability = final_use::issue_tabular_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &row,
            request,
            fence,
            crate::WorkControlV1::new(),
            &witness,
        )
        .unwrap();
        let calls = Cell::new(0);
        let result = final_use::fit_tabular_final_use_v1(capability, &witness, &witness, |_| {
            calls.set(calls.get() + 1);
            Ok(if calls.get() == 1 { 50 } else { publish_now })
        });
        assert_eq!(calls.get(), 2);
        if publish_now == 50 {
            assert!(result.is_ok());
        } else {
            assert!(matches!(
                result,
                Err(crate::FinalUseErrorV1::Source(
                    OperatorDatasetBindingError::SignedEvidence(
                        SignedEvidenceError::ValidityWindow
                    )
                ))
            ));
        }
    }
}

#[test]
fn world_row_evidence_expiring_during_fit_rejects_publication_before_deadline() {
    let fixture = Fixture::new();
    let (receipt, freeze) = fixture.dataset();
    let (fence, witness) = fence_and_witness(&receipt);
    let model_id = id("world-model");
    let samples: Vec<_> = receipt
        .snapshot
        .source_record_digests
        .iter()
        .enumerate()
        .map(|(index, evidence_digest)| WorldModelSampleV1 {
            sample_id: id(&format!("world-row-{index}")),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: id("next-state"),
            outcome: FixedQ32::from_raw(20),
            evidence_digest: *evidence_digest,
        })
        .collect();
    let row = expiring_row(
        &fixture.owner,
        &world_model_training_signing_payload_v2(&model_id, &samples, &receipt, &fixture.owner)
            .unwrap(),
    );
    let profile = crate::WorldModelProfileV1::new(
        hash("objective"),
        hash("sensors"),
        receipt.snapshot.eligible_frontier,
        /*minimum_support*/ 1,
        FixedQ32::ONE,
        FixedQ32::ONE,
        ProbabilityQ32::ONE,
        FixedQ32::ONE,
        crate::OperatorResourceBudgetV1::qualification_default(),
    )
    .unwrap();
    for publish_now in [50, 56] {
        let request = crate::WorldModelTrainingRequestV1::new(
            model_id.clone(),
            Generation::new(1).unwrap(),
            profile.clone(),
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
            /*retained_until*/ 70,
            /*expires_at*/ 80,
            samples.clone(),
        )
        .unwrap();
        let capability = final_use::issue_world_model_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &row,
            request,
            fence,
            crate::WorkControlV1::new(),
            &witness,
        )
        .unwrap();
        let calls = Cell::new(0);
        let result =
            final_use::fit_world_model_final_use_v1(capability, &witness, &witness, |_| {
                calls.set(calls.get() + 1);
                Ok(if calls.get() == 1 { 50 } else { publish_now })
            });
        assert_eq!(calls.get(), 2);
        if publish_now == 50 {
            assert!(result.is_ok());
        } else {
            assert!(matches!(
                result,
                Err(crate::FinalUseErrorV1::Source(
                    OperatorDatasetBindingError::SignedEvidence(
                        SignedEvidenceError::ValidityWindow
                    )
                ))
            ));
        }
    }
}
