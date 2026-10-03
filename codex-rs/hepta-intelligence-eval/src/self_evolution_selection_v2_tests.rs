use super::*;
use crate::freeze_paired_supervised_plan_v1;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::Sink;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::id;
use crate::paired_supervised_test_support::inputs;
use crate::paired_supervised_test_support::runner;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

struct Fixture {
    signing: SigningFixture,
    selector_key: SigningKey,
    selector: AuthenticatedPrincipalV1,
    ledger: LedgerSnapshot,
    dataset: DatasetSnapshotReceiptV3,
    execution: ProductPairedEvaluationReceiptV1,
    qualification: ProductPairedQualificationReceiptV1,
    context: ProductQualificationContextV1,
    evaluation: SignedEvaluationEvidenceV1,
    provider_releases: usize,
    sink_calls: usize,
}

impl Fixture {
    fn new(shared_selector: bool, revoked_at: Option<u64>) -> Self {
        let (signing, selector_key, selector) =
            SigningFixture::new(false).with_selector(shared_selector, revoked_at);
        let mut ledger = LearningLedger::new();
        ledger
            .append(LedgerEvent::Decision(EpisodeDecision {
                record_id: id("original-training-decision"),
                episode_id: id("original-training-episode"),
                objective_digest: digest("paired-objective"),
                policy_id: id("installed-comparator"),
                candidate_ids: vec![id("baseline-action"), id("abstain")],
                selected_candidate_id: id("baseline-action"),
                selected_propensity: ProbabilityQ32::ONE,
                completeness: CandidateSetCompleteness::Complete,
                support_digest: digest("original-training-support"),
            }))
            .unwrap();
        let ledger = ledger.snapshot();
        let dataset = freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: id("original-training-dataset"),
                producer: signing.principals[0].clone(),
                ledger_head_digest: ledger.head_digest,
                objective_digest: digest("paired-objective"),
                eligible_frontier: 1,
                outcome_watermark: 20,
                correction_cut_digest: digest("empty-correction-cut"),
                revocation_cut_digest: digest("empty-revocation-cut"),
                inclusion_policy_digest: digest("original-one-record-training-cut"),
                source_record_digests: ledger.records().iter().map(|r| r.event_digest).collect(),
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            30,
        )
        .unwrap();
        verify_dataset_snapshot_receipt_against_ledger_v3(&dataset, &ledger, 30).unwrap();
        let mut plan_inputs = inputs(128);
        plan_inputs.base_plan.dataset_digest = dataset.snapshot.dataset_digest;
        let plan = freeze_paired_supervised_plan_v1(plan_inputs).unwrap();
        let registration = signing.register(&plan);
        let mut provider = signing.provider(&plan);
        let mut runner = runner();
        let execution = runner
            .evaluate_paired_with_clock(
                &registration,
                &mut provider,
                &signing.trust,
                &mut PairedHostClockV1::fixture(&[30]),
            )
            .unwrap();
        let context = signing.context();
        let evaluation = signing.evaluation(&execution, &context);
        let mut sink = Sink::default();
        let qualification = runner
            .qualify_paired_with_clock(
                &execution,
                &context,
                &evaluation,
                &signing.trust,
                &mut sink,
                &mut PairedHostClockV1::fixture(&[30]),
            )
            .unwrap();
        assert_eq!(
            qualification.decision.decision.disposition,
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        );
        Self {
            signing,
            selector_key,
            selector,
            ledger,
            dataset,
            execution,
            qualification,
            context,
            evaluation,
            provider_releases: provider.release_count,
            sink_calls: sink.calls,
        }
    }

    fn inputs(&self) -> SelfEvolutionSelectionInputsV2<'_> {
        SelfEvolutionSelectionInputsV2 {
            execution: &self.execution,
            qualification: &self.qualification,
            context: &self.context,
            evaluation_evidence: &self.evaluation,
            dataset_receipt: &self.dataset,
            ledger_snapshot: &self.ledger,
        }
    }

    fn policy(&self) -> SelfEvolutionSelectionPolicyV2 {
        SelfEvolutionSelectionPolicyV2 {
            no_change_baseline_id: self.execution.registration.plan.frozen.baseline_id.clone(),
            no_change_baseline_digest: self
                .execution
                .registration
                .plan
                .runtime
                .deployed_baseline_digest,
            minimum_dataset_records: 1,
        }
    }

    fn request(&self) -> SelfEvolutionSelectionRequestV1 {
        let plan = &self.execution.registration.plan;
        SelfEvolutionSelectionRequestV1 {
            selection_id: id("independent-selection"),
            predecessor_id: plan.frozen.baseline_id.clone(),
            predecessor_generation: Generation::new(7).unwrap(),
            predecessor_artifact_digest: plan.runtime.deployed_baseline_digest,
            candidate_id: plan.frozen.candidate_id.clone(),
            candidate_generation: Generation::new(8).unwrap(),
            candidate_artifact_digest: plan.runtime.candidate_artifact_digest,
        }
    }

    fn prepare(&self, times: &[u64]) -> PreparedSelfEvolutionSelectionV2 {
        prepare_with_clock(
            &self.policy(),
            self.request(),
            self.inputs(),
            &self.signing.trust,
            PairedHostClockV1::fixture(times),
        )
        .unwrap()
    }

    fn select(&self, payload: &[u8]) -> SignedLearningEvidenceV1 {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id("independent-selector-evidence"),
            principal_id: self.selector.principal_id.clone(),
            role: LearningEvidenceRoleV1::Selector,
            trust_digest: self.signing.verifier.trust_digest(),
            scope_digest: self.selector.scope_digest,
            objective_digest: digest("paired-objective"),
            authority_epoch: 1,
            issued_at: 25,
            expires_at: 900,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.selector_key.sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }
}

