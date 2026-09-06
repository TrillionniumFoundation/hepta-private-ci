use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use pretty_assertions::assert_eq;

use super::*;
use crate::ConstraintClass;
use crate::PredicateTerminality;
use crate::RegisteredAxisV1;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("{error}"))
}

fn budget() -> OracleBudgetV1 {
    OracleBudgetV1 {
        max_calls: 257,
        wall_time: Duration::from_secs(5),
    }
}

fn registry(domains: Vec<(&str, RegisteredDomainV1)>) -> RegisteredGrammarV1 {
    RegisteredGrammarV1 {
        schema_digest: Digest32::of_bytes(b"registered-v1"),
        axes: domains
            .into_iter()
            .map(|(axis, domain)| {
                (
                    id(axis),
                    RegisteredAxisV1 {
                        unit: id("unit"),
                        domain,
                    },
                )
            })
            .collect(),
        evidence_sources: BTreeSet::from([id("observer")]),
    }
}

fn atom(name: &str, axis: &str, predicate: AtomPredicateV1) -> ConstraintAtomV1 {
    ConstraintAtomV1 {
        id: id(name),
        precedence: AtomPrecedenceV1::Hard(ConstraintClass::Task),
        axis: id(axis),
        predicate,
        unit: id("unit"),
        evidence_source: id("observer"),
        terminality: PredicateTerminality::Terminal,
        origin_digest: Digest32::of_bytes(b"source"),
    }
}

fn interval(lower: i64, upper: i64) -> AtomPredicateV1 {
    AtomPredicateV1::ScalarInterval {
        lower: FixedQ32::from_raw(lower),
        upper: FixedQ32::from_raw(upper),
    }
}

fn scalar_registry() -> RegisteredGrammarV1 {
    registry(vec![(
        "x",
        RegisteredDomainV1::Scalar {
            lower: FixedQ32::from_raw(-10),
            upper: FixedQ32::from_raw(10),
        },
    )])
}

#[test]
fn interval_intersection_returns_a_witness_and_ignores_soft_constraints() {
    let mut soft = atom("soft", "x", interval(8, 9));
    soft.precedence = AtomPrecedenceV1::Soft;
    let receipt = check_feasibility_v1(
        &scalar_registry(),
        vec![
            atom("a", "x", interval(0, 2)),
            atom("b", "x", interval(1, 3)),
            soft,
        ],
        budget(),
    );
    let expected = registry(vec![(
        "x",
        RegisteredDomainV1::Scalar {
            lower: FixedQ32::from_raw(1),
            upper: FixedQ32::from_raw(2),
        },
    )]);
    assert_eq!(
        receipt.outcome,
        FeasibilityOutcomeV1::Feasible(FeasibleAssignmentV1 {
            domains: expected.axes,
            required_actions: BTreeSet::new(),
            unforced_actions: BTreeSet::new()
        })
    );
    assert_eq!(receipt.oracle_calls, 1);
}

#[test]
fn core_is_permutation_invariant_and_removes_irrelevant_atoms() {
    let atoms = [
        atom("a", "x", interval(0, 1)),
        atom("b", "x", interval(2, 3)),
        atom("irrelevant", "x", interval(-5, 5)),
    ];
    for order in [
        [0, 1, 2],
        [0, 2, 1],
        [1, 0, 2],
        [1, 2, 0],
        [2, 0, 1],
        [2, 1, 0],
    ] {
        let input = order.map(|index| atoms[index].clone()).to_vec();
        let result = check_feasibility_v1(&scalar_registry(), input.clone(), budget());
        assert_eq!(result.original_constraints, input);
        assert_eq!(
            result.outcome,
            FeasibilityOutcomeV1::Infeasible {
                inclusion_minimal_conflicting_ids: vec![id("a"), id("b")]
            }
        );
        assert_eq!(result.oracle_calls, 4);
    }
}

#[test]
fn finite_enum_inclusion_and_exclusion_are_intersected() {
    let registered = registry(vec![(
        "color",
        RegisteredDomainV1::Enumeration(BTreeSet::from([id("red"), id("blue"), id("green")])),
    )]);
    let mut atoms = vec![
        atom(
            "include",
            "color",
            AtomPredicateV1::Include(BTreeSet::from([id("red"), id("blue")])),
        ),
        atom(
            "exclude-blue",
            "color",
            AtomPredicateV1::Exclude(BTreeSet::from([id("blue")])),
        ),
    ];
    let feasible = check_feasibility_v1(&registered, atoms.clone(), budget());
    let mut expected = registered.axes.clone();
    expected
        .get_mut(&id("color"))
        .unwrap_or_else(|| panic!("missing color"))
        .domain = RegisteredDomainV1::Enumeration(BTreeSet::from([id("red")]));
    assert_eq!(
        feasible.outcome,
        FeasibilityOutcomeV1::Feasible(FeasibleAssignmentV1 {
            domains: expected,
            required_actions: BTreeSet::new(),
            unforced_actions: BTreeSet::new()
        })
    );
    atoms.push(atom(
        "exclude-red",
        "color",
        AtomPredicateV1::Exclude(BTreeSet::from([id("red")])),
    ));
    assert_eq!(
        check_feasibility_v1(&registered, atoms, budget()).outcome,
        FeasibilityOutcomeV1::Infeasible {
            inclusion_minimal_conflicting_ids: vec![
                id("exclude-blue"),
                id("exclude-red"),
                id("include")
            ]
        }
    );
}

