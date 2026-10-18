//! Real owner admission tests. Keys and timestamps are isolated test fixtures;
//! no fixture token constructor or skipped admission path is used.
#![cfg(unix)]

use super::*;
use crate::LoadedTabularOperatorV2;
use crate::OperatorAdmissionStageV1;
use crate::TABULAR_ARTIFACT_SCHEMA_V1;
use crate::TABULAR_PAYLOAD_SCHEMA_V1;
use crate::TabularOperatorSampleV1;
use crate::TabularPayloadPinV2;
use crate::encode_tabular_payload_v1;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

static NEXT: AtomicU64 = AtomicU64::new(0);

#[path = "owner_dataset_expiry_tests.rs"]
mod expiry_tests;

#[path = "owner_trust_window_tests.rs"]
mod trust_window_tests;

#[path = "owner_terminal_trust_tests.rs"]
mod terminal_trust_tests;

#[path = "owner_capability_issuance_tests.rs"]
mod capability_issuance_tests;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn signer(name: &str, seed: u8, role: LearningEvidenceRoleV1) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: hash(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: hash("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(&format!("{name}-controller")),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn activated_trust_at(expires_at: u64, now: u64) -> ActivatedLearningTrustV1 {
    let key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("root"),
        scope_digest: hash("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: now - 49,
        expires_at: expires_at.checked_mul(2).unwrap().max(200),
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("distribution"),
            generation: 1,
            effective_at: now - 30,
            trust: LearningEvidenceTrustV1 {
                scope_digest: hash("scope"),
                objective_digest: hash("objective"),
                authority_epoch: 7,
                signers: vec![
                    signer("generator", 1, LearningEvidenceRoleV1::Generator),
                    signer("observer", 2, LearningEvidenceRoleV1::Observer),
                    signer("evaluator", 3, LearningEvidenceRoleV1::Evaluator),
                ]
                .into_iter()
                .map(|mut signer| {
                    signer.principal.authenticated_at = now - 40;
                    signer.principal.expires_at = expires_at
                        .checked_add((expires_at / 10).max(10))
                        .unwrap()
                        .max(100);
                    signer
                })
                .collect(),
            },
        },
        root_id: root.root_id.clone(),
        issued_at: now - 35,
        expires_at,
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    activate_learning_trust(&root, signed, None, now).unwrap()
}

fn sign(
    owner: &LedgerWriter,
    name: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    sign_at(owner, name, seed, role, payload, 20, 70)
}

fn sign_at(
    owner: &LedgerWriter,
    name: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    issued_at: u64,
    expires_at: u64,
) -> SignedLearningEvidenceV1 {
    let mut result = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence-{name}")),
        principal_id: id(name),
        role,
        trust_digest: owner.verifier().trust_digest(),
        scope_digest: hash("scope"),
        objective_digest: hash("objective"),
        authority_epoch: 7,
        issued_at,
        expires_at,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    result.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&result.signing_bytes())
        .to_bytes();
    result
}

