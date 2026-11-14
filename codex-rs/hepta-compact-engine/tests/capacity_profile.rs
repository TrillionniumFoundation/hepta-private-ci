use std::collections::BTreeMap;
use std::fs;
use std::time::Instant;

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::COMPACTION_TRUST_SCHEMA_VERSION;
use codex_hepta_compact_engine::CompactionInputRecordV2;
use codex_hepta_compact_engine::CompactionPolicyV2;
use codex_hepta_compact_engine::CompactionSemanticPayloadV2;
use codex_hepta_compact_engine::CompactionTrustRoleV1;
use codex_hepta_compact_engine::QualifiedCandidateBuildRequestV1;
use codex_hepta_compact_engine::SignedRetentionSelectionReceiptV1;
use codex_hepta_compact_engine::SignedSemanticGenerationReceiptV1;
use codex_hepta_compact_engine::TokenizationReceiptV1;
use codex_hepta_compact_engine::TrustEnrollmentV1;
use codex_hepta_compact_engine::TrustedRetentionSelectorV1;
use codex_hepta_compact_engine::TrustedSemanticGeneratorV1;
use codex_hepta_compact_engine::TrustedTokenizerV1;
use codex_hepta_compact_engine::build_qualified_candidate;
use codex_hepta_compact_engine::compaction_input_manifest_digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

const SOURCE_RECORDS: usize = 65_536;
const SOURCE_CURRENT_HEADS: usize = 16_384;
const REVISIONS_PER_HEAD: usize = 4;
const PAYLOAD_BYTES: usize = 64 * 1024 * 1024;
const PAYLOAD_TOKENS: u64 = 8_000_000;
const RETAINED_RECORDS: u32 = 1_024;
const NOW: u64 = 1_800_000_000;

