//! Real terminal owner fits retain root and signed-evidence validity windows.

use super::trust_window_tests::sign_until_at;
use super::*;
use crate::ClassifyOperatorAdmissionFailure;

fn profile() -> crate::TerminalCellProfileV1 {
    crate::TerminalCellProfileV1 {
        artifact_id: id("terminal"),
        producer_id: id("generator"),
        generation: Generation::new(1).unwrap(),
        sensor_id: id("sensor"),
        objective_digest: hash("objective"),
        run_snapshot_digest: hash("run"),
        unit_profile_digest: hash("unit"),
        action_ids: vec![id("action"), id("abstain")],
        minimum_samples_per_action: 1,
    }
}

#[test]
fn terminal_owner_training_revalidates_distribution_at_prepare_verify_and_fit() {
    let fixture = Fixture::terminal();
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, /*seed*/ 3, 95_000_000);
    let profile = profile();
    let frozen = crate::freeze_terminal_cell_from_owner_v1(
        &fixture.owner,
        &receipt,
        profile.clone(),
        89_000_000,
    )
    .unwrap();
    assert!(
        crate::fit_terminal_cell_from_owner_v1(&fixture.owner, frozen.clone(), 89_000_000).is_ok()
    );
    assert!(matches!(
        crate::fit_terminal_cell_from_owner_v1(&fixture.owner, frozen.clone(), 90_000_000),
        Err(crate::TerminalCellError::TrustDistribution(
            LearningTrustDistributionError::DistributionWindow
        ))
    ));
    assert!(matches!(
        crate::legacy::owner_terminal::fit_terminal_cell_at(
            &fixture.owner,
            &frozen,
            89_000_000,
            || Ok(90_000_000)
        ),
        Err(crate::TerminalCellError::TrustDistribution(
            LearningTrustDistributionError::DistributionWindow
        ))
    ));
    assert!(matches!(
        crate::legacy::owner_terminal::fit_terminal_cell_at(
            &fixture.owner,
            &frozen,
            89_000_000,
            || Ok(88_000_000)
        ),
        Err(crate::TerminalCellError::ClockRegression)
    ));
    for verify_now in [89_000_000, 90_000_000] {
        let prepared = crate::prepare_terminal_cell_from_owner_v3(
            &fixture.owner,
            &receipt,
            profile.clone(),
            &freeze,
            89_000_000,
        )
        .unwrap();
        let row = sign_until_at(
            sign(
                &fixture.owner,
                "observer",
                /*seed*/ 2,
                LearningEvidenceRoleV1::Observer,
                prepared.signing_payload(),
            ),
            /*seed*/ 2,
            95_000_000,
        );
        let verified = prepared.verify(&row, verify_now);
        if verify_now == 89_000_000 {
            assert!(matches!(
                crate::legacy::terminal_v3::fit_terminal_cell_verified_at(
                    verified.unwrap(),
                    89_000_000,
                    || Ok(90_000_000)
                ),
                Err(crate::TerminalCellError::TrustDistribution(
                    LearningTrustDistributionError::DistributionWindow
                ))
            ));
        } else {
            assert!(matches!(
                verified,
                Err(crate::TerminalCellError::TrustDistribution(
                    LearningTrustDistributionError::DistributionWindow
                ))
            ));
        }
    }
    assert!(matches!(
        crate::prepare_terminal_cell_from_owner_v3(
            &fixture.owner,
            &receipt,
            profile,
            &freeze,
            90_000_000
        ),
        Err(crate::TerminalCellError::TrustDistribution(
            LearningTrustDistributionError::DistributionWindow
        ))
    ));
}

#[test]
fn terminal_projection_expiring_during_fit_rejects_completed_work() {
    let fixture = Fixture::terminal();
    let (receipt, freeze) = fixture.dataset();
    let freeze = sign_until_at(freeze, /*seed*/ 3, 95_000_000);
    for finished_at in [89_000_000, 89_500_001] {
        let prepared = crate::prepare_terminal_cell_from_owner_v3(
            &fixture.owner,
            &receipt,
            profile(),
            &freeze,
            89_000_000,
        )
        .unwrap();
        let row = sign_until_at(
            sign(
                &fixture.owner,
                "observer",
                /*seed*/ 2,
                LearningEvidenceRoleV1::Observer,
                prepared.signing_payload(),
            ),
            /*seed*/ 2,
            89_500_000,
        );
        let verified = prepared.verify(&row, 89_000_000).unwrap();
        if finished_at == 89_000_000 {
            // Exercise the default public monotonic clock on the positive path.
            assert!(crate::fit_terminal_cell_verified_v3(verified, 89_000_000).is_ok());
        } else {
            let error = crate::legacy::terminal_v3::fit_terminal_cell_verified_at(
                verified,
                89_000_000,
                || Ok(finished_at),
            )
            .unwrap_err();
            assert!(error.disposition().stops_consumer());
            assert!(matches!(
                error,
                crate::TerminalCellError::SignedEvidence(SignedEvidenceError::ValidityWindow)
            ));
        }
    }
}

#[test]
fn terminal_elapsed_clock_overflow_stops_the_consumer() {
    let started = Instant::now()
        .checked_sub(std::time::Duration::from_micros(2))
        .unwrap();
    let error =
        crate::legacy::owner_terminal::terminal_effective_now(u64::MAX, &started).unwrap_err();
    assert!(error.disposition().stops_consumer());
    assert!(matches!(error, crate::TerminalCellError::TimeOverflow));
}
