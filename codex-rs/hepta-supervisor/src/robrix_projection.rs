use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_matrix_protocol::LocalApprovalDecision;
use codex_hepta_matrix_protocol::MATRIXD_CONTROL_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MAX_MATRIXD_CONTROL_FRAME_BYTES;
use codex_hepta_matrix_protocol::MAX_MATRIXD_ERROR_CODE_BYTES;
use codex_hepta_matrix_protocol::MAX_MATRIXD_ERROR_MESSAGE_BYTES;
use codex_hepta_matrix_protocol::MAX_MATRIXD_EVENT_BATCH;
use codex_hepta_matrix_protocol::MAX_PENDING_APPROVAL_SUMMARY_BYTES;
use codex_hepta_matrix_protocol::MAX_PENDING_APPROVALS;
use codex_hepta_matrix_protocol::MAX_RUNTIME_IDENTIFIER_BYTES;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::MatrixdEvent;
use codex_hepta_matrix_protocol::MatrixdEventBatch;
use codex_hepta_matrix_protocol::MatrixdEventKind;
use codex_hepta_matrix_protocol::MatrixdFence;
use codex_hepta_matrix_protocol::MatrixdHealth;
use codex_hepta_matrix_protocol::MatrixdLifecycle;
use codex_hepta_matrix_protocol::MatrixdMethod;
use codex_hepta_matrix_protocol::MatrixdPayload;
use codex_hepta_matrix_protocol::MatrixdRequest;
use codex_hepta_matrix_protocol::MatrixdResponse;
use codex_hepta_matrix_protocol::MatrixdSnapshot;
use codex_hepta_matrix_protocol::PendingApproval;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Map;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;

use crate::daemon_protocol::ControlStateDigest;
use crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES;
use crate::daemon_protocol::MAX_SUPERVISORD_ROSTER;
use crate::daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use crate::daemon_protocol::SupervisorEpoch;
use crate::daemon_protocol::SupervisordAgentStatus;
use crate::daemon_protocol::SupervisordControlFence;
use crate::daemon_protocol::SupervisordHealth;
use crate::daemon_protocol::SupervisordMatrixStatus;
use crate::daemon_protocol::SupervisordMethod;
use crate::daemon_protocol::SupervisordMutation;
use crate::daemon_protocol::SupervisordPayload;
use crate::daemon_protocol::SupervisordRequest;
use crate::daemon_protocol::SupervisordResponse;
use crate::robrix_protocol::ROBRIX_SUPERVISORD_ALLOWED_METHODS;
use crate::robrix_protocol::RobrixSupervisordMethod;
use crate::robrix_protocol::RobrixSupervisordRequest;
use crate::robrix_protocol::RobrixSupervisordResponse;

pub const ROBRIX_CONTROL_PROJECTION_SCHEMA_VERSION: u32 = 1;

pub const GENERATED_CONSTANTS_FILE: &str = "robrix_control_projection.rs";
pub const SUPERVISORD_SCHEMA_FILE: &str = "supervisord-readonly-v2.schema.json";
pub const MATRIXD_SCHEMA_FILE: &str = "matrixd-control-v2.schema.json";
pub const CORPUS_FILE: &str = "cross-parser-corpus-v2.json";
pub const MANIFEST_FILE: &str = "manifest.json";

const AGENT_A: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const AGENT_B: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13";
const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
const DIGEST_A: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const DIGEST_B: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const JSON_SCHEMA_VALIDATION_ROLE: &str = "structural_and_locally_expressible_invariants_only";
const AUTHORITATIVE_SEMANTIC_VALIDATOR: &str =
    "generated_cross_parser_corpus_with_rust_protocol_validation";
const JSON_SCHEMA_NON_SCHEMA_INVARIANT_CLASSES: [&str; 5] = [
    "selected_process_context",
    "cross_object_field_equality",
    "cross_element_key_uniqueness",
    "requested_cursor_contiguity",
    "cross_field_ordering",
];
const SUPERVISORD_NON_SCHEMA_INVARIANTS: [&str; 5] = [
    "response_request_id_matches_outstanding_request",
    "agent_status_fields_equal_control_fence",
    "matrix_attached_generation_equals_agent_spawn_generation",
    "control_fence_spawn_generation_not_greater_than_runtime_generation",
    "control_fence_current_and_previous_release_differ",
];
const MATRIXD_NON_SCHEMA_INVARIANTS: [&str; 5] = [
    "request_agent_and_fence_match_selected_process",
    "response_envelope_matches_selected_process_and_request",
    "pending_approval_keys_are_unique",
    "event_cursors_are_contiguous_from_requested_after_cursor",
    "event_latest_cursor_is_not_less_than_next_cursor",
];

pub fn generated_robrix_control_artifacts() -> Result<BTreeMap<String, Vec<u8>>> {
    let mut artifacts = BTreeMap::from([
        (
            GENERATED_CONSTANTS_FILE.to_string(),
            generated_constants_source().into_bytes(),
        ),
        (
            SUPERVISORD_SCHEMA_FILE.to_string(),
            canonical_json(&supervisord_schema())?,
        ),
        (
            MATRIXD_SCHEMA_FILE.to_string(),
            canonical_json(&matrixd_schema())?,
        ),
        (CORPUS_FILE.to_string(), canonical_json(&corpus()?)?),
    ]);
    let files = artifacts
        .iter()
        .map(|(name, bytes)| {
            (
                name.clone(),
                ArtifactDigest {
                    bytes: bytes.len() as u64,
                    sha256: sha256(bytes),
                },
            )
        })
        .collect();
    let manifest = ProjectionManifest {
        schema_version: ROBRIX_CONTROL_PROJECTION_SCHEMA_VERSION,
        supervisord_schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
        supervisord_max_frame_bytes: MAX_SUPERVISORD_CONTROL_FRAME_BYTES,
        supervisord_allowed_methods: ROBRIX_SUPERVISORD_ALLOWED_METHODS,
        matrixd_schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        matrixd_max_frame_bytes: MAX_MATRIXD_CONTROL_FRAME_BYTES,
        matrixd_bootstrap_methods: ["health", "snapshot"],
        matrixd_fenced_methods: ["events", "cancel_turn", "resolve_approval"],
        required_json_schema_keywords: ["x-hepta-max-utf8-bytes", "x-hepta-safe-text-profile"],
        json_schema_validation_role: JSON_SCHEMA_VALIDATION_ROLE,
        authoritative_semantic_validator: AUTHORITATIVE_SEMANTIC_VALIDATOR,
        json_schema_non_schema_invariant_classes: JSON_SCHEMA_NON_SCHEMA_INVARIANT_CLASSES,
        supervisord_non_schema_invariants: SUPERVISORD_NON_SCHEMA_INVARIANTS,
        matrixd_non_schema_invariants: MATRIXD_NON_SCHEMA_INVARIANTS,
        files,
    };
    artifacts.insert(MANIFEST_FILE.to_string(), canonical_json(&manifest)?);
    Ok(artifacts)
}

pub fn write_robrix_control_projection(output_dir: &Path) -> Result<()> {
    fs::create_dir_all(output_dir)
        .with_context(|| format!("create projection directory {}", output_dir.display()))?;
    for (name, bytes) in generated_robrix_control_artifacts()? {
        let path = output_dir.join(name);
        fs::write(&path, bytes)
            .with_context(|| format!("write generated projection {}", path.display()))?;
    }
    Ok(())
}

pub fn verify_robrix_control_corpus(bytes: &[u8]) -> Result<usize> {
    let document: CorpusDocument = serde_json::from_slice(bytes).context("parse Robrix corpus")?;
    ensure!(
        document.schema_version == ROBRIX_CONTROL_PROJECTION_SCHEMA_VERSION,
        "unexpected Robrix corpus schema"
    );
    ensure!(!document.cases.is_empty(), "Robrix corpus is empty");
    for case in &document.cases {
        ensure!(
            case.wire_utf8.len() as u64 == case.wire_bytes,
            "{} wire length changed",
            case.id
        );
        ensure!(
            sha256(case.wire_utf8.as_bytes()) == case.wire_sha256,
            "{} wire digest changed",
            case.id
        );
        ensure!(case.wire_utf8.ends_with('\n'), "{} is not framed", case.id);
        ensure!(
            !case.wire_utf8[..case.wire_utf8.len() - 1].contains('\n'),
            "{} contains multiple frames",
            case.id
        );
        let frame_bound = match case.plane {
            CorpusPlane::Supervisord => MAX_SUPERVISORD_CONTROL_FRAME_BYTES,
            CorpusPlane::Matrixd => MAX_MATRIXD_CONTROL_FRAME_BYTES,
        };
        ensure!(
            case.wire_bytes <= frame_bound,
            "{} exceeds frame bound",
            case.id
        );
        ensure!(
            case.expected.backend_projection_decode == case.expected.robrix_decode
                && case.expected.backend_projection_validate == case.expected.robrix_validate,
            "{} backend/UI expectation drift",
            case.id
        );
        ensure!(
            case.expected.backend_json_schema_validate == case.expected.backend_projection_validate
                || (case.expected.backend_json_schema_validate
                    && !case.expected.backend_projection_validate
                    && case.expected.json_schema_semantic_gap.is_some()),
            "{} has an undeclared JSON Schema/semantic validation divergence",
            case.id
        );
        ensure!(
            (case.expected.backend_json_schema_validate
                != case.expected.backend_projection_validate)
                == case.expected.json_schema_semantic_gap.is_some(),
            "{} JSON Schema semantic-gap declaration drift",
            case.id
        );
        match (case.plane, case.direction) {
            (CorpusPlane::Supervisord, CorpusDirection::Request) => {
                verify_supervisord_request_case(case)?
            }
            (CorpusPlane::Supervisord, CorpusDirection::Response) => {
                verify_supervisord_response_case(case)?
            }
            (CorpusPlane::Matrixd, CorpusDirection::Request) => verify_matrixd_request_case(case)?,
            (CorpusPlane::Matrixd, CorpusDirection::Response) => {
                verify_matrixd_response_case(case)?
            }
        }
    }
    verify_corpus_coverage(&document)?;
    Ok(document.cases.len())
}

