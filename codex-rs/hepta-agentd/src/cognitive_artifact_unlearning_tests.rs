use super::*;
use codex_hepta_learning_artifacts as art;
use codex_hepta_learning_ledger as led;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use std::fs;

struct Case {
    temp: tempfile::TempDir,
    sink: CognitiveRetrievalLearningSink,
    config: art::LearningArtifactOwnerServiceConfigV1,
    service: art::LearningArtifactOwnerService,
    reader: art::ArtifactOwnerCurrentReaderV1,
    cached: art::RevalidatingCandidate,
    source: art::LearningArtifactManifestV2,
    dataset: led::DatasetSnapshotReceiptV3,
    lineage: led::UnlearningLineageRequestV1,
    evidence: led::SignedLearningEvidenceV1,
    revoke: art::LearningArtifactRevokeRequestV1,
}

fn signed(
    writer: &LedgerWriter,
    name: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> led::SignedLearningEvidenceV1 {
    let seed = match name {
        "generator" => 1,
        "observer" => 2,
        "evaluator" => 4,
        "privacy-owner" => 5,
        _ => unreachable!(),
    };
    let mut evidence = led::SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence-{name}")),
        principal_id: id(name),
        role,
        trust_digest: writer.verifier().trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

fn head(
    config: &art::LearningArtifactOwnerServiceConfigV1,
    registry: &art::ArtifactRegistry,
    predecessor: Digest32,
) -> art::SignedCurrentArtifactHeadV1 {
    let key = SigningKey::from_bytes(&[9; 32]);
    let mut head = art::SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
        binding: config.storage_binding,
        witness: art::RegistryHeadWitnessV1 {
            registry_id: config.trust.registry_id.clone(),
            generation: Generation::new(registry.records().len() as u64).unwrap(),
            head_digest: registry.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("artifact-authority"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: 20,
            expires_at: 1000,
        },
        signature: [0; 64],
    };
    head.signature = key.sign(&head.signing_bytes()).to_bytes();
    head
}

fn copy_store(source: &std::path::Path, target: &std::path::Path) {
    fs::create_dir(target).unwrap();
    for directory in fs::read_dir(source).unwrap() {
        let directory = directory.unwrap();
        let out = target.join(directory.file_name());
        fs::create_dir(&out).unwrap();
        for file in fs::read_dir(directory.path()).unwrap() {
            let file = file.unwrap();
            assert!(file.file_type().unwrap().is_file());
            fs::copy(file.path(), out.join(file.file_name())).unwrap();
        }
    }
}

fn case() -> Case {
    let (temp, sink) = sink();
    let mut writer = sink.writer.lock().unwrap();
    let candidates = vec![id("action"), id("abstain")];
    let decision = led::ProductionDecisionV2 {
        record_id: id("decision"),
        episode_id: id("episode"),
        run_snapshot_digest: digest("run"),
        objective_digest: digest("objective"),
        policy_digest: digest("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: led::CandidateSetCompletenessReceiptV1 {
            set_id: id("set"),
            state_digest: digest("state"),
            generator_id: id("generator"),
            generator_code_digest: digest("code"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("filter"),
            truncation_digest: digest("truncation"),
            candidates_digest: led::candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: led::candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: digest("support"),
    };
    let evidence = signed(
        &writer,
        "generator",
        LearningEvidenceRoleV1::Generator,
        &led::decision_signing_payload_v2(&decision).unwrap(),
    );
    let first = writer
        .append_decision(Digest32::ZERO, decision, &evidence, /*now*/ 50)
        .unwrap();
    let outcome = led::AuthenticatedOutcomeV1 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: id("episode"),
        observer: trusted(
            "observer",
            "observer-controller",
            /*seed*/ 2,
            LearningEvidenceRoleV1::Observer,
        )
        .principal,
        observed_at: Some(40),
        value: Some(FixedQ32::ONE),
        unit_profile_digest: digest("units"),
        support_digest: digest("outcome-support"),
        watermark: led::OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay"),
            terminality: led::OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    };
    let evidence = signed(
        &writer,
        "observer",
        LearningEvidenceRoleV1::Observer,
        &led::outcome_signing_payload_v2(&outcome),
    );
    let last = writer
        .append_outcome(first.chain_digest, outcome, &evidence, /*now*/ 50)
        .unwrap();
    let plan = led::DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion"),
    };
    let evidence = signed(
        &writer,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &led::dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap(),
    );
    let dataset = writer.freeze_dataset(plan, &evidence, /*now*/ 50).unwrap();
    drop(writer);
    let withdrawals = art::DatasetWithdrawalRegistry::new_scoped(art::DatasetWithdrawalScopeV1 {
        authority_domain_id: id("source-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    });
    let key = SigningKey::from_bytes(&[9; 32]);
    let signer = art::TrustedArtifactSignerV1 {
        signer_id: id("artifact-authority"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: 1,
        expires_at: 1000,
        revoked_at: None,
    };
    let trust = art::ArtifactOwnerTrustV1 {
        registry_id: id("artifact-registry"),
        withdrawal_scope_digest: withdrawals.scope_digest().unwrap(),
        minimum_registry_generation: Generation::new(1).unwrap(),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = art::SignedArtifactWriterLeaseV1 {
        lease_id: id("lease"),
        producer_id: id("generator"),
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: trust.withdrawal_scope_digest,
        signer_id: id("artifact-authority"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 10,
        expires_at: 1000,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let root = temp.path().join("artifacts");
    fs::create_dir(&root).unwrap();
    let mut config = art::LearningArtifactOwnerServiceConfigV1 {
        root,
        trust,
        writer_lease: lease,
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("artifact-binding"),
        now: 20,
    };
    let mut service = art::LearningArtifactOwnerService::open(config.clone()).unwrap();
    let source = art::LearningArtifactManifestV2 {
        artifact_id: id("candidate"),
        kind: art::ArtifactKind::Model,
        generation: Generation::new(1).unwrap(),
        provenance_mode: art::ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![dataset.snapshot.dataset_digest],
        lineage_digests: vec![last.chain_digest],
        predecessor_ids: vec![],
        rollback_predecessor: None,
        bytes_digest: Digest32::of_bytes(b"payload"),
        encoded_size_bytes: 7,
        training_code_digest: digest("training"),
        runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"),
        objective_class_digest: digest("objective"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"),
        producer_id: id("generator"),
        created_at: 10,
        expires_at: 1000,
    };
    let admission = art::admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        source.clone(),
        /*now*/ 20,
    )
    .unwrap();
    let transaction = art::ArtifactPublicationTransactionV1::begin(
        id("publish"),
        admission.clone(),
        &withdrawals,
        service.registry(),
        Digest32::ZERO,
        /*now*/ 20,
    )
    .unwrap();
    let mut projected = service.registry().clone();
    projected
        .append(art::ArtifactEvent::Register {
            event_id: id(&format!(
                "artifact-publication:{}",
                transaction.intent().intent_digest
            )),
            manifest: art::ArtifactManifest {
                artifact_id: source.artifact_id.clone(),
                kind: source.kind,
                generation: source.generation,
                predecessor_id: None,
                content_digest: source.bytes_digest,
                objective_digest: source.objective_class_digest,
                support_digest: admission.validated_manifest.manifest_digest,
                producer_id: source.producer_id.clone(),
                compatibility_digest: source.compatibility_digest,
                encoded_size_bytes: source.encoded_size_bytes,
            },
        })
        .unwrap();
    let published = head(&config, &projected, Digest32::ZERO);
    service
        .publish(art::LearningArtifactPublishRequestV1 {
            operation_id: id("publish"),
            admission,
            payload: b"payload".to_vec(),
            signed_current_head: published.clone(),
            expected_registry_predecessor_head: Digest32::ZERO,
            now: 20,
        })
        .unwrap();
    config.required_current_head = Some(published.clone());
    let reader =
        art::ArtifactOwnerCurrentReaderV1::open(&config.root, config.trust.clone(), published)
            .unwrap();
    let receipt = reader.current_registry_view(/*now*/ 20).unwrap().receipt();
    let loaded = art::load_pinned_candidate(
        File::open(config.root.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        )))
        .unwrap(),
        File::open(config.root.join("payloads").join(format!(
            "{}-{}.bin",
            source.artifact_id, source.bytes_digest
        )))
        .unwrap(),
        art::PinnedCandidateSpec {
            registry_receipt: receipt,
            manifest: service
                .registry()
                .manifest(&source.artifact_id)
                .unwrap()
                .clone(),
        },
    )
    .unwrap();
    let cached = art::RevalidatingCandidate::new(loaded);
    copy_store(&config.root, &temp.path().join("before-revoke"));
    let lineage = led::UnlearningLineageRequestV1 {
        record_id: id("unlearning"),
        lineage_id: id("lineage"),
        source_record_id: id("outcome-record"),
        dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
        dataset_digest: dataset.snapshot.dataset_digest,
        artifact_id: source.artifact_id.clone(),
        reason_digest: digest("withdrawal"),
    };
    let mut writer = sink.writer.lock().unwrap();
    let evidence = signed(
        &writer,
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &led::unlearning_signing_payload_v1(&lineage),
    );
    let receipt = writer
        .append_unlearning(
            last.chain_digest,
            lineage.clone(),
            &dataset,
            &evidence,
            /*now*/ 50,
        )
        .unwrap();
    drop(writer);
    let change = art::StateChange {
        event_id: lineage.record_id.clone(),
        artifact_id: source.artifact_id.clone(),
        evaluator_id: id("artifact-authority"),
        reason_digest: receipt.append.event_digest,
    };
    let predecessor = projected.snapshot().head_digest;
    projected
        .append(art::ArtifactEvent::Revoke(change.clone()))
        .unwrap();
    let revoke = art::LearningArtifactRevokeRequestV1 {
        operation_id: change.event_id.clone(),
        change,
        signed_current_head: head(&config, &projected, predecessor),
        expected_registry_predecessor_head: predecessor,
        now: 20,
    };
    Case {
        temp,
        sink,
        config,
        service,
        reader,
        cached,
        source,
        dataset,
        lineage,
        evidence,
        revoke,
    }
}

#[test]
fn without_bridge_signed_unlearning_leaves_artifact_current_eligible() {
    let mut f = case();
    assert!(
        f.sink
            .writer
            .lock()
            .unwrap()
            .revalidate_dataset_snapshot(&f.dataset, /*now*/ 50)
            .is_err()
    );
    assert_eq!(
        f.cached
            .with_current(
                f.reader.current_registry_view(/*now*/ 20).unwrap(),
                /*now*/ 20,
                <[u8]>::to_vec
            )
            .unwrap(),
        b"payload"
    );
    assert_ne!(
        f.service
            .registry()
            .manifest(&f.source.artifact_id)
            .unwrap()
            .support_digest,
        f.dataset.snapshot.dataset_digest
    );
    assert!(
        f.sink
            .writer
            .lock()
            .unwrap()
            .verify_committed_unlearning(&f.lineage, &f.dataset, &f.evidence, /*now*/ 50)
            .is_ok()
    );
}

#[test]
fn original_revoke_control_reopens_and_retained_signed_floor_rejects_backup() {
    let mut f = case();
    let first = f.service.revoke(f.revoke.clone()).unwrap();
    assert_eq!(f.service.revoke(f.revoke.clone()).unwrap(), first);
    assert_eq!(
        f.cached.with_current(
            f.reader.current_registry_view(/*now*/ 20).unwrap(),
            /*now*/ 20,
            |_| ()
        ),
        Err(art::PinnedCandidateLoadError::Ineligible)
    );
    f.config.required_current_head = Some(f.revoke.signed_current_head.clone());
    drop(f.service);
    let mut reopened = art::LearningArtifactOwnerService::open(f.config.clone()).unwrap();
    assert_eq!(reopened.revoke(f.revoke.clone()).unwrap(), first);
    assert!(!reopened.registry().is_eligible(&f.source.artifact_id));
    drop(reopened);
    // Restore actual old files while retaining the newer authenticated floor
    // outside that owner. The old payload and valid old ACK cannot reset it.
    fs::remove_dir_all(&f.config.root).unwrap();
    fs::rename(f.temp.path().join("before-revoke"), &f.config.root).unwrap();
    let reader = art::ArtifactOwnerCurrentReaderV1::open(
        &f.config.root,
        f.config.trust,
        f.revoke.signed_current_head,
    )
    .unwrap();
    assert!(matches!(
        reader.current_registry_view(/*now*/ 20),
        Err(art::ArtifactOwnerHostError::CurrentHeadRollback)
    ));
}
