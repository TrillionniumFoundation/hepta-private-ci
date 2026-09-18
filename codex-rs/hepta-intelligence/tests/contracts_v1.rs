use codex_hepta_intelligence::IntelligenceContractErrorV1;
use codex_hepta_intelligence::IntelligenceHostEnvelopeInputV1;
use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
use codex_hepta_intelligence::LegalActionCandidateSetInputV1;
use codex_hepta_intelligence::LegalActionCandidateSetV1;
use codex_hepta_intelligence::LegalActionCandidateV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn legal_candidate_set_is_canonical_under_input_reordering() {
    let first = LegalActionCandidateV1 {
        candidate_id: id("action:a"),
        action_digest: digest("action-a"),
        support_digest: digest("support-a"),
    };
    let second = LegalActionCandidateV1 {
        candidate_id: id("action:b"),
        action_digest: digest("action-b"),
        support_digest: digest("support-b"),
    };
    let build = |candidates| LegalActionCandidateSetInputV1 {
        candidate_set_id: id("candidate-set"),
        state_digest: digest("state"),
        generator_id: id("intelligence.control"),
        grammar_digest: digest("grammar"),
        candidates,
        support_floor_ppm: 100,
    };
    let left = LegalActionCandidateSetV1::new(build(vec![second.clone(), first.clone()]))
        .expect("candidate set");
    let right = LegalActionCandidateSetV1::new(build(vec![first, second])).expect("candidate set");
    assert_eq!(left, right);
    left.validate().expect("candidate set validation");
}

#[test]
fn legal_candidate_set_rejects_duplicate_identity() {
    let candidate = LegalActionCandidateV1 {
        candidate_id: id("action:a"),
        action_digest: digest("action-a"),
        support_digest: digest("support-a"),
    };
    assert_eq!(
        LegalActionCandidateSetV1::new(LegalActionCandidateSetInputV1 {
            candidate_set_id: id("candidate-set"),
            state_digest: digest("state"),
            generator_id: id("intelligence.control"),
            grammar_digest: digest("grammar"),
            candidates: vec![candidate.clone(), candidate],
            support_floor_ppm: 0,
        }),
        Err(IntelligenceContractErrorV1::DuplicateCandidate(
            "action:a".to_string()
        ))
    );
}

#[test]
fn host_envelope_is_authority_free_and_digest_bound() {
    let envelope = IntelligenceHostEnvelopeV1::new(IntelligenceHostEnvelopeInputV1 {
        run_id: id("run:1"),
        request_digest: digest("request"),
        snapshot_digest: digest("snapshot"),
        objective_digest: digest("objective"),
        legal_candidate_set_digest: digest("candidate-set"),
        utility_digest: digest("utility"),
        evaluation_digest: digest("evaluation"),
        intuition_digest: digest("intuition"),
        context_digest: digest("context"),
        composition_trace_digest: digest("composition-trace"),
    })
    .expect("host envelope");
    assert!(!envelope.effect_authority);
    assert!(!envelope.authority.grants_any());
    envelope.validate().expect("host envelope validation");
}