fn verify_corpus_coverage(document: &CorpusDocument) -> Result<()> {
    let mut ids = BTreeMap::new();
    let mut supervisord_methods = BTreeSet::new();
    let mut supervisord_payloads = BTreeSet::new();
    let mut matrixd_methods = BTreeSet::new();
    let mut matrixd_payloads = BTreeSet::new();
    let mut matrixd_events = BTreeSet::new();

    for case in &document.cases {
        ensure!(
            ids.insert(case.id.as_str(), case).is_none(),
            "duplicate corpus case ID {}",
            case.id
        );
        if !case.expected.backend_projection_validate {
            continue;
        }
        let wire: Value = serde_json::from_str(&case.wire_utf8)
            .with_context(|| format!("parse validated corpus case {}", case.id))?;
        let tagged = |container: &str| -> Result<String> {
            wire.get(container)
                .and_then(|value| value.get("type"))
                .and_then(Value::as_str)
                .map(str::to_string)
                .with_context(|| format!("{} is missing {container}.type", case.id))
        };
        match (case.plane, case.direction) {
            (CorpusPlane::Supervisord, CorpusDirection::Request) => {
                supervisord_methods.insert(tagged("method")?);
            }
            (CorpusPlane::Supervisord, CorpusDirection::Response) => {
                supervisord_payloads.insert(tagged("payload")?);
            }
            (CorpusPlane::Matrixd, CorpusDirection::Request) => {
                matrixd_methods.insert(tagged("method")?);
            }
            (CorpusPlane::Matrixd, CorpusDirection::Response) => {
                let payload = tagged("payload")?;
                if payload == "events" {
                    for event in wire["payload"]["events"]
                        .as_array()
                        .with_context(|| format!("{} events payload is not an array", case.id))?
                    {
                        matrixd_events.insert(
                            event
                                .get("kind")
                                .and_then(|kind| kind.get("type"))
                                .and_then(Value::as_str)
                                .with_context(|| {
                                    format!("{} contains an untagged Matrix event", case.id)
                                })?
                                .to_string(),
                        );
                    }
                }
                matrixd_payloads.insert(payload);
            }
        }
    }

    ensure_exact_tags(
        "Robrix supervisord method",
        supervisord_methods,
        &["health", "roster", "snapshot"],
    )?;
    ensure_exact_tags(
        "Robrix supervisord payload",
        supervisord_payloads,
        &["health", "roster", "agent", "error"],
    )?;
    ensure_exact_tags(
        "Matrixd method",
        matrixd_methods,
        &[
            "health",
            "snapshot",
            "events",
            "cancel_turn",
            "resolve_approval",
        ],
    )?;
    ensure_exact_tags(
        "Matrixd payload",
        matrixd_payloads,
        &["health", "snapshot", "events", "accepted", "error"],
    )?;
    ensure_exact_tags(
        "Matrixd event",
        matrixd_events,
        &[
            "lifecycle",
            "agent_connection",
            "matrix_connection",
            "queue_depth",
            "turn_started",
            "turn_completed",
            "approval_pending",
            "approval_resolved",
            "resync_required",
        ],
    )?;

    for (id, valid) in [
        ("matrixd_response_event_gap", true),
        ("matrixd_response_event_cursor_skip", false),
        ("matrixd_response_latest_cursor_before_next_cursor", false),
        ("matrixd_response_event_gap_with_events", false),
        ("matrixd_response_duplicate_approval", false),
        ("matrixd_response_partial_active_turn", false),
        ("matrixd_response_health_fence_lifecycle_drift", false),
        ("matrixd_response_unsafe_resync_reason", false),
        ("matrixd_response_unsafe_error_code", false),
        ("matrixd_response_unsafe_error_message", false),
        ("matrixd_response_control_error_message", false),
        ("matrixd_response_error_message_utf8_byte_overflow", false),
        ("matrixd_response_maximum_snapshot", true),
        ("matrixd_response_maximum_events", true),
        ("supervisord_response_matrix_generation_drift", false),
        ("supervisord_response_active_matrix_inactive_agent", false),
        ("supervisord_response_active_matrix_nonrunning_agent", false),
        ("matrixd_request_runtime_id_utf8_byte_overflow", false),
        ("matrixd_request_control_runtime_id", false),
        ("matrixd_request_whitespace_runtime_id", false),
    ] {
        let case = ids
            .get(id)
            .with_context(|| format!("required corpus scenario {id} is missing"))?;
        ensure!(
            case.expected.backend_projection_validate == valid,
            "required corpus scenario {id} changed validation outcome"
        );
    }
    Ok(())
}

fn ensure_exact_tags(label: &str, actual: BTreeSet<String>, expected: &[&str]) -> Result<()> {
    let expected = expected
        .iter()
        .map(|value| (*value).to_string())
        .collect::<BTreeSet<_>>();
    ensure!(actual == expected, "{label} corpus coverage drift");
    Ok(())
}

fn verify_supervisord_request_case(case: &CorpusCase) -> Result<()> {
    let admin = serde_json::from_str::<SupervisordRequest>(&case.wire_utf8);
    ensure!(
        case.expected.backend_admin_decode == Some(admin.is_ok()),
        "{} administrator decode expectation changed",
        case.id
    );
    let projection = serde_json::from_str::<RobrixSupervisordRequest>(&case.wire_utf8);
    ensure!(
        projection.is_ok() == case.expected.backend_projection_decode,
        "{} projection decode expectation changed",
        case.id
    );
    let valid = projection
        .as_ref()
        .is_ok_and(|request| request.validate().is_ok());
    ensure!(
        valid == case.expected.backend_projection_validate,
        "{} projection validation expectation changed",
        case.id
    );
    Ok(())
}

fn verify_supervisord_response_case(case: &CorpusCase) -> Result<()> {
    let admin = serde_json::from_str::<SupervisordResponse>(&case.wire_utf8);
    ensure!(
        case.expected.backend_admin_decode == Some(admin.is_ok()),
        "{} administrator decode expectation changed",
        case.id
    );
    let projection = admin
        .ok()
        .and_then(|response| RobrixSupervisordResponse::try_from(response).ok());
    ensure!(
        projection.is_some() == case.expected.backend_projection_decode,
        "{} projection decode expectation changed",
        case.id
    );
    let valid = projection.as_ref().is_some_and(|response| {
        case.context
            .expected_request_id
            .is_some_and(|request_id| response.validate(request_id).is_ok())
    });
    ensure!(
        valid == case.expected.backend_projection_validate,
        "{} projection validation expectation changed",
        case.id
    );
    Ok(())
}

fn verify_matrixd_request_case(case: &CorpusCase) -> Result<()> {
    ensure!(
        case.expected.backend_admin_decode.is_none(),
        "{} Matrix case unexpectedly has admin expectation",
        case.id
    );
    let request = serde_json::from_str::<MatrixdRequest>(&case.wire_utf8);
    ensure!(
        request.is_ok() == case.expected.backend_projection_decode,
        "{} Matrix request decode expectation changed",
        case.id
    );
    let valid = request.as_ref().is_ok_and(|request| {
        request.validate().is_ok()
            && case
                .context
                .expected_request_id
                .is_none_or(|expected| request.request_id == expected)
            && case
                .context
                .expected_agent_id
                .as_deref()
                .is_none_or(|expected| request.agent_id.as_str() == expected)
            && case
                .context
                .expected_fence
                .as_ref()
                .is_none_or(|expected| request.fence.as_ref() == Some(expected))
    });
    ensure!(
        valid == case.expected.backend_projection_validate,
        "{} Matrix request validation expectation changed",
        case.id
    );
    Ok(())
}

