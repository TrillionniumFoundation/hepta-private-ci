//! Native durable LedgerWriter checks, not only synthetic JSON receipt checks.
use super::*;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::ActivatedLearningTrustV1;
use crate::AuthenticatedOutcomeV1;
use crate::AuthenticatedPrincipalV1;
use crate::CandidateSetCompletenessReceiptV1;
use crate::DatasetFreezePlanV2;
use crate::DurableLedger;
use crate::LearningEvidenceTrustV1;
use crate::LearningTrustDistributionV1;
use crate::LearningTrustRootV1;
use crate::LedgerRecovery;
use crate::LedgerWitnessStore;
use crate::OutcomeTerminalityV1;
use crate::OutcomeWatermarkV1;
use crate::ProductionDecisionV2;
use crate::SignedLearningTrustDistributionV1;
use crate::TrustedLearningSignerV1;
use crate::activate_learning_trust;
use crate::candidate_ids_digest_v2;
use crate::candidate_order_digest_v2;
use crate::decision_signing_payload_v2;
use crate::outcome_signing_payload_v2;

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

#[test]
fn native_observer_signs_one_real_frozen_decision_and_terminal_neuron_tick_link() {
    use codex_hepta_types::Generation;
    use crate::neuron_trial_observed_tick::neuron_trial_observer_tick_link_payload_v1;

    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_decision(&mut writer);
    append_terminal(&mut writer, head);
    let (snapshot, plan, frozen_signature, dataset) = freeze(&writer);
    let source = writer
        .read_neuron_trial_source_v1(&snapshot, &plan, &frozen_signature, &dataset, 50)
        .unwrap();
    let pair = &source.terminal_joins[0];
    let tick_digest = digest("actual-committed-neuron-tick");
    let tick_generation = Generation::new(1).unwrap();
    let payload = neuron_trial_observer_tick_link_payload_v1(
        &source,
        pair,
        tick_digest,
        plan.objective_digest,
        tick_generation,
    )
    .unwrap();
    let mut observer = signed(
        &writer,
        "observer",
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    // The independent Observer cannot certify a future terminal Outcome
    // before its own authenticated 46-second finalization.
    assert!(writer
        .read_observer_linked_neuron_tick_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &pair.episode_id,
            tick_digest,
            plan.objective_digest,
            tick_generation,
            &observer,
            50,
        )
        .is_err());
    observer.issued_at = 50;
    observer.signature = SigningKey::from_bytes(&[signer_seed("observer"); 32])
        .sign(&observer.signing_bytes())
        .to_bytes();
    let receipt = writer
        .read_observer_linked_neuron_tick_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &pair.episode_id,
            tick_digest,
            plan.objective_digest,
            tick_generation,
            &observer,
            50,
        )
        .unwrap();
    assert!(receipt.validate_integrity());
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(receipt.tick_observation_digest, tick_digest);
    assert_eq!(receipt.decision_event_digest, pair.decision_event_digest);
    assert_eq!(receipt.observer_controller_id, id("observer-controller"));
    assert_eq!(receipt.observer_signed_at, 50);

    let mut changed = receipt.clone();
    changed.tick_observation_digest = digest("another-tick");
    assert!(!changed.validate_integrity());
    assert!(writer
        .read_observer_linked_neuron_tick_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &pair.episode_id,
            digest("another-tick"),
            plan.objective_digest,
            tick_generation,
            &observer,
            50,
        )
        .is_err());
    assert!(writer
        .read_observer_linked_neuron_tick_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &id("unknown-episode"),
            tick_digest,
            plan.objective_digest,
            tick_generation,
            &observer,
            50,
        )
        .is_err());
    assert!(writer
        .read_observer_linked_neuron_tick_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &pair.episode_id,
            tick_digest,
            digest("wrong-objective"),
            tick_generation,
            &observer,
            50,
        )
        .is_err());
    let wrong_role = signed(
        &writer,
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    assert!(writer
        .read_observer_linked_neuron_tick_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &pair.episode_id,
            tick_digest,
            plan.objective_digest,
            tick_generation,
            &wrong_role,
            50,
        )
        .is_err());
}

