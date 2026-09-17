#!/usr/bin/env python3
from pathlib import Path
import json

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
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:140]!r}")
    write(path, text.replace(old, new, 1))


def load_json(path: str):
    return json.loads(read(path))


def write_json(path: str, value) -> None:
    write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Fixtures must express the new rich constraint operands and successful abstain.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_json_tests.rs",
    '\"constraints\":[{\"constraintId\":\"effects\",\"unit\":\"count\",\"comparator\":\"not_in\",\"boundQ32\":0,\"evidenceSourceId\":\"observer / effects\",\"terminal\":true}]',
    '\"constraints\":[{\"constraintId\":\"effects\",\"unit\":\"count\",\"comparator\":\"not_in\",\"boundQ32\":0,\"setValues\":[\"blocked\"],\"evidenceSourceId\":\"observer / effects\",\"terminal\":true}]',
)
# Empty legal-action arrays are now a valid route to ExplicitAbstain; retain the
# other hostile structural cases and add a positive decode assertion.
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_json_tests.rs",
    '''    for (pointer, invalid) in [
        ("/locale", json!("é".repeat(17))),
        ("/structuredIntent/legalActionClasses", json!([])),
        (
            "/structuredIntent/legalActionClasses",
            json!(vec!["read"; 129]),''',
    '''    for (pointer, invalid) in [
        ("/locale", json!("é".repeat(17))),
        (
            "/structuredIntent/legalActionClasses",
            json!(vec!["read"; 129]),''',
)
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_json_tests.rs",
    '''    let mut source = original;
    let predicates = source["structuredIntent"]["successPredicates"]''',
    '''    let mut abstain_only = original.clone();
    *abstain_only
        .pointer_mut("/structuredIntent/legalActionClasses")
        .unwrap() = json!([]);
    *abstain_only
        .pointer_mut("/structuredIntent/confirmationActionClasses")
        .unwrap() = json!([]);
    assert!(decode_source_envelope_json_v1(&serde_json::to_vec(&abstain_only).unwrap()).is_ok());

    let mut source = original;
    let predicates = source["structuredIntent"]["successPredicates"]''',
)

replace_once(
    "codex-rs/hepta-objective/src/source_envelope_v1_tests.rs",
    '("legalActionClasses", 1, 128, |s, n| {',
    '("legalActionClasses", 0, 128, |s, n| {',
)
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_v1_tests.rs",
    '("constraints", 1, 256, |s, n| {',
    '("constraints", 1, 246, |s, n| {',
)
replace_once(
    "codex-rs/hepta-objective/src/source_envelope_v1_tests.rs",
    "fn structural_validation_retains_semantics_that_native_compilation_cannot_represent()",
    "fn structural_validation_retains_rich_semantics_for_registered_admission()",
)

# ---------------------------------------------------------------------------
# Canonical ObjectiveFunctionV1 JSON must match the registered contract shape:
# resourceBudget/riskProfile are bounded objects rather than anonymous arrays.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/canonical_output.rs",
    '''    resource_budget: Vec<ConstraintWire>,
    risk_constraints: Vec<ConstraintWire>,
    soft_utility_dimensions: Vec<SoftPreferenceWire>,
}''',
    '''    resource_budget: ConstraintSetWire,
    risk_profile: ConstraintSetWire,
    soft_utility_dimensions: Vec<SoftPreferenceWire>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ConstraintSetWire {
    constraints: Vec<ConstraintWire>,
}''',
)
replace_once(
    "codex-rs/hepta-objective/src/canonical_output.rs",
    '''            resource_budget: objective
                .resource_constraints
                .iter()
                .map(constraint_wire)
                .collect(),
            risk_constraints: objective
                .risk_constraints
                .iter()
                .map(constraint_wire)
                .collect(),''',
    '''            resource_budget: ConstraintSetWire {
                constraints: objective
                    .resource_constraints
                    .iter()
                    .map(constraint_wire)
                    .collect(),
            },
            risk_profile: ConstraintSetWire {
                constraints: objective
                    .risk_constraints
                    .iter()
                    .map(constraint_wire)
                    .collect(),
            },''',
)
replace_once(
    "codex-rs/hepta-objective/src/objective_admission_tests.rs",
    '        "riskConstraints",',
    '        "riskProfile",',
)