fn verify_matrixd_response_case(case: &CorpusCase) -> Result<()> {
    ensure!(
        case.expected.backend_admin_decode.is_none(),
        "{} Matrix case unexpectedly has admin expectation",
        case.id
    );
    let response = serde_json::from_str::<MatrixdResponse>(&case.wire_utf8);
    ensure!(
        response.is_ok() == case.expected.backend_projection_decode,
        "{} Matrix response decode expectation changed",
        case.id
    );
    let valid = response.as_ref().is_ok_and(|response| {
        response.validate().is_ok()
            && case
                .context
                .expected_request_id
                .is_none_or(|expected| response.request_id == expected)
            && case
                .context
                .expected_agent_id
                .as_deref()
                .is_none_or(|expected| response.agent_id.as_str() == expected)
            && case
                .context
                .expected_fence
                .as_ref()
                .is_none_or(|expected| &response.fence() == expected)
            && case.context.after_cursor.is_none_or(|after_cursor| {
                matches!(
                    &response.payload,
                    MatrixdPayload::Events(batch) if batch.validate_after(after_cursor).is_ok()
                )
            })
    });
    ensure!(
        valid == case.expected.backend_projection_validate,
        "{} Matrix response validation expectation changed",
        case.id
    );
    Ok(())
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct ProjectionManifest {
    schema_version: u32,
    supervisord_schema_version: u32,
    supervisord_max_frame_bytes: u64,
    supervisord_allowed_methods: [&'static str; 3],
    matrixd_schema_version: u32,
    matrixd_max_frame_bytes: u64,
    matrixd_bootstrap_methods: [&'static str; 2],
    matrixd_fenced_methods: [&'static str; 3],
    required_json_schema_keywords: [&'static str; 2],
    json_schema_validation_role: &'static str,
    authoritative_semantic_validator: &'static str,
    json_schema_non_schema_invariant_classes: [&'static str; 5],
    supervisord_non_schema_invariants: [&'static str; 5],
    matrixd_non_schema_invariants: [&'static str; 5],
    files: BTreeMap<String, ArtifactDigest>,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct ArtifactDigest {
    bytes: u64,
    sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CorpusDocument {
    schema_version: u32,
    cases: Vec<CorpusCase>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CorpusCase {
    id: String,
    plane: CorpusPlane,
    direction: CorpusDirection,
    wire_utf8: String,
    wire_bytes: u64,
    wire_sha256: String,
    expected: CorpusExpectation,
    context: CorpusContext,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum CorpusPlane {
    Supervisord,
    Matrixd,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum CorpusDirection {
    Request,
    Response,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CorpusExpectation {
    backend_admin_decode: Option<bool>,
    backend_projection_decode: bool,
    backend_projection_validate: bool,
    backend_json_schema_validate: bool,
    json_schema_semantic_gap: Option<JsonSchemaSemanticGap>,
    robrix_decode: bool,
    robrix_validate: bool,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CorpusContext {
    expected_request_id: Option<u64>,
    expected_agent_id: Option<String>,
    expected_fence: Option<MatrixdFence>,
    after_cursor: Option<u64>,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum JsonSchemaSemanticGap {
    SelectedProcessContext,
    CrossObjectFieldEquality,
    CrossElementKeyUniqueness,
    RequestedCursorContiguity,
    CrossFieldOrdering,
}

fn expectation(admin: Option<bool>, decode: bool, validate: bool) -> CorpusExpectation {
    CorpusExpectation {
        backend_admin_decode: admin,
        backend_projection_decode: decode,
        backend_projection_validate: validate,
        backend_json_schema_validate: validate,
        json_schema_semantic_gap: None,
        robrix_decode: decode,
        robrix_validate: validate,
    }
}

fn corpus_case<T: Serialize>(
    id: impl Into<String>,
    plane: CorpusPlane,
    direction: CorpusDirection,
    value: &T,
    expected: CorpusExpectation,
    context: CorpusContext,
) -> Result<CorpusCase> {
    let value = canonicalize_json(&serde_json::to_value(value)?);
    let mut wire = serde_json::to_vec(&value)?;
    wire.push(b'\n');
    let wire_utf8 = String::from_utf8(wire).context("generated corpus frame was not UTF-8")?;
    Ok(CorpusCase {
        id: id.into(),
        plane,
        direction,
        wire_bytes: wire_utf8.len() as u64,
        wire_sha256: sha256(wire_utf8.as_bytes()),
        wire_utf8,
        expected,
        context,
    })
}

fn corpus() -> Result<CorpusDocument> {
    let mut cases = Vec::new();
    let agent_a = agent(AGENT_A)?;
    let agent_b = agent(AGENT_B)?;
    let supervisor_fence = supervisor_fence()?;
    let status = supervisor_status()?;

    for (id, request) in [
        (
            "supervisord_request_health",
            RobrixSupervisordRequest::new(/*request_id*/ 1, RobrixSupervisordMethod::Health),
        ),
        (
            "supervisord_request_roster",
            RobrixSupervisordRequest::new(
                /*request_id*/ 2,
                RobrixSupervisordMethod::Roster {
                    limit: MAX_SUPERVISORD_ROSTER,
                },
            ),
        ),
        (
            "supervisord_request_snapshot",
            RobrixSupervisordRequest::new(
                /*request_id*/ 3,
                RobrixSupervisordMethod::Snapshot {
                    agent_id: agent_a.clone(),
                },
            ),
        ),
    ] {
        cases.push(corpus_case(
            id,
            CorpusPlane::Supervisord,
            CorpusDirection::Request,
            &request,
            expectation(Some(true), /*decode*/ true, /*validate*/ true),
            CorpusContext::default(),
        )?);
    }

    let zero_request =
        RobrixSupervisordRequest::new(/*request_id*/ 0, RobrixSupervisordMethod::Health);
    cases.push(corpus_case(
        "supervisord_request_zero_id",
        CorpusPlane::Supervisord,
        CorpusDirection::Request,
        &zero_request,
        expectation(Some(true), /*decode*/ true, /*validate*/ false),
        CorpusContext::default(),
    )?);
    let mut unknown_request = serde_json::to_value(RobrixSupervisordRequest::new(
        /*request_id*/ 4,
        RobrixSupervisordMethod::Health,
    ))?;
    unknown_request["unknown"] = json!(true);
    cases.push(corpus_case(
        "supervisord_request_unknown_field",
        CorpusPlane::Supervisord,
        CorpusDirection::Request,
        &unknown_request,
        expectation(Some(false), /*decode*/ false, /*validate*/ false),
        CorpusContext::default(),
    )?);

    let mutations = [
        (
            "start",
            SupervisordMethod::Start {
                fence: supervisor_fence.clone(),
                release_id: release("agentd-v2")?,
            },
        ),
        (
            "drain",
            SupervisordMethod::Drain {
                fence: supervisor_fence.clone(),
            },
        ),
        (
            "stop",
            SupervisordMethod::Stop {
                fence: supervisor_fence.clone(),
            },
        ),
        (
            "kill",
            SupervisordMethod::Kill {
                fence: supervisor_fence.clone(),
            },
        ),
        (
            "restart",
            SupervisordMethod::Restart {
                fence: supervisor_fence.clone(),
            },
        ),
        (
            "upgrade",
            SupervisordMethod::Upgrade {
                fence: supervisor_fence.clone(),
                release_id: release("agentd-v2")?,
            },
        ),
        (
            "rollback",
            SupervisordMethod::Rollback {
                fence: supervisor_fence,
            },
        ),
    ];
    for (name, method) in mutations {
        cases.push(corpus_case(
            format!("supervisord_request_forbidden_{name}"),
            CorpusPlane::Supervisord,
            CorpusDirection::Request,
            &SupervisordRequest::new(/*request_id*/ 10, method),
            expectation(Some(true), /*decode*/ false, /*validate*/ false),
            CorpusContext::default(),
        )?);
    }

    for (id, response) in [
        (
            "supervisord_response_health",
            SupervisordResponse {
                schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                request_id: 20,
                payload: SupervisordPayload::Health(SupervisordHealth {
                    ready: true,
                    supervisor_epoch: epoch()?,
                    process_id: 100,
                    registered_agents: 1,
                    observed_faults: 0,
                }),
            },
        ),
        (
            "supervisord_response_roster",
            SupervisordResponse {
                schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                request_id: 21,
                payload: SupervisordPayload::Roster {
                    agents: vec![status.clone()],
                },
            },
        ),
        (
            "supervisord_response_agent",
            SupervisordResponse {
                schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                request_id: 22,
                payload: SupervisordPayload::Agent(status.clone()),
            },
        ),
        (
            "supervisord_response_error",
            SupervisordResponse {
                schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                request_id: 23,
                payload: SupervisordPayload::Error {
                    code: "stale_control_fence".to_string(),
                    message: "selected Agent changed; refresh before retry".to_string(),
                    actual: Some(status.clone()),
                },
            },
        ),
    ] {
        let request_id = response.request_id;
        cases.push(corpus_case(
            id,
            CorpusPlane::Supervisord,
            CorpusDirection::Response,
            &response,
            expectation(Some(true), /*decode*/ true, /*validate*/ true),
            CorpusContext {
                expected_request_id: Some(request_id),
                ..CorpusContext::default()
            },
        )?);
    }

    let mut generation_drift = status.clone();
    generation_drift.matrix.attached_agent_generation = generation_drift.runtime_generation;
    let mut inactive_agent = status.clone();
    inactive_agent.active = false;
    inactive_agent.healthy = false;
    let mut nonrunning_agent = status.clone();
    nonrunning_agent.lifecycle = AgentLifecycle::Starting;
    nonrunning_agent.control_fence.lifecycle = AgentLifecycle::Starting;
    nonrunning_agent.healthy = false;
    for (id, drifted) in [
        (
            "supervisord_response_matrix_generation_drift",
            generation_drift,
        ),
        (
            "supervisord_response_active_matrix_inactive_agent",
            inactive_agent,
        ),
        (
            "supervisord_response_active_matrix_nonrunning_agent",
            nonrunning_agent,
        ),
    ] {
        cases.push(corpus_case(
            id,
            CorpusPlane::Supervisord,
            CorpusDirection::Response,
            &SupervisordResponse {
                schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
                request_id: 24,
                payload: SupervisordPayload::Agent(drifted),
            },
            expectation(Some(true), /*decode*/ true, /*validate*/ false),
            CorpusContext {
                expected_request_id: Some(24),
                ..CorpusContext::default()
            },
        )?);
    }
    cases.push(corpus_case(
        "supervisord_response_forbidden_mutation_accepted",
        CorpusPlane::Supervisord,
        CorpusDirection::Response,
        &SupervisordResponse {
            schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
            request_id: 24,
            payload: SupervisordPayload::MutationAccepted {
                operation: SupervisordMutation::Restart,
                accepted_state_digest: digest_control(DIGEST_A)?,
                agent: status,
                production_receipt: None,
            },
        },
        expectation(Some(true), /*decode*/ false, /*validate*/ false),
        CorpusContext {
            expected_request_id: Some(24),
            ..CorpusContext::default()
        },
    )?);

    let matrix_fence = matrix_fence()?;
    for (id, request) in [
        (
            "matrixd_request_health",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 30,
                agent_id: agent_a.clone(),
                fence: None,
                method: MatrixdMethod::Health,
            },
        ),
        (
            "matrixd_request_snapshot",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 31,
                agent_id: agent_a.clone(),
                fence: None,
                method: MatrixdMethod::Snapshot,
            },
        ),
        (
            "matrixd_request_events",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 32,
                agent_id: agent_a.clone(),
                fence: Some(matrix_fence.clone()),
                method: MatrixdMethod::Events {
                    after_cursor: 7,
                    limit: 32,
                },
            },
        ),
        (
            "matrixd_request_cancel_turn",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 33,
                agent_id: agent_a.clone(),
                fence: Some(matrix_fence.clone()),
                method: MatrixdMethod::CancelTurn {
                    thread_id: "thread-1".to_string(),
                    turn_id: "turn-1".to_string(),
                },
            },
        ),
        (
            "matrixd_request_resolve_approval",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 34,
                agent_id: agent_a.clone(),
                fence: Some(matrix_fence.clone()),
                method: MatrixdMethod::ResolveApproval {
                    approval_key: "approval-1".to_string(),
                    decision: LocalApprovalDecision::Accept,
                },
            },
        ),
    ] {
        let expected_fence = request.fence.clone();
        let request_id = request.request_id;
        cases.push(corpus_case(
            id,
            CorpusPlane::Matrixd,
            CorpusDirection::Request,
            &request,
            expectation(
                /*admin*/ None, /*decode*/ true, /*validate*/ true,
            ),
            CorpusContext {
                expected_request_id: Some(request_id),
                expected_agent_id: Some(AGENT_A.to_string()),
                expected_fence,
                after_cursor: None,
            },
        )?);
    }

    for (id, request) in [
        (
            "matrixd_request_missing_fence",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 35,
                agent_id: agent_a.clone(),
                fence: None,
                method: MatrixdMethod::CancelTurn {
                    thread_id: "thread-1".to_string(),
                    turn_id: "turn-1".to_string(),
                },
            },
        ),
        (
            "matrixd_request_bootstrap_with_fence",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 36,
                agent_id: agent_a.clone(),
                fence: Some(matrix_fence.clone()),
                method: MatrixdMethod::Snapshot,
            },
        ),
        (
            "matrixd_request_zero_fence_revision",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 37,
                agent_id: agent_a.clone(),
                fence: Some(MatrixdFence {
                    binding_revision: 0,
                    ..matrix_fence.clone()
                }),
                method: MatrixdMethod::Events {
                    after_cursor: 0,
                    limit: 1,
                },
            },
        ),
        (
            "matrixd_request_unsafe_runtime_id",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 38,
                agent_id: agent_a.clone(),
                fence: Some(matrix_fence.clone()),
                method: MatrixdMethod::CancelTurn {
                    thread_id: "thread\u{202e}1".to_string(),
                    turn_id: "turn-1".to_string(),
                },
            },
        ),
        (
            "matrixd_request_runtime_id_utf8_byte_overflow",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 39,
                agent_id: agent_a.clone(),
                fence: Some(matrix_fence.clone()),
                method: MatrixdMethod::CancelTurn {
                    // 129 scalar values but 516 UTF-8 bytes. JSON Schema's
                    // standard maxLength cannot express this byte bound.
                    thread_id: "🦉".repeat(129),
                    turn_id: "turn-1".to_string(),
                },
            },
        ),
        (
            "matrixd_request_control_runtime_id",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 39,
                agent_id: agent_a.clone(),
                fence: Some(matrix_fence.clone()),
                method: MatrixdMethod::CancelTurn {
                    thread_id: "thread\u{0001}1".to_string(),
                    turn_id: "turn-1".to_string(),
                },
            },
        ),
        (
            "matrixd_request_whitespace_runtime_id",
            MatrixdRequest {
                schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
                request_id: 39,
                agent_id: agent_a.clone(),
                fence: Some(matrix_fence.clone()),
                method: MatrixdMethod::CancelTurn {
                    thread_id: "thread 1".to_string(),
                    turn_id: "turn-1".to_string(),
                },
            },
        ),
    ] {
        cases.push(corpus_case(
            id,
            CorpusPlane::Matrixd,
            CorpusDirection::Request,
            &request,
            expectation(
                /*admin*/ None, /*decode*/ true, /*validate*/ false,
            ),
            CorpusContext {
                expected_request_id: Some(request.request_id),
                expected_agent_id: Some(AGENT_A.to_string()),
                expected_fence: request.fence.clone(),
                after_cursor: None,
            },
        )?);
    }
    let wrong_agent = MatrixdRequest {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id: 39,
        agent_id: agent_b,
        fence: Some(matrix_fence.clone()),
        method: MatrixdMethod::Events {
            after_cursor: 0,
            limit: 1,
        },
    };
    cases.push(corpus_case(
        "matrixd_request_wrong_agent",
        CorpusPlane::Matrixd,
        CorpusDirection::Request,
        &wrong_agent,
        expectation(
            /*admin*/ None, /*decode*/ true, /*validate*/ false,
        ),
        CorpusContext {
            expected_request_id: Some(39),
            expected_agent_id: Some(AGENT_A.to_string()),
            expected_fence: Some(matrix_fence.clone()),
            after_cursor: None,
        },
    )?);
    for (name, drifted) in drifted_fences(&matrix_fence)? {
        let request = MatrixdRequest {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 40,
            agent_id: agent_a.clone(),
            fence: Some(drifted),
            method: MatrixdMethod::Events {
                after_cursor: 0,
                limit: 1,
            },
        };
        cases.push(corpus_case(
            format!("matrixd_request_stale_fence_{name}"),
            CorpusPlane::Matrixd,
            CorpusDirection::Request,
            &request,
            expectation(
                /*admin*/ None, /*decode*/ true, /*validate*/ false,
            ),
            CorpusContext {
                expected_request_id: Some(40),
                expected_agent_id: Some(AGENT_A.to_string()),
                expected_fence: Some(matrix_fence.clone()),
                after_cursor: None,
            },
        )?);
    }
    let mut bad_digest = serde_json::to_value(MatrixdRequest {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id: 41,
        agent_id: agent_a.clone(),
        fence: Some(matrix_fence.clone()),
        method: MatrixdMethod::Events {
            after_cursor: 0,
            limit: 1,
        },
    })?;
    bad_digest["fence"]["binding_digest"] = json!("bad");
    cases.push(corpus_case(
        "matrixd_request_bad_digest",
        CorpusPlane::Matrixd,
        CorpusDirection::Request,
        &bad_digest,
        expectation(
            /*admin*/ None, /*decode*/ true, /*validate*/ false,
        ),
        CorpusContext::default(),
    )?);

    let snapshot = matrix_snapshot(/*maximum*/ false)?;
    let events = all_matrixd_event_variants();
    for (id, request_id, payload, after_cursor) in [
        (
            "matrixd_response_health",
            50,
            MatrixdPayload::Health(MatrixdHealth {
                lifecycle: MatrixdLifecycle::Ready,
                process_id: 200,
                agentd_connected: true,
                matrix_sync_connected: true,
                fenced: false,
            }),
            None,
        ),
        (
            "matrixd_response_snapshot",
            51,
            MatrixdPayload::Snapshot(snapshot),
            None,
        ),
        (
            "matrixd_response_events",
            52,
            MatrixdPayload::Events(events),
            Some(7),
        ),
        (
            "matrixd_response_accepted",
            53,
            MatrixdPayload::Accepted,
            None,
        ),
        (
            "matrixd_response_error",
            54,
            MatrixdPayload::Error {
                code: "stale_fence".to_string(),
                message: "request fence does not match this process".to_string(),
            },
            None,
        ),
        (
            "matrixd_response_event_gap",
            55,
            MatrixdPayload::Events(MatrixdEventBatch {
                events: Vec::new(),
                gap: true,
                next_cursor: 7,
                latest_cursor: 16,
            }),
            Some(7),
        ),
    ] {
        let response = matrix_response(agent_a.clone(), request_id, matrix_fence.clone(), payload);
        cases.push(corpus_case(
            id,
            CorpusPlane::Matrixd,
            CorpusDirection::Response,
            &response,
            expectation(
                /*admin*/ None, /*decode*/ true, /*validate*/ true,
            ),
            CorpusContext {
                expected_request_id: Some(request_id),
                expected_agent_id: Some(AGENT_A.to_string()),
                expected_fence: Some(matrix_fence.clone()),
                after_cursor,
            },
        )?);
    }

    let maximum = matrix_response(
        agent_a.clone(),
        /*request_id*/ 56,
        matrix_fence.clone(),
        MatrixdPayload::Snapshot(matrix_snapshot(/*maximum*/ true)?),
    );
    let maximum_case = corpus_case(
        "matrixd_response_maximum_snapshot",
        CorpusPlane::Matrixd,
        CorpusDirection::Response,
        &maximum,
        expectation(
            /*admin*/ None, /*decode*/ true, /*validate*/ true,
        ),
        CorpusContext {
            expected_request_id: Some(56),
            expected_agent_id: Some(AGENT_A.to_string()),
            expected_fence: Some(matrix_fence.clone()),
            after_cursor: None,
        },
    )?;
    ensure!(
        maximum_case.wire_bytes > MAX_SUPERVISORD_CONTROL_FRAME_BYTES
            && maximum_case.wire_bytes <= MAX_MATRIXD_CONTROL_FRAME_BYTES,
        "maximum Matrix projection must distinguish the 64 KiB and 1 MiB bounds"
    );
    cases.push(maximum_case);

    let maximum_events = matrix_response(
        agent_a.clone(),
        /*request_id*/ 57,
        matrix_fence.clone(),
        MatrixdPayload::Events(maximum_matrixd_events()),
    );
    let maximum_events_case = corpus_case(
        "matrixd_response_maximum_events",
        CorpusPlane::Matrixd,
        CorpusDirection::Response,
        &maximum_events,
        expectation(
            /*admin*/ None, /*decode*/ true, /*validate*/ true,
        ),
        CorpusContext {
            expected_request_id: Some(57),
            expected_agent_id: Some(AGENT_A.to_string()),
            expected_fence: Some(matrix_fence.clone()),
            after_cursor: Some(0),
        },
    )?;
    ensure!(
        maximum_events_case.wire_bytes > MAX_SUPERVISORD_CONTROL_FRAME_BYTES
            && maximum_events_case.wire_bytes <= MAX_MATRIXD_CONTROL_FRAME_BYTES,
        "maximum Matrix event projection must distinguish the 64 KiB and 1 MiB bounds"
    );
    cases.push(maximum_events_case);

    let mut duplicate_approval = matrix_snapshot(/*maximum*/ false)?;
    duplicate_approval
        .pending_approvals
        .push(duplicate_approval.pending_approvals[0].clone());
    let mut partial_active_turn = matrix_snapshot(/*maximum*/ false)?;
    partial_active_turn.active_turn_id = None;

    for (id, payload, after_cursor) in [
        (
            "matrixd_response_zero_process_id",
            MatrixdPayload::Health(MatrixdHealth {
                lifecycle: MatrixdLifecycle::Ready,
                process_id: 0,
                agentd_connected: true,
                matrix_sync_connected: true,
                fenced: false,
            }),
            None,
        ),
        (
            "matrixd_response_unsafe_error_code",
            MatrixdPayload::Error {
                code: "stale-fence".to_string(),
                message: "request fence does not match this process".to_string(),
            },
            None,
        ),
        (
            "matrixd_response_unsafe_error_message",
            MatrixdPayload::Error {
                code: "stale_fence".to_string(),
                message: "spoof\u{202e}txt".to_string(),
            },
            None,
        ),
        (
            "matrixd_response_error_message_utf8_byte_overflow",
            MatrixdPayload::Error {
                code: "stale_fence".to_string(),
                // 257 scalar values but 1,028 UTF-8 bytes.
                message: "🦉".repeat(257),
            },
            None,
        ),
        (
            "matrixd_response_control_error_message",
            MatrixdPayload::Error {
                code: "stale_fence".to_string(),
                message: "spoof\u{0001}txt".to_string(),
            },
            None,
        ),
        (
            "matrixd_response_duplicate_approval",
            MatrixdPayload::Snapshot(duplicate_approval),
            None,
        ),
        (
            "matrixd_response_partial_active_turn",
            MatrixdPayload::Snapshot(partial_active_turn),
            None,
        ),
        (
            "matrixd_response_health_fence_lifecycle_drift",
            MatrixdPayload::Health(MatrixdHealth {
                lifecycle: MatrixdLifecycle::Ready,
                process_id: 200,
                agentd_connected: true,
                matrix_sync_connected: true,
                fenced: true,
            }),
            None,
        ),
        (
            "matrixd_response_event_cursor_skip",
            MatrixdPayload::Events(MatrixdEventBatch {
                events: vec![MatrixdEvent {
                    cursor: 9,
                    kind: MatrixdEventKind::QueueDepth {
                        inbox: 1,
                        outbox: 2,
                    },
                }],
                gap: false,
                next_cursor: 9,
                latest_cursor: 9,
            }),
            Some(7),
        ),
        (
            "matrixd_response_event_gap_with_events",
            MatrixdPayload::Events(MatrixdEventBatch {
                events: vec![MatrixdEvent {
                    cursor: 8,
                    kind: MatrixdEventKind::QueueDepth {
                        inbox: 1,
                        outbox: 2,
                    },
                }],
                gap: true,
                next_cursor: 7,
                latest_cursor: 8,
            }),
            Some(7),
        ),
        (
            "matrixd_response_zero_event_cursor",
            MatrixdPayload::Events(MatrixdEventBatch {
                events: vec![MatrixdEvent {
                    cursor: 0,
                    kind: MatrixdEventKind::QueueDepth {
                        inbox: 1,
                        outbox: 2,
                    },
                }],
                gap: false,
                next_cursor: 0,
                latest_cursor: 0,
            }),
            Some(0),
        ),
        (
            "matrixd_response_zero_agent_generation_event",
            MatrixdPayload::Events(MatrixdEventBatch {
                events: vec![MatrixdEvent {
                    cursor: 1,
                    kind: MatrixdEventKind::AgentConnection {
                        connected: false,
                        generation: 0,
                    },
                }],
                gap: false,
                next_cursor: 1,
                latest_cursor: 1,
            }),
            Some(0),
        ),
        (
            "matrixd_response_unsafe_resync_reason",
            MatrixdPayload::Events(MatrixdEventBatch {
                events: vec![MatrixdEvent {
                    cursor: 1,
                    kind: MatrixdEventKind::ResyncRequired {
                        reason_code: "needs-resync".to_string(),
                    },
                }],
                gap: false,
                next_cursor: 1,
                latest_cursor: 1,
            }),
            Some(0),
        ),
    ] {
        let response = matrix_response(
            agent_a.clone(),
            /*request_id*/ 58,
            matrix_fence.clone(),
            payload,
        );
        cases.push(corpus_case(
            id,
            CorpusPlane::Matrixd,
            CorpusDirection::Response,
            &response,
            expectation(
                /*admin*/ None, /*decode*/ true, /*validate*/ false,
            ),
            CorpusContext {
                expected_request_id: Some(58),
                expected_agent_id: Some(AGENT_A.to_string()),
                expected_fence: Some(matrix_fence.clone()),
                after_cursor,
            },
        )?);
    }
    let response_with_stale_fence = matrix_response(
        agent_a,
        /*request_id*/ 59,
        MatrixdFence {
            plane_epoch: matrix_fence.plane_epoch + 1,
            ..matrix_fence.clone()
        },
        MatrixdPayload::Accepted,
    );
    cases.push(corpus_case(
        "matrixd_response_stale_fence",
        CorpusPlane::Matrixd,
        CorpusDirection::Response,
        &response_with_stale_fence,
        expectation(
            /*admin*/ None, /*decode*/ true, /*validate*/ false,
        ),
        CorpusContext {
            expected_request_id: Some(59),
            expected_agent_id: Some(AGENT_A.to_string()),
            expected_fence: Some(matrix_fence.clone()),
            after_cursor: None,
        },
    )?);

    cases.push(corpus_case(
        "matrixd_response_latest_cursor_before_next_cursor",
        CorpusPlane::Matrixd,
        CorpusDirection::Response,
        &matrix_response(
            agent(AGENT_A)?,
            /*request_id*/ 60,
            matrix_fence.clone(),
            MatrixdPayload::Events(MatrixdEventBatch {
                events: Vec::new(),
                gap: false,
                next_cursor: 9,
                latest_cursor: 8,
            }),
        ),
        expectation(
            /*admin*/ None, /*decode*/ true, /*validate*/ false,
        ),
        CorpusContext {
            expected_request_id: Some(60),
            expected_agent_id: Some(AGENT_A.to_string()),
            expected_fence: Some(matrix_fence),
            after_cursor: Some(9),
        },
    )?);

    declare_json_schema_semantic_gaps(&mut cases)?;

    Ok(CorpusDocument {
        schema_version: ROBRIX_CONTROL_PROJECTION_SCHEMA_VERSION,
        cases,
    })
}

fn declare_json_schema_semantic_gaps(cases: &mut [CorpusCase]) -> Result<()> {
    for case in cases {
        let gap = match case.id.as_str() {
            "supervisord_response_matrix_generation_drift" => {
                Some(JsonSchemaSemanticGap::CrossObjectFieldEquality)
            }
            "matrixd_request_wrong_agent"
            | "matrixd_request_stale_fence_binding_revision"
            | "matrixd_request_stale_fence_binding_digest"
            | "matrixd_request_stale_fence_agent_generation"
            | "matrixd_request_stale_fence_process_incarnation"
            | "matrixd_request_stale_fence_plane_epoch"
            | "matrixd_response_stale_fence" => Some(JsonSchemaSemanticGap::SelectedProcessContext),
            "matrixd_response_duplicate_approval" => {
                Some(JsonSchemaSemanticGap::CrossElementKeyUniqueness)
            }
            "matrixd_response_event_cursor_skip" => {
                Some(JsonSchemaSemanticGap::RequestedCursorContiguity)
            }
            "matrixd_response_latest_cursor_before_next_cursor" => {
                Some(JsonSchemaSemanticGap::CrossFieldOrdering)
            }
            _ => None,
        };
        if let Some(gap) = gap {
            ensure!(
                !case.expected.backend_projection_validate,
                "{} cannot declare a schema semantic gap for a valid semantic case",
                case.id
            );
            case.expected.backend_json_schema_validate = true;
            case.expected.json_schema_semantic_gap = Some(gap);
        }
    }
    Ok(())
}

fn agent(value: &str) -> Result<AgentId> {
    AgentId::parse(value).map_err(anyhow::Error::from)
}

fn release(value: &str) -> Result<ReleaseId> {
    ReleaseId::parse(value).map_err(anyhow::Error::from)
}

fn epoch() -> Result<SupervisorEpoch> {
    SupervisorEpoch::parse(EPOCH).map_err(anyhow::Error::msg)
}

fn digest_control(value: &str) -> Result<ControlStateDigest> {
    ControlStateDigest::parse(value).map_err(anyhow::Error::msg)
}

fn digest(value: &str) -> Result<Sha256Digest> {
    Sha256Digest::parse(value).map_err(anyhow::Error::msg)
}

fn supervisor_fence() -> Result<SupervisordControlFence> {
    Ok(SupervisordControlFence {
        agent_id: agent(AGENT_A)?,
        supervisor_epoch: epoch()?,
        lifecycle: AgentLifecycle::Running,
        lifecycle_generation: 7,
        spawn_generation: Some(5),
        runtime_generation: Some(7),
        current_release: Some(release("agentd-v1")?),
        previous_release: None,
        release_change_pending: false,
        state_digest: digest_control(DIGEST_A)?,
    })
}

fn supervisor_status() -> Result<SupervisordAgentStatus> {
    let fence = supervisor_fence()?;
    Ok(SupervisordAgentStatus {
        agent_id: fence.agent_id.clone(),
        lifecycle: fence.lifecycle,
        lifecycle_generation: fence.lifecycle_generation,
        active: true,
        healthy: true,
        process_id: Some(1234),
        spawn_generation: fence.spawn_generation,
        runtime_generation: fence.runtime_generation,
        current_release: fence.current_release.clone(),
        previous_release: fence.previous_release.clone(),
        release_change_pending: fence.release_change_pending,
        control_fence: fence,
        matrix: SupervisordMatrixStatus {
            configured: true,
            active: true,
            healthy: true,
            degraded: false,
            process_id: Some(4321),
            attached_agent_generation: Some(5),
            binding_revision: Some(11),
            restart_attempt: 0,
            last_error: None,
        },
    })
}

fn matrix_fence() -> Result<MatrixdFence> {
    Ok(MatrixdFence {
        binding_revision: 7,
        binding_digest: digest(DIGEST_A)?,
        attached_agent_generation: 11,
        process_incarnation: "matrixd-incarnation-19".to_string(),
        plane_epoch: 19,
    })
}

fn drifted_fences(fence: &MatrixdFence) -> Result<Vec<(&'static str, MatrixdFence)>> {
    Ok(vec![
        (
            "binding_revision",
            MatrixdFence {
                binding_revision: fence.binding_revision + 1,
                ..fence.clone()
            },
        ),
        (
            "binding_digest",
            MatrixdFence {
                binding_digest: digest(DIGEST_B)?,
                ..fence.clone()
            },
        ),
        (
            "agent_generation",
            MatrixdFence {
                attached_agent_generation: fence.attached_agent_generation + 1,
                ..fence.clone()
            },
        ),
        (
            "process_incarnation",
            MatrixdFence {
                process_incarnation: "matrixd-incarnation-20".to_string(),
                ..fence.clone()
            },
        ),
        (
            "plane_epoch",
            MatrixdFence {
                plane_epoch: fence.plane_epoch + 1,
                ..fence.clone()
            },
        ),
    ])
}

fn all_matrixd_event_variants() -> MatrixdEventBatch {
    let kinds = vec![
        MatrixdEventKind::Lifecycle {
            lifecycle: MatrixdLifecycle::Ready,
        },
        MatrixdEventKind::AgentConnection {
            connected: true,
            generation: 11,
        },
        MatrixdEventKind::MatrixConnection { connected: true },
        MatrixdEventKind::QueueDepth {
            inbox: 1,
            outbox: 2,
        },
        MatrixdEventKind::TurnStarted {
            thread_id: "thread-0".to_string(),
            turn_id: "turn-0".to_string(),
        },
        MatrixdEventKind::TurnCompleted {
            thread_id: "thread-0".to_string(),
            turn_id: "turn-0".to_string(),
        },
        MatrixdEventKind::ApprovalPending {
            approval: pending_approval(/*index*/ 0, /*maximum*/ false),
        },
        MatrixdEventKind::ApprovalResolved {
            approval_key: "approval-0".to_string(),
        },
        MatrixdEventKind::ResyncRequired {
            reason_code: "store_recovered".to_string(),
        },
    ];
    let events = kinds
        .into_iter()
        .enumerate()
        .map(|(index, kind)| MatrixdEvent {
            cursor: index as u64 + 8,
            kind,
        })
        .collect::<Vec<_>>();
    MatrixdEventBatch {
        next_cursor: events.last().map_or(0, |event| event.cursor),
        latest_cursor: events.last().map_or(0, |event| event.cursor),
        events,
        gap: false,
    }
}

fn maximum_matrixd_events() -> MatrixdEventBatch {
    let events = (0..usize::from(MAX_MATRIXD_EVENT_BATCH))
        .map(|index| MatrixdEvent {
            cursor: index as u64 + 1,
            kind: MatrixdEventKind::ApprovalPending {
                approval: pending_approval(index, /*maximum*/ true),
            },
        })
        .collect::<Vec<_>>();
    MatrixdEventBatch {
        next_cursor: events.len() as u64,
        latest_cursor: events.len() as u64,
        events,
        gap: false,
    }
}

fn pending_approval(index: usize, maximum: bool) -> PendingApproval {
    let runtime_id = |prefix: &str| {
        if maximum {
            let prefix = format!("{prefix}-{index}-");
            format!(
                "{prefix}{}",
                "x".repeat(MAX_RUNTIME_IDENTIFIER_BYTES - prefix.len())
            )
        } else {
            format!("{prefix}-{index}")
        }
    };
    PendingApproval {
        approval_key: runtime_id("approval"),
        kind: runtime_id("command_execution"),
        thread_id: runtime_id("thread"),
        turn_id: runtime_id("turn"),
        summary: if maximum {
            "s".repeat(MAX_PENDING_APPROVAL_SUMMARY_BYTES)
        } else {
            "Run a local command".to_string()
        },
        created_at_ms: 1_777_777_777_000 + index as u64,
        allowed_decisions: vec![
            LocalApprovalDecision::Accept,
            LocalApprovalDecision::AcceptForSession,
            LocalApprovalDecision::Decline,
            LocalApprovalDecision::Cancel,
        ],
    }
}

fn matrix_snapshot(maximum: bool) -> Result<MatrixdSnapshot> {
    let count = if maximum { MAX_PENDING_APPROVALS } else { 1 };
    let active_rooms = if maximum {
        (0..256)
            .map(|index| {
                MatrixRoomId::parse(format!("!room-{index}-{}:example.test", "r".repeat(210)))
                    .map_err(anyhow::Error::from)
            })
            .collect::<Result<Vec<_>>>()?
    } else {
        vec![MatrixRoomId::parse("!room-a:example.test").map_err(anyhow::Error::from)?]
    };
    Ok(MatrixdSnapshot {
        lifecycle: MatrixdLifecycle::Ready,
        expected_mxid: MatrixUserId::parse("@hepta-a:example.test").map_err(anyhow::Error::from)?,
        active_rooms,
        inbox_depth: 1,
        outbox_depth: 2,
        oldest_inbox_age_seconds: Some(3),
        oldest_outbox_age_seconds: None,
        active_thread_id: Some("thread-1".to_string()),
        active_turn_id: Some("turn-1".to_string()),
        pending_approvals: (0..count)
            .map(|index| pending_approval(index, maximum))
            .collect(),
        resync_required: false,
        event_cursor: count as u64,
    })
}

fn matrix_response(
    agent_id: AgentId,
    request_id: u64,
    fence: MatrixdFence,
    payload: MatrixdPayload,
) -> MatrixdResponse {
    MatrixdResponse {
        schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
        request_id,
        agent_id,
        release_id: "release-7".to_string(),
        binding_revision: fence.binding_revision,
        binding_digest: fence.binding_digest,
        attached_agent_generation: fence.attached_agent_generation,
        process_incarnation: fence.process_incarnation,
        plane_epoch: fence.plane_epoch,
        payload,
    }
}

fn generated_constants_source() -> String {
    format!(
        "// @generated by codex-hepta-supervisor; do not edit by hand.\n\
         pub(crate) const ROBRIX_CONTROL_PROJECTION_SCHEMA_VERSION: u32 = {ROBRIX_CONTROL_PROJECTION_SCHEMA_VERSION};\n\
         pub(crate) const ROBRIX_SUPERVISORD_SCHEMA_VERSION: u32 = {SUPERVISORD_CONTROL_SCHEMA_VERSION};\n\
         pub(crate) const ROBRIX_SUPERVISORD_MAX_FRAME_BYTES: usize = {MAX_SUPERVISORD_CONTROL_FRAME_BYTES};\n\
         pub(crate) const ROBRIX_SUPERVISORD_MAX_ROSTER: u16 = {MAX_SUPERVISORD_ROSTER};\n\
         pub(crate) const ROBRIX_SUPERVISORD_ALLOWED_METHODS: [&str; 3] = [\"health\", \"roster\", \"snapshot\"];\n\
         pub(crate) const MATRIXD_CONTROL_SCHEMA_VERSION: u32 = {MATRIXD_CONTROL_SCHEMA_VERSION};\n\
         pub(crate) const MAX_MATRIXD_CONTROL_FRAME_BYTES: usize = {MAX_MATRIXD_CONTROL_FRAME_BYTES};\n\
         pub(crate) const MAX_MATRIXD_EVENT_BATCH: u16 = {MAX_MATRIXD_EVENT_BATCH};\n\
         pub(crate) const MAX_PENDING_APPROVALS: usize = {MAX_PENDING_APPROVALS};\n\
         pub(crate) const MAX_PENDING_APPROVAL_SUMMARY_BYTES: usize = {MAX_PENDING_APPROVAL_SUMMARY_BYTES};\n\
         pub(crate) const MAX_RUNTIME_IDENTIFIER_BYTES: usize = {MAX_RUNTIME_IDENTIFIER_BYTES};\n\
         pub(crate) const MAX_MATRIXD_ERROR_CODE_BYTES: usize = {MAX_MATRIXD_ERROR_CODE_BYTES};\n\
         pub(crate) const MAX_MATRIXD_ERROR_MESSAGE_BYTES: usize = {MAX_MATRIXD_ERROR_MESSAGE_BYTES};\n\
         pub(crate) const ROBRIX_REQUIRED_JSON_SCHEMA_KEYWORDS: [&str; 2] = [\"x-hepta-max-utf8-bytes\", \"x-hepta-safe-text-profile\"];\n\
         pub(crate) const MATRIXD_BOOTSTRAP_METHODS: [&str; 2] = [\"health\", \"snapshot\"];\n\
         pub(crate) const MATRIXD_FENCED_METHODS: [&str; 3] = [\"events\", \"cancel_turn\", \"resolve_approval\"];\n"
    )
}

fn supervisord_schema() -> Value {
    let mut definitions = common_supervisor_definitions();
    let health_payload = tagged_object_from_schema("health", &definitions["SupervisordHealth"]);
    let agent_payload = tagged_object_from_schema("agent", &definitions["SupervisordAgentStatus"]);
    definitions.insert(
        "RobrixSupervisordMethod".to_string(),
        json!({
            "oneOf": [
                tagged_object("health", json!({}), &[]),
                tagged_object(
                    "roster",
                    json!({"limit": {"type": "integer", "minimum": 1, "maximum": MAX_SUPERVISORD_ROSTER}}),
                    &["limit"],
                ),
                tagged_object(
                    "snapshot",
                    json!({"agent_id": {"$ref": "#/$defs/AgentId"}}),
                    &["agent_id"],
                ),
            ]
        }),
    );
    definitions.insert(
        "RobrixSupervisordRequest".to_string(),
        strict_object(
            json!({
                "schema_version": {"const": SUPERVISORD_CONTROL_SCHEMA_VERSION},
                "request_id": {"type": "integer", "minimum": 1},
                "method": {"$ref": "#/$defs/RobrixSupervisordMethod"},
            }),
            &["schema_version", "request_id", "method"],
        ),
    );
    definitions.insert(
        "RobrixSupervisordPayload".to_string(),
        json!({
            "oneOf": [
                health_payload,
                tagged_object(
                    "roster",
                    json!({"agents": {"type": "array", "maxItems": MAX_SUPERVISORD_ROSTER, "items": {"$ref": "#/$defs/SupervisordAgentStatus"}}}),
                    &["agents"],
                ),
                agent_payload,
                tagged_object(
                    "error",
                    json!({
                        "code": safe_code_schema(),
                        "message": safe_message_schema(),
                        "actual": nullable_ref("SupervisordAgentStatus"),
                    }),
                    &["code", "message", "actual"],
                ),
            ]
        }),
    );
    definitions.insert(
        "RobrixSupervisordResponse".to_string(),
        strict_object(
            json!({
                "schema_version": {"const": SUPERVISORD_CONTROL_SCHEMA_VERSION},
                "request_id": {"type": "integer", "minimum": 1},
                "payload": {"$ref": "#/$defs/RobrixSupervisordPayload"},
            }),
            &["schema_version", "request_id", "payload"],
        ),
    );
    json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://hepta.local/schema/robrix-supervisord-readonly-v2.json",
        "title": "Robrix read-only supervisord protocol v2",
        "x-hepta-validation-role": JSON_SCHEMA_VALIDATION_ROLE,
        "x-hepta-authoritative-semantic-validator": AUTHORITATIVE_SEMANTIC_VALIDATOR,
        "x-hepta-non-schema-invariant-classes": JSON_SCHEMA_NON_SCHEMA_INVARIANT_CLASSES,
        "x-hepta-non-schema-invariants": SUPERVISORD_NON_SCHEMA_INVARIANTS,
        "oneOf": [
            {"$ref": "#/$defs/RobrixSupervisordRequest"},
            {"$ref": "#/$defs/RobrixSupervisordResponse"},
        ],
        "$defs": definitions,
    })
}

fn matrixd_schema() -> Value {
    let definitions = BTreeMap::from([
        ("AgentId".to_string(), agent_id_schema()),
        ("Digest".to_string(), digest_schema()),
        ("RuntimeId".to_string(), runtime_id_schema()),
        ("MatrixRoomId".to_string(), matrix_id_schema("!")),
        ("MatrixUserId".to_string(), matrix_id_schema("@")),
        (
            "MatrixdFence".to_string(),
            strict_object(
                json!({
                    "binding_revision": nonzero_integer_schema(),
                    "binding_digest": {"$ref": "#/$defs/Digest"},
                    "attached_agent_generation": nonzero_integer_schema(),
                    "process_incarnation": {"$ref": "#/$defs/RuntimeId"},
                    "plane_epoch": nonzero_integer_schema(),
                }),
                &[
                    "binding_revision",
                    "binding_digest",
                    "attached_agent_generation",
                    "process_incarnation",
                    "plane_epoch",
                ],
            ),
        ),
        (
            "MatrixdBootstrapMethod".to_string(),
            matrixd_bootstrap_method_schema(),
        ),
        (
            "MatrixdFencedMethod".to_string(),
            matrixd_fenced_method_schema(),
        ),
        ("MatrixdMethod".to_string(), matrixd_method_schema()),
        (
            "MatrixdRequest".to_string(),
            json!({
                "oneOf": [
                    matrixd_request_schema(
                        json!({"type": "null"}),
                        "MatrixdBootstrapMethod",
                    ),
                    matrixd_request_schema(
                        json!({"$ref": "#/$defs/MatrixdFence"}),
                        "MatrixdFencedMethod",
                    ),
                ]
            }),
        ),
        (
            "ApprovalDecision".to_string(),
            json!({"enum": ["accept", "accept_for_session", "decline", "cancel"]}),
        ),
        (
            "PendingApproval".to_string(),
            strict_object(
                json!({
                    "approval_key": {"$ref": "#/$defs/RuntimeId"},
                    "kind": {"$ref": "#/$defs/RuntimeId"},
                    "thread_id": {"$ref": "#/$defs/RuntimeId"},
                    "turn_id": {"$ref": "#/$defs/RuntimeId"},
                    "summary": bounded_safe_string_schema(
                        MAX_PENDING_APPROVAL_SUMMARY_BYTES,
                        "safe_message",
                    ),
                    "created_at_ms": nonzero_integer_schema(),
                    "allowed_decisions": {"type": "array", "minItems": 1, "maxItems": 4, "uniqueItems": true, "items": {"$ref": "#/$defs/ApprovalDecision"}},
                }),
                &[
                    "approval_key",
                    "kind",
                    "thread_id",
                    "turn_id",
                    "summary",
                    "created_at_ms",
                    "allowed_decisions",
                ],
            ),
        ),
        (
            "MatrixdLifecycle".to_string(),
            json!({"enum": ["starting", "syncing", "ready", "degraded", "draining", "fenced"]}),
        ),
        ("MatrixdHealth".to_string(), matrixd_health_schema()),
        ("MatrixdSnapshot".to_string(), matrixd_snapshot_schema()),
        ("MatrixdEventKind".to_string(), matrixd_event_kind_schema()),
        (
            "MatrixdEvent".to_string(),
            strict_object(
                json!({
                    "cursor": nonzero_integer_schema(),
                    "kind": {"$ref": "#/$defs/MatrixdEventKind"},
                }),
                &["cursor", "kind"],
            ),
        ),
        (
            "MatrixdEventBatch".to_string(),
            matrixd_event_batch_schema(),
        ),
        ("MatrixdPayload".to_string(), matrixd_payload_schema()),
        (
            "MatrixdResponse".to_string(),
            strict_object(
                json!({
                    "schema_version": {"const": MATRIXD_CONTROL_SCHEMA_VERSION},
                    "request_id": nonzero_integer_schema(),
                    "agent_id": {"$ref": "#/$defs/AgentId"},
                    "release_id": {"$ref": "#/$defs/RuntimeId"},
                    "binding_revision": nonzero_integer_schema(),
                    "binding_digest": {"$ref": "#/$defs/Digest"},
                    "attached_agent_generation": nonzero_integer_schema(),
                    "process_incarnation": {"$ref": "#/$defs/RuntimeId"},
                    "plane_epoch": nonzero_integer_schema(),
                    "payload": {"$ref": "#/$defs/MatrixdPayload"},
                }),
                &[
                    "schema_version",
                    "request_id",
                    "agent_id",
                    "release_id",
                    "binding_revision",
                    "binding_digest",
                    "attached_agent_generation",
                    "process_incarnation",
                    "plane_epoch",
                    "payload",
                ],
            ),
        ),
    ]);
    json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://hepta.local/schema/robrix-matrixd-control-v2.json",
        "title": "Robrix owner-local Matrix companion protocol v2",
        "x-hepta-validation-role": JSON_SCHEMA_VALIDATION_ROLE,
        "x-hepta-authoritative-semantic-validator": AUTHORITATIVE_SEMANTIC_VALIDATOR,
        "x-hepta-non-schema-invariant-classes": JSON_SCHEMA_NON_SCHEMA_INVARIANT_CLASSES,
        "x-hepta-non-schema-invariants": MATRIXD_NON_SCHEMA_INVARIANTS,
        "oneOf": [
            {"$ref": "#/$defs/MatrixdRequest"},
            {"$ref": "#/$defs/MatrixdResponse"},
        ],
        "$defs": definitions,
    })
}

fn common_supervisor_definitions() -> BTreeMap<String, Value> {
    BTreeMap::from([
        ("AgentId".to_string(), agent_id_schema()),
        ("SupervisorEpoch".to_string(), uuid_schema()),
        ("Digest".to_string(), digest_schema()),
        (
            "ReleaseId".to_string(),
            json!({"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9._-]+$"}),
        ),
        (
            "AgentLifecycle".to_string(),
            json!({"enum": ["stopped", "starting", "running", "draining", "failed"]}),
        ),
        (
            "SupervisordControlFence".to_string(),
            with_all_of(
                strict_object(
                    json!({
                        "agent_id": {"$ref": "#/$defs/AgentId"},
                        "supervisor_epoch": {"$ref": "#/$defs/SupervisorEpoch"},
                        "lifecycle": {"$ref": "#/$defs/AgentLifecycle"},
                        "lifecycle_generation": {"type": "integer", "minimum": 0},
                        "spawn_generation": nullable_integer(),
                        "runtime_generation": nullable_integer(),
                        "current_release": nullable_ref("ReleaseId"),
                        "previous_release": nullable_ref("ReleaseId"),
                        "release_change_pending": {"type": "boolean"},
                        "state_digest": {"$ref": "#/$defs/Digest"},
                    }),
                    &[
                        "agent_id",
                        "supervisor_epoch",
                        "lifecycle",
                        "lifecycle_generation",
                        "spawn_generation",
                        "runtime_generation",
                        "current_release",
                        "previous_release",
                        "release_change_pending",
                        "state_digest",
                    ],
                ),
                vec![
                    json!({
                        "oneOf": [
                            {"properties": {"spawn_generation": {"type": "null"}, "runtime_generation": {"type": "null"}}},
                            {"properties": {"spawn_generation": {"type": "integer", "minimum": 0}, "runtime_generation": {"type": "integer", "minimum": 0}}},
                        ]
                    }),
                    json!({
                        "if": {"properties": {"lifecycle": {"enum": ["starting", "running", "draining"]}}},
                        "then": {"properties": {"runtime_generation": {"type": "integer", "minimum": 0}}}
                    }),
                    json!({
                        "if": {"properties": {"lifecycle": {"const": "stopped"}}},
                        "then": {"properties": {"runtime_generation": {"type": "null"}}}
                    }),
                    json!({
                        "if": {"properties": {"release_change_pending": {"const": true}}},
                        "then": {"properties": {"current_release": {"$ref": "#/$defs/ReleaseId"}}}
                    }),
                ],
            ),
        ),
        (
            "SupervisordMatrixStatus".to_string(),
            with_all_of(
                strict_object(
                    json!({
                        "configured": {"type": "boolean"},
                        "active": {"type": "boolean"},
                        "healthy": {"type": "boolean"},
                        "degraded": {"type": "boolean"},
                        "process_id": nullable_positive_integer(),
                        "attached_agent_generation": nullable_positive_integer(),
                        "binding_revision": nullable_positive_integer(),
                        "restart_attempt": {"type": "integer", "minimum": 0, "maximum": u32::MAX},
                        "last_error": {"oneOf": [{"type": "null"}, safe_message_schema()]},
                    }),
                    &[
                        "configured",
                        "active",
                        "healthy",
                        "degraded",
                        "process_id",
                        "attached_agent_generation",
                        "binding_revision",
                        "restart_attempt",
                        "last_error",
                    ],
                ),
                vec![
                    json!({
                        "oneOf": [
                            {"properties": {"active": {"const": true}, "process_id": {"type": "integer", "minimum": 1}, "attached_agent_generation": {"type": "integer", "minimum": 1}, "binding_revision": {"type": "integer", "minimum": 1}}},
                            {"properties": {"active": {"const": false}, "process_id": {"type": "null"}, "attached_agent_generation": {"type": "null"}, "binding_revision": {"type": "null"}}},
                        ]
                    }),
                    json!({
                        "if": {"properties": {"healthy": {"const": true}}},
                        "then": {"properties": {"configured": {"const": true}, "active": {"const": true}, "degraded": {"const": false}}}
                    }),
                    json!({
                        "if": {"properties": {"configured": {"const": false}}},
                        "then": {"properties": {"active": {"const": false}, "healthy": {"const": false}, "degraded": {"const": false}, "process_id": {"type": "null"}, "attached_agent_generation": {"type": "null"}, "binding_revision": {"type": "null"}, "last_error": {"type": "null"}}}
                    }),
                ],
            ),
        ),
        (
            "SupervisordAgentStatus".to_string(),
            with_all_of(
                strict_object(
                    json!({
                        "agent_id": {"$ref": "#/$defs/AgentId"},
                        "lifecycle": {"$ref": "#/$defs/AgentLifecycle"},
                        "lifecycle_generation": {"type": "integer", "minimum": 0},
                        "active": {"type": "boolean"},
                        "healthy": {"type": "boolean"},
                        "process_id": nullable_positive_integer(),
                        "spawn_generation": nullable_integer(),
                        "runtime_generation": nullable_integer(),
                        "current_release": nullable_ref("ReleaseId"),
                        "previous_release": nullable_ref("ReleaseId"),
                        "release_change_pending": {"type": "boolean"},
                        "control_fence": {"$ref": "#/$defs/SupervisordControlFence"},
                        "matrix": {"$ref": "#/$defs/SupervisordMatrixStatus"},
                    }),
                    &[
                        "agent_id",
                        "lifecycle",
                        "lifecycle_generation",
                        "active",
                        "healthy",
                        "process_id",
                        "spawn_generation",
                        "runtime_generation",
                        "current_release",
                        "previous_release",
                        "release_change_pending",
                        "control_fence",
                        "matrix",
                    ],
                ),
                vec![
                    json!({
                        "if": {"properties": {"healthy": {"const": true}}},
                        "then": {"properties": {"active": {"const": true}, "lifecycle": {"const": "running"}}}
                    }),
                    json!({
                        "if": {"properties": {"matrix": {"properties": {"active": {"const": true}}, "required": ["active"]}}},
                        "then": {"properties": {"active": {"const": true}, "lifecycle": {"const": "running"}}}
                    }),
                ],
            ),
        ),
        (
            "SupervisordHealth".to_string(),
            strict_object(
                json!({
                    "ready": {"type": "boolean"},
                    "supervisor_epoch": {"$ref": "#/$defs/SupervisorEpoch"},
                    "process_id": {"type": "integer", "minimum": 1, "maximum": u32::MAX},
                    "registered_agents": {"type": "integer", "minimum": 0, "maximum": MAX_SUPERVISORD_ROSTER},
                    "observed_faults": {"type": "integer", "minimum": 0},
                }),
                &[
                    "ready",
                    "supervisor_epoch",
                    "process_id",
                    "registered_agents",
                    "observed_faults",
                ],
            ),
        ),
    ])
}

fn matrixd_bootstrap_method_schema() -> Value {
    json!({
        "oneOf": [
            tagged_object("health", json!({}), &[]),
            tagged_object("snapshot", json!({}), &[]),
        ]
    })
}

fn matrixd_fenced_method_schema() -> Value {
    json!({
        "oneOf": [
            tagged_object(
                "events",
                json!({
                    "after_cursor": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_MATRIXD_EVENT_BATCH},
                }),
                &["after_cursor", "limit"],
            ),
            tagged_object(
                "cancel_turn",
                json!({
                    "thread_id": {"$ref": "#/$defs/RuntimeId"},
                    "turn_id": {"$ref": "#/$defs/RuntimeId"},
                }),
                &["thread_id", "turn_id"],
            ),
            tagged_object(
                "resolve_approval",
                json!({
                    "approval_key": {"$ref": "#/$defs/RuntimeId"},
                    "decision": {"$ref": "#/$defs/ApprovalDecision"},
                }),
                &["approval_key", "decision"],
            ),
        ]
    })
}

