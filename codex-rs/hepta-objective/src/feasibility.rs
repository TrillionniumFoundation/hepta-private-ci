use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::time::Instant;

use codex_hepta_types::StableId;

use crate::AtomPrecedenceV1;
use crate::AtomPredicateV1;
use crate::ConstraintAtomV1;
use crate::FeasibilityOutcomeV1;
use crate::FeasibilityReceiptV1;
use crate::FeasibleAssignmentV1;
use crate::IdentityValueV1;
use crate::OracleBudgetV1;
use crate::RegisteredDomainV1;
use crate::RegisteredGrammarV1;

const MAX_ATOMS: usize = 256;
const MAX_ACTIONS: usize = 128;
const MAX_ENUM_VALUES: usize = 128;
const MAX_PAYLOAD_BYTES: usize = 256 * 1024;

/// Solves registered conjunctions and extracts an inclusion-minimal core with
/// at most n + 1 oracle calls. Unsupported or expired work publishes no core.
pub fn check_feasibility_v1(
    registry: &RegisteredGrammarV1,
    atoms: Vec<ConstraintAtomV1>,
    budget: OracleBudgetV1,
) -> FeasibilityReceiptV1 {
    let start = Instant::now();
    let mut oracle_calls = 0;
    let outcome = match validate(registry, &atoms) {
        Some(outcome) => outcome,
        None => {
            let mut canonical: Vec<_> = atoms
                .iter()
                .filter(|atom| atom.precedence != AtomPrecedenceV1::Soft)
                .collect();
            canonical.sort_by_key(|atom| (atom.precedence, &atom.axis, &atom.id));
            let mut oracle = |candidate: &[&ConstraintAtomV1]| {
                if oracle_calls >= budget.max_calls.min(257) || start.elapsed() >= budget.wall_time
                {
                    return Err(());
                }
                oracle_calls += 1;
                let result = solve(registry, candidate);
                if start.elapsed() >= budget.wall_time {
                    Err(())
                } else {
                    Ok(result)
                }
            };
            match oracle(&canonical) {
                Err(()) => FeasibilityOutcomeV1::Exhausted,
                Ok(Some(assignment)) => FeasibilityOutcomeV1::Feasible(assignment),
                Ok(None) => minimize(canonical, &mut oracle),
            }
        }
    };
    let elapsed = start.elapsed();
    let outcome = if elapsed >= budget.wall_time
        && !matches!(outcome, FeasibilityOutcomeV1::Unsupported { .. })
    {
        FeasibilityOutcomeV1::Exhausted
    } else {
        outcome
    };
    FeasibilityReceiptV1 {
        schema_digest: registry.schema_digest,
        original_constraints: atoms,
        outcome,
        oracle_calls,
        elapsed,
    }
}

fn minimize(
    mut core: Vec<&ConstraintAtomV1>,
    oracle: &mut impl FnMut(&[&ConstraintAtomV1]) -> Result<Option<FeasibleAssignmentV1>, ()>,
) -> FeasibilityOutcomeV1 {
    let mut index = 0;
    while index < core.len() {
        let mut trial = core.clone();
        trial.remove(index);
        match oracle(&trial) {
            Err(()) => return FeasibilityOutcomeV1::Exhausted,
            Ok(None) => core = trial,
            Ok(Some(_)) => index += 1,
        }
    }
    FeasibilityOutcomeV1::Infeasible {
        inclusion_minimal_conflicting_ids: core.iter().map(|atom| atom.id.clone()).collect(),
    }
}

fn validate(
    registry: &RegisteredGrammarV1,
    atoms: &[ConstraintAtomV1],
) -> Option<FeasibilityOutcomeV1> {
    let reject = |reason, atom_ids| Some(FeasibilityOutcomeV1::Unsupported { reason, atom_ids });
    if atoms.len() > MAX_ATOMS
        || registry.axes.len() > MAX_ATOMS
        || registry.evidence_sources.len() > MAX_ATOMS
    {
        return reject("pilot count bound", Vec::new());
    }
    let mut actions = 0;
    // Conservative payload allowance for the bounded in-process grammar, not a wire encoding.
    let mut bytes = registry
        .evidence_sources
        .iter()
        .map(|id| id.as_str().len() + 8)
        .sum::<usize>();
    for (id, axis) in &registry.axes {
        bytes += id.as_str().len() + axis.unit.as_str().len() + 64;
        match &axis.domain {
            RegisteredDomainV1::Scalar { lower, upper } if lower > upper => {
                return reject("invalid registered interval", Vec::new());
            }
            RegisteredDomainV1::Enumeration(values) => {
                if values.is_empty() || values.len() > MAX_ENUM_VALUES {
                    return reject("invalid registered enum", Vec::new());
                }
                bytes += values
                    .iter()
                    .map(|value| value.as_str().len() + 8)
                    .sum::<usize>();
            }
            RegisteredDomainV1::Action => actions += 1,
            RegisteredDomainV1::ImmutableIdentity(IdentityValueV1::Scope(scope)) => {
                bytes += scope.as_str().len()
            }
            RegisteredDomainV1::Scalar { .. }
            | RegisteredDomainV1::ImmutableIdentity(IdentityValueV1::Generation(_)) => {}
        }
    }
    if actions > MAX_ACTIONS || registry.schema_digest.is_zero() {
        return reject("invalid registered profile", Vec::new());
    }
    let mut ids = BTreeSet::new();
    let mut unsupported = Vec::new();
    for atom in atoms {
        if !ids.insert(&atom.id) {
            return reject("duplicate atom identity", vec![atom.id.clone()]);
        }
        bytes += atom.id.as_str().len()
            + atom.axis.as_str().len()
            + atom.unit.as_str().len()
            + atom.evidence_source.as_str().len()
            + 256;
        if let AtomPredicateV1::Include(values) | AtomPredicateV1::Exclude(values) = &atom.predicate
        {
            if values.len() > MAX_ENUM_VALUES {
                return reject("enum atom count bound", vec![atom.id.clone()]);
            }
            bytes += values
                .iter()
                .map(|value| value.as_str().len() + 8)
                .sum::<usize>();
        }
        if !supported(registry, atom) {
            unsupported.push(atom.id.clone());
        }
    }
    if bytes > MAX_PAYLOAD_BYTES {
        return reject("pilot payload bound", Vec::new());
    }
    if unsupported.is_empty() {
        None
    } else {
        unsupported.sort();
        reject("unregistered or unsupported atom", unsupported)
    }
}

