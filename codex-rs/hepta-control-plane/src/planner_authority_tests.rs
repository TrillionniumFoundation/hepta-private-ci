use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::ExecutionAuthorityErrorV1;
use super::claim_execution_grant_v1;
use super::execution_grant_scope_digest_v1;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::canonical_resource_profile_digest;
use crate::collect_snapshot;
use crate::finalize_plan;
use crate::prepare_plan;
use crate::request_execution_grants;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn request_set() -> crate::GrantRequestSetV1 {
    let generation = Generation::new(1).expect("generation");
    let snapshot = collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 50,
            expires_at_micros: 500,
            required_owner_ids: vec![id("planner")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("planner"),
            revision: Revision::new(1).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            observed_at_micros: 90,
            expires_at_micros: 500,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }],
    )
    .expect("snapshot");
    let reservations = vec![ResourceReservationV1 {
        axis: id("compute"),
        endowment: q32(10),
        essential_floor: q32(2),
    }];
    let prepared = prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("authority-plan"),
            now_micros: 100,
            deadline_micros: 400,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: canonical_resource_profile_digest(&reservations)
                .expect("resource profile"),
            candidates: vec![
                PlanCandidateV1 {
                    candidate_id: id("abstain"),
                    operation_id: id("operation-abstain"),
                    plan_digest: digest("plan:abstain"),
                    required_owner_ids: vec![id("planner")],
                    final_payload_digests: vec![],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: FixedQ32::ZERO,
                    }],
                },
                PlanCandidateV1 {
                    candidate_id: id("work"),
                    operation_id: id("operation-work"),
                    plan_digest: digest("plan:work"),
                    required_owner_ids: vec![id("planner")],
                    final_payload_digests: vec![digest("payload:work")],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: q32(1),
                    }],
                },
            ],
            resource_reservations: reservations,
        },
    )
    .expect("prepared");
    let evaluation = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest(),
        body_generation: prepared.body_generation(),
        evaluation_policy_digest: prepared.evaluation_policy_digest(),
        evaluation_digest: digest("ndu-evaluation"),
        evaluated_candidate_ids: vec![id("abstain"), id("work")],
        rejected_candidate_ids: vec![],
        pareto_candidate_ids: vec![id("work")],
        advisory_candidate_id: Some(id("work")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    })
    .expect("evaluation");
    let receipt = finalize_plan(&snapshot, &prepared, &evaluation, 110).expect("receipt");
    request_execution_grants(&snapshot, &prepared, &receipt, 120).expect("requests")
}

fn signed_grant(
    signing: &SigningKey,
    binding: FinalUseBinding,
    grant_id: &str,
    nonce_byte: u8,
) -> SignedFinalUseGrant {
    let now_ms = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("millis");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "control-authority".to_string(),
        authority_epoch: 7,
        grant_id: grant_id.to_string(),
        nonce: [nonce_byte; 32],
        binding,
        not_before_unix_ms: now_ms.saturating_sub(1_000),
        expires_at_unix_ms: now_ms + 60_000,
    };
    let signature = signing.sign(&grant.signing_bytes().expect("signing bytes"));
    SignedFinalUseGrant {
        grant,
        signature: signature.to_bytes().to_vec(),
    }
}

fn authority(
    directory: &std::path::Path,
    signing: &SigningKey,
) -> FinalUseAuthority {
    FinalUseAuthority::open_state_dir(
        directory,
        "control-authority".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority")
}

fn binding(set: &crate::GrantRequestSetV1, subject: &str, destination: &str) -> FinalUseBinding {
    let request = &set.requests()[0];
    FinalUseBinding {
        subject_id: subject.to_string(),
        destination_id: destination.to_string(),
        request_sha256: *set.request_set_digest().as_array(),
        scope_sha256: *execution_grant_scope_digest_v1(request).as_array(),
        payload_sha256: *request.final_payload_digest.as_array(),
    }
}

#[test]
fn independent_authority_claim_revalidates_at_effect_boundary() {
    let set = request_set();
    let temp = tempfile::tempdir().expect("tempdir");
    let signing = SigningKey::from_bytes(&[7; 32]);
    let authority = authority(temp.path(), &signing);
    let expected = binding(&set, "agent-1", "provider-instance-1");
    let signed = signed_grant(&signing, expected, "grant-1", 1);

    let claimed = claim_execution_grant_v1(
        &authority,
        &set,
        0,
        "agent-1",
        "provider-instance-1",
        &signed,
    )
    .expect("independent claim");
    let observed = claimed
        .with_verified_use(&authority, |request| request.final_payload_digest)
        .expect("final revalidation");
    assert_eq!(observed, digest("payload:work"));
}

#[test]
fn payload_or_scope_drift_rejects_before_nonce_claim() {
    let set = request_set();
    let temp = tempfile::tempdir().expect("tempdir");
    let signing = SigningKey::from_bytes(&[8; 32]);
    let authority = authority(temp.path(), &signing);
    let mut wrong = binding(&set, "agent-1", "provider-instance-1");
    wrong.scope_sha256 = *digest("wrong-scope").as_array();
    let signed = signed_grant(&signing, wrong, "grant-wrong", 2);

    assert_eq!(
        claim_execution_grant_v1(
            &authority,
            &set,
            0,
            "agent-1",
            "provider-instance-1",
            &signed,
        )
        .expect_err("scope drift must reject"),
        ExecutionAuthorityErrorV1::BindingMismatch
    );

    let exact = binding(&set, "agent-1", "provider-instance-1");
    let corrected = signed_grant(&signing, exact, "grant-correct", 2);
    assert!(
        claim_execution_grant_v1(
            &authority,
            &set,
            0,
            "agent-1",
            "provider-instance-1",
            &corrected,
        )
        .is_ok(),
        "failed binding validation must not consume an unrelated valid grant"
    );
}

#[test]
fn authority_nonce_is_single_use_even_when_effect_is_not_dispatched() {
    let set = request_set();
    let temp = tempfile::tempdir().expect("tempdir");
    let signing = SigningKey::from_bytes(&[9; 32]);
    let authority = authority(temp.path(), &signing);
    let exact = binding(&set, "agent-1", "provider-instance-1");
    let signed = signed_grant(&signing, exact, "grant-single-use", 3);

    let _claimed = claim_execution_grant_v1(
        &authority,
        &set,
        0,
        "agent-1",
        "provider-instance-1",
        &signed,
    )
    .expect("first claim");

    assert_eq!(
        claim_execution_grant_v1(
            &authority,
            &set,
            0,
            "agent-1",
            "provider-instance-1",
            &signed,
        )
        .expect_err("nonce replay must reject"),
        ExecutionAuthorityErrorV1::Authority(FinalUseError::AlreadyClaimed)
    );
}
