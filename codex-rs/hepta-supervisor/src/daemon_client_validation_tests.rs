use anyhow::Context;
use anyhow::Result;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::*;
use crate::daemon_protocol::ControlStateDigest;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const OTHER_AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13";
const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
const DIGEST: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn status(agent_id: &str) -> Result<crate::SupervisordAgentStatus> {
    Ok(serde_json::from_value(json!({
        "agent_id": agent_id, "lifecycle": "running", "lifecycle_generation": 7,
        "active": true, "healthy": true, "process_id": 100,
        "spawn_generation": 5, "runtime_generation": 7,
        "current_release": "agentd-v1", "previous_release": null,
        "release_change_pending": false,
        "control_fence": {
            "agent_id": agent_id, "supervisor_epoch": EPOCH,
            "lifecycle": "running", "lifecycle_generation": 7,
            "spawn_generation": 5, "runtime_generation": 7,
            "current_release": "agentd-v1", "previous_release": null,
            "release_change_pending": false, "state_digest": DIGEST
        },
        "matrix": {
            "configured": false, "active": false, "healthy": false, "degraded": false,
            "process_id": null, "attached_agent_generation": null, "binding_revision": null,
            "restart_attempt": 0, "last_error": null
        }
    }))?)
}

fn response(payload: SupervisordPayload) -> SupervisordResponse {
    SupervisordResponse {
        schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
        request_id: 41,
        payload,
    }
}

fn accepted() -> Result<SupervisordPayload> {
    let agent = status(AGENT)?;
    Ok(SupervisordPayload::MutationAccepted {
        operation: SupervisordMutation::Restart,
        accepted_state_digest: agent.control_fence.state_digest.clone(),
        agent,
        production_receipt: None,
    })
}

#[test]
fn response_identity_payload_and_selected_agent_must_match_request() -> Result<()> {
    let selected = status(AGENT)?;
    let request = SupervisordRequest::new(
        /*request_id*/ 41,
        SupervisordMethod::Snapshot {
            agent_id: selected.agent_id.clone(),
        },
    );
    let valid = response(SupervisordPayload::Agent(selected));
    validate_response(&request, &valid)?;
    let mut wrong_id = valid.clone();
    wrong_id.request_id += 1;
    let mut wrong_schema = valid;
    wrong_schema.schema_version += 1;
    let wrong_agent = response(SupervisordPayload::Agent(status(OTHER_AGENT)?));
    let wrong_type = response(SupervisordPayload::Roster { agents: Vec::new() });
    for invalid in [wrong_id, wrong_schema, wrong_agent, wrong_type] {
        assert!(validate_response(&request, &invalid).is_err());
    }
    Ok(())
}

#[test]
fn mutation_acceptance_binds_operation_digest_agent_and_owner_epoch() -> Result<()> {
    let fence = status(AGENT)?.control_fence;
    let request =
        SupervisordRequest::new(/*request_id*/ 41, SupervisordMethod::Restart { fence });
    let valid = response(accepted()?);
    validate_response(&request, &valid)?;
    for field in [
        "operation",
        "accepted_state_digest",
        "agent",
        "epoch",
        "status",
    ] {
        let mut changed = valid.clone();
        let SupervisordPayload::MutationAccepted {
            operation,
            accepted_state_digest,
            agent,
            ..
        } = &mut changed.payload
        else {
            unreachable!("fixture acceptance")
        };
        match field {
            "operation" => *operation = SupervisordMutation::Kill,
            "accepted_state_digest" => {
                *accepted_state_digest = ControlStateDigest::from_bytes([1; 32])
            }
            "agent" => *agent = status(OTHER_AGENT)?,
            "epoch" => agent.control_fence.supervisor_epoch = crate::SupervisorEpoch::new(),
            "status" => agent.control_fence.lifecycle_generation += 1,
            _ => unreachable!("fixture substitution"),
        }
        assert!(validate_response(&request, &changed).is_err(), "{field}");
    }
    Ok(())
}

