#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def regex_replace(path: str, pattern: str, replacement: str, expected_min: int = 1) -> None:
    text = read(path)
    text, count = re.subn(pattern, replacement, text, flags=re.S)
    if count < expected_min:
        raise RuntimeError(f"{path}: regex replacement matched {count}, expected >= {expected_min}: {pattern}")
    write(path, text)


# ---------------------------------------------------------------------------
# Feasibility engine: exact scalar != support and exact witness exclusions.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/feasibility_model.rs",
    "    ScalarInterval { lower: FixedQ32, upper: FixedQ32 },\n    Include(BTreeSet<StableId>),",
    "    ScalarInterval { lower: FixedQ32, upper: FixedQ32 },\n    ScalarNotEqual(FixedQ32),\n    Include(BTreeSet<StableId>),",
)
replace_once(
    "codex-rs/hepta-objective/src/feasibility_model.rs",
    "pub struct FeasibleAssignmentV1 {\n    pub domains: BTreeMap<StableId, RegisteredAxisV1>,\n    pub required_actions: BTreeSet<StableId>,",
    "pub struct FeasibleAssignmentV1 {\n    pub domains: BTreeMap<StableId, RegisteredAxisV1>,\n    /// Scalar holes excluded by exact `!=` atoms. The interval in `domains`\n    /// remains the closed outer hull; this map makes the witness domain exact.\n    pub scalar_exclusions: BTreeMap<StableId, BTreeSet<FixedQ32>>,\n    pub required_actions: BTreeSet<StableId>,",
)

replace_once(
    "codex-rs/hepta-objective/src/feasibility.rs",
    "        (RegisteredDomainV1::Scalar { .. }, AtomPredicateV1::ScalarInterval { .. }) => true,",
    "        (RegisteredDomainV1::Scalar { .. }, AtomPredicateV1::ScalarInterval { .. })\n        | (RegisteredDomainV1::Scalar { .. }, AtomPredicateV1::ScalarNotEqual(_)) => true,",
)
replace_once(
    "codex-rs/hepta-objective/src/feasibility.rs",
    "    let mut domains = registry.axes.clone();\n    let mut required = BTreeSet::new();",
    "    let mut domains = registry.axes.clone();\n    let mut scalar_exclusions: BTreeMap<StableId, BTreeSet<codex_hepta_types::FixedQ32>> =\n        BTreeMap::new();\n    let mut required = BTreeSet::new();",
)
replace_once(
    "codex-rs/hepta-objective/src/feasibility.rs",
    "                if lower > upper {\n                    return None;\n                }\n            }\n            (RegisteredDomainV1::Enumeration(values), AtomPredicateV1::Include(included)) => {",
    "                if lower > upper\n                    || !scalar_domain_has_value(\n                        *lower,\n                        *upper,\n                        scalar_exclusions.get(&atom.axis),\n                    )\n                {\n                    return None;\n                }\n            }\n            (\n                RegisteredDomainV1::Scalar { lower, upper },\n                AtomPredicateV1::ScalarNotEqual(excluded),\n            ) => {\n                let excluded_values = scalar_exclusions.entry(atom.axis.clone()).or_default();\n                excluded_values.insert(*excluded);\n                if !scalar_domain_has_value(*lower, *upper, Some(excluded_values)) {\n                    return None;\n                }\n            }\n            (RegisteredDomainV1::Enumeration(values), AtomPredicateV1::Include(included)) => {",
)
replace_once(
    "codex-rs/hepta-objective/src/feasibility.rs",
    "    Some(FeasibleAssignmentV1 {\n        domains,\n        required_actions: required,",
    "    Some(FeasibleAssignmentV1 {\n        domains,\n        scalar_exclusions,\n        required_actions: required,",
)
replace_once(
    "codex-rs/hepta-objective/src/feasibility.rs",
    "#[cfg(test)]\n#[path = \"feasibility_tests.rs\"]",
    "fn scalar_domain_has_value(\n    lower: codex_hepta_types::FixedQ32,\n    upper: codex_hepta_types::FixedQ32,\n    excluded: Option<&BTreeSet<codex_hepta_types::FixedQ32>>,\n) -> bool {\n    if lower > upper {\n        return false;\n    }\n    let total = i128::from(upper.raw()) - i128::from(lower.raw()) + 1;\n    let excluded_count = excluded.map_or(0_i128, |values| {\n        i128::try_from(\n            values\n                .iter()\n                .filter(|value| **value >= lower && **value <= upper)\n                .count(),\n        )\n        .unwrap_or(i128::MAX)\n    });\n    total > excluded_count\n}\n\n#[cfg(test)]\n#[path = \"feasibility_tests.rs\"]",
)

# Existing exact assignment fixtures now declare an empty scalar-hole map.
text = read("codex-rs/hepta-objective/src/feasibility_tests.rs")
text = text.replace(
    "            required_actions: BTreeSet::new(),",
    "            scalar_exclusions: BTreeMap::new(),\n            required_actions: BTreeSet::new(),",
)
write("codex-rs/hepta-objective/src/feasibility_tests.rs", text)

# Add focused != behavior.
with (ROOT / "codex-rs/hepta-objective/src/feasibility_tests.rs").open("a", encoding="utf-8") as handle:
    handle.write(r'''

#[test]
fn scalar_not_equal_preserves_exact_holes_and_detects_singleton_conflict() {
    let registered = scalar_registry();
    let feasible = check_feasibility_v1(
        &registered,
        vec![atom(
            "not-zero",
            "x",
            AtomPredicateV1::ScalarNotEqual(FixedQ32::ZERO),
        )],
        budget(),
    );
    let FeasibilityOutcomeV1::Feasible(assignment) = feasible.outcome else {
        panic!("not-equal should be feasible on a multi-value domain");
    };
    assert_eq!(
        assignment.scalar_exclusions.get(&id("x")),
        Some(&BTreeSet::from([FixedQ32::ZERO]))
    );

    let singleton = registry(vec![(
        "x",
        RegisteredDomainV1::Scalar {
            lower: FixedQ32::ZERO,
            upper: FixedQ32::ZERO,
        },
    )]);
    assert_eq!(
        check_feasibility_v1(
            &singleton,
            vec![atom(
                "not-zero",
                "x",
                AtomPredicateV1::ScalarNotEqual(FixedQ32::ZERO),
            )],
            budget(),
        )
        .outcome,
        FeasibilityOutcomeV1::Infeasible {
            inclusion_minimal_conflicting_ids: vec![id("not-zero")]
        }
    );
}
''')

# ---------------------------------------------------------------------------
# Source grammar: carry enum sets and action implication targets explicitly.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_v1.rs",
    "pub enum ObjectiveConstraintComparatorV1 {\n    Equal,\n    NotEqual,\n    LessThan,\n    LessThanOrEqual,\n    GreaterThan,\n    GreaterThanOrEqual,\n    In,\n    NotInSet,\n}",
    "pub enum ObjectiveConstraintComparatorV1 {\n    Equal,\n    NotEqual,\n    LessThan,\n    LessThanOrEqual,\n    GreaterThan,\n    GreaterThanOrEqual,\n    In,\n    NotInSet,\n    RequireAction,\n    ForbidAction,\n    ImpliesAction,\n}",
)
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_v1.rs",
    "pub struct ObjectiveSourceConstraintV1 {\n    pub constraint_id: String,\n    pub unit: String,\n    pub comparator: ObjectiveConstraintComparatorV1,\n    pub bound_q32: i64,\n    pub evidence_source_id: String,\n    pub terminal: bool,\n}",
    "pub struct ObjectiveSourceConstraintV1 {\n    pub constraint_id: String,\n    pub unit: String,\n    pub comparator: ObjectiveConstraintComparatorV1,\n    /// Scalar operand for eq/ne/lt/lte/gt/gte. Must be zero for enum/action predicates.\n    pub bound_q32: i64,\n    /// Source enum spellings for `in`/`not_in`; profile mapping supplies canonical values.\n    pub set_values: Vec<String>,\n    /// Source action class named by `implies_action`; absent for all other predicates.\n    pub implication_target_action_class: Option<String>,\n    pub evidence_source_id: String,\n    pub terminal: bool,\n}",
)
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_v1.rs",
    "/// All eleven required structured-intent fields, including fields that the\n/// existing scalar compiler cannot yet represent or enforce.",
    "/// All eleven required structured-intent fields. Rich hard constraints are\n/// retained through the registered feasibility path even when the legacy scalar\n/// compatibility IR has no direct representation for the predicate.",
)

replace_once(
    "codex-rs/hepta-objective/src/source_envelope_json_dto.rs",
    "    comparator: ObjectiveConstraintComparatorV1,\n    bound_q32: i64,\n    evidence_source_id: String,",
    "    comparator: ObjectiveConstraintComparatorV1,\n    bound_q32: i64,\n    #[serde(default)]\n    set_values: Vec<String>,\n    #[serde(default, deserialize_with = \"shape::present_optional_string\")]\n    implication_target_action_class: Option<String>,\n    evidence_source_id: String,",
)
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_json_shape.rs",
    "pub(super) fn present_deadline<'de, D: Deserializer<'de>>(\n    deserializer: D,\n) -> Result<Option<String>, D::Error> {\n    String::deserialize(deserializer).map(Some)\n}",
    "pub(super) fn present_deadline<'de, D: Deserializer<'de>>(\n    deserializer: D,\n) -> Result<Option<String>, D::Error> {\n    String::deserialize(deserializer).map(Some)\n}\n\npub(super) fn present_optional_string<'de, D: Deserializer<'de>>(\n    deserializer: D,\n) -> Result<Option<String>, D::Error> {\n    String::deserialize(deserializer).map(Some)\n}",
)
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_json_shape.rs",
    "string_enum!(constraint_comparator, ObjectiveConstraintComparatorV1, {\n    \"eq\" => Equal, \"ne\" => NotEqual, \"lt\" => LessThan, \"lte\" => LessThanOrEqual,\n    \"gt\" => GreaterThan, \"gte\" => GreaterThanOrEqual, \"in\" => In, \"not_in\" => NotInSet,\n});",
    "string_enum!(constraint_comparator, ObjectiveConstraintComparatorV1, {\n    \"eq\" => Equal, \"ne\" => NotEqual, \"lt\" => LessThan, \"lte\" => LessThanOrEqual,\n    \"gt\" => GreaterThan, \"gte\" => GreaterThanOrEqual, \"in\" => In, \"not_in\" => NotInSet,\n    \"require_action\" => RequireAction, \"forbid_action\" => ForbidAction,\n    \"implies_action\" => ImpliesAction,\n});",
)

