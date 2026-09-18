use super::*;

use crate::test_support::TestAuthority;
use crate::test_support::admission_request;
use crate::test_support::digest;
use crate::test_support::factor_with_id;
use crate::test_support::id;
use crate::test_support::registry;

#[test]
fn unauthenticated_admission_fails_closed() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    assert_eq!(
        registry.admit_factor(&id("factor:1"), &id("reviewer:1"), digest("evidence")),
        Err(Error::AuthenticatedAdmissionRequired)
    );
    assert_eq!(
        registry.factor(&id("factor:1")).expect("factor").lifecycle,
        Lifecycle::Draft
    );
}

#[test]
fn external_material_cannot_be_admitted_even_with_a_valid_grant() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::ExternalUntrusted))
        .expect("register external draft");
    let authority = TestAuthority::new();
    let request = admission_request("factor:1", "reviewer:1");
    let token = authority.token(&registry, &request, 1);
    assert_eq!(
        registry.admit_factor_authorized(&authority.authority, token, request),
        Err(Error::ExternalSelfAdmission)
    );
    assert!(registry.admission(&id("factor:1")).is_none());
}

#[test]
fn signed_admission_persists_evidence_scope_and_immutable_history() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    let authority = TestAuthority::new();
    let request = admission_request("factor:1", "reviewer:1");
    let expected_evidence = request.evidence_digest;
    let expected_scope = request.reviewed_scope_digest;
    let token = authority.token(&registry, &request, 2);
    let receipt = registry
        .admit_factor_authorized(&authority.authority, token, request)
        .expect("authorized admission");
    assert!(!receipt.authority.grants_any());
    let admission = registry.admission(&id("factor:1")).expect("admission");
    assert_eq!(admission.reviewer_id, id("reviewer:1"));
    assert_eq!(admission.evidence_digest, expected_evidence);
    assert_eq!(admission.reviewed_scope_digest, expected_scope);
    assert_eq!(admission.revision, receipt.revision);
    admission.validate().expect("admission digest");
    assert_eq!(registry.lifecycle_history().len(), 2);
    assert_eq!(
        registry.lifecycle_history()[1].kind,
        LifecycleEventKind::Admitted
    );
    assert_eq!(
        registry.lifecycle_history()[1].event_digest,
        registry.lifecycle_history()[1].compute_digest()
    );
    registry.validate_integrity().expect("registry integrity");
}

#[test]
fn signed_grant_is_bound_to_reviewer_scope_and_evidence() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    let authority = TestAuthority::new();
    let request = admission_request("factor:1", "reviewer:1");
    let token = authority.token(&registry, &request, 3);
    let mut drifted = request;
    drifted.reviewed_scope_digest = digest("other-scope");
    assert!(matches!(
        registry.admit_factor_authorized(&authority.authority, token, drifted),
        Err(Error::Authority(_))
    ));
    assert_eq!(
        registry.factor(&id("factor:1")).expect("factor").lifecycle,
        Lifecycle::Draft
    );
}

#[test]
fn proposer_cannot_self_review_even_with_signed_authority() {
    let mut registry = registry();
    let factor = factor_with_id("factor:1", FactorSource::GovernedInternal);
    let proposer = factor.proposer_id.clone();
    registry.register_factor(factor).expect("register factor");
    let authority = TestAuthority::new();
    let request = AdmissionRequest {
        factor_id: id("factor:1"),
        reviewer_id: proposer,
        evidence_digest: digest("evidence:self"),
        reviewed_scope_digest: digest("scope:self"),
    };
    let token = authority.token(&registry, &request, 4);
    assert_eq!(
        registry.admit_factor_authorized(&authority.authority, token, request),
        Err(Error::SelfReview)
    );
}

#[test]
fn new_digest_only_realizations_are_rejected_and_v2_payloads_are_required() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    let authority = TestAuthority::new();
    crate::test_support::admit(&mut registry, &authority, "factor:1", 51);
    let realization = PromptRealization {
        realization_id: id("realization:legacy"),
        factor_id: id("factor:1"),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        content_digest: digest("legacy-payload"),
        active: true,
    };
    assert_eq!(
        registry.register_realization(realization),
        Err(Error::PayloadRequired)
    );
    assert!(registry.realization(&id("realization:legacy")).is_none());
}

