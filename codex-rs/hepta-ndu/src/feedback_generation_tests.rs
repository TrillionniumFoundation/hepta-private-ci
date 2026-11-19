use std::io::Cursor;

use pretty_assertions::assert_eq;

use super::*;
use crate::run_feedback_generation_protocol;

fn config() -> FeedbackGenerationConfigV1 {
    FeedbackGenerationConfigV1 {
        session_id: 1,
        budget_macs: 22,
        emit_macs: 10,
        refine_macs: 6,
        max_refinements: 3,
        portfolio_index: 2,
        latent_digest: Digest32::of_bytes(b"initial latent"),
    }
}

fn actions(emit: f64, refine: f64) -> [FeedbackActionValueV1; 2] {
    [
        FeedbackActionValueV1 {
            action: FeedbackActionV1::Refine,
            value: refine,
            cost_macs: 6,
        },
        FeedbackActionValueV1 {
            action: FeedbackActionV1::Emit,
            value: emit,
            cost_macs: 10,
        },
    ]
}

#[test]
fn observed_feedback_drives_charged_actions_and_terminal_sealing() -> Result<(), Box<dyn Error>> {
    let mut owner = FeedbackGenerationSessionV1::new(config())?;
    let initial = owner.snapshot();
    assert_eq!(
        owner.choose(initial, &actions(/*emit*/ -1.0, /*refine*/ -0.2))?,
        FeedbackDecisionV1 {
            action: FeedbackActionV1::Refine,
            value: -0.2,
            version: 1,
            depth: 1,
            remaining_macs: 16,
        }
    );
    assert_eq!(
        owner.choose(initial, &actions(/*emit*/ 0.0, /*refine*/ 1.0)),
        Err(FeedbackGenerationError::PendingExecution)
    );
    let mut observed = owner.snapshot();
    observed.latent_digest = Digest32::of_bytes(b"observed first refinement");
    owner.confirm_refinement(observed)?;
    assert_eq!(
        owner.choose(initial, &actions(/*emit*/ 0.0, /*refine*/ 1.0)),
        Err(FeedbackGenerationError::SnapshotMismatch)
    );
    assert_eq!(
        owner.choose(observed, &actions(/*emit*/ -0.1, /*refine*/ -0.4))?,
        FeedbackDecisionV1 {
            action: FeedbackActionV1::Emit,
            value: -0.1,
            version: 2,
            depth: 1,
            remaining_macs: 6,
        }
    );
    assert_eq!(
        owner.confirm_emission(
            /*session_id*/ 1,
            /*version*/ 2,
            [Digest32::ZERO; 4]
        ),
        Err(FeedbackGenerationError::InvalidOutputs)
    );
    let outputs = [b"text".as_slice(), b"audio", b"image", b"video"].map(Digest32::of_bytes);
    owner.confirm_emission(/*session_id*/ 1, /*version*/ 2, outputs)?;
    assert_eq!(
        (
            owner.phase(),
            owner.remaining_macs(),
            owner.output_digests()
        ),
        (FeedbackPhaseV1::Sealed, 6, Some(outputs))
    );
    assert_eq!(
        owner.choose(owner.snapshot(), &actions(/*emit*/ 0.0, /*refine*/ 1.0)),
        Err(FeedbackGenerationError::Sealed)
    );
    assert_eq!(
        owner.confirm_refinement(observed),
        Err(FeedbackGenerationError::Sealed)
    );
    assert_eq!(
        owner.confirm_emission(/*session_id*/ 1, /*version*/ 2, outputs),
        Err(FeedbackGenerationError::Sealed)
    );
    Ok(())
}

#[test]
fn finite_values_fixed_costs_and_snapshots_are_checked_before_mutation()
-> Result<(), Box<dyn Error>> {
    let mut owner = FeedbackGenerationSessionV1::new(config())?;
    let snapshot = owner.snapshot();
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert_eq!(
            owner.choose(snapshot, &actions(/*emit*/ 0.0, value)),
            Err(FeedbackGenerationError::NonFiniteValue)
        );
    }
    let mut bad_cost = actions(/*emit*/ 0.0, /*refine*/ 1.0);
    bad_cost[0].cost_macs = 0;
    assert_eq!(
        owner.choose(snapshot, &bad_cost),
        Err(FeedbackGenerationError::CostMismatch)
    );
    let duplicate = [actions(/*emit*/ 0.0, /*refine*/ 1.0)[1]; 2];
    assert_eq!(
        owner.choose(snapshot, &duplicate),
        Err(FeedbackGenerationError::InvalidTable)
    );
    for changed in [
        FeedbackSnapshotV1 {
            session_id: 2,
            ..snapshot
        },
        FeedbackSnapshotV1 {
            version: 1,
            ..snapshot
        },
        FeedbackSnapshotV1 {
            depth: 1,
            ..snapshot
        },
        FeedbackSnapshotV1 {
            portfolio_index: 0,
            ..snapshot
        },
        FeedbackSnapshotV1 {
            latent_digest: Digest32::of_bytes(b"other"),
            ..snapshot
        },
    ] {
        assert_eq!(
            owner.choose(changed, &actions(/*emit*/ 0.0, /*refine*/ 1.0)),
            Err(FeedbackGenerationError::SnapshotMismatch)
        );
    }
    assert_eq!(
        (owner.snapshot(), owner.phase(), owner.remaining_macs()),
        (snapshot, FeedbackPhaseV1::Ready, 22)
    );
    Ok(())
}

