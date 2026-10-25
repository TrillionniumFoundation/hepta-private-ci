//! Controlled source/receipt fixtures; these do not claim model execution.

use crate::native_memory_types::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::*;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

pub(crate) struct Verifier(pub AtomicBool);
impl ProductionAuthorityVerifier for Verifier {
    fn verify(&self, authority: &ProductionAuthorityLease, owner: &AgentId) -> Result<(), String> {
        if self.0.load(Ordering::SeqCst) || &authority.agent_id != owner {
            Err("controlled grant withdrawn".to_string())
        } else {
            Ok(())
        }
    }
}

pub(crate) struct Fixture {
    pub temp: tempfile::TempDir,
    pub writer: Arc<ProductionDurableWriter>,
    pub verifier: Arc<Verifier>,
    pub admission: Arc<MemoryCellAdmissionV1>,
    pub config: NativeMemoryModelConfigV1,
    pub access: CognitiveAccess,
    pub claim: MemoryCellSourceClaimV1,
}

pub(crate) async fn fixture() -> Fixture {
    let temp = tempfile::tempdir().unwrap();
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cff").unwrap();
    let fleet = HeptaFleetRoot::parse(temp.path().join("fleet")).unwrap();
    let store = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .unwrap();
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"controlled-grant"),
        1,
        1,
        now / 1000 + 3600,
        ProductionAuthorityToken::from_verified_bytes(b"controlled-token".to_vec()).unwrap(),
    )
    .unwrap();
    let verifier = Arc::new(Verifier(AtomicBool::new(false)));
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store,
            authority,
            verifier.clone(),
            "native-read-test",
            1,
        )
        .await
        .unwrap(),
    );
    fixture_with_writer(temp, writer, verifier).await
}

pub(crate) async fn fixture_with_writer(
    temp: tempfile::TempDir,
    writer: Arc<ProductionDurableWriter>,
    verifier: Arc<Verifier>,
) -> Fixture {
    fixture_with_document_bytes(temp, writer, verifier, controlled_document_bytes()).await
}

pub(crate) fn controlled_document_bytes() -> Vec<u8> {
    let key = MemoryCellKeyV1 {
        role: MemoryCellRoleV1::Procedural,
        entity: "case-one".to_string(),
        relation: "repair".to_string(),
    };
    serde_json::to_string(&MemoryCellDocumentV1 {
        schema_version: 1,
        key,
        value: "order".to_string(),
    })
    .unwrap()
    .into_bytes()
}

pub(crate) async fn fixture_with_document_bytes(
    temp: tempfile::TempDir,
    writer: Arc<ProductionDurableWriter>,
    verifier: Arc<Verifier>,
    document_bytes: Vec<u8>,
) -> Fixture {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let access = CognitiveAccess::agent_private(writer.owner_agent_id().clone());
    // Preserve the original UTF-8 bytes, including whitespace. Parsing selects
    // the typed key; it never reserializes the source into different ancestry.
    let content = String::from_utf8(document_bytes).unwrap();
    let document: MemoryCellDocumentV1 = serde_json::from_str(&content).unwrap();
    document.validate().unwrap();
    let key = document.key;
    let source = SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "ci-import-test".to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: (now / 1000) as i64,
    };
    let revision = MemoryRevisionDraft {
        scope: source.scope.clone(),
        content,
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: source.observed_at_unix_seconds,
        valid_to_unix_seconds: None,
        citations: vec![],
    };
    let production = writer
        .cognitive_mutation_capability()
        .unwrap()
        .remember_with_kg(
            &access,
            &source,
            &MemoryDraft {
                stable_key: key.stable_key().unwrap(),
                revision,
            },
            &KgFactSetDraft::default(),
        )
        .await
        .unwrap();
    let hash = production.source_content_sha256.as_str();
    let misc = Digest32::of_bytes(b"controlled-profile").to_string();
    let event = serde_json::from_value(serde_json::json!({
        "eventId": "hnmf:ci-import-test", "episodeId": "episode:ci-test",
        "scope": {"kind":"agent_private", "agentId": writer.owner_agent_id().as_str()},
        "observedInterval": {"startUnixMs": source.observed_at_unix_seconds as u64 * 1000, "endUnixMs": null},
        "modalitySpans": [{"spanId": "span:ci-test", "modality": "text", "assetSha256": hash,
            "range": {"kind":"byte_range", "start": 0, "end": source.content.len()},
            "preprocessorManifestSha256": misc, "featureBlobSha256": null, "symbolicProjectionSha256": null,
            "uncertaintyPpm": 0, "privacyClass": "agent_private", "redactionMaskSha256": null}],
        "crossModalBindings": [], "semanticKeys": [key.stable_key().unwrap()],
        "provenance": [{"sourceId": production.write.source.source_id.as_str(), "sourceRevision": 1, "sourceSha256": hash, "observedAtUnixMs": source.observed_at_unix_seconds as u64 * 1000}],
        "verification": "verified", "retentionPolicy": {"kind":"persistent", "retainUntilUnixMs": null},
        "objectiveDigest": misc, "nduStateDigest": misc, "causalParents": [], "temporalNeighbors": [],
        "behaviorPropensityPpm": null, "lifecycle": {"state":"active"}
    })).unwrap();
    let query = MemoryCellQueryV1 {
        request_id: StableId::new("native:fixture:1").unwrap(),
        key,
        deadline_unix_ms: now + 300_000,
    };
    let claim = MemoryCellSourceClaimV1 { event, production };
    let admission = Arc::new(
        writer
            .admit_memory_cell(&access, &query, &claim)
            .await
            .unwrap(),
    );
    let config = config(temp.path());
    Fixture {
        temp,
        writer,
        verifier,
        admission,
        config,
        access,
        claim,
    }
}

