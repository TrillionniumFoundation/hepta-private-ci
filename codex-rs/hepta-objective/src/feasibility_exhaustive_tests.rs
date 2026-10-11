use std::error::Error;
use std::time::Duration;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::*;
use crate::ConstraintClass;
use crate::PredicateTerminality;
use crate::RegisteredAxisV1;

const EDGES: [(usize, usize); 6] = [(0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)];

#[derive(Clone, Copy)]
enum Clause {
    Require(usize),
    Forbid(usize),
    Implies(usize, usize),
}

// This oracle enumerates all eight assignments. It deliberately does not use
// the production forward/reverse graph closure or its conflict minimizer.
fn models(clauses: &[(ConstraintAtomV1, Clause)]) -> Vec<u8> {
    (0..8)
        .filter(|assignment| {
            clauses.iter().all(|(_, clause)| match *clause {
                Clause::Require(index) => assignment & (1 << index) != 0,
                Clause::Forbid(index) => assignment & (1 << index) == 0,
                Clause::Implies(source, target) => {
                    assignment & (1 << source) == 0 || assignment & (1 << target) != 0
                }
            })
        })
        .collect()
}

fn compile_clause(
    number: usize,
    clause: Clause,
    actions: &[StableId; 3],
    unit: &StableId,
    observer: &StableId,
) -> Result<(ConstraintAtomV1, Clause), Box<dyn Error>> {
    let (axis, predicate) = match clause {
        Clause::Require(index) => (index, AtomPredicateV1::RequireAction),
        Clause::Forbid(index) => (index, AtomPredicateV1::ForbidAction),
        Clause::Implies(source, target) => {
            (source, AtomPredicateV1::Implies(actions[target].clone()))
        }
    };
    Ok((
        ConstraintAtomV1 {
            id: StableId::new(format!("clause-{number:02}"))?,
            precedence: AtomPrecedenceV1::Hard(ConstraintClass::Task),
            axis: actions[axis].clone(),
            predicate,
            unit: unit.clone(),
            evidence_source: observer.clone(),
            terminality: PredicateTerminality::Terminal,
            origin_digest: Digest32::of_bytes(b"exhaustive fixture only"),
        },
        clause,
    ))
}

fn action_set(mask: u8, actions: &[StableId; 3]) -> BTreeSet<StableId> {
    actions
        .iter()
        .enumerate()
        .filter(|(index, _)| mask & (1 << index) != 0)
        .map(|(_, action)| action.clone())
        .collect()
}

#[test]
fn all_three_action_graphs_match_truth_table_and_have_minimal_conflicts()
-> Result<(), Box<dyn Error>> {
    let actions = [
        StableId::new("a")?,
        StableId::new("b")?,
        StableId::new("c")?,
    ];
    let unit = StableId::new("boolean")?;
    let observer = StableId::new("fixture-observer")?;
    let registry = RegisteredGrammarV1 {
        schema_digest: Digest32::of_bytes(b"three-action-grammar"),
        axes: actions
            .iter()
            .map(|action| {
                (
                    action.clone(),
                    RegisteredAxisV1 {
                        unit: unit.clone(),
                        domain: RegisteredDomainV1::Action,
                    },
                )
            })
            .collect(),
        evidence_sources: BTreeSet::from([observer.clone()]),
    };
    let budget = OracleBudgetV1 {
        max_calls: 257,
        wall_time: Duration::from_secs(5),
    };
    let mut cases = 0;
    for edge_mask in 0..64 {
        for required in 0..8 {
            for forbidden in 0..8 {
                let mut clauses = Vec::new();
                for (index, (source, target)) in EDGES.iter().copied().enumerate() {
                    if edge_mask & (1 << index) != 0 {
                        clauses.push(Clause::Implies(source, target));
                    }
                }
                for index in 0..3 {
                    if required & (1 << index) != 0 {
                        clauses.push(Clause::Require(index));
                    }
                    if forbidden & (1 << index) != 0 {
                        clauses.push(Clause::Forbid(index));
                    }
                }
                let clauses = clauses
                    .into_iter()
                    .enumerate()
                    .map(|(number, clause)| {
                        compile_clause(number, clause, &actions, &unit, &observer)
                    })
                    .collect::<Result<Vec<_>, _>>()?;
                let input: Vec<_> = clauses.iter().map(|(atom, _)| atom.clone()).collect();
                let receipt = check_feasibility_v1(&registry, input.clone(), budget);
                assert_eq!(receipt.original_constraints, input);
                assert_eq!(receipt.schema_digest, registry.schema_digest);
                assert!(usize::from(receipt.oracle_calls) <= input.len() + 1);
                let satisfying = models(&clauses);
                match &receipt.outcome {
                    FeasibilityOutcomeV1::Feasible(assignment) => {
                        assert!(!satisfying.is_empty());
                        let always_true = satisfying.iter().fold(7, |mask, value| mask & value);
                        let possibly_true = satisfying.iter().fold(0, |mask, value| mask | value);
                        assert_eq!(assignment.domains, registry.axes);
                        assert_eq!(
                            assignment.required_actions,
                            action_set(always_true, &actions)
                        );
                        assert_eq!(
                            assignment.unforced_actions,
                            action_set(possibly_true & !always_true, &actions)
                        );
                        assert!(satisfying.contains(&always_true));
                        assert_eq!(receipt.oracle_calls, 1);
                    }
                    FeasibilityOutcomeV1::Infeasible {
                        inclusion_minimal_conflicting_ids: ids,
                    } => {
                        assert!(satisfying.is_empty());
                        let core: Vec<_> = clauses
                            .iter()
                            .filter(|(atom, _)| ids.contains(&atom.id))
                            .cloned()
                            .collect();
                        assert_eq!(core.len(), ids.len());
                        assert!(!core.is_empty());
                        assert!(models(&core).is_empty());
                        for removed in 0..core.len() {
                            let mut trial = core.clone();
                            trial.remove(removed);
                            assert!(!models(&trial).is_empty());
                        }
                    }
                    other => panic!("bounded registered fixture returned {other:?}"),
                }
                let reversed = input.into_iter().rev().collect();
                let permuted = check_feasibility_v1(&registry, reversed, budget);
                assert_eq!(receipt.outcome, permuted.outcome);
                assert_eq!(receipt.oracle_calls, permuted.oracle_calls);
                cases += 1;
            }
        }
    }
    assert_eq!(cases, 4096);
    Ok(())
}
