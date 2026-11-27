use std::collections::BTreeSet;
use std::fmt::Debug;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use crate::AxisValue;
use crate::NduError;
use crate::NduIterationContextV1;
use crate::NduLegacyIterationReceiptV1 as NduIterationReceiptV1;
use crate::PreferenceState;
use crate::SubjectClass;
use crate::bind_legacy_solver_iteration_receipt_v1 as bind_solver_iteration_receipt_v1;
use crate::bind_solver_iteration_receipt_v2;
use crate::solve_preference_target;
use crate::solve_preference_target_with_context_v2;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn context() -> NduIterationContextV1 {
    NduIterationContextV1 {
        subject_id: id("agent-a"),
        subject_class: SubjectClass::Agent,
        objective_digest: digest("objective"),
        generation: must(Generation::new(/*value*/ 4)),
        event_digest: digest("event"),
        coefficient_digest: digest("coefficient"),
    }
}

fn target(value: FixedQ32) -> Vec<AxisValue> {
    vec![AxisValue {
        axis: id("quality"),
        value,
    }]
}

fn initial(value: FixedQ32) -> PreferenceState {
    must(PreferenceState::genesis(
        id("agent-a"),
        SubjectClass::Agent,
        target(value),
    ))
}

#[test]
fn legacy_v1_layout_and_digest_remain_compatible() {
    let (_, _, steps) = must(solve_preference_target(
        initial(FixedQ32::ZERO),
        target(FixedQ32::ONE),
        FixedQ32::from_raw(/*raw*/ 1_i64 << 30),
    ));
    let context = context();
    let step = steps.first().expect("a real first solver step");
    let actual = must(bind_solver_iteration_receipt_v1(&context, step));
    // This literal uses every original public field. The expected digest is a
    // fixed V1 byte vector, independent of either new V2 hashing helper.
    let expected = NduIterationReceiptV1 {
        subject_id: id("agent-a"),
        subject_class: SubjectClass::Agent,
        objective_digest: digest("objective"),
        generation: must(Generation::new(/*value*/ 4)),
        event_digest: digest("event"),
        coefficient_digest: digest("coefficient"),
        iteration: 1,
        predecessor_revision: must(Revision::new(/*value*/ 1)),
        next_revision: must(Revision::new(/*value*/ 2)),
        residual_raw: 3_i64 << 30,
        projection_count: 0,
        state_digest: must(
            "643db2e907e3453bf08c5ba3548dd8f02498fd93c1bf1ded262100e0771cf61e".parse(),
        ),
        receipt_digest: must(
            "f02084af3d74afdad1cb4aff885b1d298a49137d12c854ab61452dc9f726b58a".parse(),
        ),
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(actual, expected);

    // V1 retains its historical adapter semantics. A fresh claimed context
    // changes the old digest but does not acquire V2 invocation provenance.
    let changed = NduIterationContextV1 {
        objective_digest: digest("another-objective"),
        ..context
    };
    let rebound = must(bind_solver_iteration_receipt_v1(&changed, step));
    assert_ne!(rebound.receipt_digest, actual.receipt_digest);
    assert_eq!(rebound.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn v2_digest_matches_source_bound_input_and_preserves_denial() {
    let context = context();
    let (_, _, steps) = must(solve_preference_target_with_context_v2(
        initial(FixedQ32::ZERO),
        target(FixedQ32::ONE),
        FixedQ32::from_raw(/*raw*/ 1_i64 << 30),
        &context,
    ));
    let step = steps.first().expect("a source-bound first solver step");
    let receipt = must(bind_solver_iteration_receipt_v2(&context, step));
    must(receipt.validate());
    assert_eq!(
        (
            step.source_context_digest(),
            step.solve_input_digest(),
            receipt.solve_input_digest(),
            receipt.receipt_digest(),
            receipt.authority(),
        ),
        (
            must("646822ecc21ff53b03ed84533ff15095491cc1d360e395940f78552a6425c28d".parse()),
            must("e8f49e9851129a98fb91e56ad59ffbfe646940ab0591207a50069c5efd1a5649".parse()),
            must("e8f49e9851129a98fb91e56ad59ffbfe646940ab0591207a50069c5efd1a5649".parse()),
            must("6441584ee960224705d6ea35dbb7d349bb490c2f88f36e7dbed185fe543076b3".parse()),
            AuthorityPosture::DENY_ALL,
        )
    );
    let legacy = must(bind_solver_iteration_receipt_v1(
        &context,
        step.solver_step(),
    ));
    assert_ne!(receipt.receipt_digest(), legacy.receipt_digest);
}

#[test]
fn v2_preserves_the_legacy_numerical_result_and_target_order() {
    let context = context();
    let initial = must(PreferenceState::genesis(
        context.subject_id.clone(),
        context.subject_class,
        vec![
            AxisValue {
                axis: id("a"),
                value: FixedQ32::ZERO,
            },
            AxisValue {
                axis: id("z"),
                value: FixedQ32::ZERO,
            },
        ],
    ));
    let mut target = vec![
        AxisValue {
            axis: id("z"),
            value: FixedQ32::ONE,
        },
        AxisValue {
            axis: id("a"),
            value: FixedQ32::ONE,
        },
    ];
    let eta = FixedQ32::from_raw(/*raw*/ 1_i64 << 30);
    let legacy = must(solve_preference_target(
        initial.clone(),
        target.clone(),
        eta,
    ));
    let bound = must(solve_preference_target_with_context_v2(
        initial.clone(),
        target.clone(),
        eta,
        &context,
    ));
    target.reverse();
    let reordered = must(solve_preference_target_with_context_v2(
        initial, target, eta, &context,
    ));
    assert_eq!(bound, reordered);
    let plain_steps: Vec<_> = bound
        .2
        .iter()
        .map(|step| step.solver_step().clone())
        .collect();
    assert_eq!((bound.0, bound.1, plain_steps), legacy);
}

#[test]
fn v2_rejects_context_rebinding() {
    let original = context();
    let (_, _, steps) = must(solve_preference_target_with_context_v2(
        initial(FixedQ32::ZERO),
        target(FixedQ32::ONE),
        FixedQ32::from_raw(/*raw*/ 1_i64 << 30),
        &original,
    ));
    let step = steps.first().expect("a real source-bound solver step");
    for changed in [
        NduIterationContextV1 {
            objective_digest: digest("changed"),
            ..original.clone()
        },
        NduIterationContextV1 {
            event_digest: digest("changed"),
            ..original.clone()
        },
        NduIterationContextV1 {
            coefficient_digest: digest("changed"),
            ..original.clone()
        },
        NduIterationContextV1 {
            generation: must(Generation::new(/*value*/ 5)),
            ..original.clone()
        },
    ] {
        assert_eq!(
            bind_solver_iteration_receipt_v2(&changed, step),
            Err(NduError::InvalidSolverReceipt("solve context mismatch"))
        );
    }
    for changed in [
        NduIterationContextV1 {
            subject_id: id("agent-b"),
            ..original.clone()
        },
        NduIterationContextV1 {
            subject_class: SubjectClass::Domain,
            ..original.clone()
        },
    ] {
        assert_eq!(
            bind_solver_iteration_receipt_v2(&changed, step),
            Err(NduError::ProtocolSubjectMismatch)
        );
    }
    must(bind_solver_iteration_receipt_v2(&original, step));
}

#[test]
fn v2_source_identity_changes_with_each_numerical_input() {
    let context = context();
    let mut identities = BTreeSet::new();
    for (start, desired, eta) in [
        (0, 1_i64 << 32, 1_i64 << 30),
        (0, 1_i64 << 31, 1_i64 << 30),
        (0, 1_i64 << 32, 7_i64 << 27),
        (1_i64 << 29, 1_i64 << 32, 1_i64 << 30),
    ] {
        let (_, _, steps) = must(solve_preference_target_with_context_v2(
            initial(FixedQ32::from_raw(start)),
            target(FixedQ32::from_raw(desired)),
            FixedQ32::from_raw(eta),
            &context,
        ));
        let step = steps.first().expect("a source-bound solver step");
        let receipt = must(bind_solver_iteration_receipt_v2(&context, step));
        must(receipt.validate());
        assert!(identities.insert(step.solve_input_digest()));
    }
}

#[test]
fn v2_rejects_invalid_context_state_and_dimension() {
    let context = context();
    let eta = FixedQ32::from_raw(/*raw*/ 1_i64 << 30);
    let changed = NduIterationContextV1 {
        objective_digest: Digest32::ZERO,
        ..context.clone()
    };
    assert_eq!(
        solve_preference_target_with_context_v2(
            initial(FixedQ32::ZERO),
            target(FixedQ32::ONE),
            eta,
            &changed
        ),
        Err(NduError::EmptyProtocolDigest("objective"))
    );
    let changed = NduIterationContextV1 {
        subject_id: id("agent-b"),
        ..context
    };
    assert_eq!(
        solve_preference_target_with_context_v2(
            initial(FixedQ32::ZERO),
            target(FixedQ32::ONE),
            eta,
            &changed
        ),
        Err(NduError::ProtocolSubjectMismatch)
    );
    let mut invalid = initial(FixedQ32::ZERO);
    invalid.state_digest = digest("wrong-state");
    assert_eq!(
        solve_preference_target_with_context_v2(invalid, target(FixedQ32::ONE), eta, &context),
        Err(NduError::StateDigestMismatch)
    );
    for invalid_target in [
        Vec::new(),
        vec![
            AxisValue {
                axis: id("quality"),
                value: FixedQ32::ONE
            };
            65
        ],
    ] {
        assert_eq!(
            solve_preference_target_with_context_v2(
                initial(FixedQ32::ZERO),
                invalid_target,
                eta,
                &context
            ),
            Err(NduError::PreferenceDimensionLimitExceeded)
        );
    }
    // Source binding does not turn kernel exhaustion into successful evidence.
    assert_eq!(
        solve_preference_target_with_context_v2(
            initial(FixedQ32::ZERO),
            target(FixedQ32::ONE),
            FixedQ32::from_raw(/*raw*/ 1_i64 << 28),
            &context
        )
        .unwrap_err(),
        solve_preference_target(
            initial(FixedQ32::ZERO),
            target(FixedQ32::ONE),
            FixedQ32::from_raw(/*raw*/ 1_i64 << 28)
        )
        .unwrap_err()
    );
}

#[test]
fn v2_zero_step_termination_has_no_step_evidence() {
    let context = context();
    let eta = FixedQ32::from_raw(/*raw*/ 1_i64 << 30);
    let initial = initial(FixedQ32::ONE);
    let legacy = must(solve_preference_target(
        initial.clone(),
        target(FixedQ32::ONE),
        eta,
    ));
    let bound = must(solve_preference_target_with_context_v2(
        initial,
        target(FixedQ32::ONE),
        eta,
        &context,
    ));
    assert!(bound.2.is_empty());
    assert_eq!((bound.0, bound.1), (legacy.0, legacy.1));
    assert!(legacy.2.is_empty());
}

#[test]
fn v2_validation_detects_changed_sealed_fields() {
    let context = context();
    let (_, _, steps) = must(solve_preference_target_with_context_v2(
        initial(FixedQ32::ZERO),
        target(FixedQ32::ONE),
        FixedQ32::from_raw(/*raw*/ 1_i64 << 30),
        &context,
    ));
    let receipt = must(bind_solver_iteration_receipt_v2(
        &context,
        steps.first().expect("first step"),
    ));
    let mut changed = receipt.clone();
    changed.context.coefficient_digest = digest("changed");
    assert_eq!(
        changed.validate(),
        Err(NduError::InvalidSolverReceipt("solve context mismatch"))
    );
    let mut changed = receipt.clone();
    changed.source.solve_input_digest = digest("changed");
    assert_eq!(
        changed.validate(),
        Err(NduError::InvalidSolverReceipt("V2 receipt digest"))
    );
    let mut changed = receipt.clone();
    changed.receipt_digest = digest("changed");
    assert_eq!(
        changed.validate(),
        Err(NduError::InvalidSolverReceipt("V2 receipt digest"))
    );
    must(receipt.validate());
}

#[test]
fn explicit_legacy_binding_does_not_upgrade_an_unbound_step() {
    let context = context();
    let (_, _, steps) = must(solve_preference_target(
        initial(FixedQ32::ZERO),
        target(FixedQ32::ONE),
        FixedQ32::from_raw(/*raw*/ 1_i64 << 30),
    ));
    let step = steps.first().expect("a context-free solver step");
    let before = step.clone();
    let legacy = must(bind_solver_iteration_receipt_v1(&context, step));
    assert_eq!(step, &before);
    assert_eq!(legacy.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        crate::bind_solver_iteration_receipt_v1(&context, step),
        Err(NduError::InvalidSolverReceipt(
            "solve context mismatch or unbound legacy step"
        ))
    );
    assert_eq!(
        crate::bind_legacy_solver_iteration_receipt_v2(&context, step),
        Err(crate::NduEvidenceV2Error::ContextMismatch)
    );
}