fn matrixd_method_schema() -> Value {
    json!({
        "oneOf": [
            {"$ref": "#/$defs/MatrixdBootstrapMethod"},
            {"$ref": "#/$defs/MatrixdFencedMethod"},
        ]
    })
}

fn matrixd_request_schema(fence: Value, method_definition: &str) -> Value {
    strict_object(
        json!({
            "schema_version": {"const": MATRIXD_CONTROL_SCHEMA_VERSION},
            "request_id": nonzero_integer_schema(),
            "agent_id": {"$ref": "#/$defs/AgentId"},
            "fence": fence,
            "method": {"$ref": format!("#/$defs/{method_definition}")},
        }),
        &[
            "schema_version",
            "request_id",
            "agent_id",
            "fence",
            "method",
        ],
    )
}

fn matrixd_snapshot_schema() -> Value {
    with_all_of(
        strict_object(
            json!({
                "lifecycle": {"$ref": "#/$defs/MatrixdLifecycle"},
                "expected_mxid": {"$ref": "#/$defs/MatrixUserId"},
                "active_rooms": {"type": "array", "maxItems": 256, "uniqueItems": true, "items": {"$ref": "#/$defs/MatrixRoomId"}},
                "inbox_depth": {"type": "integer", "minimum": 0, "maximum": u32::MAX},
                "outbox_depth": {"type": "integer", "minimum": 0, "maximum": u32::MAX},
                "oldest_inbox_age_seconds": nullable_integer(),
                "oldest_outbox_age_seconds": nullable_integer(),
                "active_thread_id": nullable_ref("RuntimeId"),
                "active_turn_id": nullable_ref("RuntimeId"),
                "pending_approvals": {"type": "array", "maxItems": MAX_PENDING_APPROVALS, "items": {"$ref": "#/$defs/PendingApproval"}},
                "resync_required": {"type": "boolean"},
                "event_cursor": {"type": "integer", "minimum": 0},
            }),
            &[
                "lifecycle",
                "expected_mxid",
                "active_rooms",
                "inbox_depth",
                "outbox_depth",
                "oldest_inbox_age_seconds",
                "oldest_outbox_age_seconds",
                "active_thread_id",
                "active_turn_id",
                "pending_approvals",
                "resync_required",
                "event_cursor",
            ],
        ),
        vec![json!({
            "oneOf": [
                {"properties": {"active_thread_id": {"type": "null"}, "active_turn_id": {"type": "null"}}},
                {"properties": {"active_thread_id": {"$ref": "#/$defs/RuntimeId"}, "active_turn_id": {"$ref": "#/$defs/RuntimeId"}}},
            ]
        })],
    )
}