#[test]
fn reserve_and_depth_limits_override_higher_refinement_values() -> Result<(), Box<dyn Error>> {
    for settings in [
        FeedbackGenerationConfigV1 {
            budget_macs: 15,
            ..config()
        },
        FeedbackGenerationConfigV1 {
            max_refinements: 0,
            ..config()
        },
    ] {
        let mut owner = FeedbackGenerationSessionV1::new(settings)?;
        let decision = owner.choose(owner.snapshot(), &actions(/*emit*/ -1.0, /*refine*/ 1e300))?;
        assert_eq!(
            decision,
            FeedbackDecisionV1 {
                action: FeedbackActionV1::Emit,
                value: -1.0,
                version: 1,
                depth: 0,
                remaining_macs: settings.budget_macs - 10
            }
        );
    }
    for budget in [0, 9] {
        assert_eq!(
            FeedbackGenerationSessionV1::new(FeedbackGenerationConfigV1 {
                budget_macs: budget,
                ..config()
            })
            .err(),
            Some(FeedbackGenerationError::InvalidConfiguration)
        );
    }
    Ok(())
}

#[test]
fn emission_wins_small_ties_independent_of_table_order() -> Result<(), Box<dyn Error>> {
    for improvement in [0.0, 0.5e-12, 1e-12] {
        let mut owner = FeedbackGenerationSessionV1::new(config())?;
        assert_eq!(
            owner
                .choose(owner.snapshot(), &actions(/*emit*/ 0.0, improvement))?
                .action,
            FeedbackActionV1::Emit
        );
    }
    Ok(())
}

#[test]
fn persistent_protocol_executes_feedback_before_next_choice() -> Result<(), Box<dyn Error>> {
    let latent = "11".repeat(32);
    let refined = "22".repeat(32);
    let input = format!(
        "INIT\t1\t22\t10\t6\t3\t2\t{latent}\n\
         CHOOSE\t1\t0\t0\t2\t{latent}\temit\t-1\t10\trefine\t-0.2\t6\n\
         CHOOSE\t1\t1\t1\t2\t{latent}\temit\t0\t10\n\
         REFINED\t1\t1\t1\t2\t{refined}\n\
         CHOOSE\t1\t1\t1\t2\t{refined}\temit\t0\t10\trefine\t-1\t6\n\
         EMITTED\t1\t2\t{latent}\t{latent}\t{latent}\t{latent}\n\
         INIT\t1\t22\t10\t6\t3\t2\t{latent}\n"
    );
    let mut output = Vec::new();
    run_feedback_generation_protocol(Cursor::new(input), &mut output)?;
    assert_eq!(
        String::from_utf8(output)?,
        "OK\tINIT\t1\t0\t22\t0\tready\n\
         OK\tCHOOSE\t1\t1\t16\t1\trefine\t-2.00000000000000011e-1\n\
         ERR\tPendingExecution\n\
         OK\tREFINED\t1\t1\t16\t1\tready\n\
         OK\tCHOOSE\t1\t2\t6\t1\temit\t0.00000000000000000e0\n\
         OK\tEMITTED\t1\t2\t6\t1\tsealed\n\
         ERR\tSessionSequence\n"
    );
    Ok(())
}

#[test]
fn bounded_protocol_rejects_oversized_and_unfinished_sessions() {
    let mut output = Vec::new();
    assert_eq!(
        run_feedback_generation_protocol(Cursor::new("x".repeat(4097)), &mut output)
            .err()
            .map(|e| e.kind()),
        Some(std::io::ErrorKind::InvalidData)
    );
    assert_eq!(output, b"ERR\tLineLimit\n");
    let input = format!("INIT\t1\t22\t10\t6\t3\t2\t{}\n", "11".repeat(32));
    assert_eq!(
        run_feedback_generation_protocol(Cursor::new(input), Vec::new())
            .err()
            .map(|e| e.kind()),
        Some(std::io::ErrorKind::UnexpectedEof)
    );
}
