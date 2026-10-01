//! The actual issuance guard runs after durable owner and signature work.

use super::trust_window_tests::sign_until_at;
use super::trust_window_tests::tabular_request;
use super::trust_window_tests::world_request_until;
use super::*;
use crate::final_use;

fn fence_and_witness(
    receipt: &DatasetSnapshotReceiptV3,
) -> (crate::FinalUseFenceV1, crate::FinalUseWitnessV1) {
    let generation = Generation::new(1).unwrap();
    (
        crate::FinalUseFenceV1::new(
            receipt.snapshot.ledger_head_digest,
            receipt.snapshot.eligible_frontier,
            generation,
            7,
            3,
            120_000_000,
        )
        .unwrap(),
        crate::FinalUseWitnessV1::new(
            50_000_000,
            receipt.snapshot.ledger_head_digest,
            receipt.snapshot.eligible_frontier,
            generation,
            7,
            3,
            false,
        )
        .unwrap(),
    )
}

#[test]
fn tabular_issuance_revalidates_root_and_evidence_after_owner_verification() {
    let fixture =
        Fixture::with_candidates_and_expiry(vec![id("action"), id("abstain")], 90_000_000);
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, 3, 95_000_000);
    let (fence, witness) = fence_and_witness(&receipt);
    for final_now in [50_000_000, 56_000_000, 90_000_000] {
        let (request, row) = tabular_request(&fixture, &receipt);
        let row = sign_until_at(row, 2, 55_000_000);
        let mut capability = final_use::issue_tabular_final_use_capability_v1(
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
        let result = capability.revalidate_issued_at(&witness, final_now);
        match final_now {
            50_000_000 => assert!(result.is_ok()),
            56_000_000 => assert!(matches!(
                result,
                Err(crate::FinalUseErrorV1::Source(
                    OperatorDatasetBindingError::SignedEvidence(
                        SignedEvidenceError::ValidityWindow
                    )
                ))
            )),
            _ => assert!(matches!(result,
                Err(crate::FinalUseErrorV1::OwnerState(reason)) if reason == "DistributionWindow")),
        }
    }
    let (request, row) = tabular_request(&fixture, &receipt);
    let row = sign_until_at(row, 2, 95_000_000);
    // The public default API uses this same post-work guard with real elapsed
    // time. A healthy seconds-long fixture must still reach that API.
    assert!(
        crate::issue_tabular_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &row,
            request,
            fence,
            crate::WorkControlV1::new(),
            &witness,
        )
        .is_ok()
    );
}

#[test]
fn world_issuance_revalidates_model_retention_after_owner_verification() {
    let fixture =
        Fixture::with_candidates_and_expiry(vec![id("action"), id("abstain")], 90_000_000);
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, 3, 95_000_000);
    let (fence, witness) = fence_and_witness(&receipt);
    let (request, row) = world_request_until(&fixture, &receipt, 55_000_000, 97_000_000);
    let row = sign_until_at(row, 2, 95_000_000);
    let mut capability = final_use::issue_world_model_final_use_capability_v1(
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
    assert!(
        capability
            .revalidate_issued_at(&witness, 50_000_000)
            .is_ok()
    );
    assert!(matches!(
        capability.revalidate_issued_at(&witness, 56_000_000),
        Err(crate::FinalUseErrorV1::WorldModel(
            crate::world_model_v2::WorldModelV2Error::Expired
        ))
    ));
    let (request, row) = world_request_until(&fixture, &receipt, 96_000_000, 97_000_000);
    let row = sign_until_at(row, 2, 95_000_000);
    assert!(
        crate::issue_world_model_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &row,
            request,
            fence,
            crate::WorkControlV1::new(),
            &witness,
        )
        .is_ok()
    );
}

#[test]
fn retained_issuance_evidence_reserves_shared_memory_until_capability_drop() {
    let fixture =
        Fixture::with_candidates_and_expiry(vec![id("action"), id("abstain")], 90_000_000);
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, 3, 95_000_000);
    let (fence, witness) = fence_and_witness(&receipt);
    let (request, row) = tabular_request(&fixture, &receipt);
    let row = sign_until_at(row, 2, 95_000_000);
    let control = crate::WorkControlV1::new();
    let context = control.fit_context();
    crate::with_fit_context_v1(&context, || {
        let capability = final_use::issue_tabular_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &row,
            request,
            fence,
            control,
            &witness,
        )
        .unwrap();
        let retained = context.peak_estimated_bytes();
        assert!(retained > 0);
        let budget = crate::OperatorResourceBudgetV1::qualification_default();
        let mut worker = crate::OperatorWorkMeter::new(budget).unwrap();
        assert!(matches!(
            worker.reserve_total_bytes(budget.max_estimated_bytes - retained + 1),
            Err(crate::OperatorWorkErrorV1::ResourceExhausted {
                resource: crate::OperatorResourceKindV1::EstimatedBytes,
                ..
            })
        ));
        drop(capability);
        assert!(
            worker
                .reserve_total_bytes(budget.max_estimated_bytes)
                .is_ok()
        );
    });
}
