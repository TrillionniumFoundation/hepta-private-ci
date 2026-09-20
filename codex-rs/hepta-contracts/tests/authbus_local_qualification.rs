#![cfg(feature = "authbus-local-qualification")]

use serde::Serialize;

use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SubjectRef;
use codex_hepta_contracts::authbus_b4;
use codex_hepta_contracts::authbus_b4::LocalScheduler;
use codex_hepta_contracts::authbus_b4::QuotaLimits;
use codex_hepta_contracts::authbus_b4::QuotaVector;
use codex_hepta_contracts::authbus_b4::ResourceState;
use codex_hepta_contracts::authbus_b4::SchedulerError;
use codex_hepta_contracts::authbus_b4::SchedulerRequest;
use codex_hepta_contracts::authbus_b4::SchedulerResource;
use codex_hepta_contracts::authbus_b5;
use codex_hepta_contracts::authbus_b5::B5AppendDisposition;
use codex_hepta_contracts::authbus_b5::B5Error;
use codex_hepta_contracts::authbus_b5::B5Fence;
use codex_hepta_contracts::authbus_b5::B5Intent;
use codex_hepta_contracts::authbus_b5::B5OutboxDelivery;
use codex_hepta_contracts::authbus_b5::B5RecoveryAction;
use codex_hepta_contracts::authbus_b5::LocalB5Wal;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn scheduler_resource(quota: QuotaLimits) -> SchedulerResource {
    SchedulerResource {
        resource_id: "resource:qualification".to_string(),
        resource_sha256: digest("resource:qualification"),
        authority_epoch: 1,
        owner_epoch: 1,
        generation: 1,
        fencing_token_sha256: digest("fence:1"),
        quota,
        state: ResourceState::Available,
        cooldown_until_ms: 0,
    }
}

fn scheduler_request(
    resource: &SchedulerResource,
    request_id: &str,
    generation: u64,
) -> SchedulerRequest {
    SchedulerRequest {
        request_id: request_id.to_string(),
        command_id: format!("command:{request_id}"),
        run_id: format!("run:{request_id}"),
        aggregate_id: format!("aggregate:{request_id}"),
        idempotency_key: format!("idempotency:{request_id}"),
        subject: SubjectRef::new(
            "tenant:qualification",
            "workspace:qualification",
            "agent:qualification",
            "service:qualification",
            generation,
        )
        .unwrap_or_else(|error| panic!("static qualification subject must be valid: {error:?}")),
        resource_sha256: resource.resource_sha256.clone(),
        payload_sha256: digest(&format!("payload:{request_id}")),
        policy_sha256: digest("policy:qualification"),
        expected_revision: 1,
        authority_epoch: resource.authority_epoch,
        owner_epoch: resource.owner_epoch,
        generation,
        fencing_token_sha256: resource.fencing_token_sha256.clone(),
        estimate: QuotaVector::new(
            /*rpm*/ 1, /*tpm*/ 1, /*concurrency*/ 1, /*day_budget*/ 1,
            /*context*/ 1,
        ),
        safety_margin: QuotaVector::default(),
        enqueued_at_ms: 1,
        deadline_ms: 100,
        weight: 1,
    }
}

fn effect_key(label: &str) -> ProviderEffectKey {
    ProviderEffectKey::parse(format!("provider-effect:v1:{}", digest(label).as_str()))
        .unwrap_or_else(|error| panic!("derived qualification effect key must be valid: {error:?}"))
}

fn fence(generation: u64) -> B5Fence {
    B5Fence {
        authority_epoch: 3,
        owner_epoch: 7,
        generation,
        fencing_token_sha256: digest(&format!("fence:{generation}")),
    }
}

fn intent(label: &str, generation: u64) -> B5Intent {
    B5Intent {
        effect_key: effect_key(label),
        idempotency_key: format!("idempotency:{label}"),
        payload_sha256: digest(&format!("payload:{label}")),
        fence: fence(generation),
    }
}

fn delivery(label: &str) -> B5OutboxDelivery {
    B5OutboxDelivery {
        outbox_id: format!("outbox:{label}"),
        event_id: format!("event:{label}"),
        idempotency_key: format!("delivery:{label}"),
        payload_sha256: digest(&format!("delivery-payload:{label}")),
        delivery_seq: 1,
        fence: fence(/*generation*/ 11),
    }
}