fn matrixd_health_schema() -> Value {
    with_all_of(
        strict_object(
            json!({
                "lifecycle": {"$ref": "#/$defs/MatrixdLifecycle"},
                "process_id": {"type": "integer", "minimum": 1, "maximum": u32::MAX},
                "agentd_connected": {"type": "boolean"},
                "matrix_sync_connected": {"type": "boolean"},
                "fenced": {"type": "boolean"},
            }),
            &[
                "lifecycle",
                "process_id",
                "agentd_connected",
                "matrix_sync_connected",
                "fenced",
            ],
        ),
        vec![json!({
            "oneOf": [
                {"properties": {"lifecycle": {"const": "fenced"}, "fenced": {"const": true}}},
                {"properties": {"lifecycle": {"enum": ["starting", "syncing", "ready", "degraded", "draining"]}, "fenced": {"const": false}}},
            ]
        })],
    )
}

fn matrixd_event_batch_schema() -> Value {
    with_all_of(
        strict_object(
            json!({
                "events": {"type": "array", "maxItems": MAX_MATRIXD_EVENT_BATCH, "items": {"$ref": "#/$defs/MatrixdEvent"}},
                "gap": {"type": "boolean"},
                "next_cursor": {"type": "integer", "minimum": 0},
                "latest_cursor": {"type": "integer", "minimum": 0},
            }),
            &["events", "gap", "next_cursor", "latest_cursor"],
        ),
        vec![json!({
            "if": {"properties": {"gap": {"const": true}}},
            "then": {"properties": {"events": {"maxItems": 0}}}
        })],
    )
}