#[test]
fn native_observer_cohort_is_signed_complete_and_rejects_reused_tick() {
    use codex_hepta_types::Generation;
    use crate::neuron_trial_observer_cohort::NeuronTrialCohortTickV1;
    use crate::neuron_trial_observer_cohort::neuron_trial_observer_cohort_payload_v1;

    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_decision(&mut writer);
    append_terminal(&mut writer, head);
    let (snapshot, plan, frozen_signature, dataset) = freeze(&writer);
    let source = writer
        .read_neuron_trial_source_v1(&snapshot, &plan, &frozen_signature, &dataset, 50)
        .unwrap();
    let tick = NeuronTrialCohortTickV1 {
        episode_id: source.terminal_joins[0].episode_id.clone(),
        tick_observation_digest: digest("actual-agentd-committed-tick"),
        tick_generation: Generation::new(1).unwrap(),
    };
    let payload =
        neuron_trial_observer_cohort_payload_v1(&source, plan.objective_digest, &[tick.clone()])
            .unwrap();
    let mut signature = signed(
        &writer,
        "observer",
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    // The Observer cannot attest terminal labels before the actual Outcome
    // finalization, even if an attacker already knows the frozen event hashes.
    assert!(writer
        .read_observer_linked_neuron_cohort_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &[tick.clone()],
            &signature,
            50,
        )
        .is_err());
    signature.issued_at = 50;
    signature.signature = SigningKey::from_bytes(&[signer_seed("observer"); 32])
        .sign(&signature.signing_bytes())
        .to_bytes();
    let received = writer
        .read_observer_linked_neuron_cohort_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &[tick.clone()],
            &signature,
            50,
        )
        .unwrap();
    assert!(received.validate_integrity());
    assert_eq!(received.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(received.ticks, vec![tick.clone()]);
    assert_eq!(received.observer_controller_id, id("observer-controller"));
    assert!(!received.observer_trust_digest.is_zero());
    let mut forged_trust = received.clone();
    forged_trust.observer_trust_digest = digest("different-observer-trust");
    assert!(!forged_trust.validate_integrity());
    let mut forged_mixed = received.clone();
    forged_mixed.ticks.push(NeuronTrialCohortTickV1 {
        episode_id: id("new-episode"),
        tick_observation_digest: digest("new-unique-tick"),
        tick_generation: Generation::new(2).unwrap(),
    });
    forged_mixed.diagnostic_digest = forged_mixed.computed_digest();
    assert!(!forged_mixed.validate_integrity());
    let mut changed = received.clone();
    changed.ticks[0].tick_observation_digest = digest("different-tick");
    assert!(!changed.validate_integrity());
    let wrong_role = signed(
        &writer,
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    assert!(writer
        .read_observer_linked_neuron_cohort_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &[tick.clone()],
            &wrong_role,
            50,
        )
        .is_err());
    let modified = NeuronTrialCohortTickV1 {
        tick_observation_digest: digest("different-tick"),
        ..tick.clone()
    };
    assert!(writer
        .read_observer_linked_neuron_cohort_v1(
            &snapshot,
            &plan,
            &frozen_signature,
            &dataset,
            &[modified],
            &signature,
            50,
        )
        .is_err());
    assert!(neuron_trial_observer_cohort_payload_v1(
        &source,
        plan.objective_digest,
        &[],
    )
    .is_err());

    // Deliberately self-consistent FAKE source is enough for a structural
    // rejection test; only LedgerWriter can admit a genuine source. A single
    // real tick digest cannot be reused as two independent learning episodes.
    let mut fabricated = source.clone();
    let mut second = fabricated.terminal_joins[0].clone();
    second.episode_id = id("second-episode");
    second.decision_event_digest = digest("second-decision");
    second.outcome_event_digest = digest("second-outcome");
    fabricated.terminal_joins.push(second.clone());
    fabricated.diagnostic_digest = fabricated.computed_digest();
    assert!(fabricated.validate_integrity());
    let reused = NeuronTrialCohortTickV1 {
        episode_id: second.episode_id.clone(),
        tick_observation_digest: tick.tick_observation_digest,
        tick_generation: tick.tick_generation,
    };
    assert!(neuron_trial_observer_cohort_payload_v1(
        &fabricated,
        plan.objective_digest,
        &[tick.clone(), reused],
    )
    .is_err());
    // A frozen no-change cohort cannot silently mix two model generations,
    // even if the two tick digests are unique and the caller rehashes metadata.
    let mixed_generation = NeuronTrialCohortTickV1 {
        episode_id: second.episode_id.clone(),
        tick_observation_digest: digest("other-generation-tick"),
        tick_generation: Generation::new(2).unwrap(),
    };
    assert!(neuron_trial_observer_cohort_payload_v1(
        &fabricated,
        plan.objective_digest,
        &[tick.clone(), mixed_generation],
    )
    .is_err());
    let duplicated = NeuronTrialCohortTickV1 {
        tick_observation_digest: digest("different-unique-tick"),
        ..tick.clone()
    };
    assert!(neuron_trial_observer_cohort_payload_v1(
        &fabricated,
        plan.objective_digest,
        &[tick.clone(), duplicated],
    )
    .is_err());
    assert!(neuron_trial_observer_cohort_payload_v1(
        &fabricated,
        plan.objective_digest,
        &[tick.clone()],
    )
    .is_err());
    fabricated.pending_episodes += 1;
    fabricated.diagnostic_digest = fabricated.computed_digest();
    assert!(neuron_trial_observer_cohort_payload_v1(
        &fabricated,
        plan.objective_digest,
        &[tick, NeuronTrialCohortTickV1 {
            episode_id: second.episode_id,
            tick_observation_digest: digest("distinct-tick"),
            tick_generation: Generation::new(1).unwrap(),
        }],
    )
    .is_err());
}
