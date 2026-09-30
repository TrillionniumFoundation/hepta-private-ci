use std::fs::File;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_bellman_operator::FinalUseError;
use codex_hepta_bellman_operator::RuntimeLimitsV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::TrainingProfileV1;
use codex_hepta_bellman_operator::UnboundTabularOperatorPlanV3;
use codex_hepta_bellman_operator::UnboundWorldModelDatasetV3;
use codex_hepta_bellman_operator::WorkControlError;
use codex_hepta_bellman_operator::WorldModelProfileV1;
use codex_hepta_bellman_operator::WorldModelSampleV1;
use codex_hepta_bellman_operator::fit_tabular_operator_verified_v3;
use codex_hepta_bellman_operator::fit_transition_model_verified_v3;
use codex_hepta_bellman_operator::revalidate_tabular_candidate_for_publication_v3;
use codex_hepta_bellman_operator::revalidate_world_model_candidate_for_publication_v3;
use codex_hepta_bellman_operator::verify_tabular_operator_plan_v3;
use codex_hepta_bellman_operator::verify_world_model_dataset_v3;
use codex_hepta_learning_ledger::ArtifactKindV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::DecisionRecordV2;
use codex_hepta_learning_ledger::DurableLearningOwner;
use codex_hepta_learning_ledger::FileLedgerStoreV1;
use codex_hepta_learning_ledger::FileReplayStoreV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::OutcomeRecordV1;
use codex_hepta_learning_ledger::PolicyFingerprintV1;
use codex_hepta_learning_ledger::ProductionOwnerConfigV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ReplayId;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(1);
static NEXT_EVIDENCE: AtomicU64 = AtomicU64::new(1);

fn id(value: impl AsRef<str>) -> StableId {
    StableId::new(value.as_ref()).unwrap()
}

fn digest(value: impl AsRef<[u8]>) -> Digest32 {
    Digest32::of_bytes(value.as_ref())
}

fn key(seed: u8) -> SigningKey {
    SigningKey::from_bytes(&[seed; 32])
}

fn trust(
    principal: &str,
    role: LearningEvidenceRoleV1,
    signing: &SigningKey,
) -> LearningEvidenceTrustV1 {
    LearningEvidenceTrustV1 {
        principal_id: id(principal),
        role,
        public_key: signing.verifying_key().to_bytes(),
        binding_digest: digest(format!("binding-{principal}")),
        not_before: 1,
        expires_at: 100,
    }
}

