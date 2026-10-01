//! Root-distribution lifetime is independent of signer and row-evidence TTL.

use super::*;
use crate::final_use;
use std::cell::Cell;

fn sign_until(evidence: SignedLearningEvidenceV1, seed: u8) -> SignedLearningEvidenceV1 {
    sign_until_at(evidence, seed, 95)
}

pub(super) fn sign_until_at(
    mut evidence: SignedLearningEvidenceV1,
    seed: u8,
    expires_at: u64,
) -> SignedLearningEvidenceV1 {
    evidence.expires_at = expires_at;
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

fn fence_and_witness(
    receipt: &DatasetSnapshotReceiptV3,
    observed_at: u64,
) -> (crate::FinalUseFenceV1, crate::FinalUseWitnessV1) {
    let generation = Generation::new(1).unwrap();
    (
        crate::FinalUseFenceV1::new(
            receipt.snapshot.ledger_head_digest,
            receipt.snapshot.eligible_frontier,
            generation,
            /*expected_authority_epoch*/ 7,
            /*expected_stop_epoch*/ 3,
            /*absolute_deadline_unix_micros*/ 80_000_000,
        )
        .unwrap(),
        crate::FinalUseWitnessV1::new(
            observed_at,
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

pub(super) fn tabular_request(
    fixture: &Fixture,
    receipt: &DatasetSnapshotReceiptV3,
) -> (crate::TabularTrainingRequestV1, SignedLearningEvidenceV1) {
    let profile = crate::TrainingProfileV1::new(
        hash("objective"),
        hash("sensors"),
        receipt.snapshot.eligible_frontier,
        /*minimum_samples_per_cell*/ 1,
        FixedQ32::ONE,
        crate::OperatorResourceBudgetV1::qualification_default(),
    )
    .unwrap();
    let mut input = plan(receipt);
    input.training_profile_digest = profile.digest();
    let payload = tabular_training_signing_payload_v2(&input, receipt, &fixture.owner).unwrap();
    let row = sign_until(
        sign(
            &fixture.owner,
            "observer",
            /*seed*/ 2,
            LearningEvidenceRoleV1::Observer,
            &payload,
        ),
        /*seed*/ 2,
    );
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
    (request, row)
}

fn world_request(
    fixture: &Fixture,
    receipt: &DatasetSnapshotReceiptV3,
    retained_until: u64,
) -> (crate::WorldModelTrainingRequestV1, SignedLearningEvidenceV1) {
    world_request_until(fixture, receipt, retained_until, 97)
}

pub(super) fn world_request_until(
    fixture: &Fixture,
    receipt: &DatasetSnapshotReceiptV3,
    retained_until: u64,
    expires_at: u64,
) -> (crate::WorldModelTrainingRequestV1, SignedLearningEvidenceV1) {
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
    let payload =
        world_model_training_signing_payload_v2(&model_id, &samples, receipt, &fixture.owner)
            .unwrap();
    let row = sign_until(
        sign(
            &fixture.owner,
            "observer",
            /*seed*/ 2,
            LearningEvidenceRoleV1::Observer,
            &payload,
        ),
        /*seed*/ 2,
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
    let request = crate::WorldModelTrainingRequestV1::new(
        model_id,
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
        retained_until,
        expires_at,
        samples,
    )
    .unwrap();
    (request, row)
}

#[test]
fn tabular_distribution_expiry_blocks_effective_publication_with_valid_signatures() {
    let fixture = Fixture::new();
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until(freeze, /*seed*/ 3);
    let (fence, witness) = fence_and_witness(&receipt, /*observed_at*/ 89);
    for (publish_now, final_now) in [(89, 89), (89, 90), (90, 90)] {
        let (request, row) = tabular_request(&fixture, &receipt);
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
            Ok(match calls.get() {
                1 => 89,
                2 => publish_now,
                _ => final_now,
            })
        });
        assert_eq!(calls.get(), if publish_now == 89 { 3 } else { 2 });
        if final_now == 89 {
            assert!(result.is_ok());
        } else {
            assert!(
                matches!(result, Err(crate::FinalUseErrorV1::OwnerState(reason)) if reason == "DistributionWindow")
            );
        }
    }
    let (request, row) = tabular_request(&fixture, &receipt);
    let (_, expired) = fence_and_witness(&receipt, /*observed_at*/ 90);
    assert!(
        matches!(crate::issue_tabular_final_use_capability_v1(&fixture.owner, &receipt, &freeze, &row, request, fence, crate::WorkControlV1::new(), &expired), Err(crate::FinalUseErrorV1::OwnerState(reason)) if reason == "DistributionWindow")
    );
}

#[test]
fn world_distribution_expiry_blocks_effective_publication_with_valid_signatures() {
    let fixture = Fixture::new();
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until(freeze, /*seed*/ 3);
    let (fence, witness) = fence_and_witness(&receipt, /*observed_at*/ 89);
    for (publish_now, final_now) in [(89, 89), (89, 90), (90, 90)] {
        let (request, row) = world_request(&fixture, &receipt, /*retained_until*/ 96);
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
                Ok(match calls.get() {
                    1 => 89,
                    2 => publish_now,
                    _ => final_now,
                })
            });
        assert_eq!(calls.get(), if publish_now == 89 { 3 } else { 2 });
        if final_now == 89 {
            assert!(result.is_ok());
        } else {
            assert!(
                matches!(result, Err(crate::FinalUseErrorV1::OwnerState(reason)) if reason == "DistributionWindow")
            );
        }
    }
}

#[test]
fn world_retention_expiring_during_fit_rejects_effective_publication() {
    let fixture = Fixture::new();
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until(freeze, /*seed*/ 3);
    let (fence, witness) = fence_and_witness(&receipt, /*observed_at*/ 80);
    let (request, row) = world_request(&fixture, &receipt, /*retained_until*/ 88);
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
    let result = final_use::fit_world_model_final_use_v1(capability, &witness, &witness, |_| {
        calls.set(calls.get() + 1);
        Ok(if calls.get() == 1 { 80 } else { 89 })
    });
    assert_eq!(calls.get(), 2);
    assert!(matches!(
        result,
        Err(crate::FinalUseErrorV1::WorldModel(
            crate::world_model_v2::WorldModelV2Error::Expired
        ))
    ));
    let (request, row) = world_request(&fixture, &receipt, /*retained_until*/ 79);
    assert!(matches!(
        crate::issue_world_model_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &row,
            request,
            fence,
            crate::WorkControlV1::new(),
            &witness
        ),
        Err(crate::FinalUseErrorV1::WorldModel(
            crate::world_model_v2::WorldModelV2Error::Expired
        ))
    ));
}