// These typed envelopes exercise response association only. The daemon's
// independent signature/admission checks are covered by the authority tests.
fn signed_request() -> Result<SupervisordRequest> {
    let fence = status(AGENT)?.control_fence;
    let method = serde_json::from_value(json!({
        "type": "signed_upgrade", "fence": fence,
        "grant": {
            "schema_version": 1, "namespace": "fixture", "agent_id": AGENT,
            "source_release": "agentd-v1", "target_release": "agentd-v2", "transition": "upgrade",
            "h7_envelope_sha256": DIGEST, "artifact_sha256": DIGEST,
            "expected_control_revision": 3, "expected_lifecycle_generation": 7,
            "authority_epoch": 1, "signer_id": "fixture", "signer_epoch": 1,
            "issued_at_unix_seconds": 1, "expires_at_unix_seconds": 2,
            "production_authority": true, "external_effects": true,
            "operator_acceptance": true, "promotion": true, "governance_bypass": false,
            "signature_base64": "fixture", "grant_sha256": DIGEST
        },
        "h7_envelope": {
            "schema_version": 1, "namespace": "fixture", "signature_domain": "fixture",
            "signature_algorithm": "fixture", "artifact_id": "fixture",
            "artifact_sha256": DIGEST, "trajectory_sha256": DIGEST, "evaluation_sha256": DIGEST,
            "ope_evaluation_sha256": null, "signer_id": "fixture", "signer_epoch": 1,
            "issued_at_unix_seconds": 1, "expires_at_unix_seconds": 2,
            "transition": "reload", "expected_runtime_generation": 7,
            "predecessor_artifact_sha256": null, "qualification_only": true,
            "production_authority": false, "external_effects": false, "promotion_eligible": false,
            "signature_base64": "fixture", "envelope_sha256": DIGEST
        }
    }))?;
    Ok(SupervisordRequest::new(/*request_id*/ 41, method))
}

fn receipt() -> Result<ProductionMutationReceipt> {
    Ok(serde_json::from_value(json!({
        "grant_sha256": DIGEST, "agent_id": AGENT, "transition": "upgrade",
        "source_release": "agentd-v1", "target_release": "agentd-v2",
        "control_revision": 4, "status": "queued", "production_authority": true,
        "external_effects": true, "operator_acceptance": true, "promotion": true
    }))?)
}

#[test]
fn signed_acceptance_requires_exact_queued_grant_receipt() -> Result<()> {
    let request = signed_request()?;
    let valid = response(SupervisordPayload::MutationAccepted {
        operation: SupervisordMutation::Upgrade,
        accepted_state_digest: status(AGENT)?.control_fence.state_digest,
        agent: status(AGENT)?,
        production_receipt: Some(receipt()?),
    });
    validate_response(&request, &valid)?;
    for field in [
        "missing",
        "grant",
        "agent",
        "transition",
        "source",
        "target",
        "revision",
        "status",
        "flags",
    ] {
        let mut changed = valid.clone();
        let SupervisordPayload::MutationAccepted {
            production_receipt, ..
        } = &mut changed.payload
        else {
            unreachable!("fixture acceptance")
        };
        if field == "missing" {
            *production_receipt = None;
        } else if let Some(receipt) = production_receipt {
            match field {
                "grant" => {
                    receipt.grant_sha256 =
                        codex_hepta_contracts::Sha256Digest::for_bytes(b"unrelated")
                }
                "agent" => receipt.agent_id = OTHER_AGENT.to_string(),
                "transition" => receipt.transition = H7H89ProductionTransition::Rollback,
                "source" => receipt.source_release = "unrelated-source".to_string(),
                "target" => receipt.target_release = "unrelated-target".to_string(),
                "revision" => receipt.control_revision += 1,
                "status" => receipt.status = ProductionMutationStatus::Committed,
                "flags" => receipt.operator_acceptance = false,
                _ => unreachable!("fixture substitution"),
            }
        }
        assert!(validate_response(&request, &changed).is_err(), "{field}");
    }
    let ordinary = SupervisordRequest::new(
        /*request_id*/ 41,
        SupervisordMethod::Upgrade {
            fence: status(AGENT)?.control_fence,
            release_id: ReleaseId::parse("agentd-v2").map_err(anyhow::Error::msg)?,
        },
    );
    assert!(validate_response(&ordinary, &valid).is_err());
    Ok(())
}

#[test]
fn error_text_and_error_agent_are_bounded_safe_and_associated() -> Result<()> {
    let selected = status(AGENT)?;
    let request = SupervisordRequest::new(
        /*request_id*/ 41,
        SupervisordMethod::Snapshot {
            agent_id: selected.agent_id.clone(),
        },
    );
    let valid = response(SupervisordPayload::Error {
        code: "stale_control_fence".to_string(),
        message: "refresh before retry".to_string(),
        actual: Some(selected),
    });
    validate_response(&request, &valid)?;
    for text in [
        "unsafe\ntext".to_string(),
        "unsafe\u{202e}text".to_string(),
        "x".repeat(1_025),
    ] {
        let mut changed = valid.clone();
        if let SupervisordPayload::Error { message, .. } = &mut changed.payload {
            *message = text;
        }
        let error = validate_response(&request, &changed)
            .err()
            .context("unsafe response rejected")?;
        assert!(error.to_string().len() < 128);
        assert!(!error.to_string().contains("unsafe\ntext"));
    }
    let mut changed = valid;
    if let SupervisordPayload::Error { actual, .. } = &mut changed.payload {
        *actual = Some(status(OTHER_AGENT)?);
        assert!(validate_response(&request, &changed).is_err());
        if let SupervisordPayload::Error { actual, code, .. } = &mut changed.payload {
            *actual = None;
            *code = "INVALID".to_string();
        }
    }
    assert!(validate_response(&request, &changed).is_err());
    Ok(())
}