#[test]
fn immutable_scope_and_generation_must_match_the_registered_snapshot() {
    let registered = registry(vec![
        (
            "scope",
            RegisteredDomainV1::ImmutableIdentity(IdentityValueV1::Scope(id("principal-a"))),
        ),
        (
            "generation",
            RegisteredDomainV1::ImmutableIdentity(IdentityValueV1::Generation(7)),
        ),
    ]);
    let valid = vec![
        atom(
            "scope-eq",
            "scope",
            AtomPredicateV1::IdentityEqual(IdentityValueV1::Scope(id("principal-a"))),
        ),
        atom(
            "generation-eq",
            "generation",
            AtomPredicateV1::IdentityEqual(IdentityValueV1::Generation(7)),
        ),
    ];
    assert!(matches!(
        check_feasibility_v1(&registered, valid.clone(), budget()).outcome,
        FeasibilityOutcomeV1::Feasible(_)
    ));
    let mut stale = valid;
    stale[1].predicate = AtomPredicateV1::IdentityEqual(IdentityValueV1::Generation(6));
    assert_eq!(
        check_feasibility_v1(&registered, stale, budget()).outcome,
        FeasibilityOutcomeV1::Infeasible {
            inclusion_minimal_conflicting_ids: vec![id("generation-eq")]
        }
    );
}

#[test]
fn unsupported_atoms_are_detected_before_a_known_conflict() {
    let atoms = vec![
        atom("a", "x", interval(0, 1)),
        atom("b", "x", interval(2, 3)),
        atom(
            "nonlinear",
            "x",
            AtomPredicateV1::Unsupported(id("nonlinear")),
        ),
    ];
    let result = check_feasibility_v1(&scalar_registry(), atoms.clone(), budget());
    assert_eq!(
        result.outcome,
        FeasibilityOutcomeV1::Unsupported {
            reason: "unregistered or unsupported atom",
            atom_ids: vec![id("nonlinear")]
        }
    );
    assert_eq!(result.oracle_calls, 0);
    assert_eq!(result.original_constraints, atoms);
}

#[test]
fn unknown_axes_units_observers_and_origins_fail_closed() {
    let mut cases = vec![atom("a", "unknown", interval(0, 1)); 4];
    cases[1] = atom("a", "x", interval(0, 1));
    cases[1].unit = id("other-unit");
    cases[2] = atom("a", "x", interval(0, 1));
    cases[2].evidence_source = id("unknown-observer");
    cases[3] = atom("a", "x", interval(0, 1));
    cases[3].origin_digest = Digest32::from_array([0; 32]);
    for candidate in cases {
        let result = check_feasibility_v1(&scalar_registry(), vec![candidate], budget());
        assert!(matches!(
            result.outcome,
            FeasibilityOutcomeV1::Unsupported { .. }
        ));
        assert_eq!(result.oracle_calls, 0);
    }
}

#[test]
fn exhaustion_never_exposes_a_partial_conflict_or_drops_an_atom() {
    let atoms = vec![
        atom("a", "x", interval(0, 1)),
        atom("b", "x", interval(2, 3)),
        atom("0-irrelevant", "x", interval(-5, 5)),
    ];
    for limited in [
        OracleBudgetV1 {
            max_calls: 2,
            ..budget()
        },
        OracleBudgetV1 {
            max_calls: 0,
            ..budget()
        },
        OracleBudgetV1 {
            wall_time: Duration::ZERO,
            ..budget()
        },
    ] {
        let result = check_feasibility_v1(&scalar_registry(), atoms.clone(), limited);
        assert_eq!(result.outcome, FeasibilityOutcomeV1::Exhausted);
        assert_eq!(result.original_constraints, atoms);
        assert!(result.oracle_calls <= limited.max_calls);
    }
}

