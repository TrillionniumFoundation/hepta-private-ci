use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::StableId;

use crate::AtomPrecedenceV1;
use crate::AtomPredicateV1;
use crate::ConstraintAtomV1;
use crate::DeterministicOracleBudgetV1;
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
const LEGACY_MAX_ORACLE_CALLS: u16 = 257;

/// Compatibility wrapper that applies a caller-owned wall-clock availability
/// budget around the deterministic feasibility engine.
///
/// The deterministic engine never reads a clock. A wall-clock expiration is a
/// runtime exhaustion result, never semantic infeasibility. New owner code
/// should call [`check_feasibility_deterministic_v1`] inside its trusted
/// deadline/cancellation boundary and record that runtime disposition there.
pub fn check_feasibility_v1(
    registry: &RegisteredGrammarV1,
    atoms: Vec<ConstraintAtomV1>,
    budget: OracleBudgetV1,
) -> FeasibilityReceiptV1 {
    let started = Instant::now();
    if budget.wall_time.is_zero() || budget.max_calls == 0 {
        return exhausted_receipt(registry, atoms, 0, started.elapsed());
    }

    let deterministic_budget = DeterministicOracleBudgetV1 {
        max_calls: budget.max_calls.min(LEGACY_MAX_ORACLE_CALLS),
        max_work_units: u64::from(budget.max_calls.min(LEGACY_MAX_ORACLE_CALLS))
            .saturating_mul(MAX_ATOMS as u64),
        max_cache_entries: 64,
    };
    let mut receipt = check_feasibility_deterministic_v1(registry, atoms, deterministic_budget);
    let elapsed = started.elapsed();
    receipt.elapsed = elapsed;
    if elapsed >= budget.wall_time
        && !matches!(receipt.outcome, FeasibilityOutcomeV1::Unsupported { .. })
    {
        receipt.outcome = FeasibilityOutcomeV1::Exhausted;
    }
    receipt
}

/// Deterministic feasibility entrypoint.
///
/// This function is independent of host scheduling and wall clocks. It is
/// bounded only by explicit solver-call, candidate-visit and memoization
/// budgets. Budget exhaustion is reported as `Exhausted`; it is never converted
/// into an infeasibility proof.
pub fn check_feasibility_deterministic_v1(
    registry: &RegisteredGrammarV1,
    atoms: Vec<ConstraintAtomV1>,
    budget: DeterministicOracleBudgetV1,
) -> FeasibilityReceiptV1 {
    let mut oracle_calls = 0;
    let outcome = match validate(registry, &atoms) {
        Some(outcome) => outcome,
        None => {
            let mut canonical: Vec<_> = atoms
                .iter()
                .filter(|atom| atom.precedence != AtomPrecedenceV1::Soft)
                .collect();
            canonical.sort_by_key(|atom| (atom.precedence, &atom.axis, &atom.id));
            let mut oracle = OracleSessionV1::new(registry, budget);
            let outcome = match oracle.solve(&canonical) {
                Err(()) => FeasibilityOutcomeV1::Exhausted,
                Ok(Some(assignment)) => FeasibilityOutcomeV1::Feasible(assignment),
                Ok(None) => {
                    let seed = native_conflict_seed(registry, &canonical);
                    minimize(seed, &mut oracle)
                }
            };
            oracle_calls = oracle.calls;
            outcome
        }
    };
    FeasibilityReceiptV1 {
        schema_digest: registry.schema_digest,
        original_constraints: atoms,
        outcome,
        oracle_calls,
        // Runtime owners may project their own elapsed duration. Keeping the
        // semantic engine at zero makes equal inputs and budgets byte-stable.
        elapsed: Duration::ZERO,
    }
}