#[test]
fn revocation_cascades_is_terminal_and_keeps_reason_cutoff_history() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    let authority = TestAuthority::new();
    crate::test_support::admit(&mut registry, &authority, "factor:1", 5);
    let payload = b"revocation payload".to_vec();
    let binding = PromptRealizationBindingV2 {
        realization_id: id("realization:1"),
        factor_id: id("factor:1"),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(&payload),
        token_cost: 8,
        expires_unix_ms: None,
        predecessor_realization_id: None,
    };
    registry
        .register_realization_v2(binding.clone(), payload)
        .expect("register payload-backed realization");
    let reason = digest("reason:revoked");
    let receipt = registry
        .revoke_factor_with_reason(&id("factor:1"), &id("operator:1"), reason, 42)
        .expect("revoke");
    assert!(registry.revocation_frontier() > 0);
    assert_eq!(
        registry.factor(&id("factor:1")).expect("factor").lifecycle,
        Lifecycle::Revoked
    );
    assert!(
        !registry
            .realization(&binding.realization_id)
            .expect("realization")
            .active
    );
    let event = registry
        .lifecycle_history()
        .last()
        .expect("revocation event");
    assert_eq!(event.kind, LifecycleEventKind::Revoked);
    assert_eq!(event.reason_digest, Some(reason));
    assert_eq!(event.cutoff_unix_ms, Some(42));
    assert_eq!(event.revision, receipt.revision);
    assert_eq!(
        registry.revoke_factor_with_reason(&id("factor:1"), &id("operator:1"), reason, 43),
        Err(Error::InvalidTransition)
    );
    assert_eq!(
        registry.admit_factor(&id("factor:1"), &id("reviewer:2"), digest("evidence:2")),
        Err(Error::AuthenticatedAdmissionRequired)
    );
    registry.validate_integrity().expect("registry integrity");
}

#[test]
fn retirement_requires_reason_and_is_audited() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    let authority = TestAuthority::new();
    crate::test_support::admit(&mut registry, &authority, "factor:1", 6);
    assert_eq!(
        registry.retire_factor(&id("factor:1")),
        Err(Error::LifecycleReasonRequired)
    );
    let reason = digest("retirement-reason");
    registry
        .retire_factor_with_reason(&id("factor:1"), &id("operator:1"), reason)
        .expect("retire");
    let event = registry
        .lifecycle_history()
        .last()
        .expect("retirement event");
    assert_eq!(event.kind, LifecycleEventKind::Retired);
    assert_eq!(event.reason_digest, Some(reason));
    registry.validate_integrity().expect("registry integrity");
}

#[test]
fn conflicting_identity_is_rejected() {
    let mut registry = registry();
    let value = factor_with_id("factor:1", FactorSource::GovernedInternal);
    registry
        .register_factor(value.clone())
        .expect("insert factor");
    let mut drifted = value;
    drifted.content_digest = digest("drift");
    assert_eq!(
        registry.register_factor(drifted),
        Err(Error::FactorConflict("factor:1".to_string()))
    );
}

#[test]
fn exhausted_revision_keeps_factor_insertion_and_admission_atomic() {
    let mut registry = registry();
    let value = factor_with_id("factor:1", FactorSource::GovernedInternal);
    let maximum = Revision::new(u64::MAX).expect("maximum revision");
    registry.revision = maximum;
    let empty = registry.clone();
    assert_eq!(
        registry.register_factor(value.clone()),
        Err(Error::RevisionOverflow)
    );
    assert_eq!(registry, empty);

    registry.revision = Revision::new(1).expect("initial revision");
    registry
        .register_factor(value)
        .expect("register before exhaustion");
    registry.revision = maximum;
    let draft = registry.clone();
    let authority = TestAuthority::new();
    let request = admission_request("factor:1", "reviewer:1");
    let token = authority.token(&registry, &request, 7);
    assert_eq!(
        registry.admit_factor_authorized(&authority.authority, token, request),
        Err(Error::RevisionOverflow)
    );
    assert_eq!(registry, draft);
}
