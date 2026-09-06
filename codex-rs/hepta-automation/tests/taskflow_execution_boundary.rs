#![allow(
    clippy::expect_used,
    reason = "TaskFlow boundary fixtures should fail loudly"
)]

use codex_hepta_automation::LocalTaskFlowBoundaryActionV1;
use codex_hepta_automation::LocalTaskFlowBoundaryRequestV1;
use codex_hepta_automation::LocalTaskFlowPredecessorReferenceV1;
use codex_hepta_automation::LocalTaskFlowTerminalStateV1;
use codex_hepta_automation::MAX_TASKFLOW_BOUNDARY_ENCODED_BYTES;
use codex_hepta_automation::MAX_TASKFLOW_BOUNDARY_PREDECESSORS;
use codex_hepta_automation::TASKFLOW_EXECUTION_BOUNDARY_SCHEMA_VERSION;
use codex_hepta_automation::TaskFlowBoundaryAuthority;
use codex_hepta_automation::TaskFlowBoundaryError;
use codex_hepta_automation::TaskFlowBoundaryScope;
use codex_hepta_automation::TaskFlowBoundaryUnavailableReason;
use codex_hepta_automation::assess_local_taskflow_boundary;
use codex_hepta_automation::assess_local_taskflow_boundary_json;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use serde_json::json;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const OTHER_AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dd4";

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn predecessor(step_id: impl Into<String>) -> LocalTaskFlowPredecessorReferenceV1 {
    let step_id = step_id.into();
    LocalTaskFlowPredecessorReferenceV1 {
        state_digest: digest(&format!("state:{step_id}")),
        step_id,
    }
}

fn external_request() -> LocalTaskFlowBoundaryRequestV1 {
    LocalTaskFlowBoundaryRequestV1 {
        schema_version: TASKFLOW_EXECUTION_BOUNDARY_SCHEMA_VERSION,
        owner_agent_id: AgentId::parse(AGENT_ID).expect("agent id"),
        workflow_id: "daily-review".to_string(),
        workflow_version: 7,
        definition_digest: digest("definition"),
        run_id: "occurrence:2026-09-06T00:00:00Z".to_string(),
        run_revision: 11,
        run_state_digest: digest("run-state"),
        step_id: "dispatch".to_string(),
        attempt: 2,
        predecessor_references: vec![predecessor("collect"), predecessor("review")],
        action: LocalTaskFlowBoundaryActionV1::ExternalEffect {
            operation_intent_reference_digest: digest("operation-intent"),
            final_payload_digest: digest("final-payload"),
            destination_digest: digest("destination"),
            idempotency_key_digest: digest("idempotency-key"),
        },
    }
}

fn terminal_request(state: LocalTaskFlowTerminalStateV1) -> LocalTaskFlowBoundaryRequestV1 {
    LocalTaskFlowBoundaryRequestV1 {
        action: LocalTaskFlowBoundaryActionV1::TerminalState {
            proposed_state: state,
            result_digest: digest("result"),
        },
        ..external_request()
    }
}

#[test]
fn valid_effect_request_is_deterministically_unavailable_and_deny_all() {
    let request = external_request();
    let first = assess_local_taskflow_boundary(&request).expect("structurally valid request");
    let second = assess_local_taskflow_boundary(&request).expect("repeat assessment");

    assert_eq!(first, second);
    assert_eq!(first.authority(), TaskFlowBoundaryAuthority::DENY_ALL);
    assert!(!first.authority().grants_any());
    assert_eq!(
        first.scope(),
        TaskFlowBoundaryScope::SuppliedStepAndPredecessorsOnly
    );
    assert_eq!(
        first.reason(),
        TaskFlowBoundaryUnavailableReason::RegisteredEffectOwnerUnavailable
    );
    assert_ne!(first.request_digest().as_str(), "0".repeat(/*n*/ 64));
    assert_ne!(first.assessment_digest().as_str(), "0".repeat(/*n*/ 64));
}