struct Fixture {
    owner: LedgerWriter,
    root: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        Self::with_candidates(vec![id("action"), id("abstain")])
    }

    fn with_candidates(candidates: Vec<StableId>) -> Self {
        Self::with_candidates_and_expiry(candidates, 90)
    }

    fn with_candidates_and_expiry(candidates: Vec<StableId>, expires_at: u64) -> Self {
        Self::with_candidates_and_expiry_at(candidates, expires_at, 50)
    }

    fn with_candidates_and_expiry_at(candidates: Vec<StableId>, expires_at: u64, now: u64) -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-owner-dataset-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let file = |name: &str| {
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(root.join(name))
                .unwrap()
        };
        let ledger = DurableLedger::create(file("ledger"), hash("binding"), 64).unwrap();
        let witness = LedgerWitnessStore::create(file("witness"), hash("binding")).unwrap();
        let directory = File::open(&root).unwrap();
        let mut owner = LedgerWriter::from_durable(
            ledger,
            witness,
            activated_trust_at(expires_at, now),
            &directory,
            &directory,
        )
        .unwrap();
        append_fixture_episode_at(&mut owner, candidates, "action", "", expires_at, now);
        Self { owner, root }
    }
    fn terminal() -> Self {
        let candidates = vec![id("action"), id("abstain")];
        let mut fixture = Self::with_candidates_and_expiry(candidates.clone(), 90_000_000);
        append_fixture_episode(
            &mut fixture.owner,
            candidates,
            "abstain",
            "-abstain",
            90_000_000,
        );
        fixture
    }

    fn dataset(&self) -> (DatasetSnapshotReceiptV3, SignedLearningEvidenceV1) {
        self.dataset_at(50, 70)
    }

    fn dataset_at(
        &self,
        now: u64,
        expires_at: u64,
    ) -> (DatasetSnapshotReceiptV3, SignedLearningEvidenceV1) {
        let plan = DatasetFreezePlanV2 {
            snapshot_id: id("dataset"),
            objective_digest: hash("objective"),
            inclusion_policy_digest: hash("inclusion"),
        };
        let signed = sign_at(
            &self.owner,
            "evaluator",
            3,
            LearningEvidenceRoleV1::Evaluator,
            &dataset_freeze_signing_payload_v2(&self.owner.snapshot().unwrap(), &plan).unwrap(),
            now - 30,
            expires_at,
        );
        (
            self.owner.freeze_dataset(plan, &signed, now).unwrap(),
            signed,
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn append_fixture_episode(
    owner: &mut LedgerWriter,
    candidates: Vec<StableId>,
    selected_action: &str,
    suffix: &str,
    expires_at: u64,
) {
    append_fixture_episode_at(owner, candidates, selected_action, suffix, expires_at, 50)
}

fn append_fixture_episode_at(
    owner: &mut LedgerWriter,
    candidates: Vec<StableId>,
    selected_action: &str,
    suffix: &str,
    expires_at: u64,
    now: u64,
) {
    let decision = ProductionDecisionV2 {
        record_id: id(&format!("decision{suffix}")),
        episode_id: id(&format!("episode{suffix}")),
        run_snapshot_digest: hash("run"),
        objective_digest: hash("objective"),
        policy_digest: hash("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id(selected_action),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id(&format!("set{suffix}")),
            state_digest: hash("state"),
            generator_id: id("generator"),
            generator_code_digest: hash("code"),
            grammar_digest: hash("grammar"),
            hard_filter_digest: hash("filter"),
            truncation_digest: hash("truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: u32::try_from(candidates.len()).unwrap(),
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: hash("decision-support"),
    };
    let signed = sign_at(
        owner,
        "generator",
        1,
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&decision).unwrap(),
        now - 30,
        now + 20,
    );
    let append = owner
        .append_decision(
            owner.snapshot().unwrap().head_digest,
            decision,
            &signed,
            now,
        )
        .unwrap();
    let mut observer = signer("observer", 2, LearningEvidenceRoleV1::Observer).principal;
    observer.authenticated_at = now - 40;
    observer.expires_at = expires_at
        .checked_add((expires_at / 10).max(10))
        .unwrap()
        .max(100);
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id(&format!("outcome-record{suffix}")),
        outcome_id: id(&format!("outcome{suffix}")),
        episode_id: id(&format!("episode{suffix}")),
        observer,
        observed_at: Some(now - 10),
        value: Some(FixedQ32::from_raw(20)),
        unit_profile_digest: hash("unit"),
        support_digest: hash("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: now - 5,
            expected_delay_profile_digest: hash("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(now - 4),
        },
    };
    let signed = sign_at(
        owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&outcome),
        now - 30,
        now + 20,
    );
    owner
        .append_outcome(append.chain_digest, outcome, &signed, now)
        .unwrap();
}

fn plan(receipt: &DatasetSnapshotReceiptV3) -> TabularOperatorPlanV1 {
    TabularOperatorPlanV1 {
        artifact_id: id("operator"),
        producer_id: id("generator"),
        generation: Generation::new(1).unwrap(),
        objective_digest: hash("objective"),
        dataset_digest: receipt.snapshot.dataset_digest,
        sensor_core_digest: hash("sensors"),
        training_profile_digest: hash("profile"),
        minimum_samples_per_cell: 1,
        sensor_ids: vec![id("sensor")],
        action_ids: vec![id("action")],
        samples: receipt
            .snapshot
            .source_record_digests
            .iter()
            .enumerate()
            .map(|(index, evidence)| TabularOperatorSampleV1 {
                sample_id: id(&format!("row-{index}")),
                sensor_id: id("sensor"),
                action_id: id("action"),
                target: FixedQ32::from_raw(20),
                evidence_digest: *evidence,
            })
            .collect(),
    }
}

#[test]
fn owner_dataset_signed_freeze_and_rows_reach_real_trainer() {
    let fixture = Fixture::new();
    let (receipt, freeze) = fixture.dataset();
    let input = plan(&receipt);
    let payload = tabular_training_signing_payload_v2(&input, &receipt, &fixture.owner).unwrap();
    let row = sign(
        &fixture.owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    let verified =
        verify_tabular_operator_plan_v3(input.clone(), &receipt, &fixture.owner, &freeze, &row, 50)
            .unwrap();
    let fitted = fit_tabular_operator_verified_v3(verified, 51).unwrap();
    assert_eq!(fitted, fit_tabular_operator_strict_v2(input).unwrap());
}

#[test]
fn signed_training_rejects_config_target_duplicate_epoch_and_signature_substitution() {
    let fixture = Fixture::new();
    let (receipt, freeze) = fixture.dataset();
    let original = plan(&receipt);
    let payload = tabular_training_signing_payload_v2(&original, &receipt, &fixture.owner).unwrap();
    let row = sign(
        &fixture.owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    for mutation in 0..5 {
        let mut changed = original.clone();
        match mutation {
            0 => changed.minimum_samples_per_cell = 2,
            1 => changed.action_ids.push(id("other-action")),
            2 => changed.samples[0].target = FixedQ32::from_raw(999),
            3 => changed.samples.push(changed.samples[0].clone()),
            4 => changed.producer_id = id("imposter"),
            _ => unreachable!(),
        }
        assert!(
            verify_tabular_operator_plan_v3(changed, &receipt, &fixture.owner, &freeze, &row, 50)
                .is_err(),
            "mutation {mutation}"
        );
    }
    for mutation in 0..4 {
        let mut changed = row.clone();
        match mutation {
            0 => changed.authority_epoch += 1,
            1 => changed.role = LearningEvidenceRoleV1::Evaluator,
            2 => changed.signature[0] ^= 1,
            3 => changed.trust_digest = hash("forged-registry"),
            _ => unreachable!(),
        }
        assert!(
            verify_tabular_operator_plan_v3(
                original.clone(),
                &receipt,
                &fixture.owner,
                &freeze,
                &changed,
                50
            )
            .is_err()
        );
    }
    let mut forged_freeze = freeze;
    forged_freeze.signature[0] ^= 1;
    assert!(
        verify_tabular_operator_plan_v3(
            original,
            &receipt,
            &fixture.owner,
            &forged_freeze,
            &row,
            50
        )
        .is_err()
    );
}

#[test]
fn owner_proof_expires_before_fit_and_reordered_rows_keep_same_signature() {
    let fixture = Fixture::new();
    let (receipt, freeze) = fixture.dataset();
    let mut input = plan(&receipt);
    let payload = tabular_training_signing_payload_v2(&input, &receipt, &fixture.owner).unwrap();
    input.samples.reverse();
    assert_eq!(
        payload,
        tabular_training_signing_payload_v2(&input, &receipt, &fixture.owner).unwrap()
    );
    let row = sign(
        &fixture.owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    let verified =
        verify_tabular_operator_plan_v3(input.clone(), &receipt, &fixture.owner, &freeze, &row, 50)
            .unwrap();
    assert!(fit_tabular_operator_verified_v3(verified, 71).is_err());
    let verified =
        verify_tabular_operator_plan_v3(input, &receipt, &fixture.owner, &freeze, &row, 50)
            .unwrap();
    assert!(matches!(
        fit_tabular_operator_verified_v3(verified, 49),
        Err(OperatorDatasetBindingError::ClockRegression)
    ));
}

#[test]
fn owner_dataset_rejects_oversized_signed_rows_before_canonicalization() {
    let fixture = Fixture::new();
    let (receipt, _) = fixture.dataset();
    let mut input = plan(&receipt);
    input.samples = vec![input.samples[0].clone(); MAX_SIGNED_OPERATOR_ROWS + 1];
    assert!(matches!(
        tabular_training_signing_payload_v2(&input, &receipt, &fixture.owner),
        Err(OperatorDatasetBindingError::Bounds)
    ));
}

fn peak_rss_kib() -> u64 {
    fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|status| {
            status
                .lines()
                .find(|line| line.starts_with("VmHWM:"))
                .and_then(|line| line.split_whitespace().nth(1))
                .and_then(|value| value.parse().ok())
        })
        .unwrap_or(0)
}

#[test]
#[ignore = "explicit qualification performance profile"]
fn full_v3_qualification_path_profile() {
    let total = Instant::now();
    let fixture = Fixture::new();

    let started = Instant::now();
    let (receipt, freeze) = fixture.dataset();
    let freeze_us = started.elapsed().as_micros();

    let input = plan(&receipt);
    let started = Instant::now();
    let payload = tabular_training_signing_payload_v2(&input, &receipt, &fixture.owner).unwrap();
    let row = sign(
        &fixture.owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    let canonicalize_and_sign_us = started.elapsed().as_micros();

    let started = Instant::now();
    let verified =
        verify_tabular_operator_plan_v3(input, &receipt, &fixture.owner, &freeze, &row, 50)
            .unwrap();
    assert_eq!(
        verified.admission_stage(),
        OperatorAdmissionStageV1::SourceAuthenticated
    );
    let owner_admission_us = started.elapsed().as_micros();

    let started = Instant::now();
    let artifact = fit_tabular_operator_verified_v3(verified, 51).unwrap();
    let fit_with_revalidation_us = started.elapsed().as_micros();

    let started = Instant::now();
    let bytes = encode_tabular_payload_v1(&artifact).unwrap();
    let encode_us = started.elapsed().as_micros();

    let payload_path = fixture.root.join("operator-payload");
    let started = Instant::now();
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&payload_path)
        .unwrap();
    output.write_all(&bytes).unwrap();
    output.sync_all().unwrap();
    drop(output);
    let persist_us = started.elapsed().as_micros();

    let started = Instant::now();
    let mut reopened = Vec::new();
    File::open(&payload_path)
        .unwrap()
        .read_to_end(&mut reopened)
        .unwrap();
    let pin = TabularPayloadPinV2 {
        artifact_id: artifact.artifact_id.clone(),
        producer_id: artifact.producer_id.clone(),
        artifact_schema_version: TABULAR_ARTIFACT_SCHEMA_V1,
        payload_schema_version: TABULAR_PAYLOAD_SCHEMA_V1,
        payload_digest: Digest32::of_bytes(&reopened),
        artifact_digest: artifact.artifact_digest,
        objective_digest: artifact.objective_digest,
        dataset_digest: artifact.dataset_digest,
        sensor_core_digest: artifact.sensor_core_digest,
        training_profile_digest: artifact.training_profile_digest,
        runtime_profile_digest: hash("runtime-profile"),
        trust_digest: fixture.owner.verifier().trust_digest(),
        registry_head_digest: receipt.snapshot.ledger_head_digest,
        authority_epoch: fixture.owner.verifier().authority_epoch(),
        generation: artifact.generation,
    };
    let loaded = LoadedTabularOperatorV2::from_pinned_payload_v2(&reopened, &pin).unwrap();
    assert_eq!(
        loaded.admission_stage(),
        OperatorAdmissionStageV1::ImmutableCandidate
    );
    let reload_us = started.elapsed().as_micros();

    let started = Instant::now();
    let prediction = loaded.predict(&id("sensor"), &id("action")).unwrap();
    let first_prediction_us = started.elapsed().as_micros();
    assert_eq!(prediction.value.raw(), 20);

    println!(
        "LEARNING_OPERATOR_FULL_PATH_PROFILE={{\"rows\":{},\"payload_bytes\":{},\"peak_rss_kib\":{},\"freeze_us\":{},\"canonicalize_and_sign_us\":{},\"owner_admission_us\":{},\"fit_with_revalidation_us\":{},\"encode_us\":{},\"persist_us\":{},\"reload_us\":{},\"first_prediction_us\":{},\"total_us\":{}}}",
        receipt.snapshot.source_record_digests.len(),
        reopened.len(),
        peak_rss_kib(),
        freeze_us,
        canonicalize_and_sign_us,
        owner_admission_us,
        fit_with_revalidation_us,
        encode_us,
        persist_us,
        reload_us,
        first_prediction_us,
        total.elapsed().as_micros(),
    );
}

#[test]
fn world_final_use_request_cannot_relabel_authoritative_training_trust() {
    // Public issuance now checks actual elapsed time after owner verification.
    // Seconds-long signed TTLs isolate trust substitution from expiration.
    let fixture =
        Fixture::with_candidates_and_expiry(vec![id("action"), id("abstain")], 90_000_000);
    let (receipt, freeze) = fixture.dataset();
    let freeze = trust_window_tests::sign_until_at(freeze, 3, 95_000_000);
    let model_id = id("world-model");
    let samples: Vec<_> = receipt
        .snapshot
        .source_record_digests
        .iter()
        .enumerate()
        .map(|(index, evidence_digest)| WorldModelSampleV1 {
            sample_id: id(&format!("world-row-{index}")),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: id("next-state"),
            outcome: FixedQ32::from_raw(20),
            evidence_digest: *evidence_digest,
        })
        .collect();
    let row_payload =
        world_model_training_signing_payload_v2(&model_id, &samples, &receipt, &fixture.owner)
            .expect("owner row commitment");
    let row = sign(
        &fixture.owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        &row_payload,
    );
    let row = trust_window_tests::sign_until_at(row, 2, 95_000_000);
    let profile = crate::WorldModelProfileV1::new(
        hash("objective"),
        hash("sensors"),
        receipt.snapshot.eligible_frontier,
        /*minimum_support*/ 1,
        FixedQ32::ONE,
        FixedQ32::ONE,
        ProbabilityQ32::ONE,
        FixedQ32::ONE,
        crate::OperatorResourceBudgetV1::qualification_default(),
    )
    .expect("profile");
    let request = |trust_digest| {
        crate::WorldModelTrainingRequestV1::new(
            model_id.clone(),
            Generation::new(1).expect("generation"),
            profile.clone(),
            trust_digest,
            hash("registry"),
            hash("train-window"),
            hash("holdout-window"),
            hash("future-window"),
            /*predecessor_model_digest*/ None,
            FixedQ32::ZERO,
            FixedQ32::ZERO,
            ProbabilityQ32::ZERO,
            FixedQ32::ZERO,
            hash("change-point"),
            /*retained_until*/ 70_000_000,
            /*expires_at*/ 80_000_000,
            samples.clone(),
        )
        .expect("request")
    };
    let fence = crate::FinalUseFenceV1::new(
        receipt.snapshot.ledger_head_digest,
        receipt.snapshot.eligible_frontier,
        Generation::new(1).expect("generation"),
        /*expected_authority_epoch*/ 7,
        /*expected_stop_epoch*/ 3,
        /*absolute_deadline_unix_micros*/ 80_000_000,
    )
    .expect("fence");
    let witness = crate::FinalUseWitnessV1::new(
        /*observed_at_unix_micros*/ 50_000_000,
        receipt.snapshot.ledger_head_digest,
        receipt.snapshot.eligible_frontier,
        Generation::new(1).expect("generation"),
        /*authority_epoch*/ 7,
        /*stop_epoch*/ 3,
        /*stop_requested*/ false,
    )
    .expect("witness");
    assert!(
        crate::issue_world_model_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &row,
            request(fixture.owner.verifier().trust_digest()),
            fence,
            crate::WorkControlV1::new(),
            &witness,
        )
        .is_ok()
    );
    assert!(matches!(
        crate::issue_world_model_final_use_capability_v1(
            &fixture.owner,
            &receipt,
            &freeze,
            &row,
            request(hash("foreign-trust")),
            fence,
            crate::WorkControlV1::new(),
            &witness,
        ),
        Err(crate::FinalUseErrorV1::Binding(
            "world-model request does not name the training owner's trust"
        ))
    ));
}

#[path = "owner_real_clock_tests.rs"]
mod real_clock_tests;
