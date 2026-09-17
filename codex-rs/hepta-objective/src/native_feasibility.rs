use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::Duration;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::AtomPrecedenceV1;
use crate::AtomPredicateV1;
use crate::ConstraintAtomV1;
use crate::ConstraintRelation;
use crate::FeasibilityReceiptV1;
use crate::ObjectiveError;
use crate::ObjectiveSourceEnvelope;
use crate::OracleBudgetV1;
use crate::PredicateTerminality;
use crate::RegisteredAxisV1;
use crate::RegisteredDomainV1;
use crate::RegisteredGrammarV1;
use crate::check_feasibility_v1;

/// Project the native V1 objective IR into the general registered feasibility
/// engine before objective freezing.
///
/// The native V1 IR currently carries normalized scalar hard constraints. This
/// projection is therefore scalar for those fields, but it is deliberately the
/// same `RegisteredGrammarV1` / `ConstraintAtomV1` engine used by richer enum,
/// action-implication and immutable-identity callers. `ObjectiveSourceEnvelopeV1`
/// must not claim those richer source semantics until its bounded wire grammar
/// carries the corresponding payloads and admission mappings.
pub(crate) fn check_native_feasibility_v1(
    source: &ObjectiveSourceEnvelope,
) -> Result<FeasibilityReceiptV1, ObjectiveError> {
    let unit = StableId::new("fixed-q32-v1").map_err(|_| ObjectiveError::Arithmetic)?;
    let lower_limit = FixedQ32::from_raw(i64::MIN);
    let upper_limit = FixedQ32::from_raw(i64::MAX);
    let mut axes = BTreeMap::new();
    let mut evidence_sources = BTreeSet::new();
    let mut atoms = Vec::with_capacity(source.constraints.len());

    for constraint in &source.constraints {
        axes.insert(
            constraint.axis.clone(),
            RegisteredAxisV1 {
                unit: unit.clone(),
                domain: RegisteredDomainV1::Scalar {
                    lower: lower_limit,
                    upper: upper_limit,
                },
            },
        );
        evidence_sources.insert(constraint.evidence_source.clone());
        let (lower, upper) = match constraint.relation {
            ConstraintRelation::AtLeast => (constraint.bound, upper_limit),
            ConstraintRelation::AtMost => (lower_limit, constraint.bound),
            ConstraintRelation::Equal => (constraint.bound, constraint.bound),
        };
        atoms.push(ConstraintAtomV1 {
            id: constraint.id.clone(),
            precedence: AtomPrecedenceV1::Hard(constraint.class),
            axis: constraint.axis.clone(),
            predicate: AtomPredicateV1::ScalarInterval { lower, upper },
            unit: unit.clone(),
            evidence_source: constraint.evidence_source.clone(),
            terminality: PredicateTerminality::Intermediate,
            origin_digest: source.source_digest,
        });
    }

    let registry = RegisteredGrammarV1 {
        schema_digest: source.schema_digest,
        axes,
        evidence_sources,
    };
    // Native compile is deterministic. Use the protocol n + 1 call ceiling,
    // while avoiding host scheduling changing a valid objective into Exhausted.
    let budget = OracleBudgetV1 {
        max_calls: 257,
        wall_time: Duration::MAX,
    };
    Ok(check_feasibility_v1(&registry, atoms, budget))
}