#[test]
fn every_proposed_terminal_state_requires_a_trusted_external_observer() {
    for state in [
        LocalTaskFlowTerminalStateV1::Succeeded,
        LocalTaskFlowTerminalStateV1::Failed,
        LocalTaskFlowTerminalStateV1::Cancelled,
    ] {
        let result = assess_local_taskflow_boundary(&terminal_request(state))
            .expect("valid terminal proposal");
        assert_eq!(result.authority(), TaskFlowBoundaryAuthority::DENY_ALL);
        assert_eq!(
            result.reason(),
            TaskFlowBoundaryUnavailableReason::TrustedTerminalObserverUnavailable
        );
    }
}

#[test]
fn callers_cannot_add_verified_use_approval_or_graph_completeness_claims() {
    let request = external_request();
    let mut value = serde_json::to_value(&request).expect("request JSON");
    for field in [
        "verified_use",
        "verified_use_token",
        "approved",
        "graph_complete",
        "task_graph",
        "terminal_observed",
        "authority",
    ] {
        assert!(
            value
                .as_object_mut()
                .expect("request object")
                .insert(field.to_string(), json!(true))
                .is_none()
        );
        let encoded = serde_json::to_vec(&value).expect("hostile JSON");
        assert_eq!(
            assess_local_taskflow_boundary_json(&encoded),
            Err(TaskFlowBoundaryError::MalformedInput),
            "field {field} must be rejected"
        );
        assert!(
            value
                .as_object_mut()
                .expect("request object")
                .remove(field)
                .is_some()
        );
    }

    let mut nested = serde_json::to_value(&request).expect("request JSON");
    nested["action"]["approval_digest"] = json!(digest("self-approved").as_str());
    assert_eq!(
        assess_local_taskflow_boundary_json(
            &serde_json::to_vec(&nested).expect("nested hostile JSON")
        ),
        Err(TaskFlowBoundaryError::MalformedInput)
    );

    // Matching caller-created content digests still produce only Unavailable.
    let result = assess_local_taskflow_boundary(&request).expect("local assessment");
    assert_eq!(
        result.reason(),
        TaskFlowBoundaryUnavailableReason::RegisteredEffectOwnerUnavailable
    );
}

#[test]
fn json_shape_version_and_enums_are_exact() {
    let value = serde_json::to_value(external_request()).expect("request JSON");

    for version in [0, 2, u32::MAX] {
        let mut changed = value.clone();
        changed["schema_version"] = json!(version);
        assert_eq!(
            assess_local_taskflow_boundary_json(
                &serde_json::to_vec(&changed).expect("version JSON")
            ),
            Err(TaskFlowBoundaryError::UnsupportedSchemaVersion)
        );
    }

    let mut missing = value.clone();
    assert!(
        missing
            .as_object_mut()
            .expect("request object")
            .remove("run_revision")
            .is_some()
    );
    assert_eq!(
        assess_local_taskflow_boundary_json(&serde_json::to_vec(&missing).expect("missing JSON")),
        Err(TaskFlowBoundaryError::MalformedInput)
    );

    let mut unknown_kind = value.clone();
    unknown_kind["action"]["kind"] = json!("run_arbitrary_tool");
    assert_eq!(
        assess_local_taskflow_boundary_json(
            &serde_json::to_vec(&unknown_kind).expect("unknown kind JSON")
        ),
        Err(TaskFlowBoundaryError::MalformedInput)
    );

    let mut unknown_predecessor = value.clone();
    unknown_predecessor["predecessor_references"][0]["complete"] = json!(true);
    assert_eq!(
        assess_local_taskflow_boundary_json(
            &serde_json::to_vec(&unknown_predecessor).expect("unknown predecessor JSON")
        ),
        Err(TaskFlowBoundaryError::MalformedInput)
    );

    let mut terminal =
        serde_json::to_value(terminal_request(LocalTaskFlowTerminalStateV1::Succeeded))
            .expect("terminal JSON");
    terminal["action"]["proposed_state"] = json!("caller_verified_success");
    assert_eq!(
        assess_local_taskflow_boundary_json(
            &serde_json::to_vec(&terminal).expect("unknown terminal JSON")
        ),
        Err(TaskFlowBoundaryError::MalformedInput)
    );

    let duplicate = serde_json::to_vec(&value).expect("request JSON");
    let duplicate = String::from_utf8(duplicate).expect("UTF-8 JSON").replacen(
        "{",
        "{\"schema_version\":1,",
        /*count*/ 1,
    );
    assert_eq!(
        assess_local_taskflow_boundary_json(duplicate.as_bytes()),
        Err(TaskFlowBoundaryError::MalformedInput)
    );
}