fn exhausted_receipt(
    registry: &RegisteredGrammarV1,
    atoms: Vec<ConstraintAtomV1>,
    oracle_calls: u16,
    elapsed: Duration,
) -> FeasibilityReceiptV1 {
    FeasibilityReceiptV1 {
        schema_digest: registry.schema_digest,
        original_constraints: atoms,
        outcome: FeasibilityOutcomeV1::Exhausted,
        oracle_calls,
        elapsed,
    }
}

struct OracleSessionV1<'a> {
    registry: &'a RegisteredGrammarV1,
    budget: DeterministicOracleBudgetV1,
    calls: u16,
    work_units: u64,
    cache: BTreeMap<Vec<StableId>, Option<FeasibleAssignmentV1>>,
}

impl<'a> OracleSessionV1<'a> {
    fn new(registry: &'a RegisteredGrammarV1, budget: DeterministicOracleBudgetV1) -> Self {
        Self {
            registry,
            budget,
            calls: 0,
            work_units: 0,
            cache: BTreeMap::new(),
        }
    }

    fn solve(
        &mut self,
        candidate: &[&ConstraintAtomV1],
    ) -> Result<Option<FeasibleAssignmentV1>, ()> {
        let key: Vec<_> = candidate.iter().map(|atom| atom.id.clone()).collect();
        if let Some(cached) = self.cache.get(&key) {
            return Ok(cached.clone());
        }

        let next_work = self
            .work_units
            .checked_add(candidate.len() as u64)
            .ok_or(())?;
        if self.calls >= self.budget.max_calls || next_work > self.budget.max_work_units {
            return Err(());
        }
        self.calls += 1;
        self.work_units = next_work;
        let result = solve(self.registry, candidate);
        if self.cache.len() < usize::from(self.budget.max_cache_entries) {
            self.cache.insert(key, result.clone());
        }
        Ok(result)
    }

    fn spare_calls_after_linear_pass(&self, core_len: usize) -> u16 {
        self.budget
            .max_calls
            .saturating_sub(self.calls)
            .saturating_sub(u16::try_from(core_len).unwrap_or(u16::MAX))
    }
}

fn minimize(
    mut core: Vec<&ConstraintAtomV1>,
    oracle: &mut OracleSessionV1<'_>,
) -> FeasibilityOutcomeV1 {
    // Deterministic contiguous batching is used only when the caller supplied
    // calls beyond the complete linear minimality pass. This keeps the legacy
    // n+1 budget compatible while allowing large future profiles to shed broad
    // irrelevant regions quickly.
    let mut chunk = core.len().checked_next_power_of_two().unwrap_or(core.len()) / 2;
    while chunk > 1 && oracle.spare_calls_after_linear_pass(core.len()) > 0 {
        let mut start = 0;
        let mut reduced = false;
        while start < core.len() && oracle.spare_calls_after_linear_pass(core.len()) > 0 {
            let end = (start + chunk).min(core.len());
            if end - start == core.len() {
                break;
            }
            let trial: Vec<_> = core[..start]
                .iter()
                .chain(core[end..].iter())
                .copied()
                .collect();
            match oracle.solve(&trial) {
                Err(()) => return FeasibilityOutcomeV1::Exhausted,
                Ok(None) => {
                    core = trial;
                    reduced = true;
                }
                Ok(Some(_)) => start = end,
            }
        }
        if !reduced {
            chunk /= 2;
        } else {
            chunk = chunk.min(core.len().saturating_sub(1));
        }
    }

    let mut index = 0;
    while index < core.len() {
        let mut trial = core.clone();
        trial.remove(index);
        match oracle.solve(&trial) {
            Err(()) => return FeasibilityOutcomeV1::Exhausted,
            Ok(None) => core = trial,
            Ok(Some(_)) => index += 1,
        }
    }
    core.sort_by_key(|atom| (atom.precedence, &atom.axis, &atom.id));
    FeasibilityOutcomeV1::Infeasible {
        inclusion_minimal_conflicting_ids: core.iter().map(|atom| atom.id.clone()).collect(),
    }
}