// Keep the private WAL record shape local to this test so the recovery test
// can construct a hash-valid marker without exposing the internal record enum.
#[derive(Serialize)]
enum DispatchAttemptMarker {
    DispatchAttemptStarted {
        effect_key: ProviderEffectKey,
        idempotency_key: String,
        payload_sha256: Sha256Digest,
        attempt: u32,
        fence: B5Fence,
    },
}

#[test]
fn b4_unknown_quota_and_duplicate_request_fail_closed() {
    let unknown_resource = scheduler_resource(QuotaLimits::unknown_rpm(QuotaVector::new(
        /*rpm*/ 10, /*tpm*/ 10, /*concurrency*/ 2, /*day_budget*/ 10,
        /*context*/ 10,
    )));
    let mut unknown_scheduler = LocalScheduler::new(unknown_resource.clone()).expect("scheduler");
    let unknown_request =
        scheduler_request(&unknown_resource, "unknown-quota", /*generation*/ 1);
    assert_eq!(
        unknown_scheduler.enqueue(unknown_request),
        Err(SchedulerError::UnknownQuota)
    );
    assert_eq!(unknown_scheduler.queued_request_count(), 0);

    let resource = scheduler_resource(QuotaLimits::known(QuotaVector::new(
        /*rpm*/ 10, /*tpm*/ 10, /*concurrency*/ 2, /*day_budget*/ 10,
        /*context*/ 10,
    )));
    let mut scheduler = LocalScheduler::new(resource.clone()).expect("scheduler");
    let request = scheduler_request(&resource, "duplicate", /*generation*/ 1);
    scheduler.enqueue(request.clone()).expect("first enqueue");
    let mut duplicate = request;
    duplicate.expected_revision = scheduler.revision();
    assert_eq!(
        scheduler.enqueue(duplicate),
        Err(SchedulerError::DuplicateRequest)
    );
    assert_eq!(scheduler.queued_request_count(), 1);
}

#[test]
fn b4_stale_permit_callback_does_not_mutate_accounting() {
    let resource = scheduler_resource(QuotaLimits::known(QuotaVector::new(
        /*rpm*/ 10, /*tpm*/ 10, /*concurrency*/ 2, /*day_budget*/ 10,
        /*context*/ 10,
    )));
    let mut scheduler = LocalScheduler::new(resource.clone()).expect("scheduler");
    scheduler
        .enqueue(scheduler_request(
            &resource,
            "stale-permit",
            /*generation*/ 1,
        ))
        .expect("enqueue");
    let permit = scheduler
        .grant_next(/*now_ms*/ 2)
        .expect("grant")
        .expect("permit");
    let held_before = scheduler.held();
    let used_before = scheduler.used();
    let active_before = scheduler.active_permit_count();

    let mut stale = permit;
    stale.generation += 1;
    assert_eq!(
        scheduler.complete(&stale, QuotaVector::default()),
        Err(SchedulerError::StaleFence)
    );
    assert_eq!(scheduler.held(), held_before);
    assert_eq!(scheduler.used(), used_before);
    assert_eq!(scheduler.active_permit_count(), active_before);
}

#[test]
fn b5_crash_after_call_recovers_lookup_only_without_a_second_call() {
    let original = intent("crash", /*generation*/ 11);
    let mut wal = LocalB5Wal::new();
    assert_eq!(
        wal.append_intent(original.clone()),
        Ok(B5AppendDisposition::Inserted)
    );
    wal.crash_after_call(
        &original.effect_key,
        /*attempt*/ 1,
        original.fence.clone(),
    )
    .expect("crash boundary");

    let reopened = LocalB5Wal::reopen_snapshot(&wal.durable_snapshot()).expect("reopen");
    assert_eq!(
        reopened.recover(),
        B5RecoveryAction::LookupOnly {
            effect_key: original.effect_key,
            attempt: 1,
        }
    );
    assert_eq!(reopened.adapter_calls(), 0);
}