# Rewrite the compact structural validator so source bounds reflect generated native items.
write("codex-rs/hepta-objective/src/source_envelope_validation.rs", r'''use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectiveSourceEnvelopeV1;

/// Admission appends six resource and four risk constraints. The source ceiling
/// reserves those ten slots so every structurally valid envelope can reach the
/// 256-atom feasibility ceiling without a later count surprise.
pub const MAX_OBJECTIVE_SOURCE_CONSTRAINTS: usize = 246;
pub const MAX_OBJECTIVE_COMPILED_PREDICATES: usize = 128;

/// Structural errors contain field paths/counts, never unrestricted source text.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveStructureError {
    CollectionCount {
        field: &'static str,
        actual: usize,
        minimum: usize,
        maximum: usize,
    },
    TextBytes {
        field: &'static str,
        actual: usize,
        maximum: usize,
    },
    DuplicateSemanticKey {
        field: &'static str,
        index: usize,
    },
    InvalidConstraintShape {
        index: usize,
        reason: &'static str,
    },
}

impl fmt::Display for ObjectiveStructureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CollectionCount { field, actual, minimum, maximum } => write!(
                formatter,
                "{field} has {actual} items; expected {minimum}..={maximum}"
            ),
            Self::TextBytes { field, actual, maximum } => write!(
                formatter,
                "{field} has {actual} text bytes; maximum is {maximum}"
            ),
            Self::DuplicateSemanticKey { field, index } => {
                write!(formatter, "{field} repeats a semantic key at index {index}")
            }
            Self::InvalidConstraintShape { index, reason } => {
                write!(formatter, "constraints[{index}] has invalid predicate shape: {reason}")
            }
        }
    }
}

impl Error for ObjectiveStructureError {}

impl ObjectiveSourceEnvelopeV1 {
    /// Check raw UTF-8 field byte limits, array bounds, aggregate compiler bounds
    /// and within-array semantic-key uniqueness without changing source values.
    pub fn validate_structure(&self) -> Result<(), ObjectiveStructureError> {
        text_bytes(&self.request_id, "requestId", 128)?;
        text_bytes(&self.locale, "locale", 32)?;
        text_bytes(&self.observed_at, "observedAt", 64)?;
        if let Some(deadline) = &self.deadline {
            text_bytes(deadline, "deadline", 64)?;
        }
        let intent = &self.structured_intent;
        for (predicates, field) in [
            (&intent.success_predicates, "successPredicates"),
            (&intent.terminal_conditions, "terminalConditions"),
        ] {
            collection(predicates, field, 1, 128, |value| &value.predicate_id)?;
            for predicate in predicates {
                text_bytes(&predicate.predicate_id, "predicateId", 128)?;
                text_bytes(&predicate.unit, "predicate.unit", 64)?;
                text_bytes(&predicate.evidence_source_id, "predicate.evidenceSourceId", 256)?;
            }
        }
        let predicate_total = intent
            .success_predicates
            .len()
            .saturating_add(intent.terminal_conditions.len())
            .saturating_add(intent.evidence_requirements.len());
        if predicate_total > MAX_OBJECTIVE_COMPILED_PREDICATES {
            return Err(ObjectiveStructureError::CollectionCount {
                field: "compiledPredicates",
                actual: predicate_total,
                minimum: 0,
                maximum: MAX_OBJECTIVE_COMPILED_PREDICATES,
            });
        }
        for (actions, field, minimum) in [
            (&intent.legal_action_classes, "legalActionClasses", 0),
            (&intent.forbidden_action_classes, "forbiddenActionClasses", 0),
            (&intent.confirmation_action_classes, "confirmationActionClasses", 0),
        ] {
            collection(actions, field, minimum, 128, String::as_str)?;
            for action in actions {
                text_bytes(action, field, 128)?;
            }
        }
        collection(
            &intent.constraints,
            "constraints",
            1,
            MAX_OBJECTIVE_SOURCE_CONSTRAINTS,
            |value| &value.constraint_id,
        )?;
        for (index, constraint) in intent.constraints.iter().enumerate() {
            text_bytes(&constraint.constraint_id, "constraintId", 128)?;
            text_bytes(&constraint.unit, "constraint.unit", 64)?;
            text_bytes(&constraint.evidence_source_id, "constraint.evidenceSourceId", 256)?;
            collection(
                &constraint.set_values,
                "constraint.setValues",
                0,
                128,
                String::as_str,
            )?;
            for value in &constraint.set_values {
                text_bytes(value, "constraint.setValues", 128)?;
            }
            if let Some(target) = &constraint.implication_target_action_class {
                text_bytes(target, "constraint.implicationTargetActionClass", 128)?;
            }
            validate_constraint_shape(index, constraint)?;
        }
        collection(&intent.soft_dimensions, "softDimensions", 0, 64, |value| {
            &value.dimension_id
        })?;
        for dimension in &intent.soft_dimensions {
            text_bytes(&dimension.dimension_id, "dimensionId", 128)?;
            text_bytes(&dimension.unit, "dimension.unit", 64)?;
        }
        collection(
            &intent.evidence_requirements,
            "evidenceRequirements",
            1,
            128,
            |value| &value.requirement_id,
        )?;
        for requirement in &intent.evidence_requirements {
            text_bytes(&requirement.requirement_id, "requirementId", 128)?;
            text_bytes(&requirement.evidence_source_id, "requirement.evidenceSourceId", 256)?;
        }
        text_bytes(&intent.risk.abstention_rule, "risk.abstentionRule", 512)
    }
}

fn validate_constraint_shape(
    index: usize,
    constraint: &crate::ObjectiveSourceConstraintV1,
) -> Result<(), ObjectiveStructureError> {
    use ObjectiveConstraintComparatorV1 as C;
    let invalid = |reason| ObjectiveStructureError::InvalidConstraintShape { index, reason };
    match constraint.comparator {
        C::Equal | C::NotEqual | C::LessThan | C::LessThanOrEqual | C::GreaterThan | C::GreaterThanOrEqual => {
            if !constraint.set_values.is_empty() || constraint.implication_target_action_class.is_some() {
                return Err(invalid("scalar predicate carries enum/action operand"));
            }
        }
        C::In | C::NotInSet => {
            if constraint.set_values.is_empty() {
                return Err(invalid("enum predicate requires setValues"));
            }
            if constraint.bound_q32 != 0 || constraint.implication_target_action_class.is_some() {
                return Err(invalid("enum predicate carries scalar/action operand"));
            }
        }
        C::RequireAction | C::ForbidAction => {
            if constraint.bound_q32 != 0
                || !constraint.set_values.is_empty()
                || constraint.implication_target_action_class.is_some()
            {
                return Err(invalid("action predicate carries an extra operand"));
            }
        }
        C::ImpliesAction => {
            if constraint.bound_q32 != 0
                || !constraint.set_values.is_empty()
                || constraint.implication_target_action_class.is_none()
            {
                return Err(invalid("implies_action requires exactly one target action"));
            }
        }
    }
    Ok(())
}

fn text_bytes(text: &str, field: &'static str, maximum: usize) -> Result<(), ObjectiveStructureError> {
    if text.len() > maximum {
        return Err(ObjectiveStructureError::TextBytes {
            field,
            actual: text.len(),
            maximum,
        });
    }
    Ok(())
}

fn collection<T>(
    values: &[T],
    field: &'static str,
    minimum: usize,
    maximum: usize,
    key: impl Fn(&T) -> &str,
) -> Result<(), ObjectiveStructureError> {
    if !(minimum..=maximum).contains(&values.len()) {
        return Err(ObjectiveStructureError::CollectionCount {
            field,
            actual: values.len(),
            minimum,
            maximum,
        });
    }
    let mut keys = BTreeSet::new();
    for (index, value) in values.iter().enumerate() {
        let key = key(value);
        text_bytes(key, field, 128)?;
        if !keys.insert(key) {
            return Err(ObjectiveStructureError::DuplicateSemanticKey { field, index });
        }
    }
    Ok(())
}
''')

# Every Rust source-constraint literal gets the new optional operands. Existing
# fixtures are scalar unless a later targeted replacement changes them.
for path in [
    "codex-rs/hepta-objective/src/objective_admission_tests.rs",
    "codex-rs/hepta-objective/src/source_envelope_v1_tests.rs",
    "codex-rs/hepta-objective/src/source_envelope_json_tests.rs",
    "codex-rs/hepta-intelligence/src/vertical_tests.rs",
]:
    text = read(path)
    pattern = r"(ObjectiveSourceConstraintV1 \{.*?\n\s*bound_q32: [^\n]+,\n)(\s*evidence_source_id:)"
    replacement = r"\1                set_values: Vec::new(),\n                implication_target_action_class: None,\n\2"
    text, count = re.subn(pattern, replacement, text, flags=re.S)
    if count < 1:
        raise RuntimeError(f"{path}: no ObjectiveSourceConstraintV1 literals patched")
    write(path, text)