#[test]
fn every_digest_is_nonzero_lowercase_and_bound() {
    let valid = external_request();
    let baseline = assess_local_taskflow_boundary(&valid)
        .expect("baseline")
        .request_digest()
        .clone();
    let mut mutations = Vec::new();

    let mut changed = valid.clone();
    changed.definition_digest = digest("different-definition");
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.run_state_digest = digest("different-run-state");
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.predecessor_references[0].state_digest = digest("different-predecessor-state");
    mutations.push(changed);
    let replacement = digest("changed-operation-intent");
    let mut changed = valid.clone();
    let LocalTaskFlowBoundaryActionV1::ExternalEffect {
        operation_intent_reference_digest,
        ..
    } = &mut changed.action
    else {
        unreachable!("external fixture")
    };
    *operation_intent_reference_digest = replacement;
    mutations.push(changed);
    let mut changed = valid.clone();
    let LocalTaskFlowBoundaryActionV1::ExternalEffect {
        final_payload_digest,
        ..
    } = &mut changed.action
    else {
        unreachable!("external fixture")
    };
    *final_payload_digest = digest("changed-final-payload");
    mutations.push(changed);
    let mut changed = valid.clone();
    let LocalTaskFlowBoundaryActionV1::ExternalEffect {
        destination_digest, ..
    } = &mut changed.action
    else {
        unreachable!("external fixture")
    };
    *destination_digest = digest("changed-destination");
    mutations.push(changed);
    let mut changed = valid.clone();
    let LocalTaskFlowBoundaryActionV1::ExternalEffect {
        idempotency_key_digest,
        ..
    } = &mut changed.action
    else {
        unreachable!("external fixture")
    };
    *idempotency_key_digest = digest("changed-idempotency-key");
    mutations.push(changed);
    for changed in mutations {
        assert_ne!(
            assess_local_taskflow_boundary(&changed)
                .expect("changed valid input")
                .request_digest(),
            &baseline
        );
    }

    let mut zero = serde_json::to_value(&valid).expect("request JSON");
    for pointer in [
        "/definition_digest",
        "/run_state_digest",
        "/predecessor_references/0/state_digest",
        "/action/operation_intent_reference_digest",
        "/action/final_payload_digest",
        "/action/destination_digest",
        "/action/idempotency_key_digest",
    ] {
        let original = zero.pointer(pointer).expect("digest field").clone();
        *zero.pointer_mut(pointer).expect("digest field") = json!("0".repeat(/*n*/ 64));
        assert!(matches!(
            assess_local_taskflow_boundary_json(
                &serde_json::to_vec(&zero).expect("zero digest JSON")
            ),
            Err(TaskFlowBoundaryError::InvalidField(_))
        ));
        *zero.pointer_mut(pointer).expect("digest field") = original;
    }

    *zero.pointer_mut("/definition_digest").expect("digest") = json!("A".repeat(/*n*/ 64));
    assert_eq!(
        assess_local_taskflow_boundary_json(&serde_json::to_vec(&zero).expect("uppercase JSON")),
        Err(TaskFlowBoundaryError::InvalidField("definition_digest"))
    );

    let mut terminal =
        serde_json::to_value(terminal_request(LocalTaskFlowTerminalStateV1::Succeeded))
            .expect("terminal JSON");
    terminal["action"]["result_digest"] = json!("0".repeat(/*n*/ 64));
    assert_eq!(
        assess_local_taskflow_boundary_json(
            &serde_json::to_vec(&terminal).expect("zero terminal digest JSON")
        ),
        Err(TaskFlowBoundaryError::InvalidField("action.result_digest"))
    );
}