pub(crate) fn config(root: &std::path::Path) -> NativeMemoryModelConfigV1 {
    let hash = Digest32::of_bytes(b"controlled-fixture").to_string();
    NativeMemoryModelConfigV1 {
        python: std::env::current_exe().unwrap(),
        repo: root.to_path_buf(),
        model: root.join("model"),
        checkpoint: root.join("checkpoint"),
        receipt_directory: root.join("receipts"),
        scope: "native-test".to_string(),
        model_id: "model:native-test".to_string(),
        config_id: "config:native-test".to_string(),
        generation: 1,
        rank: 8,
        seed: 1,
        output_width: 4,
        timeout_millis: 30_000,
        pins: NativeMemoryPinsV1 {
            manifest_sha256: hash.clone(),
            base_identity: hash.clone(),
            adapter_sha256: hash.clone(),
            weights_digest: Digest32::of_parts(&[hash.as_bytes(), hash.as_bytes()]).to_string(),
            tokenizer_digest: hash.clone(),
            preprocessor_digest: Digest32::of_bytes(SYSTEM.as_bytes()).to_string(),
            quantization_digest: Digest32::of_bytes(
                b"hepta.memory-cell.cpu-float32-unquantized.v1",
            )
            .to_string(),
            runtime_digest: hash.clone(),
            device_digest: hash.clone(),
            worker_sha256: hash.clone(),
            launcher_sha256: hash,
        },
    }
}

pub(crate) fn execution(f: &Fixture) -> NativeMemoryExecutionV1 {
    let question = f.admission.query().key.question().unwrap();
    NativeMemoryExecutionV1 {
        schema: "hepta.memory-cell.native-execution.v1".to_string(),
        request_sha256: Digest32::of_bytes(b"request").to_string(),
        query_digest: f.admission.binding().query_digest.to_string(),
        source_binding_digest: f.admission.binding().binding_digest.to_string(),
        pins: f.config.pins.clone(),
        question: question.clone(),
        prompt: f.config.prompt(&question),
        prompt_token_ids: vec![1, 2],
        generated_token_ids: vec![3],
        text: "fixture-only".to_string(),
        drive_q24: vec![1; f.config.output_width],
        prediction_q24: vec![2; f.config.output_width],
        latency_micros: 100,
        resident_bytes: 1000,
        process_peak_rss_bytes: 2000,
        resident_measurement: "model_parameter_bytes_excludes_allocator".to_string(),
        feature_forward_calls: 1,
        decoder_queries: 1,
        adapter_enabled: true,
        answer_postprocessed: false,
        facts_received: false,
        retrieval_received: false,
        base_unchanged: true,
        adapter_unchanged: true,
    }
}
