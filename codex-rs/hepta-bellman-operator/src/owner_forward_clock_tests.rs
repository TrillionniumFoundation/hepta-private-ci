//! Signed owner expiry still applies after a forward fit-use host clock jump.

use super::trust_window_tests::sign_until_at;
use super::trust_window_tests::tabular_request;
use super::trust_window_tests::world_request_until;
use super::*;
use crate::final_use;
use crate::final_use_hardening::clock::FinalUseClockV1;
use pretty_assertions::assert_eq;
use std::cell::Cell;

pub(super) fn fence_and_witness(
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
            /*absolute_deadline_unix_micros*/ 120_000_000,
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

#[test]
fn tabular_forward_clock_jump_cannot_publish_after_root_distribution_expiry() {
    let fixture = Fixture::with_candidates_and_expiry(
        vec![id("action"), id("abstain")],
        /*expires_at*/ 80_000_000,
    );
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, /*seed*/ 3, /*expires_at*/ 86_000_000);
    let (request, row) = tabular_request(&fixture, &receipt);
    let row = sign_until_at(row, /*seed*/ 2, /*expires_at*/ 86_000_000);
    let (fence, issued) = fence_and_witness(&receipt, /*observed_at*/ 50_000_000);
    let (_, use_witness) = fence_and_witness(&receipt, /*observed_at*/ 75_000_000);
    let capability = final_use::issue_tabular_final_use_capability_v1(
        &fixture.owner,
        &receipt,
        &freeze,
        &row,
        request,
        fence,
        crate::WorkControlV1::new(),
        &issued,
    )
    .unwrap();
    let clock = FinalUseClockV1::new(issued.observed_at());
    clock
        .observe(use_witness.observed_at(), /*elapsed_micros*/ 1_000_000)
        .unwrap();
    let calls = Cell::new(0);
    let result = final_use::fit_tabular_final_use_v1(
        capability,
        &use_witness,
        &use_witness,
        |observed_at| {
            calls.set(calls.get() + 1);
            clock.observe(
                observed_at,
                if calls.get() == 1 {
                    1_000_000
                } else {
                    7_000_000
                },
            )
        },
    );
    assert_eq!(calls.get(), 2);
    assert!(
        matches!(result, Err(crate::FinalUseErrorV1::OwnerState(reason)) if reason == "DistributionWindow")
    );
}

#[test]
fn world_forward_clock_jump_cannot_publish_after_model_retention() {
    let fixture = Fixture::with_candidates_and_expiry(
        vec![id("action"), id("abstain")],
        /*expires_at*/ 90_000_000,
    );
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, /*seed*/ 3, /*expires_at*/ 95_000_000);
    let (request, row) = world_request_until(
        &fixture, &receipt, /*retained_until*/ 80_000_000, /*expires_at*/ 95_000_000,
    );
    let row = sign_until_at(row, /*seed*/ 2, /*expires_at*/ 95_000_000);
    let (fence, issued) = fence_and_witness(&receipt, /*observed_at*/ 50_000_000);
    let (_, use_witness) = fence_and_witness(&receipt, /*observed_at*/ 75_000_000);
    let capability = final_use::issue_world_model_final_use_capability_v1(
        &fixture.owner,
        &receipt,
        &freeze,
        &row,
        request,
        fence,
        crate::WorkControlV1::new(),
        &issued,
    )
    .unwrap();
    let clock = FinalUseClockV1::new(issued.observed_at());
    clock
        .observe(use_witness.observed_at(), /*elapsed_micros*/ 1_000_000)
        .unwrap();
    let calls = Cell::new(0);
    let result = final_use::fit_world_model_final_use_v1(
        capability,
        &use_witness,
        &use_witness,
        |observed_at| {
            calls.set(calls.get() + 1);
            clock.observe(
                observed_at,
                if calls.get() == 1 {
                    1_000_000
                } else {
                    7_000_000
                },
            )
        },
    );
    assert_eq!(calls.get(), 2);
    assert!(matches!(
        result,
        Err(crate::FinalUseErrorV1::WorldModel(
            crate::world_model_v2::WorldModelV2Error::Expired
        ))
    ));
}