#[test]
fn request_digest_binds_identity_count_and_action_shape() {
    let valid = external_request();
    let baseline = assess_local_taskflow_boundary(&valid)
        .expect("baseline")
        .request_digest()
        .clone();
    let mut mutations = Vec::new();

    let mut changed = valid.clone();
    changed.owner_agent_id = AgentId::parse(OTHER_AGENT_ID).expect("other agent id");
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.workflow_id = "other-workflow".to_string();
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.workflow_version = 8;
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.run_id = "other-run".to_string();
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.run_revision = 12;
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.step_id = "other-dispatch".to_string();
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.attempt = 3;
    mutations.push(changed);
    let mut changed = valid.clone();
    changed.predecessor_references[0].step_id = "assemble".to_string();
    mutations.push(changed);
    let mut changed = valid;
    let _removed = changed.predecessor_references.pop();
    mutations.push(changed);
    mutations.push(terminal_request(LocalTaskFlowTerminalStateV1::Succeeded));

    for changed in mutations {
        assert_ne!(
            assess_local_taskflow_boundary(&changed)
                .expect("changed valid input")
                .request_digest(),
            &baseline
        );
    }

    let terminal = terminal_request(LocalTaskFlowTerminalStateV1::Succeeded);
    let terminal_baseline = assess_local_taskflow_boundary(&terminal)
        .expect("terminal baseline")
        .request_digest()
        .clone();
    let mut changed = terminal;
    changed.action = LocalTaskFlowBoundaryActionV1::TerminalState {
        proposed_state: LocalTaskFlowTerminalStateV1::Failed,
        result_digest: digest("result"),
    };
    assert_ne!(
        assess_local_taskflow_boundary(&changed)
            .expect("changed terminal state")
            .request_digest(),
        &terminal_baseline
    );
    changed.action = LocalTaskFlowBoundaryActionV1::TerminalState {
        proposed_state: LocalTaskFlowTerminalStateV1::Succeeded,
        result_digest: digest("different-result"),
    };
    assert_ne!(
        assess_local_taskflow_boundary(&changed)
            .expect("changed terminal result")
            .request_digest(),
        &terminal_baseline
    );
}

#[test]
fn predecessor_count_identity_and_order_are_strictly_bounded() {
    let mut maximum = external_request();
    maximum.predecessor_references = (0..MAX_TASKFLOW_BOUNDARY_PREDECESSORS)
        .map(|index| predecessor(format!("p{index:03}")))
        .collect();
    assert!(assess_local_taskflow_boundary(&maximum).is_ok());

    let mut too_many = maximum;
    too_many.predecessor_references.push(predecessor("p127"));
    assert_eq!(
        assess_local_taskflow_boundary(&too_many),
        Err(TaskFlowBoundaryError::ResourceLimit {
            field: "predecessor_references",
            maximum: MAX_TASKFLOW_BOUNDARY_PREDECESSORS,
        })
    );

    let mut duplicate = external_request();
    duplicate.predecessor_references = vec![predecessor("same"), predecessor("same")];
    assert_eq!(
        assess_local_taskflow_boundary(&duplicate),
        Err(TaskFlowBoundaryError::NonCanonicalPredecessors)
    );

    let mut reversed = external_request();
    reversed.predecessor_references.reverse();
    assert_eq!(
        assess_local_taskflow_boundary(&reversed),
        Err(TaskFlowBoundaryError::NonCanonicalPredecessors)
    );

    let mut recursive = external_request();
    recursive.predecessor_references = vec![predecessor("dispatch")];
    assert_eq!(
        assess_local_taskflow_boundary(&recursive),
        Err(TaskFlowBoundaryError::CurrentStepAsPredecessor)
    );

    assert_eq!(
        assess_local_taskflow_boundary_json(&vec![b' '; MAX_TASKFLOW_BOUNDARY_ENCODED_BYTES + 1]),
        Err(TaskFlowBoundaryError::EncodedSizeExceeded {
            max_bytes: MAX_TASKFLOW_BOUNDARY_ENCODED_BYTES,
        })
    );
}

#[test]
fn validation_errors_do_not_reflect_untrusted_values() {
    let mut unsupported_version = external_request();
    unsupported_version.schema_version = u32::MAX;
    let unsupported = assess_local_taskflow_boundary(&unsupported_version)
        .expect_err("unsupported version must be rejected");
    assert_eq!(unsupported, TaskFlowBoundaryError::UnsupportedSchemaVersion);
    assert!(!unsupported.to_string().contains(&u32::MAX.to_string()));

    let attacker_step_id = "attacker-controlled-step";
    let mut recursive = external_request();
    recursive.step_id = attacker_step_id.to_string();
    recursive.predecessor_references = vec![predecessor(attacker_step_id)];
    let current_step = assess_local_taskflow_boundary(&recursive)
        .expect_err("current step predecessor must be rejected");
    assert_eq!(
        current_step,
        TaskFlowBoundaryError::CurrentStepAsPredecessor
    );
    assert!(!current_step.to_string().contains(attacker_step_id));
}

