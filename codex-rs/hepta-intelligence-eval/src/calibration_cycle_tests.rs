//! Synthetic independent signers and real durable files; no production custody.
use crate::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
static NEXT: AtomicU64 = AtomicU64::new(0);
fn id(s: &str) -> StableId {
    StableId::new(s).unwrap()
}
fn digest(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}
fn authenticate(index: usize) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(&format!("cycle-fixture-{index}")),
        credential_chain_digest: digest(&format!("credential-{index}")),
        signing_key_digest: Digest32::of_bytes(
            SigningKey::from_bytes(&[index as u8 + 1; 32])
                .verifying_key()
                .as_bytes(),
        ),
        scope_digest: digest("fixture-scope"),
        authority_epoch: 1,
        authenticated_at: 1,
        expires_at: 1000,
    }
}
fn activated() -> ActivatedLearningTrustV1 {
    let root_key = SigningKey::from_bytes(&[90; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("cycle-fixture-root"),
        scope_digest: digest("fixture-scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 1000,
        revoked_at: None,
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        root_id: root.root_id.clone(),
        issued_at: 1,
        expires_at: 999,
        signature: [0; 64],
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("cycle-fixture-distribution"),
            generation: 1,
            effective_at: 1,
            trust: LearningEvidenceTrustV1 {
                scope_digest: digest("fixture-scope"),
                objective_digest: digest("fixture-objective"),
                authority_epoch: 1,
                signers: (0..4)
                    .map(|i| TrustedLearningSignerV1 {
                        principal: authenticate(i),
                        controller_id: id(&format!("controller-{}", if i == 2 { 1 } else { i })),
                        verifying_key: SigningKey::from_bytes(&[i as u8 + 1; 32])
                            .verifying_key()
                            .to_bytes(),
                        roles: vec![match i {
                            0 => LearningEvidenceRoleV1::Generator,
                            1 => LearningEvidenceRoleV1::Observer,
                            _ => LearningEvidenceRoleV1::Evaluator,
                        }],
                        revoked_at: None,
                    })
                    .collect(),
            },
        },
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().unwrap())
        .to_bytes();
    activate_learning_trust(&root, distribution, None, 100).unwrap()
}
fn signed(
    verifier: &LearningEvidenceVerifierV1,
    i: usize,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!(
            "fixture-evidence-{i}-{}",
            Digest32::of_bytes(payload)
        )),
        principal_id: authenticate(i).principal_id,
        role: match i {
            0 => LearningEvidenceRoleV1::Generator,
            1 => LearningEvidenceRoleV1::Observer,
            _ => LearningEvidenceRoleV1::Evaluator,
        },
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("fixture-scope"),
        objective_digest: digest("fixture-objective"),
        authority_epoch: 1,
        issued_at: 100,
        expires_at: 900,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[i as u8 + 1; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}
struct Fixture {
    root: PathBuf,
    writer: Option<LedgerWriter>,
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-cal-cycle-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&root).unwrap();
        let directory = File::open(&root).unwrap();
        let file = |name: &str| {
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(root.join(name))
                .unwrap()
        };
        let ledger = DurableLedger::create(file("ledger"), digest("ledger-binding"), 4096).unwrap();
        let witness =
            LedgerWitnessStore::create(file("witness"), digest("ledger-binding")).unwrap();
        let writer =
            LedgerWriter::from_durable(ledger, witness, activated(), &directory, &directory)
                .unwrap();
        Self {
            root,
            writer: Some(writer),
        }
    }
    fn append_cycle(
        &mut self,
        audit: Digest32,
    ) -> (CalibrationCycleScopeV2, Vec<u8>, SignedLearningEvidenceV1) {
        let writer = self.writer.as_mut().unwrap();
        let before = writer.snapshot().unwrap();
        let mut head = before.head_digest;
        let mut payload = Vec::new();
        let mut first = None;
        let snapshots = vec![
            [digest("task-a-candidate"), digest("task-a-baseline")],
            [digest("task-b-candidate"), digest("task-b-baseline")],
        ];
        for (index, pair) in snapshots.iter().enumerate() {
            for (policy, offset) in [("candidate", 0usize), ("baseline", 1usize)] {
                let candidates = vec![id("SUPPORT"), id("CONTRADICT"), id("abstain")];
                let decision = ProductionDecisionV2 {
                    record_id: id(&format!("calibration.decision.{audit}.{policy}.{index}")),
                    episode_id: id(&format!("calibration.episode.{audit}.{policy}.{index}")),
                    run_snapshot_digest: pair[offset],
                    objective_digest: digest("fixture-objective"),
                    policy_digest: digest(policy),
                    candidate_ids: candidates.clone(),
                    selected_candidate_id: candidates[0].clone(),
                    selected_propensity: ProbabilityQ32::ONE,
                    completeness: CandidateSetCompletenessReceiptV1 {
                        set_id: id(&format!("set-{audit}-{index}-{offset}")),
                        state_digest: pair[offset],
                        generator_id: authenticate(0).principal_id,
                        generator_code_digest: digest("actual-fixture-generator"),
                        grammar_digest: digest("all-labels"),
                        hard_filter_digest: digest("no-filter"),
                        truncation_digest: digest("no-truncation"),
                        candidates_digest: candidate_ids_digest_v2(&candidates),
                        candidate_count: 3,
                        omitted_count_bound: 0,
                        canonical_order_digest: candidate_order_digest_v2(&candidates),
                        complete_for_generator: true,
                    },
                    support_digest: digest(&format!("native-original-{audit}-{index}-{policy}")),
                };
                let generated = decision_signing_payload_v2(&decision).unwrap();
                let evidence = signed(writer.verifier(), 0, &generated);
                head = writer
                    .append_decision(head, decision.clone(), &evidence, 100)
                    .unwrap()
                    .chain_digest;
                if first.is_none() {
                    payload = generated;
                    first = Some(evidence);
                }
                let observed = AuthenticatedOutcomeV1 {
                    record_id: id(&format!("{}.outcome", decision.record_id)),
                    outcome_id: id(&format!("{}.outcome", decision.episode_id)),
                    episode_id: decision.episode_id,
                    observer: authenticate(1),
                    observed_at: Some(90),
                    value: Some(if policy == "candidate" {
                        FixedQ32::ZERO
                    } else {
                        FixedQ32::ONE
                    }),
                    unit_profile_digest: digest("binary-original-gold"),
                    support_digest: digest(&format!("native-observer-{audit}-{index}-{policy}")),
                    watermark: OutcomeWatermarkV1 {
                        latest_observable_at: 90,
                        expected_delay_profile_digest: digest("terminal-direct-execution"),
                        terminality: OutcomeTerminalityV1::Terminal,
                        censoring_reason: None,
                        correction_predecessor: None,
                        finalized_at: Some(90),
                    },
                };
                let signature =
                    signed(writer.verifier(), 1, &outcome_signing_payload_v2(&observed));
                head = writer
                    .append_outcome(head, observed, &signature, 100)
                    .unwrap()
                    .chain_digest;
            }
        }
        (
            CalibrationCycleScopeV2 {
                first_sequence: before.records().len() as u64 + 1,
                previous_acknowledged_head: before.head_digest,
                original_task_sources_digest: digest("same-two-original-tasks-repeated"),
                run_snapshot_digests: snapshots,
                current_program_approval_digest: digest("frozen-current-program-approval"),
            },
            payload,
            first.unwrap(),
        )
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        drop(self.writer.take());
        std::fs::remove_dir_all(&self.root).unwrap();
    }
}
struct Cut {
    snapshot: LedgerSnapshot,
    dataset: DatasetSnapshotReceiptV3,
    binding: CalibrationCutBindingV1,
    cycle: CalibrationCycleScopeV2,
    payload: Vec<u8>,
    generator: SignedLearningEvidenceV1,
    observer: SignedLearningEvidenceV1,
    producer: SignedLearningEvidenceV1,
    evaluator: SignedLearningEvidenceV1,
}
fn cut(
    fixture: &Fixture,
    cycle: CalibrationCycleScopeV2,
    payload: Vec<u8>,
    generator: SignedLearningEvidenceV1,
    audit: Digest32,
) -> Cut {
    let writer = fixture.writer.as_ref().unwrap();
    let snapshot = writer.snapshot().unwrap();
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id(&format!("snapshot-{audit}")),
        objective_digest: digest("fixture-objective"),
        inclusion_policy_digest: digest("whole-intact-history"),
    };
    let producer = signed(
        writer.verifier(),
        2,
        &dataset_freeze_signing_payload_v2(&snapshot, &plan).unwrap(),
    );
    let dataset = writer.freeze_dataset(plan, &producer, 100).unwrap();
    let authentication = |e: &SignedLearningEvidenceV1| {
        let mut bytes = e.signing_bytes();
        bytes.extend_from_slice(&e.signature);
        Digest32::of_bytes(&bytes)
    };
    let binding = CalibrationCutBindingV1 {
        observer_program_digest: digest("actual-observer-program"),
        ledger_binding_digest: digest("ledger-binding"),
        ledger_file_digest: Digest32::of_bytes(
            &std::fs::read(fixture.root.join("ledger")).unwrap(),
        ),
        acknowledged_sequence: snapshot.records().len() as u64,
        acknowledged_head: snapshot.head_digest,
        candidate_manifest_digest: digest("candidate-manifest"),
        baseline_manifest_digest: digest("baseline-manifest"),
        candidate_weights_digest: digest("candidate"),
        baseline_weights_digest: digest("baseline"),
        audit_digest: audit,
        dataset_digest: dataset.snapshot.dataset_digest,
        generator_payload_digest: Digest32::of_bytes(&payload),
        generator_authentication_digest: authentication(&generator),
        freeze_payload_digest: producer.payload_digest,
        freeze_authentication_digest: authentication(&producer),
    };
    let observer = signed(
        writer.verifier(),
        1,
        &calibration_cycle_cut_signing_payload_v2(&binding, &cycle),
    );
    let evaluator = signed(
        writer.verifier(),
        3,
        &calibration_cycle_preflight_signing_payload_v2(
            &calibration_cycle_cut_signing_payload_v2(&binding, &cycle),
            FixedQ32::ZERO,
        )
        .unwrap(),
    );
    Cut {
        snapshot,
        dataset,
        binding,
        cycle,
        payload,
        generator,
        observer,
        producer,
        evaluator,
    }
}
impl Cut {
    fn request(&self) -> SignedCalibrationPreflightRequestV1<'_> {
        SignedCalibrationPreflightRequestV1 {
            snapshot: &self.snapshot,
            dataset: &self.dataset,
            cut_binding: &self.binding,
            generator_payload: &self.payload,
            minimum_primary_improvement: FixedQ32::ZERO,
            generator: &self.generator,
            observer: &self.observer,
            producer: &self.producer,
            evaluator: &self.evaluator,
        }
    }
    fn resign(&mut self, verifier: &LearningEvidenceVerifierV1) {
        let payload = calibration_cycle_cut_signing_payload_v2(&self.binding, &self.cycle);
        self.observer = signed(verifier, 1, &payload);
        self.evaluator = signed(
            verifier,
            3,
            &calibration_cycle_preflight_signing_payload_v2(&payload, FixedQ32::ZERO).unwrap(),
        );
    }
}
#[test]
fn cycle_v2_rejects_actual_failed_candidate_on_exact_new_cycle_retaining_durable_prefix_and_witness()
 {
    let mut fixture = Fixture::new();
    fixture.append_cycle(digest("old-cycle"));
    let old = fixture.writer.as_ref().unwrap().snapshot().unwrap();
    let old_bytes = std::fs::read(fixture.root.join("ledger")).unwrap();
    let (cycle, payload, generated) = fixture.append_cycle(digest("new-cycle"));
    let cut = cut(&fixture, cycle, payload, generated, digest("new-cycle"));
    let writer = fixture.writer.as_ref().unwrap();
    let decision =
        decide_with_signed_calibration_cycle_v2(cut.request(), &cut.cycle, writer.verifier(), 100)
            .unwrap();
    assert_eq!(
        decision.disposition,
        CalibrationPreflightDispositionV1::Rejected
    );
    assert_eq!(
        (
            decision.labeled_pairs,
            decision.candidate_correct,
            decision.baseline_correct
        ),
        (2, 0, 2)
    );
    assert_eq!(&cut.snapshot.records()[..8], old.records());
    assert_eq!(
        &std::fs::read(fixture.root.join("ledger")).unwrap()[..old_bytes.len()],
        old_bytes
    );
    assert_eq!(writer.witness_frontier().unwrap().anchor.sequence, 16);
    assert!(
        decide_with_signed_calibration_preflight_v1(cut.request(), writer.verifier(), 100).is_err()
    );
    let anchor = writer.witness_frontier().unwrap().anchor;
    drop(fixture.writer.take());
    let reopened = inspect_ledger(
        File::open(fixture.root.join("ledger")).unwrap(),
        digest("ledger-binding"),
        4096,
        anchor,
    )
    .unwrap();
    assert_eq!(reopened, cut.snapshot);
}
#[test]
fn cycle_v2_refuses_resigned_success_subsets_wrong_original_prefix_snapshots_order_and_program_approval()
 {
    let mut fixture = Fixture::new();
    fixture.append_cycle(digest("old-cycle"));
    let (cycle, payload, generated) = fixture.append_cycle(digest("new-cycle"));
    let mut cut = cut(&fixture, cycle, payload, generated, digest("new-cycle"));
    let verifier = fixture.writer.as_ref().unwrap().verifier();
    for change in 0..7 {
        let original = cut.cycle.clone();
        match change {
            0 => cut.cycle.first_sequence = 1,
            1 => cut.cycle.previous_acknowledged_head = digest("different-original-head"),
            2 => {
                cut.cycle.run_snapshot_digests.pop();
            }
            3 => cut.cycle.run_snapshot_digests[0][0] = digest("other-request-input"),
            4 => cut.cycle.run_snapshot_digests.swap(0, 1),
            5 => cut.cycle.original_task_sources_digest = Digest32::ZERO,
            _ => cut.cycle.current_program_approval_digest = Digest32::ZERO,
        };
        cut.resign(verifier);
        assert!(
            decide_with_signed_calibration_cycle_v2(cut.request(), &cut.cycle, verifier, 100)
                .is_err(),
            "change {change}"
        );
        cut.cycle = original;
    }
}
#[test]
fn cycle_v2_requires_fresh_independent_signed_original_binding_and_exact_full_dataset() {
    let mut fixture = Fixture::new();
    fixture.append_cycle(digest("old-cycle"));
    let (cycle, payload, generated) = fixture.append_cycle(digest("new-cycle"));
    let mut cut = cut(&fixture, cycle, payload, generated, digest("new-cycle"));
    let verifier = fixture.writer.as_ref().unwrap().verifier();
    assert!(
        decide_with_signed_calibration_cycle_v2(cut.request(), &cut.cycle, verifier, 901).is_err()
    );
    cut.observer = signed(
        verifier,
        1,
        &calibration_cut_signing_payload_v1(&cut.binding),
    );
    assert!(
        decide_with_signed_calibration_cycle_v2(cut.request(), &cut.cycle, verifier, 100).is_err()
    );
    cut.resign(verifier);
    cut.binding.acknowledged_head = digest("replaced-history");
    cut.resign(verifier);
    assert!(
        decide_with_signed_calibration_cycle_v2(cut.request(), &cut.cycle, verifier, 100).is_err()
    );
}
#[test]
fn original_v1_still_accepts_only_its_actual_single_cycle_and_original_domains() {
    let mut fixture = Fixture::new();
    let (cycle, payload, generated) = fixture.append_cycle(digest("single-original-cycle"));
    let mut cut = cut(
        &fixture,
        cycle,
        payload,
        generated,
        digest("single-original-cycle"),
    );
    let verifier = fixture.writer.as_ref().unwrap().verifier();
    let payload = calibration_cut_signing_payload_v1(&cut.binding);
    cut.observer = signed(verifier, 1, &payload);
    cut.evaluator = signed(
        verifier,
        3,
        &calibration_preflight_signing_payload_v1(&payload, FixedQ32::ZERO).unwrap(),
    );
    let rejected =
        decide_with_signed_calibration_preflight_v1(cut.request(), verifier, 100).unwrap();
    assert_eq!(
        (
            rejected.labeled_pairs,
            rejected.candidate_correct,
            rejected.baseline_correct
        ),
        (2, 0, 2)
    );
    assert_eq!(
        rejected.disposition,
        CalibrationPreflightDispositionV1::Rejected
    );
    assert!(
        decide_with_signed_calibration_cycle_v2(cut.request(), &cut.cycle, verifier, 100).is_err()
    );
}
