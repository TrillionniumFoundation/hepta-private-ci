use super::*;
use crate::AgentId;
use crate::RunBridgeIdentityV1;
use crate::RunBridgeProviderOutcomeV1;
use crate::Sha256Digest;
use pretty_assertions::assert_eq;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn pending() -> TestResult<RunBridgeOutboxV1> {
    let identity = RunBridgeIdentityV1 {
        schema_version: 1,
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001")?,
        run_id: "outbox-run".into(),
        request_id: "outbox-request".into(),
        owner_generation: 1,
        owner_dispatch_revision: 3,
        source_dispatch_revision: 4,
        fence_sha256: Sha256Digest::for_bytes(b"fence"),
        context_sha256: Sha256Digest::for_bytes(b"context"),
        envelope_sha256: Sha256Digest::for_bytes(b"envelope"),
        execution_binding_sha256: Sha256Digest::for_bytes(b"execution"),
        dispatch_sha256: Sha256Digest::for_bytes(b"dispatch"),
    };
    let binding = RunBridgeBindingV1 {
        abort_commitment_sha256: RunBridgeBindingV1::abort_commitment(&identity, &[7; 32])?,
        identity,
    };
    let primary = RunBridgePrimaryV1 {
        schema_version: 1,
        binding_sha256: binding.digest()?,
        source_revision: 6,
        provider_outcome: RunBridgeProviderOutcomeV1::Completed,
        logical_outcome: RunBridgeLogicalOutcomeV1::Succeeded,
        qualification_sha256: Sha256Digest::for_bytes(b"normalized success"),
        terminal_correlation_sha256: Some(Sha256Digest::for_bytes(b"terminal")),
        abort_proof_sha256: None,
    };
    Ok(RunBridgeOutboxV1::new(binding, primary)?)
}
fn notice(state: &RunBridgeOutboxV1) -> TestResult<RunBridgeQualificationConflictV1> {
    Ok(RunBridgeQualificationConflictV1 {
        schema_version: 1,
        binding_sha256: state.binding().digest()?,
        primary_sha256: state.primary().digest(state.binding())?,
        source_revision: 7,
        qualification_sha256: Sha256Digest::for_bytes(b"late quota denial"),
    })
}
fn primary_ack(state: &RunBridgeOutboxV1) -> TestResult<RunBridgeAcknowledgementV1> {
    Ok(RunBridgeAcknowledgementV1 {
        schema_version: 1,
        binding_sha256: state.binding().digest()?,
        publication_sha256: state.primary().digest(state.binding())?,
        kind: RunBridgePublicationKindV1::Primary,
        owner_revision: 8,
    })
}
fn notice_ack(state: &RunBridgeOutboxV1) -> TestResult<RunBridgeAcknowledgementV1> {
    Ok(RunBridgeAcknowledgementV1 {
        schema_version: 1,
        binding_sha256: state.binding().digest()?,
        publication_sha256: notice(state)?.digest(state.binding(), state.primary())?,
        kind: RunBridgePublicationKindV1::QualificationConflict,
        owner_revision: 9,
    })
}

#[test]
fn early_notice_ack_rejects_without_losing_retry_obligation() -> TestResult {
    let state = pending()?;
    let state = state.transition(RunBridgeOutboxChangeV1::QueueConflict(notice(&state)?))?;
    let before = serde_json::to_vec(&state)?;
    let ack = notice_ack(&state)?;
    assert!(
        state
            .transition(RunBridgeOutboxChangeV1::AcknowledgeConflict(ack.clone()))
            .is_err()
    );
    assert_eq!(serde_json::to_vec(&state)?, before);
    assert!(state.primary_delivery_pending());
    assert!(state.conflict_delivery_pending());
    let state = state.transition(RunBridgeOutboxChangeV1::AcknowledgePrimary(primary_ack(
        &state,
    )?))?;
    let state = state.transition(RunBridgeOutboxChangeV1::AcknowledgeConflict(ack))?;
    assert!(!state.primary_delivery_pending());
    assert!(!state.conflict_delivery_pending());
    assert!(!state.acknowledged_success_without_conflict());
    Ok(())
}