# Historical shape fixtures that intentionally used not_in now provide a set.
for path in [
    "codex-rs/hepta-objective/src/source_envelope_v1_tests.rs",
    "codex-rs/hepta-objective/src/source_envelope_json_tests.rs",
]:
    text = read(path)
    text = text.replace(
        "comparator: ObjectiveConstraintComparatorV1::NotInSet,\n                bound_q32: 0,\n                set_values: Vec::new(),",
        "comparator: ObjectiveConstraintComparatorV1::NotInSet,\n                bound_q32: 0,\n                set_values: vec![\"blocked\".into()],",
    )
    write(path, text)

# ---------------------------------------------------------------------------
# Native model: complete scalar relations, explicit canonical V1 surfaces.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/model.rs",
    "use codex_hepta_types::Digest32;\nuse codex_hepta_types::FixedQ32;",
    "use codex_hepta_types::AuthorityPosture;\nuse codex_hepta_types::Digest32;\nuse codex_hepta_types::FixedQ32;",
)
replace_once(
    "codex-rs/hepta-objective/src/model.rs",
    "pub enum ConstraintRelation {\n    AtLeast,\n    AtMost,\n    Equal,\n}",
    "pub enum ConstraintRelation {\n    AtLeast,\n    AtMost,\n    Equal,\n    NotEqual,\n    LessThan,\n    GreaterThan,\n}",
)
replace_once(
    "codex-rs/hepta-objective/src/model.rs",
    "            Self::AtLeast => 0,\n            Self::AtMost => 1,\n            Self::Equal => 2,",
    "            Self::AtLeast => 0,\n            Self::AtMost => 1,\n            Self::Equal => 2,\n            Self::NotEqual => 3,\n            Self::LessThan => 4,\n            Self::GreaterThan => 5,",
)
replace_once(
    "codex-rs/hepta-objective/src/model.rs",
    "pub struct ObjectiveFunction {\n    pub request_id: StableId,\n    pub principal_scope: StableId,\n    pub revision: Revision,\n    pub source_digest: Digest32,\n    pub schema_digest: Digest32,\n    pub hard_constraint_digest: Digest32,\n    pub semantic_digest: Digest32,\n    pub constraints: Vec<Constraint>,\n    pub success_predicates: Vec<SuccessPredicate>,\n    pub legal_actions: Vec<ActionClass>,\n    pub soft_preferences: Vec<SoftPreference>,\n}",
    "pub struct ObjectiveFunction {\n    pub request_id: StableId,\n    pub principal_scope: StableId,\n    pub revision: Revision,\n    pub source_digest: Digest32,\n    pub schema_digest: Digest32,\n    pub profile_digest: Option<Digest32>,\n    pub intent_digest: Option<Digest32>,\n    pub hard_constraint_digest: Digest32,\n    pub semantic_digest: Digest32,\n    /// Legacy scalar/native projection retained for compatibility.\n    pub constraints: Vec<Constraint>,\n    /// Canonical hard-constraint grammar, including enum/action predicates.\n    pub constraint_atoms: Vec<crate::ConstraintAtomV1>,\n    /// Nonterminal success predicates only on admitted V1 outputs.\n    pub success_predicates: Vec<SuccessPredicate>,\n    pub terminal_conditions: Vec<SuccessPredicate>,\n    pub evidence_requirements: Vec<SuccessPredicate>,\n    pub legal_actions: Vec<ActionClass>,\n    pub forbidden_actions: Vec<StableId>,\n    pub resource_constraints: Vec<Constraint>,\n    pub risk_constraints: Vec<Constraint>,\n    pub soft_preferences: Vec<SoftPreference>,\n}",
)
replace_once(
    "codex-rs/hepta-objective/src/model.rs",
    "pub struct ObjectiveCompileReceipt {\n    pub objective: ObjectiveFunction,\n    pub disposition: CompileDisposition,\n    pub removed_action_ids: Vec<StableId>,\n}\n\n#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ObjectiveConflictReceipt",
    "pub struct ObjectiveCompileReceipt {\n    pub objective: ObjectiveFunction,\n    pub disposition: CompileDisposition,\n}\n\n/// Canonical protocol names are source-compatible aliases of the now-complete\n/// native structures. The legacy names remain exported for downstream callers.\npub type ObjectiveFunctionV1 = ObjectiveFunction;\npub type ObjectiveCompileReceiptV1 = ObjectiveCompileReceipt;\npub type ObjectiveConflictReceiptV1 = ObjectiveConflictReceipt;\n\n#[derive(Clone, Debug, Eq, PartialEq)]\npub struct RunStartSnapshotV1 {\n    pub request_id: StableId,\n    pub principal_scope: StableId,\n    pub revision: Revision,\n    pub objective_digest: Digest32,\n    pub admitted_source_digest: Digest32,\n    pub profile_digest: Digest32,\n    pub intent_digest: Digest32,\n    pub observed_at_unix_micros: u64,\n    pub deadline_unix_micros: Option<u64>,\n    pub snapshot_digest: Digest32,\n    pub authority: AuthorityPosture,\n}\n\n#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ObjectiveConflictReceipt",
)

# ---------------------------------------------------------------------------
# Legacy scalar adapter remains available, but understands the full scalar set.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/scalar_adapter.rs",
    "        let (lower, upper) = match constraint.relation {\n            ConstraintRelation::AtLeast => (constraint.bound, upper_limit),\n            ConstraintRelation::AtMost => (lower_limit, constraint.bound),\n            ConstraintRelation::Equal => (constraint.bound, constraint.bound),\n        };\n        atoms.push(ConstraintAtomV1 {",
    "        let predicate = match constraint.relation {\n            ConstraintRelation::AtLeast => AtomPredicateV1::ScalarInterval {\n                lower: constraint.bound,\n                upper: upper_limit,\n            },\n            ConstraintRelation::AtMost => AtomPredicateV1::ScalarInterval {\n                lower: lower_limit,\n                upper: constraint.bound,\n            },\n            ConstraintRelation::Equal => AtomPredicateV1::ScalarInterval {\n                lower: constraint.bound,\n                upper: constraint.bound,\n            },\n            ConstraintRelation::NotEqual => AtomPredicateV1::ScalarNotEqual(constraint.bound),\n            ConstraintRelation::LessThan => AtomPredicateV1::ScalarInterval {\n                lower: lower_limit,\n                upper: FixedQ32::from_raw(constraint.bound.raw().saturating_sub(1)),\n            },\n            ConstraintRelation::GreaterThan => AtomPredicateV1::ScalarInterval {\n                lower: FixedQ32::from_raw(constraint.bound.raw().saturating_add(1)),\n                upper: upper_limit,\n            },\n        };\n        atoms.push(ConstraintAtomV1 {",
)
replace_once(
    "codex-rs/hepta-objective/src/scalar_adapter.rs",
    "            predicate: AtomPredicateV1::ScalarInterval { lower, upper },",
    "            predicate,",
)

# ---------------------------------------------------------------------------
# Compiler: canonical fields, prevalidated path, no dead removed_action_ids.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/compiler.rs",
    "pub fn compile(\n    mut source: ObjectiveSourceEnvelope,\n) -> Result<Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>, ObjectiveError> {\n    validate_source(&source)?;",
    "pub fn compile(\n    source: ObjectiveSourceEnvelope,\n) -> Result<Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>, ObjectiveError> {\n    compile_inner(source, true)\n}\n\npub(crate) fn compile_prevalidated(\n    source: ObjectiveSourceEnvelope,\n) -> Result<Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>, ObjectiveError> {\n    compile_inner(source, false)\n}\n\nfn compile_inner(\n    mut source: ObjectiveSourceEnvelope,\n    run_legacy_scalar_feasibility: bool,\n) -> Result<Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>, ObjectiveError> {\n    validate_source(&source)?;",
)
replace_once(
    "codex-rs/hepta-objective/src/compiler.rs",
    "    if let Some(conflicting_ids) = crate::scalar_adapter::scalar_conflict(&source)? {\n        return Ok(Err(conflict_receipt(&source, conflicting_ids)));\n    }",
    "    if run_legacy_scalar_feasibility {\n        if let Some(conflicting_ids) = crate::scalar_adapter::scalar_conflict(&source)? {\n            return Ok(Err(conflict_receipt(&source, conflicting_ids)));\n        }\n    }",
)
replace_once(
    "codex-rs/hepta-objective/src/compiler.rs",
    "    let mut removed_action_ids = Vec::new();\n    let mut legal_actions = Vec::new();",
    "    let mut legal_actions = Vec::new();",
)
replace_once(
    "codex-rs/hepta-objective/src/compiler.rs",
    "            removed_action_ids.push(action.id.clone());\n            requested_forbidden.push(action.id);",
    "            requested_forbidden.push(action.id);",
)
replace_once(
    "codex-rs/hepta-objective/src/compiler.rs",
    "    let objective = ObjectiveFunction {\n        request_id: source.request_id,\n        principal_scope: source.principal_scope,\n        revision: source.revision,\n        source_digest: source.source_digest,\n        schema_digest: source.schema_digest,\n        hard_constraint_digest,\n        semantic_digest,\n        constraints: source.constraints,\n        success_predicates: source.success_predicates,\n        legal_actions,\n        soft_preferences: source.soft_preferences,\n    };\n\n    Ok(Ok(ObjectiveCompileReceipt {\n        objective,\n        disposition,\n        removed_action_ids,\n    }))",
    "    let objective = ObjectiveFunction {\n        request_id: source.request_id,\n        principal_scope: source.principal_scope,\n        revision: source.revision,\n        source_digest: source.source_digest,\n        schema_digest: source.schema_digest,\n        profile_digest: None,\n        intent_digest: None,\n        hard_constraint_digest,\n        semantic_digest,\n        constraints: source.constraints,\n        constraint_atoms: Vec::new(),\n        success_predicates: source.success_predicates,\n        terminal_conditions: Vec::new(),\n        evidence_requirements: Vec::new(),\n        legal_actions,\n        forbidden_actions: source.forbidden_actions,\n        resource_constraints: Vec::new(),\n        risk_constraints: Vec::new(),\n        soft_preferences: source.soft_preferences,\n    };\n\n    Ok(Ok(ObjectiveCompileReceipt { objective, disposition }))",
)
replace_once(
    "codex-rs/hepta-objective/src/compiler.rs",
    "fn conflict_receipt(\n    source: &ObjectiveSourceEnvelope,",
    "pub(crate) fn conflict_receipt(\n    source: &ObjectiveSourceEnvelope,",
)