/// Produce a deterministic native conflict seed before the generic deletion
/// pass. Non-action domains are independent, so the first conflicting axis in
/// canonical order is sufficient. Any remaining conflict belongs to the action
/// implication graph, for which all action assumptions form a sound seed.
fn native_conflict_seed<'a>(
    registry: &RegisteredGrammarV1,
    canonical: &[&'a ConstraintAtomV1],
) -> Vec<&'a ConstraintAtomV1> {
    let mut by_axis: BTreeMap<&StableId, Vec<&ConstraintAtomV1>> = BTreeMap::new();
    for atom in canonical {
        by_axis.entry(&atom.axis).or_default().push(*atom);
    }
    for (axis_id, atoms) in &by_axis {
        let Some(axis) = registry.axes.get(*axis_id) else {
            continue;
        };
        if axis.domain != RegisteredDomainV1::Action && axis_conflicts(&axis.domain, atoms) {
            return atoms.clone();
        }
    }
    let action_seed: Vec<_> = canonical
        .iter()
        .copied()
        .filter(|atom| {
            registry
                .axes
                .get(&atom.axis)
                .is_some_and(|axis| axis.domain == RegisteredDomainV1::Action)
        })
        .collect();
    if action_seed.is_empty() {
        canonical.to_vec()
    } else {
        action_seed
    }
}

fn axis_conflicts(domain: &RegisteredDomainV1, atoms: &[&ConstraintAtomV1]) -> bool {
    match domain {
        RegisteredDomainV1::Scalar { lower, upper } => {
            let mut lower = *lower;
            let mut upper = *upper;
            for atom in atoms {
                let AtomPredicateV1::ScalarInterval {
                    lower: next_lower,
                    upper: next_upper,
                } = &atom.predicate
                else {
                    return true;
                };
                lower = lower.max(*next_lower);
                upper = upper.min(*next_upper);
                if lower > upper {
                    return true;
                }
            }
            false
        }
        RegisteredDomainV1::Enumeration(values) => {
            let mut values = values.clone();
            for atom in atoms {
                match &atom.predicate {
                    AtomPredicateV1::Include(included) => {
                        values.retain(|value| included.contains(value));
                    }
                    AtomPredicateV1::Exclude(excluded) => {
                        values.retain(|value| !excluded.contains(value));
                    }
                    _ => return true,
                }
                if values.is_empty() {
                    return true;
                }
            }
            false
        }
        RegisteredDomainV1::ImmutableIdentity(value) => atoms.iter().any(|atom| {
            !matches!(&atom.predicate, AtomPredicateV1::IdentityEqual(expected) if expected == value)
        }),
        RegisteredDomainV1::Action => false,
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
    let mut reverse_edges: BTreeMap<&StableId, Vec<&StableId>> = BTreeMap::new();
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
                reverse_edges.entry(target).or_default().push(&atom.axis);
            }
            _ => return None,
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
    let mut effectively_forbidden = forbidden.clone();
    let mut pending: VecDeque<_> = forbidden.iter().cloned().collect();
    while let Some(action) = pending.pop_front() {
        if let Some(sources) = reverse_edges.get(&action) {
            for source in sources {
                if effectively_forbidden.insert((*source).clone()) {
                    pending.push_back((*source).clone());
                }
            }
        }
    }
    if required
        .iter()
        .any(|action| effectively_forbidden.contains(action))
    {
        return None;
    }
    let unforced_actions = domains
        .iter()
        .filter(|(id, axis)| {
            axis.domain == RegisteredDomainV1::Action
                && !required.contains(*id)
                && !effectively_forbidden.contains(*id)
        })
        .map(|(id, _)| id.clone())
        .collect();
    Some(FeasibleAssignmentV1 {
        domains,
        required_actions: required,
        unforced_actions,
    })
}

#[cfg(test)]
#[path = "feasibility_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "feasibility_exhaustive_tests.rs"]
mod exhaustive_tests;