fn verifier() -> LearningEvidenceVerifierV1 {
    LearningEvidenceVerifierV1::new(vec![
        trust("generator", LearningEvidenceRoleV1::Generator, &key(1)),
        trust("observer", LearningEvidenceRoleV1::Observer, &key(2)),
        trust("independent", LearningEvidenceRoleV1::Independent, &key(3)),
        trust(
            "unlearning-authority",
            LearningEvidenceRoleV1::UnlearningAuthority,
            &key(4),
        ),
        trust(
            "artifact-publisher",
            LearningEvidenceRoleV1::ArtifactPublisher,
            &key(5),
        ),
    ])
    .unwrap()
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let trust = verifier.trust(principal, role).unwrap();
    let signing = match principal {
        "generator" => key(1),
        "observer" => key(2),
        "independent" => key(3),
        "unlearning-authority" => key(4),
        "artifact-publisher" => key(5),
        _ => panic!("unknown principal"),
    };
    let nonce = NEXT_EVIDENCE.fetch_add(1, Ordering::Relaxed);
    let payload_digest = Digest32::of_bytes(payload);
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(format!("evidence-{principal}-{nonce}")),
        principal_id: trust.principal_id.clone(),
        role,
        binding_digest: trust.binding_digest,
        payload_digest,
        issued_at: 10,
        expires_at: 90,
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

struct Fixture {
    root: PathBuf,
    verifier: LearningEvidenceVerifierV1,
}

impl Fixture {
    fn new() -> Self {
        let suffix = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-bellman-final-use-v3-{}-{suffix}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        Self {
            root,
            verifier: verifier(),
        }
    }

    fn writer(&self) -> LedgerWriter {
        let ledger = self.root.join("ledger");
        let replay = self.root.join("replay");
        FileLedgerStoreV1::initialize(&ledger).unwrap();
        FileReplayStoreV1::initialize(&replay).unwrap();
        DurableLearningOwner::new(
            File::options().read(true).write(true).open(&ledger).unwrap(),
            File::options().read(true).write(true).open(&replay).unwrap(),
            self.verifier.clone(),
            ProductionOwnerConfigV1 {
                maximum_payload_bytes: 2 * 1024 * 1024,
                maximum_frame_bytes: 2 * 1024 * 1024,
                maximum_record_count: 1_024,
            },
        )
        .unwrap()
        .into_inner()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn decision(prefix: &str) -> DecisionRecordV2 {
    DecisionRecordV2 {
        record_id: id(format!("{prefix}.decision-record")),
        episode_id: id(format!("{prefix}.episode")),
        candidate_set_id: id(format!("{prefix}.candidate-set")),
        candidate_set_digest: digest(format!("{prefix}.candidates")),
        selected_candidate_id: id(format!("{prefix}.selected")),
        policy: PolicyFingerprintV1 {
            policy_id: id("policy"),
            policy_digest: digest("policy"),
            training_profile_digest: digest("training-profile"),
            objective_digest: digest("objective"),
            implementation_digest: digest("implementation"),
            generation: Generation::new(1).unwrap(),
        },
        candidate_scores: vec![],
        propensity: None,
        selected_candidate_log_propensity_q32: FixedQ32::ZERO,
        candidate_set_log_normalizer_q32: FixedQ32::ZERO,
        support_digest: digest(format!("{prefix}.support")),
        timestamp_millis: 1,
    }
}

fn outcome(
    record_id: &str,
    outcome_id: &str,
    predecessor: Option<&str>,
    episode_id: &str,
    value: i64,
) -> OutcomeRecordV1 {
    OutcomeRecordV1 {
        record_id: id(record_id),
        outcome_id: id(outcome_id),
        correction_predecessor_outcome_id: predecessor.map(id),
        episode_id: id(episode_id),
        objective_digest: digest("objective"),
        metrics: vec![],
        aggregate_score: FixedQ32::from_raw(value),
        artifact_kind: ArtifactKindV1::TaskResult,
        artifact_digest: digest(format!("artifact-{record_id}")),
        verifier_id: id("verifier"),
        support_digest: digest(format!("support-{record_id}")),
        timestamp_millis: 2,
    }
}

fn collect(owner: &mut LedgerWriter, prefix: &str, value: i64) -> StableId {
    let decision = decision(prefix);
    let signed = sign(
        owner.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&decision),
    );
    let head = owner.witness_frontier().unwrap().anchor.chain_digest;
    owner.append_decision(
        head,
        decision,
        &signed,
        ReplayId::new(format!("{prefix}.decision-replay")).unwrap(),
        50,
    )
    .unwrap();

    let outcome_id = id(format!("{prefix}.result"));
    let outcome = outcome(
        &format!("{prefix}.outcome-record"),
        outcome_id.as_str(),
        None,
        &format!("{prefix}.episode"),
        value,
    );
    let signed = sign(
        owner.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&outcome),
    );
    let head = owner.witness_frontier().unwrap().anchor.chain_digest;
    owner.append_outcome(head, outcome, &signed, 50).unwrap();
    outcome_id
}

fn qualified_dataset() -> (
    Fixture,
    LedgerWriter,
    DatasetSnapshotReceiptV3,
    StableId,
) {
    let fixture = Fixture::new();
    let mut owner = fixture.writer();
    let first_outcome = collect(&mut owner, "first", 0);
    collect(&mut owner, "second", FixedQ32::ONE.raw());
    let receipt = owner
        .freeze_dataset(id("dataset"), digest("policy"), 50)
        .unwrap();
    (fixture, owner, receipt, first_outcome)
}

fn runtime() -> RuntimeLimitsV1 {
    RuntimeLimitsV1::new(10_000, 1_000_000).unwrap()
}

fn training_profile(
    receipt: &DatasetSnapshotReceiptV3,
    maximum_absolute_error: FixedQ32,
) -> TrainingProfileV1 {
    TrainingProfileV1::new(
        Generation::new(1).unwrap(),
        receipt.snapshot.objective_digest,
        digest("sensor-core"),
        receipt.snapshot.eligible_frontier,
        1,
        maximum_absolute_error,
        runtime(),
    )
    .unwrap()
}

fn tabular_input(
    receipt: &DatasetSnapshotReceiptV3,
    varying_targets: bool,
) -> UnboundTabularOperatorPlanV3 {
    let sensor = id("sensor");
    let action = id("action");
    let samples = receipt
        .snapshot
        .source_record_digests
        .iter()
        .enumerate()
        .map(|(index, evidence_digest)| TabularOperatorSampleV1 {
            sample_id: id(format!("sample-{index}")),
            sensor_id: sensor.clone(),
            action_id: action.clone(),
            target: if varying_targets {
                FixedQ32::from_raw(i64::try_from(index).unwrap())
            } else {
                FixedQ32::ZERO
            },
            evidence_digest: *evidence_digest,
        })
        .collect();
    UnboundTabularOperatorPlanV3 {
        artifact_id: id("artifact"),
        producer_id: id("producer"),
        sensor_ids: vec![sensor],
        action_ids: vec![action],
        samples,
    }
}

fn append_correction(owner: &mut LedgerWriter, predecessor: &StableId) {
    let correction = outcome(
        "correction.record",
        "correction.result",
        Some(predecessor.as_str()),
        "first.episode",
        FixedQ32::ONE.raw(),
    );
    let signed = sign(
        owner.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&correction),
    );
    let head = owner.witness_frontier().unwrap().anchor.chain_digest;
    owner.append_outcome(head, correction, &signed, 50).unwrap();
}

