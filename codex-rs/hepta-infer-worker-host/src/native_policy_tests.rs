use super::*;

use codex_hepta_contracts::AUTHBUS_B2_CONTRACT_SCHEMA_VERSION;
use codex_hepta_contracts::Principal;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SubjectRef;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn subject() -> SubjectRef {
    SubjectRef::new(
        "tenant-inference",
        "workspace-inference",
        "agent-inference",
        "hepta-infer-worker",
        7,
    )
    .expect("subject")
}

fn quota(now: u64) -> QuotaReservation {
    QuotaReservation {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        reservation_id: "reservation:inference-1".to_string(),
        operation_sha256: digest("operation:inference"),
        decision_sha256: digest("decision:inference"),
        subject: subject(),
        resource_sha256: digest("resource:inference"),
        reserved_requests: 2,
        reserved_tokens: 1024,
        reserved_concurrency: 1,
        reserved_day_budget: 1024,
        state: QuotaReservationState::Held,
        expected_revision: 1,
        revision: 1,
        authority_epoch: 9,
        owner_epoch: 3,
        generation: 7,
        fencing_token_sha256: digest("fence:inference"),
        not_before_unix_seconds: now.saturating_sub(1),
        expires_at_unix_seconds: now + 60,
        authority: false,
    }
}

fn resource(now: u64, quota: &QuotaReservation) -> ResourceAdvertisement {
    ResourceAdvertisement {
        schema_version: AUTHBUS_B2_CONTRACT_SCHEMA_VERSION,
        advertisement_id: "advertisement:inference-1".to_string(),
        resource_id: "resource:inference-1".to_string(),
        owner: Principal::new("owner:inference-platform").expect("owner"),
        subject: Some(subject()),
        provider_id: "openai".to_string(),
        model: Some("gpt-test".to_string()),
        resource_sha256: digest("resource:inference"),
        quota_sha256: quota.digest().expect("quota digest"),
        capability_sha256: vec![digest("capability:inference")],
        state: ResourceAdvertisementState::Available,
        revision: 1,
        authority_epoch: 9,
        owner_epoch: 3,
        generation: 7,
        fencing_token_sha256: digest("fence:inference"),
        not_before_unix_seconds: now.saturating_sub(1),
        expires_at_unix_seconds: now + 60,
        authority: false,
    }
}

#[test]
fn admission_binding_binds_quota_resource_and_generation() {
    let now = 2_000_000_000;
    let policy = NativeExecutionPolicy {
        quota: quota(now),
        resource: resource(now, &quota(now)),
    };

    let binding = policy
        .admission_binding(now, "agent-inference", 7, "gpt-test", 512, 100)
        .expect("valid admission");

    assert_eq!(binding.quota.reserved_requests, 2);
    assert_eq!(binding.quota.reserved_tokens, 1024);
    assert_eq!(binding.quota.reserved_concurrency, 1);
    assert_eq!(binding.quota.reserved_day_budget, 1024);
    assert_eq!(binding.quota.authority_epoch, 9);
    assert_eq!(binding.resource.provider_id, "openai");
    assert_eq!(binding.resource.model, "gpt-test");
    assert_eq!(binding.resource.generation, 7);
}

#[test]
fn admission_binding_rejects_token_budget_exhaustion() {
    let now = 2_000_000_000;
    let policy = NativeExecutionPolicy {
        quota: quota(now),
        resource: resource(now, &quota(now)),
    };

    assert!(matches!(
        policy.admission_binding(now, "agent-inference", 7, "gpt-test", 1025, 100),
        Err(NativePolicyError::Invalid(
            "quota/resource authority mismatch"
        ))
    ));
}

#[test]
fn admission_binding_rejects_provider_subject_drift() {
    let now = 2_000_000_000;
    let quota = quota(now);
    let mut resource = resource(now, &quota);
    resource.generation = 8;
    let policy = NativeExecutionPolicy { quota, resource };

    assert!(matches!(
        policy.admission_binding(now, "agent-inference", 7, "gpt-test", 512, 100),
        Err(NativePolicyError::Invalid("subject or generation mismatch"))
    ));
}

#[test]
fn admission_binding_rejects_missing_resource_subject() {
    let now = 2_000_000_000;
    let quota = quota(now);
    let mut resource = resource(now, &quota);
    resource.subject = None;
    let policy = NativeExecutionPolicy { quota, resource };

    assert!(matches!(
        policy.admission_binding(now, "agent-inference", 7, "gpt-test", 512, 100),
        Err(NativePolicyError::Invalid("subject or generation mismatch"))
    ));
}

#[test]
fn admission_binding_rejects_cross_contract_digest_drift() {
    let now = 2_000_000_000;
    let quota = quota(now);
    let mut resource = resource(now, &quota);
    resource.quota_sha256 = digest("different-quota");
    let policy = NativeExecutionPolicy { quota, resource };

    assert!(matches!(
        policy.admission_binding(now, "agent-inference", 7, "gpt-test", 512, 100),
        Err(NativePolicyError::Invalid("quota/resource digest mismatch"))
    ));
}

#[test]
fn admission_binding_rejects_economic_budget_exhaustion() {
    let now = 2_000_000_000;
    let quota = quota(now);
    let resource = resource(now, &quota);
    let policy = NativeExecutionPolicy { quota, resource };

    assert!(matches!(
        policy.admission_binding(now, "agent-inference", 7, "gpt-test", 512, 1025),
        Err(NativePolicyError::Invalid(
            "quota/resource authority mismatch"
        ))
    ));
}