#[test]
fn selection_v2_admits_original_qualified_cut_without_consuming_or_republishing() {
    let fixture = Fixture::new(false, None);
    let prepared = fixture.prepare(&[30]);
    let receipt = prepared.receipt();
    assert_eq!(
        receipt.qualification_digest,
        fixture.qualification.evidence_digest
    );
    assert_eq!(
        receipt.publication_digest,
        fixture.qualification.publication_digest
    );
    assert_eq!(
        receipt.paired_execution_digest,
        fixture.execution.execution_digest()
    );
    assert_eq!(receipt.registered_at_unix_micros, 11_001);
    let evidence = fixture.select(&selection_signing_payload_v2(receipt).unwrap());
    let token =
        admit_self_evolution_selection_v2(prepared, &evidence, &fixture.signing.trust).unwrap();
    token.revalidate_current(&fixture.signing.trust).unwrap();
    assert_eq!(token.receipt().authority, AuthorityPosture::DENY_ALL);
    assert!(!token.selection_digest().is_zero());
    assert_eq!(fixture.provider_releases, 1);
    assert_eq!(fixture.sink_calls, 1);
}

#[test]
fn selection_v2_rejects_v1_domain_signature_and_changed_paired_bindings() {
    let fixture = Fixture::new(false, None);
    let prepared = fixture.prepare(&[30]);
    let receipt = prepared.receipt();
    let historical = crate::SelfEvolutionSelectionReceiptV1 {
        selection_id: receipt.request.selection_id.clone(),
        objective_digest: receipt.objective_digest,
        predecessor_id: receipt.request.predecessor_id.clone(),
        predecessor_generation: receipt.request.predecessor_generation,
        predecessor_artifact_digest: receipt.request.predecessor_artifact_digest,
        candidate_id: receipt.request.candidate_id.clone(),
        candidate_generation: receipt.request.candidate_generation,
        candidate_artifact_digest: receipt.request.candidate_artifact_digest,
        no_change_baseline_id: receipt.request.predecessor_id.clone(),
        no_change_baseline_digest: receipt.request.predecessor_artifact_digest,
        dataset_digest: receipt.dataset_digest,
        ledger_head_digest: receipt.ledger_head_digest,
        evaluation_evidence_digest: receipt.evaluation_evidence_digest,
        evaluation_authentication_digest: receipt.evaluation_authentication_digest,
        evaluation_trust_digest: receipt.evaluation_trust_digest,
        frozen_plan_digest: receipt.frozen_plan_digest,
        minimum_dataset_records: 1,
        minimum_future_window_micros: 1,
        authority: AuthorityPosture::DENY_ALL,
    };
    let old_payload = crate::selection_signing_payload_v1(&historical).unwrap();
    let payload = selection_signing_payload_v2(receipt).unwrap();
    assert_ne!(old_payload, payload);
    assert!(
        admit_self_evolution_selection_v2(
            prepared.clone(),
            &fixture.select(&old_payload),
            &fixture.signing.trust
        )
        .is_err()
    );
    for case in 0..6 {
        let mut changed = receipt.clone();
        match case {
            0 => changed.qualification_digest = digest("other-qualification"),
            1 => changed.publication_digest = digest("other-publication"),
            2 => changed.paired_execution_digest = digest("other-original-execution"),
            3 => changed.paired_profile_digest = digest("other-paired-profile"),
            4 => changed.registered_at_unix_micros += 1,
            _ => changed.request.candidate_artifact_digest = digest("other-model"),
        }
        assert_ne!(payload, selection_signing_payload_v2(&changed).unwrap());
        assert!(
            admit_self_evolution_selection_v2(
                prepared.clone(),
                &fixture.select(&selection_signing_payload_v2(&changed).unwrap()),
                &fixture.signing.trust
            )
            .is_err(),
            "case {case}"
        );
    }
}