#[test]
fn downgrade_and_primary_ack_commute_without_rewriting_history() -> TestResult {
    let initial = pending()?;
    let downgrade = RunBridgeOutboxChangeV1::QueueConflict(notice(&initial)?);
    let acknowledge = RunBridgeOutboxChangeV1::AcknowledgePrimary(primary_ack(&initial)?);
    let left = initial
        .transition(downgrade.clone())?
        .transition(acknowledge.clone())?;
    let right = initial.transition(acknowledge)?.transition(downgrade)?;
    assert_eq!(left, right);
    assert_eq!(left.primary(), initial.primary());
    assert_eq!(
        left.primary_acknowledgement(),
        Some(&primary_ack(&initial)?)
    );
    assert!(!left.primary_delivery_pending());
    assert!(left.conflict_delivery_pending());
    assert!(!left.acknowledged_success_without_conflict());
    Ok(())
}

#[test]
fn snapshot_reconstruction_retains_stable_ack_and_duplicate_delivery() -> TestResult {
    let initial = pending()?;
    let ack = primary_ack(&initial)?;
    let primary = initial.transition(RunBridgeOutboxChangeV1::AcknowledgePrimary(ack.clone()))?;
    assert!(primary.acknowledged_success_without_conflict());
    let notice = notice(&primary)?;
    let queued = primary.transition(RunBridgeOutboxChangeV1::QueueConflict(notice.clone()))?;
    let conflict_ack = notice_ack(&queued)?;
    let complete = queued.transition(RunBridgeOutboxChangeV1::AcknowledgeConflict(
        conflict_ack.clone(),
    ))?;
    for snapshot in [&initial, &primary, &queued, &complete] {
        let hydrated: RunBridgeOutboxV1 = serde_json::from_slice(&serde_json::to_vec(snapshot)?)?;
        assert_eq!(&hydrated, snapshot);
    }
    let restored: RunBridgeOutboxV1 = serde_json::from_slice(&serde_json::to_vec(&complete)?)?;
    assert_eq!(restored, complete);
    for event in [
        RunBridgeOutboxChangeV1::AcknowledgePrimary(ack),
        RunBridgeOutboxChangeV1::QueueConflict(notice),
        RunBridgeOutboxChangeV1::AcknowledgeConflict(conflict_ack),
    ] {
        assert_eq!(restored.transition(event)?, complete);
    }
    Ok(())
}

#[test]
fn conflicting_ack_notice_or_owner_order_is_atomic() -> TestResult {
    let initial = pending()?;
    let queued = initial.transition(RunBridgeOutboxChangeV1::QueueConflict(notice(&initial)?))?;
    let committed = queued.transition(RunBridgeOutboxChangeV1::AcknowledgePrimary(primary_ack(
        &queued,
    )?))?;
    let before = serde_json::to_vec(&committed)?;
    let mut wrong_ack = primary_ack(&committed)?;
    wrong_ack.owner_revision += 1;
    let mut wrong_notice = notice(&committed)?;
    wrong_notice.source_revision += 1;
    let mut reversed = notice_ack(&committed)?;
    reversed.owner_revision = primary_ack(&committed)?.owner_revision;
    let mut wrong_binding = notice_ack(&committed)?;
    wrong_binding.binding_sha256 = Sha256Digest::for_bytes(b"other binding");
    for event in [
        RunBridgeOutboxChangeV1::AcknowledgePrimary(wrong_ack),
        RunBridgeOutboxChangeV1::QueueConflict(wrong_notice),
        RunBridgeOutboxChangeV1::AcknowledgeConflict(reversed),
        RunBridgeOutboxChangeV1::AcknowledgeConflict(wrong_binding),
    ] {
        assert!(committed.transition(event).is_err());
        assert_eq!(serde_json::to_vec(&committed)?, before);
    }
    Ok(())
}

#[test]
fn hydration_rejects_missing_relationships_and_positional_objects() -> TestResult {
    let initial = pending()?;
    let state = initial
        .transition(RunBridgeOutboxChangeV1::QueueConflict(notice(&initial)?))?
        .transition(RunBridgeOutboxChangeV1::AcknowledgePrimary(primary_ack(
            &initial,
        )?))?
        .transition(RunBridgeOutboxChangeV1::AcknowledgeConflict(notice_ack(
            &initial,
        )?))?;
    let original = serde_json::to_value(&state)?;
    for field in ["primary_ack", "conflict"] {
        let mut value = original.clone();
        value[field] = serde_json::Value::Null;
        assert!(serde_json::from_value::<RunBridgeOutboxV1>(value).is_err());
    }
    for pointer in [
        "",
        "/binding",
        "/binding/identity",
        "/primary",
        "/primary_ack",
        "/conflict",
        "/conflict_ack",
    ] {
        let mut value = original.clone();
        let target = value.pointer_mut(pointer).ok_or("missing fixture object")?;
        let positional = target
            .as_object()
            .ok_or("expected object")?
            .values()
            .cloned()
            .collect();
        *target = serde_json::Value::Array(positional);
        assert!(serde_json::from_value::<RunBridgeOutboxV1>(value).is_err());
    }
    let mut value = original.clone();
    value["schema_version"] = serde_json::json!(2);
    assert!(serde_json::from_value::<RunBridgeOutboxV1>(value).is_err());
    let mut value = original;
    value["primary_ack"]["publication_sha256"] =
        serde_json::json!(Sha256Digest::for_bytes(b"other primary"));
    assert!(serde_json::from_value::<RunBridgeOutboxV1>(value).is_err());
    Ok(())
}