fn matrixd_event_kind_schema() -> Value {
    json!({
        "oneOf": [
            tagged_object("lifecycle", json!({"lifecycle": {"$ref": "#/$defs/MatrixdLifecycle"}}), &["lifecycle"]),
            tagged_object("agent_connection", json!({"connected": {"type": "boolean"}, "generation": nonzero_integer_schema()}), &["connected", "generation"]),
            tagged_object("matrix_connection", json!({"connected": {"type": "boolean"}}), &["connected"]),
            tagged_object("queue_depth", json!({"inbox": {"type": "integer", "minimum": 0, "maximum": u32::MAX}, "outbox": {"type": "integer", "minimum": 0, "maximum": u32::MAX}}), &["inbox", "outbox"]),
            tagged_object("turn_started", json!({"thread_id": {"$ref": "#/$defs/RuntimeId"}, "turn_id": {"$ref": "#/$defs/RuntimeId"}}), &["thread_id", "turn_id"]),
            tagged_object("turn_completed", json!({"thread_id": {"$ref": "#/$defs/RuntimeId"}, "turn_id": {"$ref": "#/$defs/RuntimeId"}}), &["thread_id", "turn_id"]),
            tagged_object("approval_pending", json!({"approval": {"$ref": "#/$defs/PendingApproval"}}), &["approval"]),
            tagged_object("approval_resolved", json!({"approval_key": {"$ref": "#/$defs/RuntimeId"}}), &["approval_key"]),
            tagged_object("resync_required", json!({"reason_code": safe_code_schema()}), &["reason_code"]),
        ]
    })
}