#[test]
#[ignore = "production-ceiling profile; run in compact.engine capacity workflow"]
fn production_ceiling_capacity_profile() -> Result<(), String> {
    let started = Instant::now();
    let cpu_before = process_cpu_ticks();
    let rss_before = peak_rss_kib();

    let selector_key = SigningKey::from_bytes(&[11; 32]);
    let generator_key = SigningKey::from_bytes(&[12; 32]);
    let tokenizer_key = SigningKey::from_bytes(&[13; 32]);
    let selector = TrustedRetentionSelectorV1 {
        enrollment: enrollment(
            CompactionTrustRoleV1::RetentionSelector,
            "selector:key:capacity",
            &selector_key,
        )?,
    };
    let generator = TrustedSemanticGeneratorV1 {
        enrollment: enrollment(
            CompactionTrustRoleV1::SemanticGenerator,
            "generator:key:capacity",
            &generator_key,
        )?,
    };
    let tokenizer = TrustedTokenizerV1 {
        enrollment: enrollment(
            CompactionTrustRoleV1::Tokenizer,
            "tokenizer:key:capacity",
            &tokenizer_key,
        )?,
        tokenizer_digest: digest("tokenizer:capacity"),
    };

    let source_snapshot = snapshot_key()?;
    let inputs = history_inputs(
        SOURCE_CURRENT_HEADS,
        REVISIONS_PER_HEAD,
        &tokenizer,
        &tokenizer_key,
    )?;
    assert_eq!(inputs.len(), SOURCE_RECORDS);
    let source_memory_snapshot = memory_snapshot(&inputs)?;
    let policy = CompactionPolicyV2 {
        policy_id: id("policy:capacity")?,
        algorithm_digest: digest("algorithm:deterministic-first-fit:v1"),
        compatibility_digest: digest("compatibility:capacity:v1"),
        tokenizer_digest: tokenizer.tokenizer_digest,
        tokenizer_implementation_digest: tokenizer.enrollment.implementation_digest,
        maximum_retained_records: RETAINED_RECORDS,
        maximum_retained_bytes: u64::from(RETAINED_RECORDS) * 64,
        maximum_retained_tokens: u64::from(RETAINED_RECORDS) * 8,
        maximum_payload_bytes: PAYLOAD_BYTES as u64,
        maximum_payload_tokens: PAYLOAD_TOKENS,
        protected_record_ids: vec![id("memory:capacity:00000")?],
    };

    let mut selection = SignedRetentionSelectionReceiptV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        key_id: selector.enrollment.key_id.clone(),
        trust_epoch: selector.enrollment.trust_epoch,
        issued_at_unix_seconds: NOW - 10,
        expires_at_unix_seconds: NOW + 600,
        nonce: digest("nonce:capacity:selection"),
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        policy_digest: policy.digest(),
        input_manifest_digest: compaction_input_manifest_digest(&inputs),
        tokenizer_key_id: tokenizer.enrollment.key_id.clone(),
        tokenizer_trust_epoch: tokenizer.enrollment.trust_epoch,
        tokenizer_key_digest: tokenizer.enrollment.key_digest(),
        signature: [0; 64],
    };
    selection.signature = selector_key.sign(&selection.signing_bytes()).to_bytes();

    let payload = vec![0x5a; PAYLOAD_BYTES];
    let payload_digest = Digest32::of_bytes(&payload);
    let payload_receipt = token_receipt(
        payload_digest,
        PAYLOAD_BYTES as u64,
        PAYLOAD_TOKENS,
        &tokenizer,
        &tokenizer_key,
    );
    let mut semantic_payload = CompactionSemanticPayloadV2 {
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        payload_digest,
        payload,
        generator_implementation_digest: generator.enrollment.implementation_digest,
        generator_receipt_digest: digest("placeholder:generation-receipt"),
        tokenizer_digest: tokenizer.tokenizer_digest,
        encoded_bytes: PAYLOAD_BYTES as u64,
        token_count: PAYLOAD_TOKENS,
        tokenization_receipt: payload_receipt,
    };
    let mut generation_receipt = SignedSemanticGenerationReceiptV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        key_id: generator.enrollment.key_id.clone(),
        trust_epoch: generator.enrollment.trust_epoch,
        issued_at_unix_seconds: NOW - 9,
        expires_at_unix_seconds: NOW + 600,
        nonce: digest("nonce:capacity:generation"),
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        policy_digest: policy.digest(),
        selection_receipt_digest: selection.receipt_digest(),
        payload_digest,
        tokenizer_key_id: tokenizer.enrollment.key_id.clone(),
        tokenizer_trust_epoch: tokenizer.enrollment.trust_epoch,
        tokenizer_key_digest: tokenizer.enrollment.key_digest(),
        tokenization_receipt_digest: semantic_payload.tokenization_receipt.receipt_digest(),
        signature: [0; 64],
    };
    generation_receipt.signature = generator_key
        .sign(&generation_receipt.signing_bytes())
        .to_bytes();
    semantic_payload.generator_receipt_digest = generation_receipt.receipt_digest();

    let candidate = build_qualified_candidate(QualifiedCandidateBuildRequestV1 {
        source_snapshot,
        source_memory_snapshot: &source_memory_snapshot,
        generation: generation(1)?,
        predecessor_checkpoint_digest: None,
        policy: &policy,
        semantic_payload: &semantic_payload,
        selector: &selector,
        selection_receipt: &selection,
        generator: &generator,
        generation_receipt: &generation_receipt,
        tokenizer: &tokenizer,
        inputs,
        verification_time_unix_seconds: NOW,
    })
    .expect("production ceiling candidate");

    assert_eq!(
        candidate.loss_report().source_current_heads,
        SOURCE_CURRENT_HEADS as u64
    );
    assert_eq!(candidate.semantic_payload().payload.len(), PAYLOAD_BYTES);
    assert_eq!(candidate.semantic_payload().token_count, PAYLOAD_TOKENS);
    assert_eq!(
        candidate.retained_records().len(),
        RETAINED_RECORDS as usize
    );

    let elapsed = started.elapsed();
    let cpu_after = process_cpu_ticks();
    let rss_after = peak_rss_kib();
    println!(
        "COMPACT_ENGINE_CAPACITY_PROFILE={{\"source_records\":{},\"source_current_heads\":{},\"retained_records\":{},\"payload_bytes\":{},\"payload_tokens\":{},\"wall_micros\":{},\"cpu_ticks\":{},\"peak_rss_kib_before\":{},\"peak_rss_kib_after\":{}}}",
        SOURCE_RECORDS,
        SOURCE_CURRENT_HEADS,
        candidate.retained_records().len(),
        PAYLOAD_BYTES,
        PAYLOAD_TOKENS,
        elapsed.as_micros(),
        cpu_after.saturating_sub(cpu_before),
        rss_before,
        rss_after,
    );
    Ok(())
}

// The protocol input ceiling counts revision rows; the shared snapshot
// ceiling counts distinct current heads. Preserve both independent bounds.
fn history_inputs(
    heads: usize,
    revisions: usize,
    tokenizer: &TrustedTokenizerV1,
    tokenizer_key: &SigningKey,
) -> Result<Vec<CompactionInputRecordV2>, String> {
    let mut rows = Vec::with_capacity(heads * revisions);
    for index in 0..heads {
        let mut predecessor = None;
        for revision_index in 0..revisions {
            let row = input(
                index,
                u64::try_from(revision_index + 1)
                    .map_err(|error| format!("bounded revision: {error:?}"))?,
                predecessor,
                tokenizer,
                tokenizer_key,
            )?;
            predecessor = Some(row.record.record_digest());
            rows.push(row);
        }
    }
    Ok(rows)
}