#[test]
fn hydration_rejects_duplicate_and_unknown_keys_at_every_object_depth() -> TestResult {
    let original = serde_json::to_value(pending()?)?;
    for pointer in ["", "/binding", "/binding/identity", "/primary"] {
        let mut unknown = original.clone();
        unknown
            .pointer_mut(pointer)
            .ok_or("missing object")?
            .as_object_mut()
            .ok_or("expected object")?
            .insert("unexpected".into(), serde_json::json!(1));
        assert!(serde_json::from_value::<RunBridgeOutboxV1>(unknown).is_err());
        let object = original.pointer(pointer).ok_or("missing object")?;
        let (key, value) = object
            .as_object()
            .ok_or("expected object")?
            .iter()
            .next()
            .ok_or("empty object")?;
        let encoded = serde_json::to_string(object)?;
        let duplicate = format!(
            "{{{}:{},{}",
            serde_json::to_string(key)?,
            serde_json::to_string(value)?,
            &encoded[1..]
        );
        let full = serde_json::to_string(&original)?.replacen(&encoded, &duplicate, 1);
        assert!(serde_json::from_str::<RunBridgeOutboxV1>(&full).is_err());
    }
    Ok(())
}

#[test]
fn failed_primary_cannot_acquire_a_success_downgrade() -> TestResult {
    let successful = pending()?;
    let mut primary = successful.primary().clone();
    primary.logical_outcome = RunBridgeLogicalOutcomeV1::Failed;
    let failed = RunBridgeOutboxV1::new(successful.binding().clone(), primary)?;
    let before = serde_json::to_vec(&failed)?;
    assert!(
        failed
            .transition(RunBridgeOutboxChangeV1::QueueConflict(notice(&failed)?))
            .is_err()
    );
    assert_eq!(serde_json::to_vec(&failed)?, before);
    assert!(!failed.acknowledged_success_without_conflict());
    Ok(())
}

#[test]
fn untrusted_snapshot_decode_bounds_bytes_objects_keys_strings_and_depth() -> TestResult {
    let state = pending()?;
    let bytes = serde_json::to_vec(&state)?;
    assert_eq!(RunBridgeOutboxV1::from_json_slice(&bytes)?, state);
    let oversized = format!("{{\"unknown\":\"{}\"}}", "x".repeat(MAX_SNAPSHOT_BYTES));
    assert_eq!(
        RunBridgeOutboxV1::from_json_slice(oversized.as_bytes()),
        Err(RunBridgeError("run bridge snapshot byte bound exceeded"))
    );
    let mut many = serde_json::Map::new();
    for index in 0..=MAX_OBJECT_ENTRIES {
        many.insert(format!("key{index}"), serde_json::json!(null));
    }
    for (value, expected) in [
        (
            serde_json::json!({"unknown": "x".repeat(MAX_STRING_BYTES + 1)}),
            "string bound",
        ),
        (serde_json::Value::Object(many), "object bound"),
        (
            serde_json::json!({"x".repeat(MAX_KEY_BYTES + 1): null}),
            "object bound",
        ),
        (serde_json::json!({"a":{"b":{"c":{}}}}), "depth exceeded"),
    ] {
        let encoded = serde_json::to_vec(&value)?;
        assert!(encoded.len() < MAX_SNAPSHOT_BYTES);
        assert!(
            serde_json::from_slice::<RunBridgeOutboxV1>(&encoded)
                .unwrap_err()
                .to_string()
                .contains(expected)
        );
        assert!(RunBridgeOutboxV1::from_json_slice(&encoded).is_err());
    }
    for field in ["primary_ack", "conflict", "conflict_ack"] {
        let mut value = serde_json::to_value(&state)?;
        value
            .as_object_mut()
            .ok_or("expected object")?
            .remove(field);
        assert!(RunBridgeOutboxV1::from_json_slice(&serde_json::to_vec(&value)?).is_err());
    }
    Ok(())
}
