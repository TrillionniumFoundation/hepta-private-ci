//! Whole canonical policy and actual G receipt are signed together. Synthetic
//! payloads only; no installed credentials or production model invocation.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1;
use codex_hepta_agent_components::types::AuthorityPosture;
use codex_hepta_agent_components::types::StableId;

#[test]
fn full_policy_and_actual_generator_receipt_change_the_frozen_identity() {
    let input = serde_json::json!({
        "envelopeId":"actual-window", "baseCommit":"1".repeat(40), "baseTree":"2".repeat(40),
        "objectiveDigest":Digest32::of_bytes(b"objective").to_string(),
        "grammarDigest":Digest32::of_bytes(b"grammar").to_string(),
        "allowedPaths":["original/store"], "deniedAuthorities":["promote"],
        "maximumFiles":2, "maximumBytes":4096, "maximumCandidates":2, "wallTimeMicros":1000,
        "computeBudget":{"profile":"hepta.iteration-compute-budget.v1", "maximumParallelSandboxes":1,
            "maximumMemoryBytes":4096, "maximumProcesses":2},
        "mandatoryChecks":["original/native-receipt"], "expiresUnixMs":1000,
    });
    let canonical =
        crate::CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(&input).expect("json"))
            .expect("original canonical owner");
    let envelope = IterationEnvelopeV1 {
        envelope_id: StableId::new("actual-window").expect("id"),
        base_commit: Digest32::of_bytes("1".repeat(40).as_bytes()),
        base_tree: Digest32::of_bytes("2".repeat(40).as_bytes()),
        objective_digest: Digest32::of_bytes(b"objective"),
        grammar_digest: Digest32::of_bytes(b"grammar"),
        maximum_files: 2,
        maximum_diff_bytes: 4096,
        maximum_candidates: 2,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: 1,
    };
    let mut journal = round::RoundJournal::default();
    let round = journal
        .reserve(
            StableId::new("actual.goal").expect("goal"),
            &canonical,
            &envelope,
            1,
        )
        .expect("original round");
    let assessment = SelfIterationModelAssessmentV1 {
        request_id: round
            .model_request_id(SelfIterationModelRoleV1::Generator, None)
            .expect("id"),
        role: SelfIterationModelRoleV1::Generator,
        envelope_digest: Digest32::of_bytes(b"original-execution-envelope"),
        candidate_digest: None,
        model_output: "bounded actual output".into(),
        native_run_digest: Digest32::of_bytes(b"actual-native-terminal"),
        authority: AuthorityPosture::DENY_ALL,
    };
    let legacy = b"hepta.agentd.self-iteration-candidate.v1\0original-execution";
    let frozen = canonical_frozen_payload(&canonical, &round, &assessment, legacy).expect("v2");
    let start = b"hepta.agentd.self-iteration-candidate.v2\0".len() + 8;
    assert_eq!(
        &frozen[start..start + canonical.canonical_bytes().len()],
        canonical.canonical_bytes()
    );
    assert!(frozen.ends_with(legacy));
    let mut changed_policy = input;
    changed_policy["allowedPaths"] = serde_json::json!(["another/store"]);
    let changed = crate::CanonicalIterationEnvelopeV1::decode(
        &serde_json::to_vec(&changed_policy).expect("json"),
    )
    .expect("changed canonical policy");
    assert_ne!(
        Digest32::of_bytes(&frozen),
        Digest32::of_bytes(
            &canonical_frozen_payload(&changed, &round, &assessment, legacy).expect("v2")
        )
    );
    let mut another_round = assessment.clone();
    another_round.request_id = StableId::new("actual.goal.round.2.generator").expect("id");
    assert_ne!(
        Digest32::of_bytes(&frozen),
        Digest32::of_bytes(
            &canonical_frozen_payload(&canonical, &round, &another_round, legacy).expect("v2")
        )
    );
    another_round = assessment;
    another_round.native_run_digest = Digest32::of_bytes(b"another-real-terminal");
    assert_ne!(
        Digest32::of_bytes(&frozen),
        Digest32::of_bytes(
            &canonical_frozen_payload(&canonical, &round, &another_round, legacy).expect("v2")
        )
    );
}