# ---------------------------------------------------------------------------
# Registered rich feasibility bridge used only by authenticated admission.
# ---------------------------------------------------------------------------
write("codex-rs/hepta-objective/src/admission_feasibility.rs", r'''use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::AtomPrecedenceV1;
use crate::AtomPredicateV1;
use crate::ConstraintAtomV1;
use crate::ConstraintRelation;
use crate::FeasibilityOutcomeV1;
use crate::FeasibilityReceiptV1;
use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectiveError;
use crate::ObjectiveSourceEnvelope;
use crate::ObjectiveSourceEnvelopeV1;
use crate::OracleBudgetV1;
use crate::PredicateTerminality;
use crate::RegisteredAxisV1;
use crate::RegisteredDomainV1;
use crate::RegisteredGrammarV1;
use crate::check_feasibility_v1;
use crate::objective_admission::ObjectiveAdmissionError;
use crate::objective_admission::ObjectiveAdmissionProfileV1;
use crate::objective_admission::ObjectiveConstraintDomainV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AdmissionFeasibilityResult {
    pub receipt: FeasibilityReceiptV1,
    pub required_actions: BTreeSet<StableId>,
    pub effectively_forbidden_actions: BTreeSet<StableId>,
}

pub(crate) fn evaluate(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    native_source: &ObjectiveSourceEnvelope,
    admitted_source_digest: Digest32,
    budget: OracleBudgetV1,
) -> Result<AdmissionFeasibilityResult, ObjectiveAdmissionError> {
    let mut registry = RegisteredGrammarV1 {
        schema_digest: envelope.input_schema_digest,
        axes: BTreeMap::new(),
        evidence_sources: BTreeSet::new(),
    };
    let mut atoms = Vec::with_capacity(envelope.structured_intent.constraints.len() + 10);

    for source in &envelope.structured_intent.constraints {
        let mapping = profile
            .constraints
            .iter()
            .find(|mapping| mapping.source_constraint_id == source.constraint_id)
            .ok_or(ObjectiveAdmissionError::UnknownConstraint)?;
        if mapping.expected_unit != source.unit {
            return Err(ObjectiveAdmissionError::ConstraintUnitMismatch);
        }
        let unit = stable_id(&source.unit, "constraint.unit")?;
        let domain = registered_domain(&mapping.domain)?;
        register_axis(&mut registry, mapping.axis.clone(), unit.clone(), domain.clone())?;
        let predicate = predicate_for(source, mapping, profile, &mut registry, &unit)?;
        let evidence_source = stable_id(
            &source.evidence_source_id,
            "constraint.evidenceSourceId",
        )?;
        registry.evidence_sources.insert(evidence_source.clone());
        atoms.push(ConstraintAtomV1 {
            id: stable_id(&source.constraint_id, "constraintId")?,
            precedence: AtomPrecedenceV1::Hard(mapping.class),
            axis: mapping.axis.clone(),
            predicate,
            unit,
            evidence_source,
            terminality: if source.terminal {
                PredicateTerminality::Terminal
            } else {
                PredicateTerminality::Intermediate
            },
            origin_digest: admitted_source_digest,
        });
    }

    let generated = generated_constraint_ids(profile);
    let generated_unit = StableId::new("canonical-q32-v1")
        .map_err(|_| ObjectiveAdmissionError::InvalidProfile("generated unit"))?;
    for constraint in &native_source.constraints {
        if !generated.contains(&constraint.id) {
            continue;
        }
        register_axis(
            &mut registry,
            constraint.axis.clone(),
            generated_unit.clone(),
            RegisteredDomainV1::Scalar {
                lower: FixedQ32::from_raw(i64::MIN),
                upper: FixedQ32::from_raw(i64::MAX),
            },
        )?;
        registry
            .evidence_sources
            .insert(constraint.evidence_source.clone());
        atoms.push(ConstraintAtomV1 {
            id: constraint.id.clone(),
            precedence: AtomPrecedenceV1::Hard(constraint.class),
            axis: constraint.axis.clone(),
            predicate: native_scalar_predicate(constraint.relation, constraint.bound),
            unit: generated_unit.clone(),
            evidence_source: constraint.evidence_source.clone(),
            terminality: PredicateTerminality::Intermediate,
            origin_digest: admitted_source_digest,
        });
    }

    let mut ids = BTreeSet::new();
    for atom in &atoms {
        if !ids.insert(atom.id.clone()) {
            return Err(ObjectiveAdmissionError::Compiler(
                ObjectiveError::DuplicateSemanticId(atom.id.to_string()),
            ));
        }
    }

    let receipt = check_feasibility_v1(&registry, atoms, budget);
    let (required_actions, effectively_forbidden_actions) = match &receipt.outcome {
        FeasibilityOutcomeV1::Feasible(assignment) => {
            let action_axes = assignment
                .domains
                .iter()
                .filter(|(_, axis)| axis.domain == RegisteredDomainV1::Action)
                .map(|(id, _)| id.clone())
                .collect::<BTreeSet<_>>();
            let forbidden = action_axes
                .difference(&assignment.required_actions)
                .filter(|id| !assignment.unforced_actions.contains(*id))
                .cloned()
                .collect();
            (assignment.required_actions.clone(), forbidden)
        }
        _ => (BTreeSet::new(), BTreeSet::new()),
    };
    Ok(AdmissionFeasibilityResult {
        receipt,
        required_actions,
        effectively_forbidden_actions,
    })
}

fn predicate_for(
    source: &crate::ObjectiveSourceConstraintV1,
    mapping: &crate::objective_admission::ObjectiveConstraintProfileV1,
    profile: &ObjectiveAdmissionProfileV1,
    registry: &mut RegisteredGrammarV1,
    unit: &StableId,
) -> Result<AtomPredicateV1, ObjectiveAdmissionError> {
    use ObjectiveConstraintComparatorV1 as C;
    match (&mapping.domain, source.comparator) {
        (ObjectiveConstraintDomainV1::Scalar { lower, upper }, C::Equal) => {
            Ok(AtomPredicateV1::ScalarInterval {
                lower: FixedQ32::from_raw(source.bound_q32),
                upper: FixedQ32::from_raw(source.bound_q32),
            })
        }
        (ObjectiveConstraintDomainV1::Scalar { .. }, C::NotEqual) => Ok(
            AtomPredicateV1::ScalarNotEqual(FixedQ32::from_raw(source.bound_q32)),
        ),
        (ObjectiveConstraintDomainV1::Scalar { lower, .. }, C::LessThan) => {
            Ok(AtomPredicateV1::ScalarInterval {
                lower: *lower,
                upper: predecessor(source.bound_q32),
            })
        }
        (ObjectiveConstraintDomainV1::Scalar { lower, .. }, C::LessThanOrEqual) => {
            Ok(AtomPredicateV1::ScalarInterval {
                lower: *lower,
                upper: FixedQ32::from_raw(source.bound_q32),
            })
        }
        (ObjectiveConstraintDomainV1::Scalar { .. }, C::GreaterThan) => {
            let ObjectiveConstraintDomainV1::Scalar { upper, .. } = &mapping.domain else {
                unreachable!()
            };
            Ok(AtomPredicateV1::ScalarInterval {
                lower: successor(source.bound_q32),
                upper: *upper,
            })
        }
        (ObjectiveConstraintDomainV1::Scalar { upper, .. }, C::GreaterThanOrEqual) => {
            Ok(AtomPredicateV1::ScalarInterval {
                lower: FixedQ32::from_raw(source.bound_q32),
                upper: *upper,
            })
        }
        (ObjectiveConstraintDomainV1::Enumeration(values), C::In) => {
            Ok(AtomPredicateV1::Include(map_enum_values(&source.set_values, values)?))
        }
        (ObjectiveConstraintDomainV1::Enumeration(values), C::NotInSet) => {
            Ok(AtomPredicateV1::Exclude(map_enum_values(&source.set_values, values)?))
        }
        (ObjectiveConstraintDomainV1::Action, C::RequireAction) => {
            Ok(AtomPredicateV1::RequireAction)
        }
        (ObjectiveConstraintDomainV1::Action, C::ForbidAction) => {
            Ok(AtomPredicateV1::ForbidAction)
        }
        (ObjectiveConstraintDomainV1::Action, C::ImpliesAction) => {
            let target_source = source
                .implication_target_action_class
                .as_deref()
                .ok_or(ObjectiveAdmissionError::UnsupportedComparator)?;
            let target = profile
                .actions
                .iter()
                .find(|action| action.source_action_class == target_source)
                .ok_or(ObjectiveAdmissionError::UnknownAction)?;
            register_axis(
                registry,
                target.action_id.clone(),
                unit.clone(),
                RegisteredDomainV1::Action,
            )?;
            Ok(AtomPredicateV1::Implies(target.action_id.clone()))
        }
        _ => Err(ObjectiveAdmissionError::UnsupportedComparator),
    }
}

fn registered_domain(
    domain: &ObjectiveConstraintDomainV1,
) -> Result<RegisteredDomainV1, ObjectiveAdmissionError> {
    match domain {
        ObjectiveConstraintDomainV1::Scalar { lower, upper } => {
            if lower > upper {
                return Err(ObjectiveAdmissionError::InvalidProfile("scalar domain"));
            }
            Ok(RegisteredDomainV1::Scalar {
                lower: *lower,
                upper: *upper,
            })
        }
        ObjectiveConstraintDomainV1::Enumeration(values) => {
            let canonical = values.iter().map(|value| value.value.clone()).collect();
            Ok(RegisteredDomainV1::Enumeration(canonical))
        }
        ObjectiveConstraintDomainV1::Action => Ok(RegisteredDomainV1::Action),
    }
}

fn map_enum_values(
    source: &[String],
    mappings: &[crate::objective_admission::ObjectiveEnumValueProfileV1],
) -> Result<BTreeSet<StableId>, ObjectiveAdmissionError> {
    source
        .iter()
        .map(|source_value| {
            mappings
                .iter()
                .find(|mapping| mapping.source_value == *source_value)
                .map(|mapping| mapping.value.clone())
                .ok_or(ObjectiveAdmissionError::UnknownConstraint)
        })
        .collect()
}

fn register_axis(
    registry: &mut RegisteredGrammarV1,
    axis: StableId,
    unit: StableId,
    domain: RegisteredDomainV1,
) -> Result<(), ObjectiveAdmissionError> {
    let next = RegisteredAxisV1 { unit, domain };
    if let Some(current) = registry.axes.get(&axis) {
        if current != &next {
            return Err(ObjectiveAdmissionError::InvalidProfile(
                "feasibility axis mismatch",
            ));
        }
        return Ok(());
    }
    registry.axes.insert(axis, next);
    Ok(())
}

fn generated_constraint_ids(profile: &ObjectiveAdmissionProfileV1) -> BTreeSet<StableId> {
    let resources = &profile.resources;
    [
        resources.time_micros.constraint_id.clone(),
        resources.token_count.constraint_id.clone(),
        resources.compute_micros.constraint_id.clone(),
        resources.memory_bytes.constraint_id.clone(),
        resources.network_bytes.constraint_id.clone(),
        resources.external_effect_count.constraint_id.clone(),
        profile.risk.risk_constraint_id.clone(),
        profile.risk.rollback_constraint_id.clone(),
        profile.risk.compensation_constraint_id.clone(),
        profile.risk.abstention_constraint_id.clone(),
    ]
    .into_iter()
    .collect()
}

fn native_scalar_predicate(relation: ConstraintRelation, bound: FixedQ32) -> AtomPredicateV1 {
    match relation {
        ConstraintRelation::AtLeast => AtomPredicateV1::ScalarInterval {
            lower: bound,
            upper: FixedQ32::from_raw(i64::MAX),
        },
        ConstraintRelation::AtMost => AtomPredicateV1::ScalarInterval {
            lower: FixedQ32::from_raw(i64::MIN),
            upper: bound,
        },
        ConstraintRelation::Equal => AtomPredicateV1::ScalarInterval {
            lower: bound,
            upper: bound,
        },
        ConstraintRelation::NotEqual => AtomPredicateV1::ScalarNotEqual(bound),
        ConstraintRelation::LessThan => AtomPredicateV1::ScalarInterval {
            lower: FixedQ32::from_raw(i64::MIN),
            upper: predecessor(bound.raw()),
        },
        ConstraintRelation::GreaterThan => AtomPredicateV1::ScalarInterval {
            lower: successor(bound.raw()),
            upper: FixedQ32::from_raw(i64::MAX),
        },
    }
}

fn predecessor(raw: i64) -> FixedQ32 {
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

fn stable_id(value: &str, field: &'static str) -> Result<StableId, ObjectiveAdmissionError> {
    StableId::new(value.to_owned()).map_err(|_| ObjectiveAdmissionError::InvalidIdentifier(field))
}

pub(crate) fn hard_constraint_digest(atoms: &[ConstraintAtomV1]) -> Digest32 {
    let mut canonical = atoms.to_vec();
    canonical.sort_by(|left, right| {
        (left.precedence, &left.axis, &left.id).cmp(&(right.precedence, &right.axis, &right.id))
    });
    let mut bytes = b"hepta.objective.rich-constraints.v1".to_vec();
    push_len(&mut bytes, canonical.len());
    for atom in canonical {
        push_id(&mut bytes, &atom.id);
        match atom.precedence {
            AtomPrecedenceV1::Hard(class) => {
                bytes.push(0);
                bytes.push(class.tag());
            }
            AtomPrecedenceV1::Soft => bytes.push(1),
        }
        push_id(&mut bytes, &atom.axis);
        match atom.predicate {
            AtomPredicateV1::ScalarInterval { lower, upper } => {
                bytes.push(0);
                bytes.extend_from_slice(&lower.raw().to_be_bytes());
                bytes.extend_from_slice(&upper.raw().to_be_bytes());
            }
            AtomPredicateV1::ScalarNotEqual(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.raw().to_be_bytes());
            }
            AtomPredicateV1::Include(values) => {
                bytes.push(2);
                push_len(&mut bytes, values.len());
                for value in values {
                    push_id(&mut bytes, &value);
                }
            }
            AtomPredicateV1::Exclude(values) => {
                bytes.push(3);
                push_len(&mut bytes, values.len());
                for value in values {
                    push_id(&mut bytes, &value);
                }
            }
            AtomPredicateV1::RequireAction => bytes.push(4),
            AtomPredicateV1::ForbidAction => bytes.push(5),
            AtomPredicateV1::Implies(target) => {
                bytes.push(6);
                push_id(&mut bytes, &target);
            }
            AtomPredicateV1::IdentityEqual(value) => {
                bytes.push(7);
                match value {
                    crate::IdentityValueV1::Scope(scope) => {
                        bytes.push(0);
                        push_id(&mut bytes, &scope);
                    }
                    crate::IdentityValueV1::Generation(generation) => {
                        bytes.push(1);
                        bytes.extend_from_slice(&generation.to_be_bytes());
                    }
                }
            }
            AtomPredicateV1::Unsupported(value) => {
                bytes.push(8);
                push_id(&mut bytes, &value);
            }
        }
        push_id(&mut bytes, &atom.unit);
        push_id(&mut bytes, &atom.evidence_source);
        bytes.push(match atom.terminality {
            PredicateTerminality::Intermediate => 0,
            PredicateTerminality::Terminal => 1,
        });
        bytes.extend_from_slice(atom.origin_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u32::try_from(value).unwrap_or(u32::MAX).to_be_bytes());
}
''')