fn matrixd_payload_schema() -> Value {
    json!({
        "oneOf": [
            tagged_object_from_schema("health", &matrixd_health_schema()),
            tagged_object_from_schema("snapshot", &matrixd_snapshot_schema()),
            tagged_object_from_schema("events", &matrixd_event_batch_schema()),
            tagged_object("accepted", json!({}), &[]),
            tagged_object(
                "error",
                json!({"code": safe_code_schema(), "message": safe_message_schema()}),
                &["code", "message"],
            ),
        ]
    })
}

fn strict_object(mut properties: Value, required: &[&str]) -> Value {
    let properties = properties
        .as_object_mut()
        .map(std::mem::take)
        .unwrap_or_default();
    json!({
        "type": "object",
        "additionalProperties": false,
        "properties": properties,
        "required": required,
    })
}

fn tagged_object(tag: &str, mut properties: Value, required: &[&str]) -> Value {
    let Some(properties) = properties.as_object_mut() else {
        return json!({"not": {}});
    };
    properties.insert("type".to_string(), json!({"const": tag}));
    let mut required = required.to_vec();
    required.insert(0, "type");
    strict_object(Value::Object(properties.clone()), &required)
}

fn tagged_object_from_schema(tag: &str, schema: &Value) -> Value {
    let Some(mut object) = schema.as_object().cloned() else {
        return json!({"not": {}});
    };
    let Some(mut properties) = object.get("properties").and_then(Value::as_object).cloned() else {
        return json!({"not": {}});
    };
    properties.insert("type".to_string(), json!({"const": tag}));
    let Some(mut required) = object.get("required").and_then(Value::as_array).cloned() else {
        return json!({"not": {}});
    };
    required.insert(0, Value::String("type".to_string()));
    object.insert("properties".to_string(), Value::Object(properties));
    object.insert("required".to_string(), Value::Array(required));
    Value::Object(object)
}

