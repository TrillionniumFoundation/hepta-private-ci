use std::fmt::Debug;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::final_use_binding_for_grant_request_v1;
use crate::GrantRequestV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn request() -> GrantRequestV1 {
    GrantRequestV1 {
        operation_id: id("operation"),
        candidate_id: id("candidate"),
        plan_digest: digest("plan"),
        final_payload_digest: digest("payload"),
        objective_digest: digest("objective"),
        snapshot_digest: digest("snapshot"),
        revocation_frontier_digest: digest("revocation"),
        expires_at_micros: 1_000,
    }
}

fn binding(
    request: &GrantRequestV1,
    subject: &StableId,
    destination: &StableId,
    scope: Digest32,
) -> FinalUseBinding {
    must(final_use_binding_for_grant_request_v1(
        request,
        subject,
        destination,
        scope,
    ))
}

#[test]
fn final_use_binding_changes_for_every_grant_request_dimension() {
    let request = request();
    let subject = id("subject");
    let destination = id("destination");
    let scope = digest("scope");
    let original = binding(&request, &subject, &destination, scope);

    let mut mutations = Vec::new();
    let mut changed = request.clone();
    changed.operation_id = id("different-operation");
    mutations.push(changed);
    let mut changed = request.clone();
    changed.candidate_id = id("different-candidate");
    mutations.push(changed);
    let mut changed = request.clone();
    changed.plan_digest = digest("different-plan");
    mutations.push(changed);
    let mut changed = request.clone();
    changed.final_payload_digest = digest("different-payload");
    mutations.push(changed);
    let mut changed = request.clone();
    changed.objective_digest = digest("different-objective");
    mutations.push(changed);
    let mut changed = request.clone();
    changed.snapshot_digest = digest("different-snapshot");
    mutations.push(changed);
    let mut changed = request.clone();
    changed.revocation_frontier_digest = digest("different-revocation");
    mutations.push(changed);
    let mut changed = request.clone();
    changed.expires_at_micros = 1_001;
    mutations.push(changed);

    for changed in mutations {
        let changed = binding(&changed, &subject, &destination, scope);
        assert_ne!(original.request_sha256, changed.request_sha256);
    }

    let changed_subject = binding(&request, &id("different-subject"), &destination, scope);
    assert_ne!(original.subject_id, changed_subject.subject_id);
    let changed_destination = binding(&request, &subject, &id("different-destination"), scope);
    assert_ne!(original.destination_id, changed_destination.destination_id);
    let changed_scope = binding(&request, &subject, &destination, digest("different-scope"));
    assert_ne!(original.scope_sha256, changed_scope.scope_sha256);

    let mut changed_payload = request;
    changed_payload.final_payload_digest = digest("another-payload");
    assert_ne!(
        original.payload_sha256,
        binding(&changed_payload, &subject, &destination, scope).payload_sha256
    );
}