# The registry names ObjectiveFunctionV1 as the cross-module typed contract.
# Add a dedicated canonical function encoder alongside the receipt encoder so
# consumers never need to peel a receipt wrapper to persist/transport the function.
replace_once(
    "codex-rs/hepta-objective/src/canonical_output.rs",
    '''pub fn encode_objective_compile_receipt_v1(
    receipt: &ObjectiveCompileReceipt,
) -> Result<Vec<u8>, ObjectiveWireError> {
    let objective = &receipt.objective;
    let profile_digest = objective''',
    '''pub fn encode_objective_compile_receipt_v1(
    receipt: &ObjectiveCompileReceipt,
) -> Result<Vec<u8>, ObjectiveWireError> {
    let objective = objective_wire(&receipt.objective)?;
    let wire = ReceiptWire {
        disposition: match receipt.disposition {
            CompileDisposition::Compiled => "compiled",
            CompileDisposition::ExplicitAbstain => "explicit_abstain",
        },
        objective,
    };
    encode_bounded(&wire)
}

pub fn encode_objective_function_v1(
    objective: &crate::ObjectiveFunction,
) -> Result<Vec<u8>, ObjectiveWireError> {
    let wire = objective_wire(objective)?;
    encode_bounded(&wire)
}

pub fn encode_run_start_snapshot_v1(
    snapshot: &crate::RunStartSnapshotV1,
) -> Result<Vec<u8>, ObjectiveWireError> {
    #[derive(Serialize)]
    #[serde(rename_all = "camelCase")]
    struct SnapshotWire {
        request_id: String,
        principal_scope: String,
        revision: u64,
        objective_digest: String,
        admitted_source_digest: String,
        profile_digest: String,
        intent_digest: String,
        observed_at_unix_micros: u64,
        deadline_unix_micros: Option<u64>,
        snapshot_digest: String,
        authority: &'static str,
    }
    encode_bounded(&SnapshotWire {
        request_id: snapshot.request_id.to_string(),
        principal_scope: snapshot.principal_scope.to_string(),
        revision: snapshot.revision.get(),
        objective_digest: snapshot.objective_digest.to_string(),
        admitted_source_digest: snapshot.admitted_source_digest.to_string(),
        profile_digest: snapshot.profile_digest.to_string(),
        intent_digest: snapshot.intent_digest.to_string(),
        observed_at_unix_micros: snapshot.observed_at_unix_micros,
        deadline_unix_micros: snapshot.deadline_unix_micros,
        snapshot_digest: snapshot.snapshot_digest.to_string(),
        authority: "deny_all",
    })
}

fn objective_wire(
    objective: &crate::ObjectiveFunction,
) -> Result<ObjectiveWire, ObjectiveWireError> {
    let profile_digest = objective''',
)
# Replace the old tail of the receipt function, which now lives in objective_wire.
old = '''    let wire = ReceiptWire {
        disposition: match receipt.disposition {
            CompileDisposition::Compiled => "compiled",
            CompileDisposition::ExplicitAbstain => "explicit_abstain",
        },
        objective: ObjectiveWire {
            request_id: objective.request_id.to_string(),
            principal_scope: objective.principal_scope.to_string(),
            revision: objective.revision.get(),
            source_digest: objective.source_digest.to_string(),
            schema_digest: objective.schema_digest.to_string(),
            profile_digest: profile_digest.to_string(),
            intent_digest: intent_digest.to_string(),
            hard_constraint_digest: objective.hard_constraint_digest.to_string(),
            semantic_digest: objective.semantic_digest.to_string(),
            hard_constraints: hard_constraints.into_iter().map(atom_wire).collect(),
            success_predicates: objective.success_predicates.iter().map(predicate_wire).collect(),
            terminal_conditions: objective.terminal_conditions.iter().map(predicate_wire).collect(),
            evidence_requirements: objective.evidence_requirements.iter().map(predicate_wire).collect(),
            allowed_action_classes: objective.legal_actions.iter().map(action_wire).collect(),
            forbidden_action_classes: objective
                .forbidden_actions
                .iter()
                .map(ToString::to_string)
                .collect(),
            resource_budget: ConstraintSetWire {
                constraints: objective
                    .resource_constraints
                    .iter()
                    .map(constraint_wire)
                    .collect(),
            },
            risk_profile: ConstraintSetWire {
                constraints: objective
                    .risk_constraints
                    .iter()
                    .map(constraint_wire)
                    .collect(),
            },
            soft_utility_dimensions: objective
                .soft_preferences
                .iter()
                .map(preference_wire)
                .collect(),
        },
    };
    let encoded = serde_json::to_vec(&wire)?;
    if encoded.len() > MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES {
        return Err(ObjectiveWireError::EncodedBytesExceeded {
            actual: encoded.len(),
            maximum: MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES,
        });
    }
    Ok(encoded)
}'''
new = '''    Ok(ObjectiveWire {
        request_id: objective.request_id.to_string(),
        principal_scope: objective.principal_scope.to_string(),
        revision: objective.revision.get(),
        source_digest: objective.source_digest.to_string(),
        schema_digest: objective.schema_digest.to_string(),
        profile_digest: profile_digest.to_string(),
        intent_digest: intent_digest.to_string(),
        hard_constraint_digest: objective.hard_constraint_digest.to_string(),
        semantic_digest: objective.semantic_digest.to_string(),
        hard_constraints: hard_constraints.into_iter().map(atom_wire).collect(),
        success_predicates: objective.success_predicates.iter().map(predicate_wire).collect(),
        terminal_conditions: objective.terminal_conditions.iter().map(predicate_wire).collect(),
        evidence_requirements: objective.evidence_requirements.iter().map(predicate_wire).collect(),
        allowed_action_classes: objective.legal_actions.iter().map(action_wire).collect(),
        forbidden_action_classes: objective
            .forbidden_actions
            .iter()
            .map(ToString::to_string)
            .collect(),
        resource_budget: ConstraintSetWire {
            constraints: objective
                .resource_constraints
                .iter()
                .map(constraint_wire)
                .collect(),
        },
        risk_profile: ConstraintSetWire {
            constraints: objective
                .risk_constraints
                .iter()
                .map(constraint_wire)
                .collect(),
        },
        soft_utility_dimensions: objective
            .soft_preferences
            .iter()
            .map(preference_wire)
            .collect(),
    })
}

fn encode_bounded<T: Serialize>(value: &T) -> Result<Vec<u8>, ObjectiveWireError> {
    let encoded = serde_json::to_vec(value)?;
    if encoded.len() > MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES {
        return Err(ObjectiveWireError::EncodedBytesExceeded {
            actual: encoded.len(),
            maximum: MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES,
        });
    }
    Ok(encoded)
}'''
replace_once("codex-rs/hepta-objective/src/canonical_output.rs", old, new)

