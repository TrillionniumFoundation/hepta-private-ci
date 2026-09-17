#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


# adapt_constraint must never panic on source identifiers. Structural validation
# is deliberately weaker than StableId syntax, so admission propagates typed errors.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    '''    Ok(relation.map(|relation| Constraint {
        id: stable_id(&source.constraint_id, "constraintId")
            .expect("validated source constraint id"),
        class: mapping.class,
        axis: mapping.axis.clone(),
        relation,
        bound: FixedQ32::from_raw(source.bound_q32),
        evidence_source: stable_id(
            &source.evidence_source_id,
            "constraint.evidenceSourceId",
        )
        .expect("validated constraint evidence source"),
    }))''',
    '''    let Some(relation) = relation else {
        return Ok(None);
    };
    Ok(Some(Constraint {
        id: stable_id(&source.constraint_id, "constraintId")?,
        class: mapping.class,
        axis: mapping.axis.clone(),
        relation,
        bound: FixedQ32::from_raw(source.bound_q32),
        evidence_source: stable_id(
            &source.evidence_source_id,
            "constraint.evidenceSourceId",
        )?,
    }))''',
)

# Strict relations at the representable Q32 endpoints are empty sets. Encode an
# intentionally inverted interval instead of saturating into a weaker relation.
replace_once(
    "codex-rs/hepta-objective/src/admission_feasibility.rs",
    '''        (ObjectiveConstraintDomainV1::Scalar { lower, .. }, C::LessThan) => {
            Ok(AtomPredicateV1::ScalarInterval {
                lower: *lower,
                upper: predecessor(source.bound_q32),
            })
        }''',
    '''        (ObjectiveConstraintDomainV1::Scalar { lower, .. }, C::LessThan) => {
            if source.bound_q32 == i64::MIN {
                return Ok(impossible_scalar_interval());
            }
            Ok(AtomPredicateV1::ScalarInterval {
                lower: *lower,
                upper: FixedQ32::from_raw(source.bound_q32 - 1),
            })
        }''',
)
replace_once(
    "codex-rs/hepta-objective/src/admission_feasibility.rs",
    '''        (ObjectiveConstraintDomainV1::Scalar { .. }, C::GreaterThan) => {
            let ObjectiveConstraintDomainV1::Scalar { upper, .. } = &mapping.domain else {
                unreachable!()
            };
            Ok(AtomPredicateV1::ScalarInterval {
                lower: successor(source.bound_q32),
                upper: *upper,
            })
        }''',
    '''        (ObjectiveConstraintDomainV1::Scalar { .. }, C::GreaterThan) => {
            if source.bound_q32 == i64::MAX {
                return Ok(impossible_scalar_interval());
            }
            let ObjectiveConstraintDomainV1::Scalar { upper, .. } = &mapping.domain else {
                unreachable!()
            };
            Ok(AtomPredicateV1::ScalarInterval {
                lower: FixedQ32::from_raw(source.bound_q32 + 1),
                upper: *upper,
            })
        }''',
)
replace_once(
    "codex-rs/hepta-objective/src/admission_feasibility.rs",
    '''        ConstraintRelation::LessThan => AtomPredicateV1::ScalarInterval {
            lower: FixedQ32::from_raw(i64::MIN),
            upper: predecessor(bound.raw()),
        },
        ConstraintRelation::GreaterThan => AtomPredicateV1::ScalarInterval {
            lower: successor(bound.raw()),
            upper: FixedQ32::from_raw(i64::MAX),
        },''',
    '''        ConstraintRelation::LessThan if bound.raw() == i64::MIN => impossible_scalar_interval(),
        ConstraintRelation::LessThan => AtomPredicateV1::ScalarInterval {
            lower: FixedQ32::from_raw(i64::MIN),
            upper: FixedQ32::from_raw(bound.raw() - 1),
        },
        ConstraintRelation::GreaterThan if bound.raw() == i64::MAX => impossible_scalar_interval(),
        ConstraintRelation::GreaterThan => AtomPredicateV1::ScalarInterval {
            lower: FixedQ32::from_raw(bound.raw() + 1),
            upper: FixedQ32::from_raw(i64::MAX),
        },''',
)
replace_once(
    "codex-rs/hepta-objective/src/admission_feasibility.rs",
    '''fn predecessor(raw: i64) -> FixedQ32 {
    if raw == i64::MIN {
        FixedQ32::ONE
    } else {
        FixedQ32::from_raw(raw - 1)
    }
}

fn successor(raw: i64) -> FixedQ32 {
    if raw == i64::MAX {
        FixedQ32::ZERO
    } else {
        FixedQ32::from_raw(raw + 1)
    }
}
''',
    '''fn impossible_scalar_interval() -> AtomPredicateV1 {
    AtomPredicateV1::ScalarInterval {
        lower: FixedQ32::ONE,
        upper: FixedQ32::ZERO,
    }
}
''',
)

# The legacy direct compile path gets the same exact endpoint behavior.
replace_once(
    "codex-rs/hepta-objective/src/scalar_adapter.rs",
    '''            ConstraintRelation::LessThan => AtomPredicateV1::ScalarInterval {
                lower: lower_limit,
                upper: FixedQ32::from_raw(constraint.bound.raw().saturating_sub(1)),
            },
            ConstraintRelation::GreaterThan => AtomPredicateV1::ScalarInterval {
                lower: FixedQ32::from_raw(constraint.bound.raw().saturating_add(1)),
                upper: upper_limit,
            },''',
    '''            ConstraintRelation::LessThan if constraint.bound.raw() == i64::MIN => {
                AtomPredicateV1::ScalarInterval {
                    lower: FixedQ32::ONE,
                    upper: FixedQ32::ZERO,
                }
            }
            ConstraintRelation::LessThan => AtomPredicateV1::ScalarInterval {
                lower: lower_limit,
                upper: FixedQ32::from_raw(constraint.bound.raw() - 1),
            },
            ConstraintRelation::GreaterThan if constraint.bound.raw() == i64::MAX => {
                AtomPredicateV1::ScalarInterval {
                    lower: FixedQ32::ONE,
                    upper: FixedQ32::ZERO,
                }
            }
            ConstraintRelation::GreaterThan => AtomPredicateV1::ScalarInterval {
                lower: FixedQ32::from_raw(constraint.bound.raw() + 1),
                upper: upper_limit,
            },''',
)

# Boundary regression: strict predicates at numeric endpoints are infeasible,
# never silently weakened by saturation.
with (ROOT / "codex-rs/hepta-objective/src/objective_admission_tests.rs").open("a", encoding="utf-8") as handle:
    handle.write(r'''

#[test]
fn strict_scalar_endpoint_constraints_are_infeasible_not_weakened() {
    for (comparator, bound) in [
        (ObjectiveConstraintComparatorV1::LessThan, i64::MIN),
        (ObjectiveConstraintComparatorV1::GreaterThan, i64::MAX),
    ] {
        let profile = profile();
        let mut envelope = envelope();
        envelope.structured_intent.constraints[0].comparator = comparator;
        envelope.structured_intent.constraints[0].bound_q32 = bound;
        refresh_intent_digest(&mut envelope);
        let context = context(&profile, &envelope);
        let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect("infeasibility is a typed outcome");
        assert!(outcome.compile_result.is_err());
        assert!(outcome.run_snapshot.is_none());
    }
}
''')

print("objective compiler stage1 hardening applied")