fn with_all_of(mut schema: Value, constraints: Vec<Value>) -> Value {
    if let Some(object) = schema.as_object_mut() {
        object.insert("allOf".to_string(), Value::Array(constraints));
    }
    schema
}

fn nullable_ref(definition: &str) -> Value {
    json!({"oneOf": [{"type": "null"}, {"$ref": format!("#/$defs/{definition}")}]})
}

fn nullable_integer() -> Value {
    json!({"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0}]})
}

fn nullable_positive_integer() -> Value {
    json!({"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 1}]})
}

fn nonzero_integer_schema() -> Value {
    json!({"type": "integer", "minimum": 1})
}

fn safe_code_schema() -> Value {
    json!({
        "type": "string",
        "minLength": 1,
        "maxLength": MAX_MATRIXD_ERROR_CODE_BYTES,
        "pattern": "^[a-z0-9_]+$",
    })
}

fn safe_message_schema() -> Value {
    bounded_safe_string_schema(MAX_MATRIXD_ERROR_MESSAGE_BYTES, "safe_message")
}

fn agent_id_schema() -> Value {
    json!({
        "type": "string",
        "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    })
}

fn uuid_schema() -> Value {
    json!({
        "type": "string",
        "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    })
}

fn digest_schema() -> Value {
    json!({"type": "string", "pattern": "^[0-9a-f]{64}$"})
}

fn runtime_id_schema() -> Value {
    bounded_safe_string_schema(MAX_RUNTIME_IDENTIFIER_BYTES, "runtime_identifier")
}

fn bounded_safe_string_schema(max_utf8_bytes: usize, profile: &str) -> Value {
    json!({
        "type": "string",
        "minLength": 1,
        // Standard maxLength counts Unicode scalar values, not UTF-8 bytes.
        // The required custom keyword below preserves the protocol's byte
        // bound; consumers must fail closed if they do not implement it.
        "maxLength": max_utf8_bytes,
        "x-hepta-max-utf8-bytes": max_utf8_bytes,
        "x-hepta-safe-text-profile": profile,
    })
}

fn matrix_id_schema(prefix: &str) -> Value {
    json!({
        "type": "string",
        "minLength": 3,
        "maxLength": 255,
        "pattern": format!("^{prefix}[^\\s:]+:.+$"),
    })
}

fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    let value = canonicalize_json(&serde_json::to_value(value)?);
    let mut bytes = serde_json::to_vec_pretty(&value)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn canonicalize_json(value: &Value) -> Value {
    match value {
        Value::Array(values) => Value::Array(values.iter().map(canonicalize_json).collect()),
        Value::Object(map) => {
            let mut entries = map.iter().collect::<Vec<_>>();
            entries.sort_by_key(|(key, _)| *key);
            let mut sorted = Map::with_capacity(map.len());
            for (key, value) in entries {
                sorted.insert(key.clone(), canonicalize_json(value));
            }
            Value::Object(sorted)
        }
        value => value.clone(),
    }
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