replace_once(
    "codex-rs/hepta-objective/src/lib.rs",
    "pub use canonical_output::encode_objective_compile_receipt_v1;",
    "pub use canonical_output::encode_objective_compile_receipt_v1;\npub use canonical_output::encode_objective_function_v1;\npub use canonical_output::encode_run_start_snapshot_v1;",
)

# Publication records bind both canonical ObjectiveFunctionV1 and RunStartSnapshotV1
# bytes rather than only the receipt wrapper.
replace_once(
    "codex-rs/hepta-intelligence/src/objective_publication.rs",
    "use codex_hepta_objective::encode_objective_compile_receipt_v1;",
    "use codex_hepta_objective::encode_objective_compile_receipt_v1;\nuse codex_hepta_objective::encode_objective_function_v1;\nuse codex_hepta_objective::encode_run_start_snapshot_v1;",
)
replace_once(
    "codex-rs/hepta-intelligence/src/objective_publication.rs",
    '''    pub canonical_objective_bytes: Vec<u8>,
    pub publication_digest: Digest32,''',
    '''    pub canonical_objective_bytes: Vec<u8>,
    pub canonical_function_bytes: Vec<u8>,
    pub canonical_run_snapshot_bytes: Vec<u8>,
    pub publication_digest: Digest32,''',
)
replace_once(
    "codex-rs/hepta-intelligence/src/objective_publication.rs",
    '''    let canonical_objective_bytes = encode_objective_compile_receipt_v1(&objective)
        .map_err(ObjectiveCallerError::CanonicalOutput)?;
    let mut bytes = b"hepta.objective.publication.v1".to_vec();''',
    '''    let canonical_objective_bytes = encode_objective_compile_receipt_v1(&objective)
        .map_err(ObjectiveCallerError::CanonicalOutput)?;
    let canonical_function_bytes = encode_objective_function_v1(&objective.objective)
        .map_err(ObjectiveCallerError::CanonicalOutput)?;
    let canonical_run_snapshot_bytes = encode_run_start_snapshot_v1(&run_snapshot)
        .map_err(ObjectiveCallerError::CanonicalOutput)?;
    let mut bytes = b"hepta.objective.publication.v1".to_vec();''',
)
replace_once(
    "codex-rs/hepta-intelligence/src/objective_publication.rs",
    '''    bytes.extend_from_slice(run_snapshot.snapshot_digest.as_array());
    bytes.extend_from_slice(&canonical_objective_bytes);
    let record = ObjectivePublicationRecordV1 {
        admission,
        objective,
        run_snapshot,
        canonical_objective_bytes,
        publication_digest: Digest32::of_bytes(&bytes),
    };''',
    '''    bytes.extend_from_slice(run_snapshot.snapshot_digest.as_array());
    bytes.extend_from_slice(&canonical_objective_bytes);
    bytes.extend_from_slice(&canonical_function_bytes);
    bytes.extend_from_slice(&canonical_run_snapshot_bytes);
    let record = ObjectivePublicationRecordV1 {
        admission,
        objective,
        run_snapshot,
        canonical_objective_bytes,
        canonical_function_bytes,
        canonical_run_snapshot_bytes,
        publication_digest: Digest32::of_bytes(&bytes),
    };''',
)
replace_once(
    "codex-rs/hepta-intelligence/src/vertical_tests.rs",
    "    assert!(!record.canonical_objective_bytes.is_empty());",
    "    assert!(!record.canonical_objective_bytes.is_empty());\n    assert!(!record.canonical_function_bytes.is_empty());\n    assert!(!record.canonical_run_snapshot_bytes.is_empty());",
)

