use codex_hepta_cognitive_types::consumer::CognitiveConsumerV1;
use codex_hepta_cognitive_types::consumer::ShadowComparisonStateV1;
use codex_hepta_cognitive_types::consumer::ShadowComparisonReceiptV1;
use codex_hepta_cognitive_types::contract::Validated;
use codex_hepta_cognitive_types::contract::validate_preserved_text_v1;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_cognitive_types::lane_c::MemoryWriteIntentV1 as LegacyMemoryWriteIntentV1;
use codex_hepta_cognitive_types::registry::decode_registered_wire_v1;
use codex_hepta_cognitive_types::strict::validate_json_pointer_v1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteReceiptV1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteRejectionCodeV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn seeded_digest(seed: u64, domain: &str) -> Digest32 {
    Digest32::of_parts(&[domain.as_bytes(), &seed.to_be_bytes()])
}

fn snapshot(seed: u64) -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:property"),
        purpose_id: id("purpose:property"),
        memory_ledger_frontier: seed.saturating_add(1),
        knowledge_fact_frontier: seed % 17,
        tombstone_frontier: seed % 11,
        source_ledger_frontier: seed % 23,
        knowledge_graph_generation: Generation::new(seed.saturating_add(1))
            .unwrap_or_else(|error| panic!("valid generation: {error}")),
        compact_checkpoint_generation: Generation::new((seed % 19).saturating_add(1))
            .unwrap_or_else(|error| panic!("valid generation: {error}")),
        prompt_registry_revision: Revision::new((seed % 29).saturating_add(1))
            .unwrap_or_else(|error| panic!("valid revision: {error}")),
        retrieval_profile_digest: seeded_digest(seed, "retrieval"),
        encoder_preprocessor_digest: seeded_digest(seed, "encoder"),
        authority_epoch: seed.saturating_add(1),
        model_digest: seeded_digest(seed, "model"),
        tokenizer_digest: seeded_digest(seed, "tokenizer"),
        template_digest: seeded_digest(seed, "template"),
        tool_schema_digest: seeded_digest(seed, "tools"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot: {error}"))
}

fn intent(seed: u64) -> LegacyMemoryWriteIntentV1 {
    LegacyMemoryWriteIntentV1 {
        intent_id: id(&format!("intent:property:{seed}")),
        candidate_digest: seeded_digest(seed, "candidate"),
        expected_snapshot: snapshot(seed),
        writer_fence_digest: seeded_digest(seed, "writer-fence"),
        authorization_digest: seeded_digest(seed, "authorization"),
    }
}

#[test]
fn generated_rejection_receipts_round_trip_and_reject_noncanonical_bytes() {
    let codes = [
        MemoryWriteRejectionCodeV1::AuthorizationRejected,
        MemoryWriteRejectionCodeV1::SnapshotConflict,
        MemoryWriteRejectionCodeV1::WriterFenceMismatch,
        MemoryWriteRejectionCodeV1::CandidateRejected,
        MemoryWriteRejectionCodeV1::CapacityExceeded,
        MemoryWriteRejectionCodeV1::DuplicateIntentConflict,
        MemoryWriteRejectionCodeV1::Indeterminate,
    ];
    for seed in 1..=256u64 {
        let receipt = MemoryWriteReceiptV1::rejected(
            &intent(seed),
            format!("writer:property:{}", seed % 5),
            seed.saturating_mul(1_000),
            codes[(seed as usize) % codes.len()],
            (seed % 3 != 0).then(|| seeded_digest(seed, "observed-snapshot")),
            seed % 2 == 0,
        )
        .unwrap_or_else(|error| panic!("seed {seed} receipt: {error}"));
        let bytes = Validated::from_cognitive_contract(receipt.clone())
            .unwrap_or_else(|error| panic!("seed {seed} validated: {error}"))
            .encode_wire_v1()
            .unwrap_or_else(|error| panic!("seed {seed} encode: {error}"));
        let decoded = decode_registered_wire_v1::<MemoryWriteReceiptV1>(&bytes)
            .unwrap_or_else(|error| panic!("seed {seed} decode: {error}"));
        assert_eq!(decoded, receipt, "seed {seed}");

        let mut noncanonical = bytes;
        noncanonical.push(b' ');
        assert!(
            decode_registered_wire_v1::<MemoryWriteReceiptV1>(&noncanonical).is_err(),
            "seed {seed} accepted trailing whitespace"
        );
    }
}

#[test]
fn generated_shadow_states_are_derived_not_caller_selected() {
    for seed in 1..=256u64 {
        let left = seeded_digest(seed, "left");
        let right = if seed % 4 == 0 {
            left
        } else {
            seeded_digest(seed, "right")
        };
        let (legacy, canonical, expected) = match seed % 4 {
            0 => (Some(left), Some(right), ShadowComparisonStateV1::Matched),
            1 => (
                Some(left),
                Some(right),
                ShadowComparisonStateV1::Mismatched,
            ),
            2 => (Some(left), None, ShadowComparisonStateV1::LegacyOnly),
            _ => (None, Some(right), ShadowComparisonStateV1::CanonicalOnly),
        };
        let receipt = ShadowComparisonReceiptV1::new(
            id(&format!("comparison:property:{seed}")),
            CognitiveConsumerV1::CognitiveRead,
            legacy,
            canonical,
            seed.saturating_mul(1_000),
        )
        .unwrap_or_else(|error| panic!("seed {seed} shadow receipt: {error}"));
        assert_eq!(receipt.state, expected, "seed {seed}");
        assert_eq!(
            receipt.cutover_eligible(),
            expected == ShadowComparisonStateV1::Matched,
            "seed {seed}"
        );
    }
}

#[test]
fn generated_rfc6901_escapes_have_total_accept_reject_partition() {
    for seed in 0..=255u16 {
        let valid = format!("/node/{seed}/a~1b/c~0d");
        validate_json_pointer_v1(&valid)
            .unwrap_or_else(|error| panic!("valid pointer seed {seed}: {error}"));
        for invalid_escape in ['2', 'x', '~'] {
            let invalid = format!("/node/{seed}/bad~{invalid_escape}");
            assert!(
                validate_json_pointer_v1(&invalid).is_err(),
                "invalid pointer accepted for seed {seed}: {invalid}"
            );
        }
    }
}

#[test]
fn unicode_policy_preserves_code_points_instead_of_silent_normalization() {
    let composed = "caf\u{00e9}";
    let decomposed = "cafe\u{301}";
    validate_preserved_text_v1(composed, 32, "text")
        .unwrap_or_else(|error| panic!("composed text: {error}"));
    validate_preserved_text_v1(decomposed, 32, "text")
        .unwrap_or_else(|error| panic!("decomposed text: {error}"));
    assert_ne!(composed.as_bytes(), decomposed.as_bytes());
    assert_ne!(
        Digest32::of_bytes(composed.as_bytes()),
        Digest32::of_bytes(decomposed.as_bytes())
    );
}
