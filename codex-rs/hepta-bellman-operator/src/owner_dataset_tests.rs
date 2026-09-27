//! Real owner admission tests. Keys and timestamps are isolated test fixtures;
//! no fixture token constructor or skipped admission path is used.
#![cfg(unix)]

use super::*;
use crate::TabularOperatorSampleV1;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);
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

fn activated_trust() -> ActivatedLearningTrustV1 {
    let key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("root"),
        scope_digest: hash("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("distribution"),
            generation: 1,
            effective_at: 20,
            trust: LearningEvidenceTrustV1 {
                scope_digest: hash("scope"),
                objective_digest: hash("objective"),
                authority_epoch: 7,
                signers: vec![
                    signer("generator", 1, LearningEvidenceRoleV1::Generator),
                    signer("observer", 2, LearningEvidenceRoleV1::Observer),
                    signer("evaluator", 3, LearningEvidenceRoleV1::Evaluator),
                ],
            },
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    activate_learning_trust(&root, signed, None, 50).unwrap()
}

fn sign(
    owner: &LedgerWriter,
    name: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut result = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence-{name}")),
        principal_id: id(name),
        role,
        trust_digest: owner.verifier().trust_digest(),
        scope_digest: hash("scope"),
        objective_digest: hash("objective"),
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 70,
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
        let mut owner =
            LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
                .unwrap();
        let candidates = vec![id("action"), id("abstain")];
        let decision = ProductionDecisionV2 {
            record_id: id("decision"),
            episode_id: id("episode"),
            run_snapshot_digest: hash("run"),
            objective_digest: hash("objective"),
            policy_digest: hash("policy"),
            candidate_ids: candidates.clone(),
            selected_candidate_id: id("action"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id("set"),
                state_digest: hash("state"),
                generator_id: id("generator"),
                generator_code_digest: hash("code"),
                grammar_digest: hash("grammar"),
                hard_filter_digest: hash("filter"),
                truncation_digest: hash("truncation"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 2,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: hash("decision-support"),
        };
        let signed = sign(
            &owner,
            "generator",
            1,
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&decision).unwrap(),
        );
        let append = owner
            .append_decision(Digest32::ZERO, decision, &signed, 50)
            .unwrap();
        let outcome = AuthenticatedOutcomeV1 {
            record_id: id("outcome-record"),
            outcome_id: id("outcome"),
            episode_id: id("episode"),
            observer: signer("observer", 2, LearningEvidenceRoleV1::Observer).principal,
            observed_at: Some(40),
            value: Some(FixedQ32::from_raw(20)),
            unit_profile_digest: hash("unit"),
            support_digest: hash("outcome-support"),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: 45,
                expected_delay_profile_digest: hash("delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(46),
            },
        };
        let signed = sign(
            &owner,
            "observer",
            2,
            LearningEvidenceRoleV1::Observer,
            &outcome_signing_payload_v2(&outcome),
        );
        owner
            .append_outcome(append.chain_digest, outcome, &signed, 50)
            .unwrap();
        Self { owner, root }
    }
    fn dataset(&self) -> (DatasetSnapshotReceiptV3, SignedLearningEvidenceV1) {
        let plan = DatasetFreezePlanV2 {
            snapshot_id: id("dataset"),
            objective_digest: hash("objective"),
            inclusion_policy_digest: hash("inclusion"),
        };
        let signed = sign(
            &self.owner,
            "evaluator",
            3,
            LearningEvidenceRoleV1::Evaluator,
            &dataset_freeze_signing_payload_v2(&self.owner.snapshot().unwrap(), &plan).unwrap(),
        );
        (
            self.owner.freeze_dataset(plan, &signed, 50).unwrap(),
            signed,
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
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