# ---------------------------------------------------------------------------
# Canonical protocol schemas now describe the actual explicit V1 outputs.
# ---------------------------------------------------------------------------
schemas = load_json("docs/contracts/PROTOCOL_SCHEMAS.json")
protocols = schemas["protocols"]
objective = next(row for row in protocols if row["id"] == "ObjectiveFunctionV1")
objective["fields"] = [
    {"name": "requestId", "type": "id128", "required": True, "maxBytes": 128},
    {"name": "principalScope", "type": "id128", "required": True, "maxBytes": 128},
    {"name": "revision", "type": "u64", "required": True},
    {"name": "sourceDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "schemaDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "profileDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "intentDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "hardConstraintDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "semanticDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "hardConstraints", "type": "bounded_array", "required": True, "maxBytes": 65536},
    {"name": "successPredicates", "type": "bounded_array", "required": True, "maxBytes": 32768},
    {"name": "terminalConditions", "type": "bounded_array", "required": True, "maxBytes": 16384},
    {"name": "evidenceRequirements", "type": "bounded_array", "required": True, "maxBytes": 32768},
    {"name": "allowedActionClasses", "type": "bounded_array", "required": True, "maxBytes": 32768},
    {"name": "forbiddenActionClasses", "type": "bounded_array", "required": True, "maxBytes": 32768},
    {"name": "resourceBudget", "type": "bounded_object", "required": True, "maxBytes": 8192},
    {"name": "riskProfile", "type": "bounded_object", "required": True, "maxBytes": 8192},
    {"name": "softUtilityDimensions", "type": "bounded_array", "required": True, "maxBytes": 16384},
]
for invariant in [
    "hard_constraints_bind_rich_registered_atoms",
    "admission_profile_and_intent_digests_are_required",
    "terminal_evidence_resource_and_risk_semantics_are_explicit",
]:
    if invariant not in objective["invariants"]:
        objective["invariants"].append(invariant)