#[test]
fn numeric_and_identifier_bounds_fail_closed() {
    let mut request = external_request();
    request.workflow_version = 0;
    assert_eq!(
        assess_local_taskflow_boundary(&request),
        Err(TaskFlowBoundaryError::InvalidField("workflow_version"))
    );
    for run_revision in [0, u64::MAX] {
        request = external_request();
        request.run_revision = run_revision;
        assert_eq!(
            assess_local_taskflow_boundary(&request),
            Err(TaskFlowBoundaryError::InvalidField("run_revision"))
        );
    }
    for attempt in [0, 1_000_001, u32::MAX] {
        request = external_request();
        request.attempt = attempt;
        assert_eq!(
            assess_local_taskflow_boundary(&request),
            Err(TaskFlowBoundaryError::InvalidField("attempt"))
        );
    }
    for invalid in [
        String::new(),
        "has space".to_string(),
        "x".repeat(/*n*/ 129),
    ] {
        request = external_request();
        request.workflow_id = invalid;
        assert_eq!(
            assess_local_taskflow_boundary(&request),
            Err(TaskFlowBoundaryError::InvalidField("workflow_id"))
        );
    }

    request = external_request();
    request.run_id = "bad/run".to_string();
    assert_eq!(
        assess_local_taskflow_boundary(&request),
        Err(TaskFlowBoundaryError::InvalidField("run_id"))
    );
    request = external_request();
    request.step_id.clear();
    assert_eq!(
        assess_local_taskflow_boundary(&request),
        Err(TaskFlowBoundaryError::InvalidField("step_id"))
    );
    request = external_request();
    request.predecessor_references[0].step_id = "bad predecessor".to_string();
    assert_eq!(
        assess_local_taskflow_boundary(&request),
        Err(TaskFlowBoundaryError::InvalidField("predecessor.step_id"))
    );

    let mut invalid_agent = serde_json::to_value(external_request()).expect("request JSON");
    invalid_agent["owner_agent_id"] = json!("caller-selected-owner");
    assert_eq!(
        assess_local_taskflow_boundary_json(
            &serde_json::to_vec(&invalid_agent).expect("invalid agent JSON")
        ),
        Err(TaskFlowBoundaryError::MalformedInput)
    );
}

#[test]
fn rejected_requests_are_failure_atomic_and_do_not_poison_later_results() {
    let valid = external_request();
    let before = valid.clone();
    let expected = assess_local_taskflow_boundary(&valid).expect("initial assessment");

    let mut invalid = valid.clone();
    invalid.predecessor_references.reverse();
    assert_eq!(
        assess_local_taskflow_boundary(&invalid),
        Err(TaskFlowBoundaryError::NonCanonicalPredecessors)
    );
    assert_eq!(valid, before, "borrowed input must remain unchanged");
    assert_eq!(
        assess_local_taskflow_boundary(&valid).expect("assessment after rejection"),
        expected
    );
}

#[test]
fn canonical_digest_has_independent_golden_values() {
    let external = assess_local_taskflow_boundary(&external_request()).expect("external");
    assert_eq!(
        external.request_digest().as_str(),
        "141176e15dc14f59d3b5b340e1a0a9bf23f94f23e3835313b03e081c92b960ae"
    );
    assert_eq!(
        external.assessment_digest().as_str(),
        "b24257e5fbafb44aa83806840be09cb2f7d8a95067c799099cf8938ef644f4c4"
    );

    let terminal =
        assess_local_taskflow_boundary(&terminal_request(LocalTaskFlowTerminalStateV1::Succeeded))
            .expect("terminal");
    assert_eq!(
        terminal.request_digest().as_str(),
        "6b1325c47865f95076d7e3aa17d3778dbaf0e0d80b0fb4c3749379e524c3601b"
    );
    assert_eq!(
        terminal.assessment_digest().as_str(),
        "d81b7fd9cb77204ddc88f58576007670ae545fc002e2afdf75d469dcd56acb4b"
    );
}