# ---------------------------------------------------------------------------
# Admission profile/domain and call graph. Exact-profile byte bound now uses
# the same canonical semantic bytes as the profile digest.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "use crate::ObjectiveConstraintProfileV1;" if False else "use crate::ActionClass;",
    "use crate::ActionClass;",
)
# Insert new profile-domain types immediately before ObjectiveConstraintProfileV1.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ObjectiveConstraintProfileV1 {",
    "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ObjectiveEnumValueProfileV1 {\n    pub source_value: String,\n    pub value: StableId,\n}\n\n#[derive(Clone, Debug, Eq, PartialEq)]\npub enum ObjectiveConstraintDomainV1 {\n    Scalar { lower: FixedQ32, upper: FixedQ32 },\n    Enumeration(Vec<ObjectiveEnumValueProfileV1>),\n    Action,\n}\n\n#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ObjectiveConstraintProfileV1 {",
)
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "    pub class: ConstraintClass,\n    pub axis: StableId,\n}",
    "    pub class: ConstraintClass,\n    pub axis: StableId,\n    pub domain: ObjectiveConstraintDomainV1,\n}",
)
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "pub struct ObjectiveAdmissionContextV1 {\n    pub revision: Revision,\n    pub now_unix_micros: u64,\n    pub selected_profile_digest: Digest32,\n    pub source_authentication: ObjectiveSourceAuthenticationV1,\n}",
    "pub struct ObjectiveAdmissionContextV1 {\n    pub revision: Revision,\n    pub now_unix_micros: u64,\n    pub selected_profile_digest: Digest32,\n    pub source_authentication: ObjectiveSourceAuthenticationV1,\n    pub feasibility_budget: crate::OracleBudgetV1,\n}",
)
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "pub struct ObjectiveAdmissionOutcomeV1 {\n    pub receipt: ObjectiveAdmissionReceiptV1,\n    pub compile_result: Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>,\n}",
    "pub struct ObjectiveAdmissionOutcomeV1 {\n    pub receipt: ObjectiveAdmissionReceiptV1,\n    pub compile_result: Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>,\n    pub run_snapshot: Option<crate::RunStartSnapshotV1>,\n}",
)
# Refine taxonomy.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "            Self::LocaleNotAllowed\n            | Self::SourceFromFuture\n            | Self::SourceStale\n            | Self::DeadlineMissing\n            | Self::DeadlineBeforeObservation\n            | Self::DeadlineExpired => \"OBJ-E007\",",
    "            Self::LocaleNotAllowed => \"OBJ-E010\",\n            Self::SourceFromFuture\n            | Self::SourceStale\n            | Self::DeadlineMissing\n            | Self::DeadlineBeforeObservation\n            | Self::DeadlineExpired => \"OBJ-E011\",",
)
# Replace the final admission tail with explicit rich feasibility -> prevalidated compile.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "    let admitted_source_digest =\n        admitted_source_digest(envelope, profile_digest, &context.source_authentication);\n    let source = adapt_source(envelope, profile, context, admitted_source_digest)?;\n    let compile_result = crate::compile(source)?;\n    Ok(ObjectiveAdmissionOutcomeV1 {\n        receipt: ObjectiveAdmissionReceiptV1 {\n            profile_id: profile.profile_id.clone(),\n            profile_revision: profile.profile_revision,\n            profile_digest,\n            supplied_source_digest,\n            intent_digest,\n            admitted_source_digest,\n            observed_at_unix_micros,\n            deadline_unix_micros,\n            authority: AuthorityPosture::DENY_ALL,\n        },\n        compile_result,\n    })",
    "    let admitted_source_digest =\n        admitted_source_digest(envelope, profile_digest, &context.source_authentication);\n    let mut source = adapt_source(envelope, profile, context, admitted_source_digest)?;\n    let feasibility = crate::admission_feasibility::evaluate(\n        envelope,\n        profile,\n        &source,\n        admitted_source_digest,\n        context.feasibility_budget,\n    )?;\n    let receipt = ObjectiveAdmissionReceiptV1 {\n        profile_id: profile.profile_id.clone(),\n        profile_revision: profile.profile_revision,\n        profile_digest,\n        supplied_source_digest,\n        intent_digest,\n        admitted_source_digest,\n        observed_at_unix_micros,\n        deadline_unix_micros,\n        authority: AuthorityPosture::DENY_ALL,\n    };\n\n    match &feasibility.receipt.outcome {\n        crate::FeasibilityOutcomeV1::Unsupported { .. } => {\n            return Err(ObjectiveAdmissionError::Compiler(\n                ObjectiveError::UnsupportedConstraintLanguage,\n            ));\n        }\n        crate::FeasibilityOutcomeV1::Exhausted => {\n            return Err(ObjectiveAdmissionError::Compiler(\n                ObjectiveError::FeasibilityBudgetExhausted,\n            ));\n        }\n        crate::FeasibilityOutcomeV1::Infeasible {\n            inclusion_minimal_conflicting_ids,\n        } => {\n            return Ok(ObjectiveAdmissionOutcomeV1 {\n                receipt,\n                compile_result: Err(crate::compiler::conflict_receipt(\n                    &source,\n                    inclusion_minimal_conflicting_ids.clone(),\n                )),\n                run_snapshot: None,\n            });\n        }\n        crate::FeasibilityOutcomeV1::Feasible(_) => {}\n    }\n\n    let legal_action_ids = envelope\n        .structured_intent\n        .legal_action_classes\n        .iter()\n        .map(|source_action| action_mapping(profile, source_action).map(|mapping| mapping.action_id.clone()))\n        .collect::<Result<BTreeSet<_>, _>>()?;\n    let missing_required = feasibility\n        .required_actions\n        .difference(&legal_action_ids)\n        .cloned()\n        .collect::<Vec<_>>();\n    if !missing_required.is_empty() {\n        return Ok(ObjectiveAdmissionOutcomeV1 {\n            receipt,\n            compile_result: Err(crate::compiler::conflict_receipt(&source, missing_required)),\n            run_snapshot: None,\n        });\n    }\n    source\n        .forbidden_actions\n        .extend(feasibility.effectively_forbidden_actions.iter().cloned());\n\n    let mut compile_result = crate::compiler::compile_prevalidated(source)?;\n    let run_snapshot = match &mut compile_result {\n        Ok(compiled) => Some(seal_admitted_objective(\n            compiled,\n            envelope,\n            profile,\n            &feasibility.receipt,\n            &receipt,\n        )?),\n        Err(_) => None,\n    };\n    Ok(ObjectiveAdmissionOutcomeV1 {\n        receipt,\n        compile_result,\n        run_snapshot,\n    })",
)
# adapt_source accepts rich-only constraints without projecting them into legacy scalar IR.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "    for source in &envelope.structured_intent.constraints {\n        constraints.push(adapt_constraint(source, profile)?);\n    }",
    "    for source in &envelope.structured_intent.constraints {\n        if let Some(constraint) = adapt_constraint(source, profile)? {\n            constraints.push(constraint);\n        }\n    }",
)
# Replace adapt_constraint and relation functions with complete scalar projection.
pattern = r"fn adapt_constraint\(.*?\n}\n\nfn adapt_predicate"
replacement = r'''fn adapt_constraint(
    source: &ObjectiveSourceConstraintV1,
    profile: &ObjectiveAdmissionProfileV1,
) -> Result<Option<Constraint>, ObjectiveAdmissionError> {
    let mapping = profile
        .constraints
        .iter()
        .find(|mapping| mapping.source_constraint_id == source.constraint_id)
        .ok_or(ObjectiveAdmissionError::UnknownConstraint)?;
    if mapping.expected_unit != source.unit {
        return Err(ObjectiveAdmissionError::ConstraintUnitMismatch);
    }
    let relation = match source.comparator {
        crate::ObjectiveConstraintComparatorV1::Equal => Some(ConstraintRelation::Equal),
        crate::ObjectiveConstraintComparatorV1::NotEqual => Some(ConstraintRelation::NotEqual),
        crate::ObjectiveConstraintComparatorV1::LessThan => Some(ConstraintRelation::LessThan),
        crate::ObjectiveConstraintComparatorV1::LessThanOrEqual => Some(ConstraintRelation::AtMost),
        crate::ObjectiveConstraintComparatorV1::GreaterThan => Some(ConstraintRelation::GreaterThan),
        crate::ObjectiveConstraintComparatorV1::GreaterThanOrEqual => Some(ConstraintRelation::AtLeast),
        crate::ObjectiveConstraintComparatorV1::In
        | crate::ObjectiveConstraintComparatorV1::NotInSet
        | crate::ObjectiveConstraintComparatorV1::RequireAction
        | crate::ObjectiveConstraintComparatorV1::ForbidAction
        | crate::ObjectiveConstraintComparatorV1::ImpliesAction => None,
    };
    Ok(relation.map(|relation| Constraint {
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
    }))
}

fn adapt_predicate'''
regex_replace("codex-rs/hepta-objective/src/objective_admission.rs", pattern, replacement)
pattern = r"fn constraint_relation\(.*?\n}\n\nfn predicate_relation\(.*?\n}\n"
replacement = r'''fn predicate_relation(
    comparator: ObjectivePredicateComparatorV1,
) -> Result<ConstraintRelation, ObjectiveAdmissionError> {
    match comparator {
        ObjectivePredicateComparatorV1::Equal => Ok(ConstraintRelation::Equal),
        ObjectivePredicateComparatorV1::NotEqual => Ok(ConstraintRelation::NotEqual),
        ObjectivePredicateComparatorV1::LessThan => Ok(ConstraintRelation::LessThan),
        ObjectivePredicateComparatorV1::LessThanOrEqual => Ok(ConstraintRelation::AtMost),
        ObjectivePredicateComparatorV1::GreaterThan => Ok(ConstraintRelation::GreaterThan),
        ObjectivePredicateComparatorV1::GreaterThanOrEqual => Ok(ConstraintRelation::AtLeast),
    }
}
'''
regex_replace("codex-rs/hepta-objective/src/objective_admission.rs", pattern, replacement)
# Profile source constraint ceiling aligns with reserved generated constraints.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "const MAX_PROFILE_CONSTRAINTS: usize = 256;",
    "const MAX_PROFILE_CONSTRAINTS: usize = crate::source_envelope_validation::MAX_OBJECTIVE_SOURCE_CONSTRAINTS;",
)
# Canonical byte length replaces manual estimator.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "    if profile_encoded_size(profile) > MAX_PROFILE_ENCODED_BYTES {",
    "    if profile_semantic_bytes(profile).len() > MAX_PROFILE_ENCODED_BYTES {",
)
# Delete profile_encoded_size helper entirely.
text = read("codex-rs/hepta-objective/src/objective_admission.rs")
text, count = re.subn(
    r"\nfn profile_encoded_size\(profile: &ObjectiveAdmissionProfileV1\) -> usize \{.*?\n}\n\nfn validate_source_mappings",
    "\nfn validate_source_mappings",
    text,
    flags=re.S,
)
if count != 1:
    raise RuntimeError(f"profile_encoded_size removal matched {count}")