snapshot = next(row for row in protocols if row["id"] == "RunStartSnapshotV1")
snapshot["fields"] = [
    {"name": "requestId", "type": "id128", "required": True, "maxBytes": 128},
    {"name": "principalScope", "type": "id128", "required": True, "maxBytes": 128},
    {"name": "revision", "type": "u64", "required": True},
    {"name": "objectiveDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "admittedSourceDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "profileDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "intentDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "observedAtUnixMicros", "type": "u64", "required": True},
    {"name": "deadlineUnixMicros", "type": "u64", "required": False},
    {"name": "snapshotDigest", "type": "sha256", "required": True, "maxBytes": 64},
    {"name": "authority", "type": "enum", "required": True, "maxBytes": 32},
]
for invariant in [
    "objective_profile_intent_and_source_digests_are_coherent",
    "authority_is_deny_all",
]:
    if invariant not in snapshot["invariants"]:
        snapshot["invariants"].append(invariant)
write_json("docs/contracts/PROTOCOL_SCHEMAS.json", schemas)

# ---------------------------------------------------------------------------
# Remove stale source-gap prose that still says the adapter/compiler connection
# does not exist. Keep the real remaining product-host/evidence boundaries.
# ---------------------------------------------------------------------------
path = "docs/readiness/GAP_CLOSURE_IMPLEMENTATION.md"
text = read(path)
old = '''Canonical objective admission also needs an explicit native adapter and
registered baseline/classification profile. The canonical envelope cannot by
itself recover native constraint class/axis, principal scope or a selected soft
weight; resource, risk and evidence requirements must retain their semantics.
Plain turn text and attribution metadata cannot supply this missing binding.

The owner-local `ObjectiveSourceEnvelopeV1` representation now preserves every
canonical input field and integer/enum alternative. Its `validate_structure`
checks raw UTF-8 field sizes, collection counts and within-array semantic keys.
It neither admits a wire message nor converts a trust label into authority.
Canonical encoding and aggregate encoded bounds, NFC, identifier/time syntax,
digest/profile verification and the actual compiler adapter remain separate
prerequisites. The existing scalar compiler API and digest scope are preserved.

The separate `decode_source_envelope_json_v1` input decoder now checks the
specified JSON field grammar through private DTOs. Nested structs must be
objects, enums must be strings, and duplicate decoded keys, unknown or missing
required fields, explicit nulls, wrong integer widths and malformed digest
strings fail closed. Optional deadline omission is allowed; a present deadline
must be a string. The raw JSON ingress guard is 262144 bytes including whitespace
and escapes, separately from canonical or nested aggregate encoded bounds.
Errors expose only safe structural details. The decoder preserves source
spelling and supplied trust/digest values; it does not publish canonical bytes,
verify profiles, normalize identities, admit authority or connect the compiler
to the product host. The owner-local models gain no public serde wire surface.'''
new = '''Canonical objective admission now has a profile-bound native adapter. The
admission profile supplies registered constraint class, axis, unit and domain;
the authenticated source context binds principal/source identity and the exact
profile digest. Scalar equality/inequality/strict bounds, finite-enum inclusion
and exclusion, and positive action require/forbid/implication atoms enter the
bounded `check_feasibility_v1` engine before the legacy scalar compatibility
projection is compiled. Resource, risk, terminal and evidence semantics remain
explicit in the admitted `ObjectiveFunctionV1` projection and canonical JSON.

The owner-local `ObjectiveSourceEnvelopeV1` representation preserves every
canonical input field and now carries explicit set operands and action implication
targets for rich constraints. `validate_structure` reserves the ten generated
resource/risk atom slots, enforces the aggregate compiled-predicate ceiling, and
accepts an empty caller legal-action set so intrinsic `abstain` remains a typed
successful outcome. It still does not convert a supplied trust label into
authority; authenticated admission remains mandatory.

The separate `decode_source_envelope_json_v1` input decoder checks the specified
JSON field grammar through private DTOs. Nested structs must be objects, enums
must be strings, and duplicate decoded keys, unknown or missing required fields,
explicit nulls, wrong integer widths and malformed digest strings fail closed.
Optional deadline omission is allowed; a present deadline must be a string. The
raw JSON ingress guard remains 262144 bytes including whitespace and escapes.
Canonical `ObjectiveFunctionV1`, compile-receipt and `RunStartSnapshotV1` bytes
are emitted only after profile/source/intent validation and successful bounded
feasibility. `intelligence.control` provides an atomic publication-port adapter,
but the selected product-host owner store, target-host measurements and
independent acceptance remain separate qualification gates.'''
if old not in text:
    raise RuntimeError("stale objective gap block not found")