#[test]
fn pilot_atom_bound_and_maximum_oracle_count_are_enforced() {
    let mut atoms = vec![
        atom("a", "x", interval(0, 1)),
        atom("b", "x", interval(2, 3)),
    ];
    atoms.extend((2..256).map(|i| atom(&format!("irrelevant-{i:03}"), "x", interval(-5, 5))));
    let result = check_feasibility_v1(
        &scalar_registry(),
        atoms.clone(),
        OracleBudgetV1 {
            max_calls: u16::MAX,
            ..budget()
        },
    );
    assert!(matches!(
        result.outcome,
        FeasibilityOutcomeV1::Infeasible { .. }
    ));
    assert_eq!(result.oracle_calls, 257);
    atoms.push(atom("overflow", "x", interval(-5, 5)));
    let result = check_feasibility_v1(&scalar_registry(), atoms.clone(), budget());
    assert!(matches!(
        result.outcome,
        FeasibilityOutcomeV1::Unsupported { .. }
    ));
    assert_eq!(result.original_constraints, atoms);
    assert_eq!(result.oracle_calls, 0);
}

#[test]
fn registry_action_limit_is_checked_before_solving() {
    let mut registered = registry(Vec::new());
    registered.axes.extend((0..129).map(|i| {
        (
            id(&format!("action-{i}")),
            RegisteredAxisV1 {
                unit: id("unit"),
                domain: RegisteredDomainV1::Action,
            },
        )
    }));
    assert_eq!(
        check_feasibility_v1(&registered, Vec::new(), budget()).outcome,
        FeasibilityOutcomeV1::Unsupported {
            reason: "invalid registered profile",
            atom_ids: Vec::new()
        }
    );
}

fn boolean_truth_table(atoms: &[ConstraintAtomV1]) -> bool {
    (0_u8..4).any(|assignment| {
        atoms.iter().all(|atom| {
            let enabled =
                |axis: &StableId| assignment & if axis.as_str() == "a" { 1 } else { 2 } != 0;
            match &atom.predicate {
                AtomPredicateV1::RequireAction => enabled(&atom.axis),
                AtomPredicateV1::ForbidAction => !enabled(&atom.axis),
                AtomPredicateV1::Implies(target) => !enabled(&atom.axis) || enabled(target),
                _ => panic!("non-boolean fixture"),
            }
        })
    })
}

#[test]
fn horn_solver_and_each_minimal_core_match_exhaustive_boolean_assignments() {
    let registered = registry(vec![
        ("a", RegisteredDomainV1::Action),
        ("b", RegisteredDomainV1::Action),
    ]);
    // Every two-node graph includes self edges, mutual cycles and disconnected nodes.
    for edges in 0_u8..16 {
        for required in 0_u8..4 {
            for forbidden in 0_u8..4 {
                let mut atoms = Vec::new();
                for (index, axis) in ["a", "b"].iter().enumerate() {
                    if required & (1 << index) != 0 {
                        atoms.push(atom(
                            &format!("require-{axis}"),
                            axis,
                            AtomPredicateV1::RequireAction,
                        ));
                    }
                    if forbidden & (1 << index) != 0 {
                        atoms.push(atom(
                            &format!("forbid-{axis}"),
                            axis,
                            AtomPredicateV1::ForbidAction,
                        ));
                    }
                    for (target_index, target) in ["a", "b"].iter().enumerate() {
                        if edges & (1 << (index * 2 + target_index)) != 0 {
                            atoms.push(atom(
                                &format!("edge-{axis}-{target}"),
                                axis,
                                AtomPredicateV1::Implies(id(target)),
                            ));
                        }
                    }
                }
                let result = check_feasibility_v1(&registered, atoms.clone(), budget());
                assert_eq!(
                    matches!(result.outcome, FeasibilityOutcomeV1::Feasible(_)),
                    boolean_truth_table(&atoms)
                );
                if let FeasibilityOutcomeV1::Infeasible {
                    inclusion_minimal_conflicting_ids,
                } = result.outcome
                {
                    let core: Vec<_> = atoms
                        .into_iter()
                        .filter(|atom| inclusion_minimal_conflicting_ids.contains(&atom.id))
                        .collect();
                    assert!(!boolean_truth_table(&core));
                    for index in 0..core.len() {
                        let mut trial = core.clone();
                        trial.remove(index);
                        assert!(boolean_truth_table(&trial));
                    }
                }
            }
        }
    }
}

#[test]
fn positive_closure_enables_only_forced_actions_and_terminates_cycles() {
    let registered = registry(vec![
        ("a", RegisteredDomainV1::Action),
        ("b", RegisteredDomainV1::Action),
        ("unused", RegisteredDomainV1::Action),
    ]);
    let atoms = vec![
        atom("required", "a", AtomPredicateV1::RequireAction),
        atom("ab", "a", AtomPredicateV1::Implies(id("b"))),
        atom("ba", "b", AtomPredicateV1::Implies(id("a"))),
    ];
    assert_eq!(
        check_feasibility_v1(&registered, atoms, budget()).outcome,
        FeasibilityOutcomeV1::Feasible(FeasibleAssignmentV1 {
            domains: registered.axes,
            required_actions: BTreeSet::from([id("a"), id("b")]),
            unforced_actions: BTreeSet::from([id("unused")])
        })
    );
}