write("codex-rs/hepta-objective/src/objective_admission.rs", text)
# Profile validation: domain semantics and exact enum mappings.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "    validate_source_mappings(profile)?;\n    validate_generated_constraint_ids(profile)?;",
    "    validate_source_mappings(profile)?;\n    validate_constraint_domains(profile)?;\n    validate_generated_constraint_ids(profile)?;",
)
# Add domain validator before generated-id validator.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "fn validate_generated_constraint_ids(\n    profile: &ObjectiveAdmissionProfileV1,",
    r'''fn validate_constraint_domains(
    profile: &ObjectiveAdmissionProfileV1,
) -> Result<(), ObjectiveAdmissionError> {
    for mapping in &profile.constraints {
        stable_id(&mapping.expected_unit, "constraint unit")?;
        match &mapping.domain {
            ObjectiveConstraintDomainV1::Scalar { lower, upper } if lower <= upper => {}
            ObjectiveConstraintDomainV1::Scalar { .. } => {
                return Err(ObjectiveAdmissionError::InvalidProfile("scalar domain"));
            }
            ObjectiveConstraintDomainV1::Enumeration(values) => {
                if values.is_empty() || values.len() > 128 {
                    return Err(ObjectiveAdmissionError::InvalidProfile("enum domain"));
                }
                let source = values.iter().map(|value| value.source_value.clone()).collect::<Vec<_>>();
                unique_texts(&source, "enum source values")?;
                for value in &source {
                    safe_profile_text(value, "enum source value")?;
                }
                let canonical = values.iter().map(|value| value.value.clone()).collect::<Vec<_>>();
                unique_stable_ids(&canonical, "enum canonical values")?;
            }
            ObjectiveConstraintDomainV1::Action => {
                if !profile.actions.iter().any(|action| action.action_id == mapping.axis) {
                    return Err(ObjectiveAdmissionError::InvalidProfile("action axis mapping"));
                }
            }
        }
    }
    Ok(())
}

fn validate_generated_constraint_ids(
    profile: &ObjectiveAdmissionProfileV1,''',
)
# Profile digest bytes: turn existing digest serializer into byte serializer, then hash it.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "fn profile_digest_unchecked(profile: &ObjectiveAdmissionProfileV1) -> Digest32 {\n    let mut bytes = b\"hepta.objective.admission-profile.v1\".to_vec();",
    "fn profile_semantic_bytes(profile: &ObjectiveAdmissionProfileV1) -> Vec<u8> {\n    let mut bytes = b\"hepta.objective.admission-profile.v1\".to_vec();",
)
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "    push_risk_profile(&mut bytes, &profile.risk);\n    Digest32::of_bytes(&bytes)\n}\n\nfn push_risk_profile",
    "    push_risk_profile(&mut bytes, &profile.risk);\n    bytes\n}\n\nfn profile_digest_unchecked(profile: &ObjectiveAdmissionProfileV1) -> Digest32 {\n    Digest32::of_bytes(&profile_semantic_bytes(profile))\n}\n\nfn push_risk_profile",
)
# Include domain semantics inside canonical profile bytes.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "        bytes.push(mapping.class.tag());\n        push_id(&mut bytes, &mapping.axis);\n    }\n    let mut predicates = profile.predicates.clone();",
    "        bytes.push(mapping.class.tag());\n        push_id(&mut bytes, &mapping.axis);\n        push_constraint_domain(&mut bytes, &mapping.domain);\n    }\n    let mut predicates = profile.predicates.clone();",
)
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "fn push_risk_profile(bytes: &mut Vec<u8>, risk: &ObjectiveRiskProfileV1) {",
    r'''fn push_constraint_domain(bytes: &mut Vec<u8>, domain: &ObjectiveConstraintDomainV1) {
    match domain {
        ObjectiveConstraintDomainV1::Scalar { lower, upper } => {
            bytes.push(0);
            push_i64(bytes, lower.raw());
            push_i64(bytes, upper.raw());
        }
        ObjectiveConstraintDomainV1::Enumeration(values) => {
            bytes.push(1);
            let mut values = values.clone();
            values.sort_by(|left, right| left.source_value.cmp(&right.source_value));
            push_len(bytes, values.len());
            for value in values {
                push_text(bytes, &value.source_value);
                push_id(bytes, &value.value);
            }
        }
        ObjectiveConstraintDomainV1::Action => bytes.push(2),
    }
}

fn push_risk_profile(bytes: &mut Vec<u8>, risk: &ObjectiveRiskProfileV1) {''',
)
# Intent digest retains enum set and implication target.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "    push_i64(bytes, value.bound_q32);\n    push_text(bytes, &value.evidence_source_id);\n    bytes.push(u8::from(value.terminal));\n}\n\nfn parse_utc_micros",
    "    push_i64(bytes, value.bound_q32);\n    let mut set_values = value.set_values.clone();\n    set_values.sort();\n    push_len(bytes, set_values.len());\n    for set_value in set_values {\n        push_text(bytes, &set_value);\n    }\n    match &value.implication_target_action_class {\n        Some(target) => {\n            bytes.push(1);\n            push_text(bytes, target);\n        }\n        None => bytes.push(0),\n    }\n    push_text(bytes, &value.evidence_source_id);\n    bytes.push(u8::from(value.terminal));\n}\n\nfn parse_utc_micros",
)
# Comparator tag gains action variants.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "        crate::ObjectiveConstraintComparatorV1::In => 6,\n        crate::ObjectiveConstraintComparatorV1::NotInSet => 7,",
    "        crate::ObjectiveConstraintComparatorV1::In => 6,\n        crate::ObjectiveConstraintComparatorV1::NotInSet => 7,\n        crate::ObjectiveConstraintComparatorV1::RequireAction => 8,\n        crate::ObjectiveConstraintComparatorV1::ForbidAction => 9,\n        crate::ObjectiveConstraintComparatorV1::ImpliesAction => 10,",
)