write(path, text.replace(old, new, 1))

# Make the stable module guide describe the real rich path without advancing
# activation/release truth states.
path = "docs/modules/objective.compiler/TECHNICAL.md"
text = read(path)
needle = "The bounded components are:\n\n- `input normalizer`\n- `constraint validator`\n- `deterministic compiler`\n- `digest and receipt emitter`"
replacement = "The bounded components are:\n\n- `input normalizer`\n- `constraint validator`\n- `registered rich-feasibility adapter`\n- `deterministic compiler`\n- `canonical ObjectiveFunctionV1 / RunStartSnapshotV1 encoder`\n- `digest and receipt emitter`"
if needle not in text:
    raise RuntimeError("objective guide component list not found")
text = text.replace(needle, replacement, 1)
text = text.replace(
    "Stateless compiler/admission library; embed it at a request boundary and preserve its immutable objective/run snapshot in the owning caller.",
    "Stateless compiler/admission library; embed it at a request boundary and preserve its immutable objective/run snapshot through the injected owner publication port. The repository-side `intelligence.control` adapter performs no durable write itself.",
    1,
)
write(path, text)

# Intelligence implementation dossier, if present, records the new adapter as a
# composition boundary rather than a new authoritative writer.
path = "qualification/module-execution-dossiers/detail/intelligence.control.md"
if (ROOT / path).exists():
    text = read(path)
    if "ObjectivePublicationPortV1" not in text:
        marker = "## 8. Current native implementation"
        addition = '''## 7A. Objective publication boundary\n\n`admit_compile_and_publish_objective_v1` composes authenticated objective admission with canonical `ObjectiveFunctionV1` and `RunStartSnapshotV1` encoding. It submits one immutable `ObjectivePublicationRecordV1` to an injected owner `ObjectivePublicationPortV1`; identical replays are typed and semantic drift conflicts. The façade remains non-authoritative and owns no durable objective store.\n\n'''
        if marker not in text:
            raise RuntimeError("intelligence dossier current implementation heading missing")
        text = text.replace(marker, addition + marker, 1)
        write(path, text)

# Implementation map exposes all canonical encoder entrypoints.
obj_map = load_json("docs/modules/objective.compiler/IMPLEMENTATION_MAP.json")
existing = {op["operation"] for op in obj_map["operations"]}
for operation, symbol, test in [
    (
        "encode_objective_function_v1",
        "codex_hepta_objective::encode_objective_function_v1",
        "admitted_objective_has_deterministic_bounded_canonical_output",
    ),
    (
        "encode_run_start_snapshot_v1",
        "codex_hepta_objective::encode_run_start_snapshot_v1",
        "empty_legal_action_set_is_a_successful_explicit_abstain",
    ),
]:
    if operation not in existing:
        obj_map["operations"].append({
            "operation": operation,
            "nativeSymbol": symbol,
            "sourcePath": "codex-rs/hepta-objective/src/canonical_output.rs",
            "inputs": ["admitted native V1 value"],
            "outputs": ["bounded canonical JSON bytes"],
            "state": "source_implemented_not_product_composed",
            "authority": "none",
            "tests": [{
                "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
                "symbol": test,
            }],
            "designOperation": operation,
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "sourcePathExists": True,
        })
write_json("docs/modules/objective.compiler/IMPLEMENTATION_MAP.json", obj_map)

print("objective compiler stage3 alignment applied")