#[test]
fn durable_selection_and_production_state_match_selected_agent_and_digest_shape() -> Result<()> {
    let selected = status(AGENT)?.agent_id;
    let selection = crate::DurableReleaseTransaction::new(
        AGENT,
        crate::ReleaseTransactionKind::Upgrade,
        "agentd-v1",
        "agentd-v2",
        /*rollback_predecessor*/ None,
        /*source_binding*/ None,
        /*target_binding*/ None,
        /*expected_release_state_generation*/ 1,
        /*expected_lifecycle_generation*/ 7,
    )?;
    let request = SupervisordRequest::new(
        /*request_id*/ 41,
        SupervisordMethod::ReleaseSelection {
            agent_id: selected.clone(),
        },
    );
    let mut wire = response(SupervisordPayload::ReleaseSelection {
        selection: Some(selection),
    });
    validate_response(&request, &wire)?;
    if let SupervisordPayload::ReleaseSelection {
        selection: Some(selection),
    } = &mut wire.payload
    {
        selection.target_release = "tampered".to_string();
    }
    assert!(validate_response(&request, &wire).is_err());
    let request = SupervisordRequest::new(
        /*request_id*/ 41,
        SupervisordMethod::ProductionMutationStatus { agent_id: selected },
    );
    let state = ProductionMutationState {
        receipt: receipt()?,
        intent_sha256: codex_hepta_contracts::Sha256Digest::for_bytes(b"intent"),
        release_transaction_sha256: None,
    };
    let mut wire = response(SupervisordPayload::ProductionMutationStatus { state: Some(state) });
    validate_response(&request, &wire)?;
    if let SupervisordPayload::ProductionMutationStatus { state: Some(state) } = &mut wire.payload {
        // Sha256Digest serde is transparent, so response validation must check it.
        state.intent_sha256 = serde_json::from_value(json!("not-a-digest"))?;
    }
    assert!(validate_response(&request, &wire).is_err());
    Ok(())
}