# Add admitted-objective sealing helpers before authentication.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "fn validate_authentication(\n    envelope: &ObjectiveSourceEnvelopeV1,",
    r'''fn seal_admitted_objective(
    compiled: &mut ObjectiveCompileReceipt,
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    feasibility: &crate::FeasibilityReceiptV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<crate::RunStartSnapshotV1, ObjectiveAdmissionError> {
    let terminal_ids = envelope
        .structured_intent
        .terminal_conditions
        .iter()
        .map(|value| stable_id(&value.predicate_id, "predicateId"))
        .collect::<Result<BTreeSet<_>, _>>()?;
    let evidence_ids = envelope
        .structured_intent
        .evidence_requirements
        .iter()
        .map(|value| stable_id(&value.requirement_id, "requirementId"))
        .collect::<Result<BTreeSet<_>, _>>()?;
    let mut primary = Vec::new();
    let mut terminal = Vec::new();
    let mut evidence = Vec::new();
    for predicate in std::mem::take(&mut compiled.objective.success_predicates) {
        if terminal_ids.contains(&predicate.id) {
            terminal.push(predicate);
        } else if evidence_ids.contains(&predicate.id) {
            evidence.push(predicate);
        } else {
            primary.push(predicate);
        }
    }
    compiled.objective.success_predicates = primary;
    compiled.objective.terminal_conditions = terminal;
    compiled.objective.evidence_requirements = evidence;
    compiled.objective.constraint_atoms = feasibility.original_constraints.clone();
    compiled.objective.profile_digest = Some(admission.profile_digest);
    compiled.objective.intent_digest = Some(admission.intent_digest);

    let resource_ids = [
        &profile.resources.time_micros,
        &profile.resources.token_count,
        &profile.resources.compute_micros,
        &profile.resources.memory_bytes,
        &profile.resources.network_bytes,
        &profile.resources.external_effect_count,
    ]
    .into_iter()
    .map(|mapping| mapping.constraint_id.clone())
    .collect::<BTreeSet<_>>();
    let risk_ids = BTreeSet::from([
        profile.risk.risk_constraint_id.clone(),
        profile.risk.rollback_constraint_id.clone(),
        profile.risk.compensation_constraint_id.clone(),
        profile.risk.abstention_constraint_id.clone(),
    ]);
    compiled.objective.resource_constraints = compiled
        .objective
        .constraints
        .iter()
        .filter(|constraint| resource_ids.contains(&constraint.id))
        .cloned()
        .collect();
    compiled.objective.risk_constraints = compiled
        .objective
        .constraints
        .iter()
        .filter(|constraint| risk_ids.contains(&constraint.id))
        .cloned()
        .collect();

    let hard_digest = crate::admission_feasibility::hard_constraint_digest(
        &compiled.objective.constraint_atoms,
    );
    let legacy_semantic_digest = compiled.objective.semantic_digest;
    compiled.objective.hard_constraint_digest = hard_digest;
    let mut semantic_bytes = b"hepta.objective.admitted-semantic.v1".to_vec();
    semantic_bytes.extend_from_slice(legacy_semantic_digest.as_array());
    semantic_bytes.extend_from_slice(hard_digest.as_array());
    semantic_bytes.extend_from_slice(admission.profile_digest.as_array());
    semantic_bytes.extend_from_slice(admission.intent_digest.as_array());
    semantic_bytes.extend_from_slice(admission.admitted_source_digest.as_array());
    compiled.objective.semantic_digest = Digest32::of_bytes(&semantic_bytes);

    let mut snapshot_bytes = b"hepta.objective.run-start.v1".to_vec();
    push_id(&mut snapshot_bytes, &compiled.objective.request_id);
    push_id(&mut snapshot_bytes, &compiled.objective.principal_scope);
    push_u64(&mut snapshot_bytes, compiled.objective.revision.get());
    push_digest(&mut snapshot_bytes, compiled.objective.semantic_digest);
    push_digest(&mut snapshot_bytes, admission.admitted_source_digest);
    push_digest(&mut snapshot_bytes, admission.profile_digest);
    push_digest(&mut snapshot_bytes, admission.intent_digest);
    push_u64(&mut snapshot_bytes, admission.observed_at_unix_micros);
    match admission.deadline_unix_micros {
        Some(deadline) => {
            snapshot_bytes.push(1);
            push_u64(&mut snapshot_bytes, deadline);
        }
        None => snapshot_bytes.push(0),
    }
    let snapshot_digest = Digest32::of_bytes(&snapshot_bytes);
    Ok(crate::RunStartSnapshotV1 {
        request_id: compiled.objective.request_id.clone(),
        principal_scope: compiled.objective.principal_scope.clone(),
        revision: compiled.objective.revision,
        objective_digest: compiled.objective.semantic_digest,
        admitted_source_digest: admission.admitted_source_digest,
        profile_digest: admission.profile_digest,
        intent_digest: admission.intent_digest,
        observed_at_unix_micros: admission.observed_at_unix_micros,
        deadline_unix_micros: admission.deadline_unix_micros,
        snapshot_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_authentication(
    envelope: &ObjectiveSourceEnvelopeV1,''',
)

# Existing profile fixtures are scalar domains; context fixtures get deterministic budgets.
for path in [
    "codex-rs/hepta-objective/src/objective_admission_tests.rs",
    "codex-rs/hepta-intelligence/src/vertical_tests.rs",
]:
    text = read(path)
    text = text.replace(
        "            class: ConstraintClass::Task,\n            axis: id(\"latency.micros\"),\n        }],",
        "            class: ConstraintClass::Task,\n            axis: id(\"latency.micros\"),\n            domain: codex_hepta_objective::ObjectiveConstraintDomainV1::Scalar {\n                lower: FixedQ32::from_raw(i64::MIN),\n                upper: FixedQ32::from_raw(i64::MAX),\n            },\n        }]," if "hepta-intelligence" in path else
        "            class: ConstraintClass::Task,\n            axis: id(\"latency.micros\"),\n            domain: super::ObjectiveConstraintDomainV1::Scalar {\n                lower: FixedQ32::from_raw(i64::MIN),\n                upper: FixedQ32::from_raw(i64::MAX),\n            },\n        }],",
    )
    # Add feasibility budget after source_authentication blocks by targeting context literal close.
    if "hepta-objective" in path:
        marker = "            source_digest: envelope.structured_intent.provenance.source_digest,\n        },\n    }\n}"
        replacement = "            source_digest: envelope.structured_intent.provenance.source_digest,\n        },\n        feasibility_budget: crate::OracleBudgetV1 {\n            max_calls: 257,\n            wall_time: std::time::Duration::MAX,\n        },\n    }\n}"
    else:
        marker = "            source_digest: envelope.structured_intent.provenance.source_digest,\n        },\n    }\n}"
        replacement = "            source_digest: envelope.structured_intent.provenance.source_digest,\n        },\n        feasibility_budget: codex_hepta_objective::OracleBudgetV1 {\n            max_calls: 257,\n            wall_time: std::time::Duration::MAX,\n        },\n    }\n}"
    if marker not in text:
        raise RuntimeError(f"{path}: context marker missing")
    text = text.replace(marker, replacement, 1)
    write(path, text)