fn world_input(
    receipt: &DatasetSnapshotReceiptV3,
    split_next_states: bool,
) -> UnboundWorldModelDatasetV3 {
    let samples = receipt
        .snapshot
        .source_record_digests
        .iter()
        .enumerate()
        .map(|(index, evidence_digest)| WorldModelSampleV1 {
            sample_id: id(format!("world-sample-{index}")),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: if split_next_states && index % 2 == 1 {
                id("next-b")
            } else {
                id("next-a")
            },
            outcome: FixedQ32::ZERO,
            evidence_digest: *evidence_digest,
        })
        .collect();
    UnboundWorldModelDatasetV3 {
        model_id: id("world-model"),
        samples,
    }
}

fn world_profile(receipt: &DatasetSnapshotReceiptV3) -> WorldModelProfileV1 {
    WorldModelProfileV1::new(
        Generation::new(1).unwrap(),
        receipt.snapshot.objective_digest,
        digest("sensor-core"),
        receipt.snapshot.eligible_frontier,
        1,
        FixedQ32::ZERO,
        runtime(),
    )
    .unwrap()
}

#[test]
fn tabular_v3_uses_profile_control_and_only_hands_off_pinned_payload() {
    let (_fixture, owner, receipt, _) = qualified_dataset();
    let profile = training_profile(&receipt, FixedQ32::ONE);
    let (verified, cancellation) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, false),
        &profile,
        receipt,
        50,
    )
    .unwrap();
    assert!(!cancellation.is_cancelled());
    let fitted = fit_tabular_operator_verified_v3(&owner, verified, 50).unwrap();
    let ready = revalidate_tabular_candidate_for_publication_v3(&owner, fitted, 50).unwrap();
    let prepared = ready.prepare_pinned_payload().unwrap();
    assert!(!prepared.pin().payload_digest.is_zero());
    let loaded = prepared.into_loaded().unwrap();
    let prediction = loaded.predict(&id("sensor"), &id("action")).unwrap();
    assert_eq!(prediction.value, FixedQ32::ZERO);
    assert!(!prediction.authority.grants_any());
}

#[test]
fn tabular_v3_observes_cancellation_and_fit_time_currentness() {
    let (_fixture, mut owner, receipt, predecessor) = qualified_dataset();
    let profile = training_profile(&receipt, FixedQ32::ONE);
    let (verified, cancellation) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, false),
        &profile,
        receipt.clone(),
        50,
    )
    .unwrap();
    cancellation.cancel();
    assert!(matches!(
        fit_tabular_operator_verified_v3(&owner, verified, 50),
        Err(FinalUseError::WorkControl(WorkControlError::Cancelled))
    ));

    let (verified, _) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, false),
        &profile,
        receipt,
        50,
    )
    .unwrap();
    append_correction(&mut owner, &predecessor);
    assert!(matches!(
        fit_tabular_operator_verified_v3(&owner, verified, 50),
        Err(FinalUseError::Ledger(_))
    ));
}

#[test]
fn tabular_v3_revalidates_again_before_publication() {
    let (_fixture, mut owner, receipt, predecessor) = qualified_dataset();
    let profile = training_profile(&receipt, FixedQ32::ONE);
    let (verified, _) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, false),
        &profile,
        receipt,
        50,
    )
    .unwrap();
    let fitted = fit_tabular_operator_verified_v3(&owner, verified, 50).unwrap();
    append_correction(&mut owner, &predecessor);
    assert!(matches!(
        revalidate_tabular_candidate_for_publication_v3(&owner, fitted, 50),
        Err(FinalUseError::Ledger(_))
    ));
}

#[test]
fn canonical_error_budget_is_an_admission_condition() {
    let (_fixture, owner, receipt, _) = qualified_dataset();
    let profile = training_profile(&receipt, FixedQ32::ZERO);
    let (verified, _) = verify_tabular_operator_plan_v3(
        &owner,
        tabular_input(&receipt, true),
        &profile,
        receipt,
        50,
    )
    .unwrap();
    assert!(matches!(
        fit_tabular_operator_verified_v3(&owner, verified, 50),
        Err(FinalUseError::Binding("tabular error budget"))
    ));
}

#[test]
fn world_v3_enforces_uncertainty_and_keeps_raw_model_private() {
    let (_fixture, owner, receipt, _) = qualified_dataset();
    let profile = world_profile(&receipt);
    let (verified, cancellation) = verify_world_model_dataset_v3(
        &owner,
        world_input(&receipt, false),
        &profile,
        receipt.clone(),
        50,
    )
    .unwrap();
    assert!(!cancellation.is_cancelled());
    let fitted = fit_transition_model_verified_v3(&owner, verified, 50).unwrap();
    let ready =
        revalidate_world_model_candidate_for_publication_v3(&owner, fitted, 50).unwrap();
    assert!(!ready.model_digest().is_zero());
    assert_eq!(ready.dataset_digest(), receipt.snapshot.dataset_digest);
    assert_eq!(ready.profile_digest(), profile.digest());

    let (verified, _) = verify_world_model_dataset_v3(
        &owner,
        world_input(&receipt, true),
        &profile,
        receipt,
        50,
    )
    .unwrap();
    assert!(matches!(
        fit_transition_model_verified_v3(&owner, verified, 50),
        Err(FinalUseError::Binding("world uncertainty budget"))
    ));
}