fn supported(registry: &RegisteredGrammarV1, atom: &ConstraintAtomV1) -> bool {
    let Some(axis) = registry.axes.get(&atom.axis) else {
        return false;
    };
    if axis.unit != atom.unit
        || atom.origin_digest.is_zero()
        || !registry.evidence_sources.contains(&atom.evidence_source)
    {
        return false;
    }
    match (&axis.domain, &atom.predicate) {
        (RegisteredDomainV1::Scalar { .. }, AtomPredicateV1::ScalarInterval { .. }) => true,
        (
            RegisteredDomainV1::Enumeration(domain),
            AtomPredicateV1::Include(values) | AtomPredicateV1::Exclude(values),
        ) => values.is_subset(domain),
        (
            RegisteredDomainV1::Action,
            AtomPredicateV1::RequireAction | AtomPredicateV1::ForbidAction,
        ) => true,
        (RegisteredDomainV1::Action, AtomPredicateV1::Implies(target)) => {
            registry.axes.get(target).is_some_and(|target| {
                target.domain == RegisteredDomainV1::Action && target.unit == atom.unit
            })
        }
        (
            RegisteredDomainV1::ImmutableIdentity(IdentityValueV1::Scope(_)),
            AtomPredicateV1::IdentityEqual(IdentityValueV1::Scope(_)),
        )
        | (
            RegisteredDomainV1::ImmutableIdentity(IdentityValueV1::Generation(_)),
            AtomPredicateV1::IdentityEqual(IdentityValueV1::Generation(_)),
        ) => true,
        _ => false,
    }
}

fn solve(
    registry: &RegisteredGrammarV1,
    atoms: &[&ConstraintAtomV1],
) -> Option<FeasibleAssignmentV1> {
    let mut domains = registry.axes.clone();
    let mut required = BTreeSet::new();
    let mut forbidden = BTreeSet::new();
    let mut edges: BTreeMap<&StableId, Vec<&StableId>> = BTreeMap::new();
    for atom in atoms {
        let axis = domains.get_mut(&atom.axis)?;
        match (&mut axis.domain, &atom.predicate) {
            (
                RegisteredDomainV1::Scalar { lower, upper },
                AtomPredicateV1::ScalarInterval {
                    lower: next_lower,
                    upper: next_upper,
                },
            ) => {
                *lower = (*lower).max(*next_lower);
                *upper = (*upper).min(*next_upper);
                if lower > upper {
                    return None;
                }
            }
            (RegisteredDomainV1::Enumeration(values), AtomPredicateV1::Include(included)) => {
                values.retain(|value| included.contains(value));
                if values.is_empty() {
                    return None;
                }
            }
            (RegisteredDomainV1::Enumeration(values), AtomPredicateV1::Exclude(excluded)) => {
                values.retain(|value| !excluded.contains(value));
                if values.is_empty() {
                    return None;
                }
            }
            (
                RegisteredDomainV1::ImmutableIdentity(value),
                AtomPredicateV1::IdentityEqual(expected),
            ) => {
                if value != expected {
                    return None;
                }
            }
            (RegisteredDomainV1::Action, AtomPredicateV1::RequireAction) => {
                required.insert(atom.axis.clone());
            }
            (RegisteredDomainV1::Action, AtomPredicateV1::ForbidAction) => {
                forbidden.insert(atom.axis.clone());
            }
            (RegisteredDomainV1::Action, AtomPredicateV1::Implies(target)) => {
                edges.entry(&atom.axis).or_default().push(target);
            }
            _ => return None, // Validation runs once before any oracle call.
        }
    }
    let mut pending: VecDeque<_> = required.iter().cloned().collect();
    while let Some(action) = pending.pop_front() {
        if forbidden.contains(&action) {
            return None;
        }
        if let Some(targets) = edges.get(&action) {
            for target in targets {
                if required.insert((*target).clone()) {
                    pending.push_back((*target).clone());
                }
            }
        }
    }
    let unforced_actions = domains
        .iter()
        .filter(|(id, axis)| axis.domain == RegisteredDomainV1::Action && !required.contains(*id))
        .map(|(id, _)| id.clone())
        .collect();
    Some(FeasibleAssignmentV1 {
        domains,
        required_actions: required,
        unforced_actions,
    })
}
