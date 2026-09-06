use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::Duration;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::AtomPrecedenceV1;
use crate::AtomPredicateV1;
use crate::ConstraintAtomV1;
use crate::ConstraintRelation;
use crate::FeasibilityOutcomeV1;
use crate::ObjectiveError;
use crate::ObjectiveSourceEnvelope;
use crate::OracleBudgetV1;
use crate::PredicateTerminality;
use crate::RegisteredAxisV1;
use crate::RegisteredDomainV1;
use crate::RegisteredGrammarV1;
use crate::check_feasibility_v1;

/// Legacy envelopes already carry normalized FixedQ32 values without units.
/// Bind that existing representation to its explicit compatibility profile;
/// new typed callers must supply independently registered domains and units.
pub(crate) fn scalar_conflict(
    source: &ObjectiveSourceEnvelope,
) -> Result<Option<Vec<StableId>>, ObjectiveError> {
    let unit = StableId::new("legacy-fixed-q32-v1").map_err(|_| ObjectiveError::Arithmetic)?;
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
    // Compatibility availability ceiling, not a measured latency qualification.
    let budget = OracleBudgetV1 {
        max_calls: 257,
        wall_time: Duration::from_secs(1),
    };
    match check_feasibility_v1(&registry, atoms, budget).outcome {
        FeasibilityOutcomeV1::Feasible(_) => Ok(None),
        FeasibilityOutcomeV1::Infeasible {
            inclusion_minimal_conflicting_ids,
        } => Ok(Some(inclusion_minimal_conflicting_ids)),
        FeasibilityOutcomeV1::Unsupported { .. } => {
            Err(ObjectiveError::UnsupportedConstraintLanguage)
        }
        FeasibilityOutcomeV1::Exhausted => Err(ObjectiveError::FeasibilityBudgetExhausted),
    }
}