#[test]
fn recovery_reply_binds_decision_context_and_accepts_changed_terminal_intent() -> Result<()> {
    let predecessor = crate::SignedSupervisorIntent::new(
        codex_hepta_contracts::Sha256Digest::parse(DIGEST).map_err(anyhow::Error::msg)?,
        AGENT,
        H7H89ProductionTransition::Upgrade,
        "agentd-v1",
        "agentd-v2",
        /*expected_control_revision*/ 3,
        /*expected_lifecycle_generation*/ 7,
        /*authority_epoch*/ 1,
        crate::SignedIntentStatus::RecoveryRequired,
    )?;
    let terminal_intent = predecessor.with_status(crate::SignedIntentStatus::Committed)?;
    assert_ne!(predecessor.intent_sha256, terminal_intent.intent_sha256);
    let fence = status(AGENT)?.control_fence;
    let decision = serde_json::from_value(json!({
        "schema_version": 1, "namespace": "fixture", "agent_id": AGENT,
        "grant_sha256": DIGEST, "intent_sha256": predecessor.intent_sha256,
        "release_transaction_sha256": DIGEST, "observed_release": "agentd-v2",
        "observed_manifest_sha256": DIGEST, "observed_agentd_sha256": DIGEST,
        "observed_matrixd_sha256": null, "outcome": "committed",
        "expected_lifecycle_generation": 7, "authority_epoch": 1,
        "signer_id": "fixture", "signer_epoch": 1,
        "issued_at_unix_seconds": 1, "expires_at_unix_seconds": 2,
        "signature_base64": "fixture", "decision_sha256": DIGEST
    }))?;
    let request = SupervisordRequest::new(
        /*request_id*/ 41,
        SupervisordMethod::ResolveProductionRecovery { fence, decision },
    );
    let mut terminal = receipt()?;
    terminal.status = ProductionMutationStatus::Committed;
    let valid = response(SupervisordPayload::ProductionMutationStatus {
        state: Some(ProductionMutationState {
            receipt: terminal,
            intent_sha256: terminal_intent.intent_sha256,
            release_transaction_sha256: Some(codex_hepta_contracts::Sha256Digest::for_bytes(
                b"terminal transaction",
            )),
        }),
    });
    validate_response(&request, &valid)?;
    for field in ["grant", "intent", "outcome", "release", "transaction"] {
        let mut changed = valid.clone();
        if let SupervisordPayload::ProductionMutationStatus { state: Some(state) } =
            &mut changed.payload
        {
            match field {
                "grant" => {
                    state.receipt.grant_sha256 =
                        codex_hepta_contracts::Sha256Digest::for_bytes(b"other")
                }
                "intent" => state.intent_sha256 = predecessor.intent_sha256.clone(),
                "outcome" => state.receipt.status = ProductionMutationStatus::RolledBack,
                "release" => state.receipt.target_release = "other-release".to_string(),
                "transaction" => state.release_transaction_sha256 = None,
                _ => unreachable!("fixture substitution"),
            }
        }
        assert!(validate_response(&request, &changed).is_err(), "{field}");
    }
    let rollback_predecessor = crate::SignedSupervisorIntent::new(
        predecessor.grant_sha256,
        AGENT,
        H7H89ProductionTransition::Rollback,
        "agentd-v1",
        "agentd-v2",
        /*expected_control_revision*/ 3,
        /*expected_lifecycle_generation*/ 7,
        /*authority_epoch*/ 1,
        crate::SignedIntentStatus::RecoveryRequired,
    )?;
    let rollback_terminal =
        rollback_predecessor.with_status(crate::SignedIntentStatus::RolledBack)?;
    let mut rollback_request = request;
    if let SupervisordMethod::ResolveProductionRecovery { decision, .. } =
        &mut rollback_request.method
    {
        decision.outcome = ProductionRecoveryOutcome::RolledBack;
        decision.intent_sha256 = rollback_predecessor.intent_sha256;
    }
    let mut rollback_reply = valid;
    if let SupervisordPayload::ProductionMutationStatus { state: Some(state) } =
        &mut rollback_reply.payload
    {
        state.receipt.transition = H7H89ProductionTransition::Rollback;
        state.receipt.status = ProductionMutationStatus::RolledBack;
        state.intent_sha256 = rollback_terminal.intent_sha256;
    }
    for selected in ["agentd-v1", "agentd-v2"] {
        if let SupervisordMethod::ResolveProductionRecovery { decision, .. } =
            &mut rollback_request.method
        {
            decision.observed_release = selected.to_string();
        }
        validate_response(&rollback_request, &rollback_reply)?;
    }
    if let SupervisordMethod::ResolveProductionRecovery { decision, .. } =
        &mut rollback_request.method
    {
        decision.observed_release = "unrelated".to_string();
    }
    assert!(validate_response(&rollback_request, &rollback_reply).is_err());
    if let SupervisordMethod::ResolveProductionRecovery { decision, .. } =
        &mut rollback_request.method
    {
        decision.outcome = ProductionRecoveryOutcome::Committed;
        decision.observed_release = "agentd-v2".to_string();
    }
    if let SupervisordPayload::ProductionMutationStatus { state: Some(state) } =
        &mut rollback_reply.payload
    {
        state.receipt.status = ProductionMutationStatus::Committed;
    }
    assert!(validate_response(&rollback_request, &rollback_reply).is_err());
    Ok(())
}

#[test]
fn malformed_response_json_never_echoes_hostile_field_or_variant_text() -> Result<()> {
    let raw = serde_json::to_vec(&json!({
        "schema_version": 2, "request_id": 41,
        "payload": {"type": "private-authority-evidence".repeat(16_384)}
    }))?;
    let error = decode_response(&raw)
        .err()
        .context("invalid payload rejected")?;
    assert_eq!(
        error.to_string(),
        "invalid supervisor value: supervisord returned invalid response JSON"
    );
    Ok(())
}

#[test]
fn unexpected_payload_diagnostic_never_debug_formats_authority_evidence() -> Result<()> {
    let mut authority = receipt()?;
    authority.source_release = "sensitive".repeat(16_384);
    let error = super::super::unexpected::<()>(SupervisordPayload::MutationAccepted {
        operation: SupervisordMutation::Upgrade,
        accepted_state_digest: status(AGENT)?.control_fence.state_digest,
        agent: status(AGENT)?,
        production_receipt: Some(authority),
    })
    .err()
    .context("unexpected payload rejected")?;
    assert_eq!(
        error.to_string(),
        "invalid supervisor value: supervisord returned an unexpected payload type"
    );
    Ok(())
}
