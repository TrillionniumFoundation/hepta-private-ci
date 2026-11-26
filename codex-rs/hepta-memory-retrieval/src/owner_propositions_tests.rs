use super::*;
use crate::product::*;
use crate::*;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;

fn digest(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}
fn id(text: &str) -> StableId {
    StableId::new(text).expect("id")
}
fn revision(value: u64) -> Revision {
    Revision::new(value).expect("revision")
}
fn fixture(
    second_score: FixedQ32,
) -> (
    MemoryCueV1,
    RetrievalPolicyV1,
    ValidatedCandidateSetV1,
    EngramSnapshotV1,
    EngramDynamicsPolicyV1,
) {
    let policy = RetrievalPolicyV1 {
        policy_id: id("policy:owner-claims"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        }],
        maximum_results: 2,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    };
    let d = digest("external-owner");
    let key = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:owner"),
        purpose_id: id("purpose:owner"),
        memory_ledger_frontier: 3,
        source_ledger_frontier: 4,
        tombstone_frontier: 1,
        knowledge_fact_frontier: 2,
        knowledge_graph_generation: Generation::new(1).expect("generation"),
        compact_checkpoint_generation: Generation::new(1).expect("generation"),
        prompt_registry_revision: revision(1),
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: d,
        authority_epoch: 1,
        model_digest: d,
        tokenizer_digest: d,
        template_digest: d,
        tool_schema_digest: d,
    })
    .expect("key");
    let generation = key.vector_digest;
    let cue = compile_cue(id("cue:owner"), d, d, d, key, d).expect("cue");
    let candidates = (1..=2)
        .map(|n| RetrievalChannelCandidateV1 {
            record: MemoryRecord {
                record_id: id(&format!("memory:{n}")),
                revision: revision(1),
                kind: MemoryKind::Fact,
                content_digest: digest(&format!("content:{n}")),
                predecessor_digest: None,
                citations: Vec::new(),
                state: RecordState::Live,
            },
            channel: RetrievalChannelV1::Lexical,
            channel_rank: n,
            normalized_score: if n == 1 { FixedQ32::ONE } else { second_score },
            ood: ProbabilityQ32::ZERO,
            support_digest: digest(&format!("original-support:{n}")),
            contradiction_group_digest: None,
            generation_vector_digest: generation,
        })
        .collect::<Vec<_>>();
    let nodes = candidates
        .iter()
        .map(|c| EngramNodeV1 {
            node_id: c.record.record_id.clone(),
            population: EngramPopulationV1::SemanticConcept,
            support: vec![EngramSupportV1 {
                record_id: c.record.record_id.clone(),
                record_revision: c.record.revision,
            }],
            threshold: FixedQ32::ZERO,
            confidence: ProbabilityQ32::ONE,
            generation_vector_digest: generation,
        })
        .collect();
    let graph = EngramSnapshotV1::new(generation, d, nodes, Vec::new()).expect("graph");
    let batch = RetrievalGeneratorBatchV1 {
        receipt: RetrievalGeneratorReceiptV1::new(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            generation,
            d,
            2,
            RetrievalSourceCompletenessV1::Exhausted,
        )
        .expect("receipt"),
        candidates,
    };
    let completeness = RetrievalCompletenessPolicyV1::new(vec![RetrievalCompletenessPolicyRowV1 {
        generator: RetrievalGeneratorOwnerV1::CognitiveLexical,
        on_limit_reached: IncompleteSourceActionV1::Degrade,
        on_unavailable: IncompleteSourceActionV1::FailClosed,
    }])
    .expect("completeness");
    let input = ValidatedCandidateSetV1::new(
        GeneratedCandidateInputV1::new(vec![batch]).expect("input"),
        &completeness,
    )
    .expect("admission");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    dynamics.minimum_activation = FixedQ32::ZERO;
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    (cue, policy, input, graph, dynamics)
}
fn evidence(
    input: &ValidatedCandidateSetV1,
    n: usize,
    name: &str,
    polarity: PropositionPolarityV2,
) -> OwnerPropositionEvidenceV2 {
    let record = &input.input().batches[0].candidates[n].record;
    OwnerPropositionEvidenceV2::new(
        record.record_id.clone(),
        record.revision,
        record.record_digest(),
        ContradictionEvidenceV2::new(
            digest(name),
            input.input().batches[0].receipt.generation_vector_digest,
            polarity,
        )
        .expect("claim"),
        digest(&format!("owner-original:{n}:{name}:{polarity:?}")),
    )
    .expect("evidence")
}
fn run(
    f: &(
        MemoryCueV1,
        RetrievalPolicyV1,
        ValidatedCandidateSetV1,
        EngramSnapshotV1,
        EngramDynamicsPolicyV1,
    ),
    claims: &[OwnerPropositionEvidenceV2],
) -> Result<ProductRecallWithPropositionsV2, ProductRecallErrorV1> {
    let work = RecallWorkControlV1::bounded(
        std::time::Instant::now() + std::time::Duration::from_secs(30),
        100_000,
    );
    recall_product_with_owner_propositions_v2(&f.0, &f.1, &f.2, claims, &f.3, &f.4, &work)
}
#[test]
fn complete_multi_assertion_veto_preserves_original_v1_packet_and_action() {
    let f = fixture(FixedQ32::ONE);
    // Three claims on a single-channel record exceed V1's one slot; no claims
    // are stuffed into that union and no channels/ranks are manufactured.
    let claims = vec![
        evidence(&f.2, 0, "unrelated", PropositionPolarityV2::Affirmed),
        evidence(&f.2, 0, "overlap", PropositionPolarityV2::Affirmed),
        evidence(&f.2, 0, "extra", PropositionPolarityV2::Denied),
        evidence(&f.2, 1, "overlap", PropositionPolarityV2::Denied),
    ];
    let original = run(&f, &[]).expect("original");
    let result = run(&f, &claims).expect("multi assertions");
    assert_eq!(result.product, original.product);
    assert_eq!(result.assignment, original.assignment);
    result
        .product
        .recall
        .as_ref()
        .expect("recall")
        .validate()
        .expect("valid V1");
    let semantic = result.semantic.expect("semantic");
    assert_eq!(semantic.conflict_digests(), &[digest("overlap")]);
    assert_eq!(
        semantic.disposition(),
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
    assert!(semantic.selected_candidates().is_empty());
    assert_eq!(
        original
            .assignment
            .expect("assignment")
            .selected_candidates
            .len(),
        2
    );
}
#[test]
fn canonical_order_and_all_original_supports_bind_semantic_decision() {
    let f = fixture(FixedQ32::ONE);
    let claims = vec![
        evidence(&f.2, 0, "a", PropositionPolarityV2::Affirmed),
        evidence(&f.2, 1, "b", PropositionPolarityV2::Denied),
    ];
    let original = run(&f, &claims).expect("original");
    let mut swapped = claims;
    swapped.reverse();
    assert_eq!(run(&f, &swapped).expect("permutation"), original);
    swapped[0].source_evidence_digest = digest("changed original support");
    let changed = run(&f, &swapped).expect("changed support");
    assert_eq!(changed.product, original.product);
    assert_ne!(
        changed.semantic.expect("changed").binding_digest(),
        original.semantic.expect("original").binding_digest()
    );
}
#[test]
fn absent_revision_record_digest_generation_duplicates_reject_before_omission() {
    let f = fixture(FixedQ32::ONE);
    let claim = evidence(&f.2, 0, "a", PropositionPolarityV2::Affirmed);
    let mut bad = claim.clone();
    bad.record_id = id("memory:absent");
    assert!(run(&f, &[bad]).is_err());
    let mut bad = claim.clone();
    bad.revision = revision(2);
    assert!(run(&f, &[bad]).is_err());
    let mut bad = claim.clone();
    bad.record_digest = digest("other bytes");
    assert!(run(&f, &[bad]).is_err());
    let mut bad = claim.clone();
    bad.claim = ContradictionEvidenceV2::new(
        digest("a"),
        digest("other generation"),
        PropositionPolarityV2::Affirmed,
    )
    .expect("claim");
    assert!(run(&f, &[bad]).is_err());
    assert!(run(&f, &[claim.clone(), claim]).is_err());
    let claim = evidence(&f.2, 0, "a", PropositionPolarityV2::Affirmed);
    assert!(run(&f, &vec![claim; 4097]).is_err());
}
#[test]
fn excluded_score_record_cannot_poison_conflict_but_evidence_remains_bound() {
    let mut f = fixture(FixedQ32::from_raw(1_i64 << 28));
    f.1.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    let claims = vec![
        evidence(&f.2, 0, "a", PropositionPolarityV2::Affirmed),
        evidence(&f.2, 1, "a", PropositionPolarityV2::Denied),
    ];
    let result = run(&f, &claims).expect("policy admission");
    let semantic = result.semantic.expect("semantic");
    assert!(semantic.conflict_digests().is_empty());
    assert_eq!(semantic.selected_candidates().len(), 1);
    assert_ne!(
        semantic.evidence_digest(),
        run(&f, &claims[..1])
            .expect("one")
            .semantic
            .expect("one")
            .evidence_digest()
    );
}
#[test]
fn conflict_report_is_not_polarity_and_native_posture_stays_explicit() {
    let mut f = fixture(FixedQ32::ONE);
    let claims = vec![
        evidence(&f.2, 0, "a", PropositionPolarityV2::Affirmed),
        evidence(&f.2, 1, "a", PropositionPolarityV2::ConflictReported),
    ];
    let result = run(&f, &claims).expect("reported conflict");
    assert!(
        result
            .semantic
            .expect("semantic")
            .conflict_digests()
            .is_empty()
    );
    f.1.abstain_on_contradiction = false;
    f.4.contradiction_forces_abstention = false;
    let claims = vec![
        evidence(&f.2, 0, "a", PropositionPolarityV2::Affirmed),
        evidence(&f.2, 1, "a", PropositionPolarityV2::Denied),
    ];
    let semantic = run(&f, &claims)
        .expect("posture")
        .semantic
        .expect("semantic");
    assert_eq!(semantic.conflict_digests().len(), 1);
    assert_eq!(semantic.selected_candidates().len(), 2);
}
#[test]
fn cancellation_never_returns_partial_semantic_decision() {
    let f = fixture(FixedQ32::ONE);
    let work = RecallWorkControlV1::bounded(
        std::time::Instant::now() - std::time::Duration::from_secs(1),
        100_000,
    );
    assert!(
        recall_product_with_owner_propositions_v2(&f.0, &f.1, &f.2, &[], &f.3, &f.4, &work)
            .is_err()
    );
}

#[test]
fn semantic_delivery_retains_hnmf_order_not_assignment_identity_order() {
    let mut f = fixture(FixedQ32::ONE);
    let mut input = f.2.input().clone();
    input.batches[0].candidates[0].normalized_score = FixedQ32::from_raw(1_i64 << 29);
    let completeness = RetrievalCompletenessPolicyV1::new(vec![RetrievalCompletenessPolicyRowV1 {
        generator: RetrievalGeneratorOwnerV1::CognitiveLexical,
        on_limit_reached: IncompleteSourceActionV1::Degrade,
        on_unavailable: IncompleteSourceActionV1::FailClosed,
    }])
    .expect("completeness");
    f.2 = ValidatedCandidateSetV1::new(input, &completeness).expect("input");
    let result = run(&f, &[]).expect("ranking");
    let semantic = result.semantic.expect("semantic");
    assert_eq!(semantic.selected_candidates()[0].record_id, id("memory:2"));
    assert_eq!(
        result
            .assignment
            .expect("canonical assignment")
            .selected_candidates[0]
            .record_id,
        id("memory:1")
    );
    assert_eq!(
        result
            .product
            .recall
            .expect("original ranking")
            .packet
            .selections[0]
            .record_id,
        id("memory:2")
    );
}
