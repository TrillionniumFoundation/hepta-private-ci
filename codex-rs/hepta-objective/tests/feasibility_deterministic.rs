use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::Duration;

use codex_hepta_objective::AtomPrecedenceV1;
use codex_hepta_objective::AtomPredicateV1;
use codex_hepta_objective::ConstraintAtomV1;
use codex_hepta_objective::ConstraintClass;
use codex_hepta_objective::DeterministicOracleBudgetV1;
use codex_hepta_objective::FeasibilityOutcomeV1;
use codex_hepta_objective::PredicateTerminality;
use codex_hepta_objective::RegisteredAxisV1;
use codex_hepta_objective::RegisteredDomainV1;
use codex_hepta_objective::RegisteredGrammarV1;
use codex_hepta_objective::check_feasibility_deterministic_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("{error}"))
}

fn registry(axis_count: usize) -> RegisteredGrammarV1 {
    let mut axes = BTreeMap::new();
    axes.insert(
        id("x"),
        RegisteredAxisV1 {
            unit: id("unit"),
            domain: RegisteredDomainV1::Scalar {
                lower: FixedQ32::from_raw(-100),
                upper: FixedQ32::from_raw(100),
            },
        },
    );
    for index in 0..axis_count {
        axes.insert(
            id(&format!("z-{index:03}")),
            RegisteredAxisV1 {
                unit: id("unit"),
                domain: RegisteredDomainV1::Scalar {
                    lower: FixedQ32::from_raw(-100),
                    upper: FixedQ32::from_raw(100),
                },
            },
        );
    }
    RegisteredGrammarV1 {
        schema_digest: Digest32::of_bytes(b"deterministic-feasibility-v1"),
        axes,
        evidence_sources: BTreeSet::from([id("observer")]),
    }
}

fn atom(name: &str, axis: &str, lower: i64, upper: i64) -> ConstraintAtomV1 {
    ConstraintAtomV1 {
        id: id(name),
        precedence: AtomPrecedenceV1::Hard(ConstraintClass::Task),
        axis: id(axis),
        predicate: AtomPredicateV1::ScalarInterval {
            lower: FixedQ32::from_raw(lower),
            upper: FixedQ32::from_raw(upper),
        },
        unit: id("unit"),
        evidence_source: id("observer"),
        terminality: PredicateTerminality::Terminal,
        origin_digest: Digest32::of_bytes(b"source"),
    }
}

fn budget() -> DeterministicOracleBudgetV1 {
    DeterministicOracleBudgetV1 {
        max_calls: 257,
        max_work_units: 65_792,
        max_cache_entries: 64,
    }
}

#[test]
fn native_seed_avoids_scanning_irrelevant_axes_during_core_minimization() {
    let mut atoms = vec![atom("a", "x", 0, 1), atom("b", "x", 2, 3)];
    for index in 0..64 {
        atoms.push(atom(
            &format!("irrelevant-{index:03}"),
            &format!("z-{index:03}"),
            -1,
            1,
        ));
    }

    let receipt = check_feasibility_deterministic_v1(&registry(64), atoms, budget());
    assert_eq!(
        receipt.outcome,
        FeasibilityOutcomeV1::Infeasible {
            inclusion_minimal_conflicting_ids: vec![id("a"), id("b")],
        }
    );
    assert_eq!(receipt.oracle_calls, 3);
    assert_eq!(receipt.elapsed, Duration::ZERO);
}

#[test]
fn deterministic_core_is_permutation_stable() {
    let left = check_feasibility_deterministic_v1(
        &registry(1),
        vec![
            atom("b", "x", 2, 3),
            atom("irrelevant", "z-000", -1, 1),
            atom("a", "x", 0, 1),
        ],
        budget(),
    );
    let right = check_feasibility_deterministic_v1(
        &registry(1),
        vec![
            atom("a", "x", 0, 1),
            atom("b", "x", 2, 3),
            atom("irrelevant", "z-000", -1, 1),
        ],
        budget(),
    );
    assert_eq!(left.outcome, right.outcome);
    assert_eq!(left.oracle_calls, right.oracle_calls);
    assert_eq!(left.elapsed, Duration::ZERO);
    assert_eq!(right.elapsed, Duration::ZERO);
}

#[test]
fn deterministic_work_exhaustion_never_claims_infeasibility() {
    let receipt = check_feasibility_deterministic_v1(
        &registry(0),
        vec![atom("a", "x", 0, 1), atom("b", "x", 2, 3)],
        DeterministicOracleBudgetV1 {
            max_calls: 257,
            max_work_units: 1,
            max_cache_entries: 64,
        },
    );
    assert_eq!(receipt.outcome, FeasibilityOutcomeV1::Exhausted);
    assert_eq!(receipt.oracle_calls, 0);
    assert_eq!(receipt.elapsed, Duration::ZERO);
}
