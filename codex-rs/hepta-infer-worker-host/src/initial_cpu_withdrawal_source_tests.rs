//! Isolated original durable owner fixtures, not a scientific cohort.
#![allow(clippy::unwrap_used, clippy::expect_used)]
use super::*;
use codex_hepta_agent_components::types::FixedQ32;
use codex_hepta_agent_components::types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use ledger::*;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn role(index: usize) -> LearningEvidenceRoleV1 {
    match index {
        0 => LearningEvidenceRoleV1::Generator,
        1 => LearningEvidenceRoleV1::Observer,
        2 | 3 => LearningEvidenceRoleV1::Evaluator,
        4 => LearningEvidenceRoleV1::UnlearningAuthority,
        _ => panic!("fixture role"),
    }
}
fn signed(
    writer: &LedgerWriter,
    key: &SigningKey,
    principal: &AuthenticatedPrincipalV1,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    now: u64,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence:{}", Digest32::of_bytes(payload))),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: writer.verifier().trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: writer.verifier().objective_digest(),
        authority_epoch: 1,
        issued_at: now,
        expires_at: now + 120_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}
fn sign(
    writer: &LedgerWriter,
    key: &SigningKey,
    principal: &AuthenticatedPrincipalV1,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    now: u64,
) -> SignedLearningEvidenceV1 {
    signed(writer, key, principal, role, payload, now)
}
fn create_writer(root: &Path, trust: ActivatedLearningTrustV1, binding: Digest32) -> LedgerWriter {
    for name in ["ledger", "witness"] {
        std::fs::create_dir(root.join(name)).unwrap();
    }
    let file = |name: &str| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(root.join(name))
            .unwrap()
    };
    let durable = DurableLedger::create(file("ledger/causal-ledger.bin"), binding, 4096).unwrap();
    let witness =
        LedgerWitnessStore::create(file("witness/acknowledged-frontier.bin"), binding).unwrap();
    LedgerWriter::from_durable(
        durable,
        witness,
        trust,
        &File::open(root.join("ledger")).unwrap(),
        &File::open(root.join("witness")).unwrap(),
    )
    .unwrap()
}
fn source(path: PathBuf, bytes: &[u8]) -> Source {
    std::fs::write(&path, bytes).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    Source {
        path,
        digest: Digest32::of_bytes(bytes).to_string(),
    }
}
fn fixture(root: &Path) -> Request {
    fixture_at(root, now_ms().unwrap())
}
fn fixture_at(root: &Path, now: u64) -> Request {
    let keys: [SigningKey; 5] =
        std::array::from_fn(|i| SigningKey::from_bytes(&[71 + i as u8; 32]));
    let principals: [AuthenticatedPrincipalV1; 5] =
        std::array::from_fn(|i| AuthenticatedPrincipalV1 {
            principal_id: id(&format!("fixture-authority-{i}")),
            credential_chain_digest: digest(&format!("fixture-chain-{i}")),
            signing_key_digest: Digest32::of_bytes(keys[i].verifying_key().as_bytes()),
            scope_digest: digest("fixture-scope"),
            authority_epoch: 1,
            authenticated_at: now - 1000,
            expires_at: now + 120_000,
        });
    let signers: Vec<TrustedLearningSignerV1> = (0..5)
        .map(|i| TrustedLearningSignerV1 {
            principal: principals[i].clone(),
            controller_id: id(&format!("fixture-controller-{i}")),
            verifying_key: keys[i].verifying_key().to_bytes(),
            roles: vec![role(i)],
            revoked_at: None,
        })
        .collect();
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let trust_root = LearningTrustRootV1 {
        root_id: id("fixture-root"),
        scope_digest: digest("fixture-scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: now - 1000,
        expires_at: now + 120_000,
        revoked_at: None,
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("fixture-distribution"),
            generation: 1,
            effective_at: now - 1000,
            trust: LearningEvidenceTrustV1 {
                scope_digest: digest("fixture-scope"),
                objective_digest: digest("fixture-objective"),
                authority_epoch: 1,
                signers: signers.clone(),
            },
        },
        root_id: trust_root.root_id.clone(),
        issued_at: now - 1000,
        expires_at: now + 120_000,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().unwrap())
        .to_bytes();
    let trust = activate_learning_trust(&trust_root, distribution.clone(), None, now).unwrap();
    let config_bytes = b"isolated original Root configuration";
    let binding = Digest32::of_bytes(
        &[
            b"hepta.fixed-custody-calibration-ledger.v1".as_slice(),
            Digest32::of_bytes(config_bytes).as_array(),
            digest("fixture-objective").as_array(),
        ]
        .concat(),
    );
    let mut writer = create_writer(root, trust.clone(), binding);
    let generator_evidence = sign(
        &writer,
        &keys[0],
        &principals[0],
        role(0),
        b"actual fixture generator batch",
        now,
    );
    let candidates = vec![id("action"), id("abstain")];
    let decision = ProductionDecisionV2 {
        record_id: id("decision"),
        episode_id: id("episode"),
        run_snapshot_digest: digest("run"),
        objective_digest: digest("fixture-objective"),
        policy_digest: digest("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id("set"),
            state_digest: digest("state"),
            generator_id: principals[0].principal_id.clone(),
            generator_code_digest: digest("code"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("filter"),
            truncation_digest: digest("truncate"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: digest("decision-support"),
    };
    let evidence = sign(
        &writer,
        &keys[0],
        &principals[0],
        role(0),
        &decision_signing_payload_v2(&decision).unwrap(),
        now,
    );
    let decision_ack = writer
        .append_decision(Digest32::ZERO, decision, &evidence, now)
        .unwrap();
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("outcome"),
        outcome_id: id("observed-outcome"),
        episode_id: id("episode"),
        observer: principals[1].clone(),
        observed_at: Some(now),
        value: Some(FixedQ32::from_raw(100)),
        unit_profile_digest: digest("unit"),
        support_digest: digest("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: now,
            expected_delay_profile_digest: digest("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(now),
        },
    };
    let evidence = sign(
        &writer,
        &keys[1],
        &principals[1],
        role(1),
        &outcome_signing_payload_v2(&outcome),
        now,
    );
    let outcome_ack = writer
        .append_outcome(decision_ack.chain_digest, outcome, &evidence, now)
        .unwrap();
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("fixture-objective"),
        inclusion_policy_digest: digest("cut"),
    };
    let evidence = sign(
        &writer,
        &keys[2],
        &principals[2],
        role(2),
        &dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap(),
        now,
    );
    let dataset = writer.freeze_dataset(plan, &evidence, now).unwrap();
    assert_eq!(
        dataset.snapshot.ledger_head_digest,
        outcome_ack.chain_digest
    );

    let snapshot = writer.snapshot().unwrap();
    let dataset_wire = ReviewDatasetWireV1 {
        snapshot_id: dataset.snapshot.snapshot_id.to_string(),
        ledger_head_digest: dataset.snapshot.ledger_head_digest.to_string(),
        objective_digest: dataset.snapshot.objective_digest.to_string(),
        eligible_frontier: dataset.snapshot.eligible_frontier,
        outcome_watermark: dataset.snapshot.outcome_watermark,
        source_record_digests: dataset
            .snapshot
            .source_record_digests
            .iter()
            .map(ToString::to_string)
            .collect(),
        pending_outcomes: dataset.snapshot.pending_outcomes,
        censored_outcomes: dataset.snapshot.censored_outcomes,
        dataset_digest: dataset.snapshot.dataset_digest.to_string(),
        authority_grants_any: false,
        producer: PrincipalWire::from_principal(&dataset.producer),
        correction_cut_digest: dataset.correction_cut_digest.to_string(),
        revocation_cut_digest: dataset.revocation_cut_digest.to_string(),
        inclusion_policy_digest: dataset.inclusion_policy_digest.to_string(),
    };
    let archive_bytes = std::fs::read(root.join("ledger/causal-ledger.bin")).unwrap();
    let d = digest("nonzero original cut binding").to_string();
    let cut = FixedCalibrationCutV1 {
        schema: "hepta.signed-calibration-cut.v1".into(),
        observer_program_digest: d.clone(),
        ledger_binding_digest: binding.to_string(),
        ledger_file_digest: Digest32::of_bytes(&archive_bytes).to_string(),
        acknowledged_sequence: snapshot.records().len() as u64,
        acknowledged_head: snapshot.head_digest.to_string(),
        candidate_manifest_digest: d.clone(),
        baseline_manifest_digest: d.clone(),
        candidate_weights_digest: d.clone(),
        baseline_weights_digest: d.clone(),
        audit_digest: d.clone(),
        dataset: dataset_wire,
        generator_payload_hex: state::hex(b"actual fixture generator batch"),
        generator_evidence: ReviewEvidenceWireV1::from_native(&generator_evidence),
        freeze_evidence: ReviewEvidenceWireV1::from_native(&evidence),
    };
    let observer = sign(
        &writer,
        &keys[1],
        &principals[1],
        role(1),
        &cut.signing_payload().unwrap(),
        now,
    );
    let roles = [
        "generator",
        "observer",
        "evaluator",
        "evaluator",
        "unlearning_authority",
    ];
    let trust_wire = ReviewTrustWireV1 {
        root_id: trust_root.root_id.to_string(),
        root_verifying_key_hex: state::hex(&trust_root.verifying_key),
        root_valid_from: trust_root.valid_from,
        root_expires_at: trust_root.expires_at,
        distribution_id: distribution.distribution.distribution_id.to_string(),
        generation: 1,
        effective_at: distribution.distribution.effective_at,
        issued_at: distribution.issued_at,
        expires_at: distribution.expires_at,
        scope_digest: trust.verifier().scope_digest().to_string(),
        objective_digest: trust.verifier().objective_digest().to_string(),
        authority_epoch: 1,
        signers: signers
            .iter()
            .enumerate()
            .map(|(i, s)| ReviewSignerWireV1 {
                principal: PrincipalWire::from_principal(&s.principal),
                controller_id: s.controller_id.to_string(),
                verifying_key_hex: state::hex(&s.verifying_key),
                role: roles[i].into(),
            })
            .collect(),
        signature_hex: state::hex(&distribution.signature),
    };
    let publication = FixedCalibrationPublicationV1 {
        cut,
        observer_evidence: ReviewEvidenceWireV1::from_native(&observer),
        trust: trust_wire,
    };
    drop(writer);
    let unused = Source {
        path: root.join("unused-not-opened"),
        digest: d.clone(),
    };
    Request {
        schema: "hepta.cpu-neuron.dataset-withdrawal-request.v1".into(),
        owner: unused.clone(),
        replacement: unused,
        replacement_index: 0,
        calibration_publication: source(
            root.join("publication.json"),
            &serde_json::to_vec(&publication).unwrap(),
        ),
        calibration_archive: source(root.join("ledger-readonly.bin"), &archive_bytes),
        calibration_trust_config: source(root.join("trust-config.json"), config_bytes),
        ledger_directory: root.join("ledger"),
        witness_directory: root.join("witness"),
        unlearning_private_key_path: root.join("unused-key"),
        record_id: "withdrawal".into(),
        lineage_id: "same-withdrawal-lineage".into(),
        source_record_id: "outcome".into(),
        artifact_id: "actual-source".into(),
        reason_digest: d,
        expected_ledger_head: snapshot.head_digest.to_string(),
        expected_artifact_head: digest("actual original artifact frontier").to_string(),
        delivery_targets: vec!["actual-source".into()],
        previous_withdrawals: vec![],
    }
}
#[test]
fn ordinary_caller_cannot_open_an_unprotected_root_withdrawal_directory() {
    let temp = tempfile::tempdir().unwrap();
    assert!(directory(temp.path()).is_err());
}
#[test]
#[ignore = "Run exact original native ELF as Root in isolated protected custody"]
fn root_reopens_original_calibration_without_reset_and_rejects_substituted_cut() {
    let root = PathBuf::from(format!(
        "/var/lib/hepta/native-withdrawal-source-tests/{}-{}",
        std::process::id(),
        now_ms().unwrap()
    ));
    std::fs::create_dir_all(&root).unwrap();
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let mut request = fixture(&root);
    let before = std::fs::read(root.join("ledger/causal-ledger.bin")).unwrap();
    let witness = std::fs::read(root.join("witness/acknowledged-frontier.bin")).unwrap();
    let loaded = open(&request).unwrap();
    let actual = loaded.writer.snapshot().unwrap();
    assert_eq!(
        loaded.dataset.snapshot.ledger_head_digest,
        actual.head_digest
    );
    drop(loaded);
    assert_eq!(
        std::fs::read(root.join("ledger/causal-ledger.bin")).unwrap(),
        before
    );
    assert_eq!(
        std::fs::read(root.join("witness/acknowledged-frontier.bin")).unwrap(),
        witness
    );
    let archive = std::fs::read(&request.calibration_archive.path).unwrap();
    let mut changed = archive.clone();
    let end = changed.len() - 1;
    changed[end] ^= 1;
    std::fs::write(&request.calibration_archive.path, &changed).unwrap();
    assert!(open(&request).is_err());
    std::fs::write(&request.calibration_archive.path, &archive).unwrap();
    let config_digest = request.calibration_trust_config.digest.clone();
    request.calibration_trust_config.digest = digest("another config").to_string();
    assert!(open(&request).is_err());
    request.calibration_trust_config.digest = config_digest;
    let publication_bytes = std::fs::read(&request.calibration_publication.path).unwrap();
    let mut publication: FixedCalibrationPublicationV1 =
        serde_json::from_slice(&publication_bytes).unwrap();
    publication.observer_evidence.role = "generator".into();
    let changed = serde_json::to_vec(&publication).unwrap();
    request.calibration_publication =
        source(request.calibration_publication.path.clone(), &changed);
    assert!(open(&request).is_err());
    assert_eq!(
        std::fs::read(root.join("ledger/causal-ledger.bin")).unwrap(),
        before
    );
    assert_eq!(
        std::fs::read(root.join("witness/acknowledged-frontier.bin")).unwrap(),
        witness
    );
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
#[ignore = "Run original native ELF as Root; expired signed history is never current authority"]
fn root_readonly_source_ack_keeps_expired_history_and_rejects_partial_or_substituted_facts() {
    use super::super::inspection_source;
    use std::io::Write;
    let root = PathBuf::from(format!(
        "/var/lib/hepta/native-withdrawal-inspection-tests/{}-{}",
        std::process::id(),
        now_ms().unwrap()
    ));
    std::fs::create_dir_all(&root).unwrap();
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let historical_now = now_ms().unwrap() - 300_000;
    let request = fixture_at(&root, historical_now);
    assert!(open(&request).is_err()); // Current trust is genuinely expired.
    let original = authenticated_archive(&request, ArchiveUse::AcknowledgedHistory).unwrap();
    let ledger_directory = directory(&request.ledger_directory).unwrap();
    let witness_directory = directory(&request.witness_directory).unwrap();
    let witness = LedgerWitnessStore::recover(
        mutable(&request.witness_directory.join("acknowledged-frontier.bin")).unwrap(),
        original.binding,
    )
    .unwrap();
    let durable = DurableLedger::recover(
        mutable(&request.ledger_directory.join("causal-ledger.bin")).unwrap(),
        original.binding,
        4096,
        LedgerRecovery::Acknowledged(witness.frontier().unwrap().anchor),
    )
    .unwrap();
    let mut writer = LedgerWriter::from_durable(
        durable,
        witness,
        original.trust,
        &ledger_directory,
        &witness_directory,
    )
    .unwrap();
    let native = UnlearningLineageRequestV1 {
        record_id: id(&request.record_id),
        lineage_id: id(&request.lineage_id),
        source_record_id: id(&request.source_record_id),
        dataset_snapshot_id: original.dataset.snapshot.snapshot_id.clone(),
        dataset_digest: original.dataset.snapshot.dataset_digest,
        artifact_id: id(&request.artifact_id),
        reason_digest: request.reason_digest.parse().unwrap(),
    };
    let publication: FixedCalibrationPublicationV1 = serde_json::from_slice(
        &request
            .calibration_publication
            .read(2 * 1024 * 1024)
            .unwrap(),
    )
    .unwrap();
    let principal = publication.trust.signers[4].principal.principal().unwrap();
    let evidence = sign(
        &writer,
        &SigningKey::from_bytes(&[75; 32]),
        &principal,
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&native),
        historical_now,
    );
    let receipt = writer
        .append_unlearning(
            request.expected_ledger_head.parse().unwrap(),
            native,
            &original.dataset,
            &evidence,
            historical_now,
        )
        .unwrap();
    assert!(
        inspection_source::read(
            &request,
            &evidence,
            receipt.source_event_digest,
            receipt.append.event_digest
        )
        .is_err()
    ); // Sole writer stays held.
    drop(writer);
    assert!(!request.unlearning_private_key_path.exists()); // Inspection must never read or create a seed.
    let causal = request.ledger_directory.join("causal-ledger.bin");
    let witness = request.witness_directory.join("acknowledged-frontier.bin");
    let before_causal = std::fs::read(&causal).unwrap();
    let before_witness = std::fs::read(&witness).unwrap();
    let observed = inspection_source::read(
        &request,
        &evidence,
        receipt.source_event_digest,
        receipt.append.event_digest,
    )
    .unwrap();
    assert_eq!(
        observed.ack["sequence"].as_u64(),
        Some(receipt.append.sequence.get())
    );
    assert_eq!(
        observed.ack["chain_digest"].as_str(),
        Some(receipt.append.chain_digest.to_string().as_str())
    );
    assert_eq!(
        observed.notice.source_tombstone_digest,
        receipt.append.event_digest
    );
    let mut substituted = evidence.clone();
    substituted.signature[0] ^= 1;
    assert!(
        inspection_source::read(
            &request,
            &substituted,
            receipt.source_event_digest,
            receipt.append.event_digest
        )
        .is_err()
    );
    assert!(
        inspection_source::read(
            &request,
            &evidence,
            receipt.source_event_digest,
            digest("substituted event")
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&causal).unwrap(), before_causal);
    assert_eq!(std::fs::read(&witness).unwrap(), before_witness);
    OpenOptions::new()
        .append(true)
        .open(&witness)
        .unwrap()
        .write_all(&[7, 8])
        .unwrap();
    let partial = std::fs::read(&witness).unwrap();
    assert!(
        inspection_source::read(
            &request,
            &evidence,
            receipt.source_event_digest,
            receipt.append.event_digest
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&witness).unwrap(), partial);
    assert_eq!(std::fs::read(&causal).unwrap(), before_causal);
    std::fs::remove_dir_all(root).unwrap();
}