#[test]
fn b5_unknown_intent_is_a_safe_stop_without_dispatch() {
    let unknown = effect_key("unknown-intent");
    let mut wal = LocalB5Wal::new();
    assert_eq!(
        wal.begin_dispatch(&unknown, /*attempt*/ 1, fence(/*generation*/ 11)),
        Err(B5Error::UnknownIntent)
    );
    assert_eq!(wal.durable_record_count(), 0);
    assert_eq!(wal.adapter_calls(), 0);

    // Also exercise the serialized recovery path.  The marker is deliberately
    // re-hashed with the same field order as the private B5 record enum so the
    // semantic UnknownIntent check is reached after chain validation.
    let original = intent("unknown-recovery", /*generation*/ 11);
    let mut wal = LocalB5Wal::new();
    wal.append_intent(original.clone()).expect("intent");
    wal.crash_after_call(
        &original.effect_key,
        /*attempt*/ 1,
        original.fence.clone(),
    )
    .expect("crash boundary");
    let mut snapshot: serde_json::Value =
        serde_json::from_slice(&wal.durable_snapshot()).expect("snapshot json");
    let previous = Sha256Digest::parse(
        snapshot[0]["record_digest"]
            .as_str()
            .expect("previous digest")
            .to_string(),
    )
    .expect("previous digest parses");
    let unknown_key = effect_key("missing-recovery-intent");
    let marker = DispatchAttemptMarker::DispatchAttemptStarted {
        effect_key: unknown_key.clone(),
        idempotency_key: original.idempotency_key.clone(),
        payload_sha256: original.payload_sha256.clone(),
        attempt: 1,
        fence: original.fence.clone(),
    };
    let record_digest = Sha256Digest::for_bytes(
        &serde_json::to_vec(&(2_u64, Some(&previous), &marker)).expect("record bytes"),
    );
    snapshot[1]["kind"]["DispatchAttemptStarted"]["effect_key"] =
        serde_json::Value::String(unknown_key.as_str().to_string());
    let record_digest_text = record_digest.as_str().to_string();
    snapshot[1]["record_digest"] = serde_json::Value::String(record_digest_text.clone());
    snapshot[1]["fsync_witness"]["commit_digest"] = serde_json::Value::String(record_digest_text);
    let tampered = serde_json::to_vec(&snapshot).expect("tampered snapshot");
    assert_eq!(
        LocalB5Wal::recover_snapshot(&tampered),
        B5RecoveryAction::SafeStop(B5Error::UnknownIntent)
    );
}

#[test]
fn b5_payload_conflict_and_stale_fence_do_not_append_records() {
    let first = delivery("one");
    let mut wal = LocalB5Wal::new();
    assert_eq!(
        wal.enqueue_outbox(first.clone()),
        Ok(B5AppendDisposition::Inserted)
    );
    let count = wal.durable_record_count();

    let mut conflict = first.clone();
    conflict.outbox_id = "outbox:conflict".to_string();
    conflict.payload_sha256 = digest("different-payload");
    assert_eq!(wal.enqueue_outbox(conflict), Err(B5Error::OutboxConflict));
    assert_eq!(wal.durable_record_count(), count);

    let mut stale = first;
    stale.outbox_id = "outbox:stale".to_string();
    stale.fence = fence(/*generation*/ 12);
    assert_eq!(wal.enqueue_outbox(stale), Err(B5Error::StaleFence));
    assert_eq!(wal.durable_record_count(), count);
}

#[test]
fn qualification_feature_keeps_b4_and_b5_authority_flags_false() {
    const {
        assert!(authbus_b4::AUTHBUS_B4_QUALIFICATION_ONLY);
        assert!(!authbus_b4::AUTHBUS_B4_AUTHORITY);
        assert!(!authbus_b4::AUTHBUS_B4_PRODUCTION_CALLER);
        assert!(!authbus_b4::AUTHBUS_B4_PRODUCTION_WRITER);
        assert!(!authbus_b4::AUTHBUS_B4_EFFECT_AUTHORITY);
        assert!(!authbus_b4::AUTHBUS_B4_OPERATOR_ACCEPTANCE);
        assert!(!authbus_b4::AUTHBUS_B4_PROMOTION);
        assert!(!authbus_b4::AUTHBUS_B4_G5_ALLOWED);
        assert!(!authbus_b4::AUTHBUS_B4_EXECUTE_ALLOWED);

        assert!(authbus_b5::AUTHBUS_B5_QUALIFICATION_ONLY);
        assert!(!authbus_b5::AUTHBUS_B5_AUTHORITY);
        assert!(!authbus_b5::AUTHBUS_B5_PRODUCTION_CALLER);
        assert!(!authbus_b5::AUTHBUS_B5_PRODUCTION_WRITER);
        assert!(!authbus_b5::AUTHBUS_B5_EFFECT_AUTHORITY);
        assert!(!authbus_b5::AUTHBUS_B5_OPERATOR_ACCEPTANCE);
        assert!(!authbus_b5::AUTHBUS_B5_PROMOTION);
        assert!(!authbus_b5::AUTHBUS_B5_G5_ALLOWED);
        assert!(!authbus_b5::AUTHBUS_B5_EXECUTE_ALLOWED);
    }
}