# Objective admission test expectations now observe canonical split surfaces.
text = read("codex-rs/hepta-objective/src/objective_admission_tests.rs")
text = text.replace("    assert_eq!(3, compiled.objective.success_predicates.len());", "    assert_eq!(1, compiled.objective.success_predicates.len());\n    assert_eq!(1, compiled.objective.terminal_conditions.len());\n    assert_eq!(1, compiled.objective.evidence_requirements.len());\n    assert_eq!(11, compiled.objective.constraint_atoms.len());\n    assert!(outcome.run_snapshot.is_some());")
# Strict comparator is now represented exactly.
old = '''    assert_eq!(
        ObjectiveAdmissionError::UnsupportedComparator,
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("strict comparator must reject")
    );'''
new = '''    let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
        .expect("strict comparator is represented exactly");
    assert!(outcome.compile_result.is_ok());'''
if old not in text:
    raise RuntimeError("strict comparator test body missing")
text = text.replace(old, new, 1)
write("codex-rs/hepta-objective/src/objective_admission_tests.rs", text)

# Append rich enum/action, aggregate-bound and zero-action abstain regressions.
with (ROOT / "codex-rs/hepta-objective/src/objective_admission_tests.rs").open("a", encoding="utf-8") as handle:
    handle.write(r'''

#[test]
fn rich_enum_and_action_implication_are_feasible_on_the_admission_path() {
    let mut profile = profile();
    profile.constraints.extend([
        ObjectiveConstraintProfileV1 {
            source_constraint_id: "mode.allowed".to_string(),
            expected_unit: "mode".to_string(),
            class: ConstraintClass::Task,
            axis: id("mode.axis"),
            domain: super::ObjectiveConstraintDomainV1::Enumeration(vec![
                super::ObjectiveEnumValueProfileV1 {
                    source_value: "safe".to_string(),
                    value: id("mode.safe"),
                },
                super::ObjectiveEnumValueProfileV1 {
                    source_value: "fast".to_string(),
                    value: id("mode.fast"),
                },
            ]),
        },
        ObjectiveConstraintProfileV1 {
            source_constraint_id: "inspect.implies.read".to_string(),
            expected_unit: "action".to_string(),
            class: ConstraintClass::Task,
            axis: id("action.inspect"),
            domain: super::ObjectiveConstraintDomainV1::Action,
        },
        ObjectiveConstraintProfileV1 {
            source_constraint_id: "inspect.required".to_string(),
            expected_unit: "action".to_string(),
            class: ConstraintClass::Task,
            axis: id("action.inspect"),
            domain: super::ObjectiveConstraintDomainV1::Action,
        },
    ]);
    let mut envelope = envelope();
    envelope.structured_intent.constraints.extend([
        ObjectiveSourceConstraintV1 {
            constraint_id: "mode.allowed".to_string(),
            unit: "mode".to_string(),
            comparator: ObjectiveConstraintComparatorV1::In,
            bound_q32: 0,
            set_values: vec!["safe".to_string()],
            implication_target_action_class: None,
            evidence_source_id: "observer.mode".to_string(),
            terminal: false,
        },
        ObjectiveSourceConstraintV1 {
            constraint_id: "inspect.implies.read".to_string(),
            unit: "action".to_string(),
            comparator: ObjectiveConstraintComparatorV1::ImpliesAction,
            bound_q32: 0,
            set_values: Vec::new(),
            implication_target_action_class: Some("read".to_string()),
            evidence_source_id: "observer.action".to_string(),
            terminal: true,
        },
        ObjectiveSourceConstraintV1 {
            constraint_id: "inspect.required".to_string(),
            unit: "action".to_string(),
            comparator: ObjectiveConstraintComparatorV1::RequireAction,
            bound_q32: 0,
            set_values: Vec::new(),
            implication_target_action_class: None,
            evidence_source_id: "observer.action".to_string(),
            terminal: true,
        },
    ]);
    refresh_intent_digest(&mut envelope);
    let context = context(&profile, &envelope);
    let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
        .expect("rich objective should admit");
    let compiled = outcome.compile_result.expect("rich objective should compile");
    assert_eq!(14, compiled.objective.constraint_atoms.len());
    assert!(compiled
        .objective
        .constraint_atoms
        .iter()
        .any(|atom| matches!(atom.predicate, crate::AtomPredicateV1::Include(_))));
    assert!(compiled
        .objective
        .constraint_atoms
        .iter()
        .any(|atom| matches!(atom.predicate, crate::AtomPredicateV1::Implies(_))));
}

#[test]
fn source_constraint_ceiling_reserves_generated_resource_and_risk_slots() {
    let mut envelope = envelope();
    let template = envelope.structured_intent.constraints[0].clone();
    envelope.structured_intent.constraints = (0..247)
        .map(|index| {
            let mut value = template.clone();
            value.constraint_id = format!("constraint-{index:03}");
            value
        })
        .collect();
    assert!(matches!(
        envelope.validate_structure(),
        Err(crate::ObjectiveStructureError::CollectionCount {
            field: "constraints",
            maximum: 246,
            ..
        })
    ));
}

#[test]
fn aggregate_predicate_ceiling_is_enforced_before_mapping() {
    let mut envelope = envelope();
    let template = envelope.structured_intent.success_predicates[0].clone();
    envelope.structured_intent.success_predicates = (0..127)
        .map(|index| {
            let mut value = template.clone();
            value.predicate_id = format!("success-{index:03}");
            value
        })
        .collect();
    assert!(matches!(
        envelope.validate_structure(),
        Err(crate::ObjectiveStructureError::CollectionCount {
            field: "compiledPredicates",
            maximum: 128,
            ..
        })
    ));
}

#[test]
fn empty_legal_action_set_is_a_successful_explicit_abstain() {
    let profile = profile();
    let mut envelope = envelope();
    envelope.structured_intent.legal_action_classes.clear();
    envelope.structured_intent.confirmation_action_classes.clear();
    refresh_intent_digest(&mut envelope);
    let context = context(&profile, &envelope);
    let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
        .expect("empty legal set should admit as abstain");
    let compiled = outcome.compile_result.expect("abstain is a successful outcome");
    assert_eq!(crate::CompileDisposition::ExplicitAbstain, compiled.disposition);
    assert_eq!(1, compiled.objective.legal_actions.len());
    assert_eq!("abstain", compiled.objective.legal_actions[0].id.as_str());
    assert!(outcome.run_snapshot.is_some());
}
''')

# ---------------------------------------------------------------------------
# Library exports and module registration.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/lib.rs",
    "mod compiler;\nmod error;",
    "mod admission_feasibility;\nmod compiler;\nmod error;",
)
replace_once(
    "codex-rs/hepta-objective/src/lib.rs",
    "pub use model::ObjectiveCompileReceipt;\npub use model::ObjectiveConflictReceipt;\npub use model::ObjectiveFunction;",
    "pub use model::ObjectiveCompileReceipt;\npub use model::ObjectiveCompileReceiptV1;\npub use model::ObjectiveConflictReceipt;\npub use model::ObjectiveConflictReceiptV1;\npub use model::ObjectiveFunction;\npub use model::ObjectiveFunctionV1;",
)
replace_once(
    "codex-rs/hepta-objective/src/lib.rs",
    "pub use model::SuccessPredicate;",
    "pub use model::SuccessPredicate;\npub use model::RunStartSnapshotV1;",
)
replace_once(
    "codex-rs/hepta-objective/src/lib.rs",
    "pub use objective_admission::ObjectiveConstraintProfileV1;",
    "pub use objective_admission::ObjectiveConstraintDomainV1;\npub use objective_admission::ObjectiveConstraintProfileV1;\npub use objective_admission::ObjectiveEnumValueProfileV1;",
)
replace_once(
    "codex-rs/hepta-objective/src/lib.rs",
    "pub use source_envelope_validation::ObjectiveStructureError;",
    "pub use source_envelope_validation::MAX_OBJECTIVE_COMPILED_PREDICATES;\npub use source_envelope_validation::MAX_OBJECTIVE_SOURCE_CONSTRAINTS;\npub use source_envelope_validation::ObjectiveStructureError;",
)

# ---------------------------------------------------------------------------
# Make vertical fixtures compile with complete relations/profile domain. The
# actual ExplicitAbstain result-semantic repair is handled in stage 2.
# ---------------------------------------------------------------------------

# source envelope model tests using explicit comparator width still need valid enum operand.
text = read("codex-rs/hepta-objective/src/source_envelope_v1_tests.rs")
text = text.replace(
    "intent.constraints[0].comparator = ObjectiveConstraintComparatorV1::NotInSet;",
    "intent.constraints[0].comparator = ObjectiveConstraintComparatorV1::NotInSet;\n    intent.constraints[0].bound_q32 = 0;\n    intent.constraints[0].set_values = vec![\"blocked\".into()];",
)
write("codex-rs/hepta-objective/src/source_envelope_v1_tests.rs", text)

print("objective compiler stage1 patch applied")
