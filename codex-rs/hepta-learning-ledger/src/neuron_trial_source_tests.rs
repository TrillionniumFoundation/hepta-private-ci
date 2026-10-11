//! Native durable LedgerWriter checks, not only synthetic JSON receipt checks.
use super::*;
use std::fs::{self, File, OpenOptions};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

use codex_hepta_types::{FixedQ32, ProbabilityQ32};
use ed25519_dalek::{Signer, SigningKey};

use crate::{
    ActivatedLearningTrustV1, AuthenticatedOutcomeV1, AuthenticatedPrincipalV1,
    CandidateSetCompletenessReceiptV1, DatasetFreezePlanV2, DurableLedger, LearningEvidenceTrustV1,
    LearningTrustDistributionV1, LearningTrustRootV1, LedgerRecovery, LedgerWitnessStore,
    OutcomeTerminalityV1,
    OutcomeWatermarkV1, ProductionDecisionV2, SignedLearningTrustDistributionV1,
    TrustedLearningSignerV1, activate_learning_trust, candidate_ids_digest_v2,
    candidate_order_digest_v2, decision_signing_payload_v2, outcome_signing_payload_v2,
};

static NEXT: AtomicU64 = AtomicU64::new(0);

fn id(x: &str) -> StableId {
    StableId::new(x.to_owned()).expect("valid id")
}
fn digest(x: &str) -> Digest32 {
    Digest32::of_bytes(x.as_bytes())
}
fn signer_seed(name: &str) -> u8 {
    match name {
        "generator" => 1,
        "observer" => 2,
        "evaluator" => 4,
        _ => panic!("unsupported test signing role"),
    }
}
fn signer(name: &str, role: LearningEvidenceRoleV1) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[signer_seed(name); 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
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
fn trust() -> ActivatedLearningTrustV1 {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("test-root"),
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("test-distribution"),
            generation: 1,
            effective_at: 20,
            trust: LearningEvidenceTrustV1 {
                scope_digest: digest("scope"),
                objective_digest: digest("objective"),
                authority_epoch: 7,
                signers: vec![
                    signer("generator", LearningEvidenceRoleV1::Generator),
                    signer("observer", LearningEvidenceRoleV1::Observer),
                    signer("evaluator", LearningEvidenceRoleV1::Evaluator),
                ],
            },
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    activate_learning_trust(&root, signed, None, 50).unwrap()
}
fn signed(
    writer: &LedgerWriter,
    name: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("signed-{name}")),
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
    evidence.signature = SigningKey::from_bytes(&[signer_seed(name); 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

struct Fixture {
    root: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-ledger-source-{}-{n}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        File::create(root.join("ledger")).unwrap();
        File::create(root.join("witness")).unwrap();
        Self { root }
    }
    fn file(&self, name: &str) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join(name))
            .unwrap()
    }
    fn directory(&self) -> File {
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(0x0200_0000)
                .open(&self.root)
                .unwrap()
        }
        #[cfg(not(windows))]
        {
            File::open(&self.root).unwrap()
        }
    }
    fn writer(&self) -> LedgerWriter {
        let ledger = DurableLedger::create(self.file("ledger"), digest("binding"), 64).unwrap();
        let witness = LedgerWitnessStore::create(self.file("witness"), digest("binding")).unwrap();
        let directory = self.directory();
        LedgerWriter::from_durable(ledger, witness, trust(), &directory, &directory).unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn append_decision(writer: &mut LedgerWriter) -> Digest32 {
    append_named_decision(
        writer,
        Digest32::ZERO,
        "decision-1",
        "episode-1",
        "candidate-set",
    )
}

fn append_named_decision(
    writer: &mut LedgerWriter,
    predecessor: Digest32,
    record: &str,
    episode: &str,
    set_id: &str,
) -> Digest32 {
    let candidates = vec![id("action"), id("abstain")];
    let request = ProductionDecisionV2 {
        record_id: id(record),
        episode_id: id(episode),
        run_snapshot_digest: digest("run"),
        objective_digest: digest("objective"),
        policy_digest: digest("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id(set_id),
            state_digest: digest("state"),
            generator_id: id("generator"),
            generator_code_digest: digest("generator-code"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: digest(&format!("{record}-support")),
    };
    let payload = decision_signing_payload_v2(&request).unwrap();
    let evidence = signed(
        writer,
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    writer
        .append_decision(predecessor, request, &evidence, 50)
        .unwrap()
        .chain_digest
}
fn append_terminal(writer: &mut LedgerWriter, predecessor: Digest32) {
    let request = AuthenticatedOutcomeV1 {
        record_id: id("outcome-1"),
        outcome_id: id("outcome-id-1"),
        episode_id: id("episode-1"),
        observer: signer("observer", LearningEvidenceRoleV1::Observer).principal,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(101)),
        unit_profile_digest: digest("units"),
        support_digest: digest("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    };
    let payload = outcome_signing_payload_v2(&request);
    let evidence = signed(
        writer,
        "observer",
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    writer
        .append_outcome(predecessor, request, &evidence, 50)
        .unwrap();
}
fn freeze(
    writer: &LedgerWriter,
) -> (
    LedgerSnapshot,
    DatasetFreezePlanV2,
    SignedLearningEvidenceV1,
    DatasetSnapshotReceiptV3,
) {
    let snapshot = writer.snapshot().unwrap();
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion"),
    };
    let payload = dataset_freeze_signing_payload_v2(&snapshot, &plan).unwrap();
    let evidence = signed(
        writer,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    let receipt = writer.freeze_dataset(plan.clone(), &evidence, 50).unwrap();
    (snapshot, plan, evidence, receipt)
}

#[test]
fn native_owner_pairs_actual_durable_decision_and_terminal_without_labels() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_decision(&mut writer);
    append_terminal(&mut writer, head);
    let (snapshot, plan, signed_freeze, dataset) = freeze(&writer);
    let report = writer
        .read_neuron_trial_source_v1(&snapshot, &plan, &signed_freeze, &dataset, 50)
        .unwrap();
    assert_eq!(report.terminal_joins.len(), 1);
    assert_eq!(
        report.terminal_joins[0].decision_record_id,
        id("decision-1")
    );
    assert_eq!(report.terminal_joins[0].outcome_record_id, id("outcome-1"));
    assert_eq!(report.pending_episodes, 0);
    assert_eq!(report.censored_episodes, 0);
    assert_eq!(report.authority, AuthorityPosture::DENY_ALL);
    assert!(report.validate_integrity());
    assert!(!format!("{report:?}").contains("FixedQ32"));
    let mut corrupted = report.clone();
    corrupted.terminal_joins[0].policy_digest = digest("forged-policy");
    assert!(!corrupted.validate_integrity());
}

#[test]
fn native_owner_keeps_missing_outcomes_as_pending_not_zero_reward() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_decision(&mut writer);
    append_terminal(&mut writer, head);
    let predecessor = writer.snapshot().unwrap().head_digest;
    append_named_decision(
        &mut writer,
        predecessor,
        "decision-pending",
        "episode-pending",
        "candidate-set-pending",
    );
    let (snapshot, plan, signed_freeze, dataset) = freeze(&writer);
    let report = writer
        .read_neuron_trial_source_v1(&snapshot, &plan, &signed_freeze, &dataset, 50)
        .unwrap();
    assert_eq!(report.terminal_joins.len(), 1);
    assert_eq!(report.pending_episodes, 1);
    assert!(report.validate_integrity());
}

#[test]
fn native_owner_rejects_changed_signed_freeze_and_forged_dataset() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_decision(&mut writer);
    append_terminal(&mut writer, head);
    let (snapshot, plan, signature, dataset) = freeze(&writer);
    let mut tampered = signature.clone();
    tampered.signature[0] ^= 1;
    assert!(
        writer
            .read_neuron_trial_source_v1(&snapshot, &plan, &tampered, &dataset, 50)
            .is_err()
    );
    let mut forged = dataset.clone();
    forged.snapshot.objective_digest = digest("wrong-objective");
    assert!(
        writer
            .read_neuron_trial_source_v1(&snapshot, &plan, &signature, &forged, 50)
            .is_err()
    );
}

#[test]
fn native_owner_rejects_frozen_ledger_that_is_not_current_prefix() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_decision(&mut writer);
    append_terminal(&mut writer, head);
    let (mut snapshot, plan, signature, dataset) = freeze(&writer);
    snapshot.head_digest = digest("wrong-chain-head");
    assert!(
        writer
            .read_neuron_trial_source_v1(&snapshot, &plan, &signature, &dataset, 50)
            .is_err()
    );
}

#[test]
fn native_owner_invalidates_frozen_terminal_after_corrected_outcome() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_decision(&mut writer);
    append_terminal(&mut writer, head);
    let (frozen, plan, evidence, dataset) = freeze(&writer);
    assert_eq!(
        writer
            .read_neuron_trial_source_v1(&frozen, &plan, &evidence, &dataset, 50)
            .unwrap()
            .terminal_joins
            .len(),
        1
    );
    let corrected = AuthenticatedOutcomeV1 {
        record_id: id("outcome-corrected"),
        outcome_id: id("outcome-id-corrected"),
        episode_id: id("episode-1"),
        observer: signer("observer", LearningEvidenceRoleV1::Observer).principal,
        observed_at: Some(47),
        value: Some(FixedQ32::from_raw(202)),
        unit_profile_digest: digest("units"),
        support_digest: digest("corrected-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 49,
            expected_delay_profile_digest: digest("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: Some(id("outcome-id-1")),
            finalized_at: Some(49),
        },
    };
    let payload = outcome_signing_payload_v2(&corrected);
    let signature = signed(
        &writer,
        "observer",
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    let predecessor = writer.snapshot().unwrap().head_digest;
    writer
        .append_outcome(predecessor, corrected, &signature, 50)
        .unwrap();
    assert!(
        writer
            .read_neuron_trial_source_v1(&frozen, &plan, &evidence, &dataset, 50)
            .is_err()
    );
}

#[test]
fn native_owner_reopens_durable_ledger_and_preserves_freeze_identity() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_decision(&mut writer);
    append_terminal(&mut writer, head);
    let (frozen, plan, evidence, dataset) = freeze(&writer);
    let frontier = writer.witness_frontier().unwrap();
    drop(writer);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        digest("binding"),
        64,
        LedgerRecovery::Acknowledged(frontier.anchor),
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), digest("binding")).unwrap();
    let directory = fixture.directory();
    let recovered =
        LedgerWriter::from_durable(ledger, witness, trust(), &directory, &directory).unwrap();
    let source = recovered
        .read_neuron_trial_source_v1(&frozen, &plan, &evidence, &dataset, 50)
        .unwrap();
    assert_eq!(source.terminal_joins.len(), 1);
    assert!(source.validate_integrity());
}