#[test]
fn selection_v2_requires_original_seal_dataset_membership_and_independent_selector() {
    let mut fixture = Fixture::new(false, None);
    fixture.qualification.publication_digest = digest("fabricated-persistence");
    assert!(
        prepare_with_clock(
            &fixture.policy(),
            fixture.request(),
            fixture.inputs(),
            &fixture.signing.trust,
            PairedHostClockV1::fixture(&[30])
        )
        .is_err()
    );
    let mut fixture = Fixture::new(false, None);
    fixture.ledger = LearningLedger::new().snapshot();
    assert!(
        prepare_with_clock(
            &fixture.policy(),
            fixture.request(),
            fixture.inputs(),
            &fixture.signing.trust,
            PairedHostClockV1::fixture(&[30])
        )
        .is_err()
    );
    let fixture = Fixture::new(true, None);
    let prepared = fixture.prepare(&[30]);
    let evidence = fixture.select(&selection_signing_payload_v2(prepared.receipt()).unwrap());
    assert!(
        admit_self_evolution_selection_v2(prepared, &evidence, &fixture.signing.trust).is_err()
    );
}

#[test]
fn selection_v2_owned_clock_rechecks_root_expiry_revocation_and_backwards_time() {
    for (revoked_at, times) in [
        (None, vec![30, 30, 30, 30, 801]),
        (Some(80), vec![30, 30, 30, 30, 80]),
        (None, vec![30, 30, 30, 30, 29]),
    ] {
        let fixture = Fixture::new(false, revoked_at);
        let prepared = fixture.prepare(&times);
        let evidence = fixture.select(&selection_signing_payload_v2(prepared.receipt()).unwrap());
        let token =
            admit_self_evolution_selection_v2(prepared, &evidence, &fixture.signing.trust).unwrap();
        assert!(token.revalidate_current(&fixture.signing.trust).is_err());
    }
    let fixture = Fixture::new(false, None);
    let prepared = fixture.prepare(&[30, 30, 801]);
    let evidence = fixture.select(&selection_signing_payload_v2(prepared.receipt()).unwrap());
    assert!(
        admit_self_evolution_selection_v2(prepared, &evidence, &fixture.signing.trust).is_err()
    );
}

#[test]
fn selection_v2_rollback_binds_fresh_regression_signature_and_advances_generation() {
    let fixture = Fixture::new(false, None);
    let prepared = fixture.prepare(&[30]);
    let evidence = fixture.select(&selection_signing_payload_v2(prepared.receipt()).unwrap());
    let selected =
        admit_self_evolution_selection_v2(prepared, &evidence, &fixture.signing.trust).unwrap();
    let regression = digest("original-current-regression-cut");
    let generation = Generation::new(9).unwrap();
    let payload = rollback_signing_payload_v2(&selected, regression, generation).unwrap();
    let evaluator = fixture.signing.sign(2, &payload, 30);
    let rollback = admit_self_evolution_rollback_v2(
        &selected,
        regression,
        generation,
        &evaluator,
        &fixture.signing.trust,
    )
    .unwrap();
    rollback.revalidate_current(&fixture.signing.trust).unwrap();
    assert_eq!(rollback.rollback_generation(), generation);
    assert_eq!(
        rollback.selection().selection_digest(),
        selected.selection_digest()
    );
    assert!(
        admit_self_evolution_rollback_v2(
            &selected,
            digest("another-regression"),
            generation,
            &evaluator,
            &fixture.signing.trust
        )
        .is_err()
    );
    assert!(
        rollback_signing_payload_v2(&selected, regression, Generation::new(7).unwrap()).is_err()
    );
    assert!(
        admit_self_evolution_rollback_v2(
            &selected,
            regression,
            generation,
            &fixture.select(&payload),
            &fixture.signing.trust
        )
        .is_err()
    );
}