fn input(
    index: usize,
    revision_value: u64,
    predecessor_digest: Option<Digest32>,
    tokenizer: &TrustedTokenizerV1,
    tokenizer_key: &SigningKey,
) -> Result<CompactionInputRecordV2, String> {
    let record_id = format!("memory:capacity:{index:05}");
    let record = MemoryRecord {
        record_id: id(&record_id)?,
        revision: revision(revision_value)?,
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("{record_id}:live:{revision_value}")),
        predecessor_digest,
        citations: Vec::new(),
        state: RecordState::Live,
    };
    Ok(CompactionInputRecordV2 {
        tokenization_receipt: token_receipt(
            record.record_digest(),
            64,
            8,
            tokenizer,
            tokenizer_key,
        ),
        retention_reason_digest: digest(&format!("reason:{record_id}")),
        record,
        retention_priority: u32::try_from(SOURCE_RECORDS - index)
            .map_err(|error| format!("bounded priority: {error:?}"))?,
        encoded_bytes: 64,
        token_count: 8,
    })
}

fn memory_snapshot(inputs: &[CompactionInputRecordV2]) -> Result<CognitiveSnapshot, String> {
    let mut heads = BTreeMap::new();
    for input in inputs {
        heads.insert(input.record.record_id.clone(), input.record.clone());
    }
    build_snapshot(generation(21)?, heads.into_values().collect())
        .map_err(|error| format!("capacity source snapshot: {error:?}"))
}

fn snapshot_key() -> Result<CognitiveSnapshotKeyV1, String> {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:compact-capacity")?,
        purpose_id: id("purpose:checkpoint-capacity")?,
        memory_ledger_frontier: 65_536,
        knowledge_fact_frontier: 65_536,
        tombstone_frontier: 0,
        source_ledger_frontier: 65_536,
        knowledge_graph_generation: generation(3)?,
        compact_checkpoint_generation: generation(1)?,
        prompt_registry_revision: revision(4)?,
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 8,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer:capacity"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .map_err(|error| format!("capacity snapshot key: {error:?}"))
}

fn token_receipt(
    subject_digest: Digest32,
    encoded_bytes: u64,
    token_count: u64,
    tokenizer: &TrustedTokenizerV1,
    key: &SigningKey,
) -> TokenizationReceiptV1 {
    let mut receipt = TokenizationReceiptV1 {
        subject_digest,
        tokenizer_digest: tokenizer.tokenizer_digest,
        tokenizer_implementation_digest: tokenizer.enrollment.implementation_digest,
        encoded_bytes,
        token_count,
        signature: [0; 64],
    };
    receipt.signature = key.sign(&receipt.signing_bytes()).to_bytes();
    receipt
}

fn enrollment(
    role: CompactionTrustRoleV1,
    key_id: &str,
    key: &SigningKey,
) -> Result<TrustEnrollmentV1, String> {
    Ok(TrustEnrollmentV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        role,
        key_id: id(key_id)?,
        trust_epoch: 1,
        valid_from_unix_seconds: NOW - 1_000,
        valid_until_unix_seconds: NOW + 10_000,
        revoked_at_unix_seconds: None,
        predecessor_key_digest: None,
        implementation_digest: digest(&format!("{key_id}:implementation")),
        attestation_digest: digest(&format!("{key_id}:attestation")),
        verifying_key: key.verifying_key().to_bytes(),
    })
}

fn process_cpu_ticks() -> u64 {
    fs::read_to_string("/proc/self/stat")
        .ok()
        .and_then(|line| {
            let tail = line.rsplit_once(") ")?.1;
            let fields = tail.split_whitespace().collect::<Vec<_>>();
            let user = fields.get(11)?.parse::<u64>().ok()?;
            let system = fields.get(12)?.parse::<u64>().ok()?;
            Some(user.saturating_add(system))
        })
        .unwrap_or(0)
}

fn peak_rss_kib() -> u64 {
    fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|status| {
            status.lines().find_map(|line| {
                line.strip_prefix("VmHWM:")?
                    .split_whitespace()
                    .next()?
                    .parse::<u64>()
                    .ok()
            })
        })
        .unwrap_or(0)
}

fn id(value: &str) -> Result<StableId, String> {
    StableId::new(value).map_err(|error| format!("valid stable id: {error:?}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Result<Generation, String> {
    Generation::new(value).map_err(|error| format!("valid generation: {error:?}"))
}

fn revision(value: u64) -> Result<Revision, String> {
    Revision::new(value).map_err(|error| format!("valid revision: {error:?}"))
}

#[path = "capacity_profile/history_tests.rs"]
mod history_tests;
