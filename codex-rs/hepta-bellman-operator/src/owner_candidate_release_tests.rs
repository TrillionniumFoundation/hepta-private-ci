//! The outer handoff retains the actual authenticated publication evidence.

use super::forward_clock_tests::fence_and_witness;
use super::trust_window_tests::sign_until_at;
use super::trust_window_tests::tabular_request;
use super::trust_window_tests::world_request_until;
use super::*;
use crate::final_use;

#[test]
fn tabular_outer_release_revalidates_root_and_signed_row_evidence() {
    for (root_expiry, row_expiry) in [(80_000_000, 86_000_000), (90_000_000, 80_000_000)] {
        let fixture =
            Fixture::with_candidates_and_expiry(vec![id("action"), id("abstain")], root_expiry);
        let (receipt, freeze) = fixture.dataset();
        let freeze = sign_until_at(freeze, /*seed*/ 3, /*expires_at*/ 86_000_000);
        let (request, rows) = tabular_request(&fixture, &receipt);
        let rows = sign_until_at(rows, /*seed*/ 2, row_expiry);
        let (fence, witness) = fence_and_witness(&receipt, /*observed_at*/ 75_000_000);
        let capability = final_use::issue_tabular_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &rows,
            request,
            fence,
            crate::WorkControlV1::new(),
            &witness,
        )
        .unwrap();
        let release =
            final_use::fit_tabular_for_release(capability, &witness, &witness, |_| Ok(75_000_000))
                .unwrap();
        let result = release.finish(/*now*/ 81_000_000);
        if root_expiry == 80_000_000 {
            assert!(
                matches!(result, Err(crate::FinalUseErrorV1::OwnerState(reason)) if reason == "DistributionWindow")
            );
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
fn world_outer_release_revalidates_model_retention_after_inner_fit() {
    let fixture = Fixture::with_candidates_and_expiry(
        vec![id("action"), id("abstain")],
        /*expires_at*/ 90_000_000,
    );
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, /*seed*/ 3, /*expires_at*/ 95_000_000);
    let (request, rows) = world_request_until(
        &fixture, &receipt, /*retained_until*/ 80_000_000, /*expires_at*/ 95_000_000,
    );
    let rows = sign_until_at(rows, /*seed*/ 2, /*expires_at*/ 95_000_000);
    let (fence, witness) = fence_and_witness(&receipt, /*observed_at*/ 75_000_000);
    let capability = final_use::issue_world_model_final_use_capability_v1(
        &fixture.owner,
        &receipt,
        &freeze,
        &rows,
        request,
        fence,
        crate::WorkControlV1::new(),
        &witness,
    )
    .unwrap();
    let release =
        final_use::fit_world_model_for_release(capability, &witness, &witness, |_| Ok(75_000_000))
            .unwrap();
    assert!(matches!(
        release.finish(/*now*/ 81_000_000),
        Err(crate::FinalUseErrorV1::WorldModel(
            crate::world_model_v2::WorldModelV2Error::Expired
        ))
    ));
}

#[test]
fn healthy_outer_handoff_records_the_actual_release_time() {
    let fixture = Fixture::with_candidates_and_expiry(
        vec![id("action"), id("abstain")],
        /*expires_at*/ 90_000_000,
    );
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, /*seed*/ 3, /*expires_at*/ 95_000_000);
    let (request, rows) = tabular_request(&fixture, &receipt);
    let rows = sign_until_at(rows, /*seed*/ 2, /*expires_at*/ 95_000_000);
    let (fence, witness) = fence_and_witness(&receipt, /*observed_at*/ 75_000_000);
    let capability = final_use::issue_tabular_final_use_capability_v1(
        &fixture.owner,
        &receipt,
        &freeze,
        &rows,
        request,
        fence,
        crate::WorkControlV1::new(),
        &witness,
    )
    .unwrap();
    let release =
        final_use::fit_tabular_for_release(capability, &witness, &witness, |_| Ok(75_000_000))
            .unwrap();
    let candidate = release.finish(/*now*/ 79_000_000).unwrap();
    assert_eq!(
        candidate.publication_view().published_at_unix_micros(),
        79_000_000
    );
}
