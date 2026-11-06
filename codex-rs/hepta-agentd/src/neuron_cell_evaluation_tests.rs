use std::io::Write;

use codex_hepta_intelligence_eval::*;
use codex_hepta_neuron::*;
use pretty_assertions::assert_eq;

use super::*;

#[path = "neuron_cell_evaluation_test_support.rs"]
mod support;
use support::*;

struct FileSink {
    file: std::fs::File,
    publications: usize,
}
impl ProductQualificationEvidenceSinkV1 for FileSink {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let bytes = [
            execution.as_array().as_slice(),
            decision.authentication_digest.as_array(),
            decision.decision.evidence_digest.as_array(),
        ]
        .concat();
        self.file
            .write_all(&bytes)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        self.publications += 1;
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[test]
fn actual_file_owners_compute_sign_and_publish_only_bound_comparison() {
    let mut fixture = Fixture::new(Costs::Complete);
    let plan = checked(fixture.freeze());
    assert_ne!(
        plan.record().candidate.manifest.source_digest,
        plan.record().fixed_expert.manifest.source_digest
    );
    let before = fixture.holdout_bytes();
    let receipt = checked(fixture.run(&plan));
    assert_ne!(fixture.holdout_bytes(), before);
    assert_eq!((fixture.provider.calls, fixture.provider.releases), (1, 1));
    let summary = checked(receipt.plan().record().candidate.cost.summary());
    assert_eq!(
        (
            summary.wall_work_micros.known_sum,
            summary.cpu_micros.known_sum,
            summary.unsuccessful_entries,
            summary.energy_microjoules.unknown_entries
        ),
        (120, 60, 1, 12)
    );
    assert_eq!(summary.complete_metrics(), None);
    assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    assert_ne!(
        receipt.temporal().candidate.estimate,
        receipt.temporal().baseline.estimate
    );
    let (context, evidence, verifier) = signed(&fixture.runner, &receipt);
    let mut sink = FileSink {
        file: file(&fixture.directory.path().join("publication")),
        publications: 0,
    };
    let mut bad = evidence.clone();
    bad.generator_plan.signature[0] ^= 1;
    assert!(
        fixture
            .runner
            .qualify_and_persist(
                &receipt,
                CellEvaluationQualificationRequestV1 {
                    context: &context,
                    evidence: &bad,
                    timing: ProductTimingEvidenceV1::Qualification,
                    verifier: &verifier,
                    now: 50,
                },
                &mut sink
            )
            .is_err()
    );
    assert_eq!(
        (sink.publications, checked(sink.file.metadata()).len()),
        (0, 0)
    );
    let qualified = checked(fixture.runner.qualify_and_persist(
        &receipt,
        CellEvaluationQualificationRequestV1 {
            context: &context,
            evidence: &evidence,
            timing: ProductTimingEvidenceV1::Qualification,
            verifier: &verifier,
            now: 50,
        },
        &mut sink,
    ));
    checked(qualified.product().validate_integrity());
    assert_eq!(qualified.comparison(), plan.record());
    assert_eq!(qualified.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(sink.publications, 1);

    let anchor = fixture.runner.product.holdout_anchor();
    let consumed = fixture.holdout_bytes();
    drop(fixture.runner);
    let store = checked(LockedFileFinalHoldoutCasStoreV1::recover(
        file(&fixture.directory.path().join("holdout")),
        digest("binding"),
        Some(anchor),
    ));
    let owner = checked(FencedFinalHoldoutOwnerV1::recover(
        store,
        digest("binding"),
        fence(),
    ));
    fixture.runner = CellEvaluationRunnerV1::new(ProductEvaluationRunnerV1::new(owner));
    assert!(fixture.run(&plan).is_err());
    assert_eq!(fixture.provider.releases, 1);
    assert_eq!(fixture.holdout_bytes(), consumed);
}

#[test]
fn unfair_or_missing_training_declarations_never_consume_holdout() {
    let fixture = Fixture::new(Costs::Complete);
    let before = fixture.holdout_bytes();
    for mutation in 0..9 {
        let mut registration = fixture.registration.clone();
        let fixed = &mut registration.comparison.fixed_expert;
        match mutation {
            0 => fixed.capacity.total_parameters += 1,
            1 => fixed.cumulative.examples_seen += 1,
            2 => fixed.cumulative.optimizer_steps += 1,
            3 => fixed.cumulative.parameter_updates += 1,
            4 => fixed.cumulative.compute_units += 1,
            5 => fixed.selective_update.schedule_digest = [99; 32],
            6 => fixed.structure_before = [99; 32],
            7 => fixed.training_receipt_digest = [0; 32],
            8 => fixed.structure_after = [99; 32],
            _ => unreachable!(),
        }
        assert!(
            freeze_cell_evaluation_plan_v1(
                registration,
                fixture.journals(),
                &fixture.candidate_temporal,
                &fixture.baseline_temporal
            )
            .is_err()
        );
        assert_eq!(fixture.holdout_bytes(), before);
    }
    assert_eq!((fixture.provider.calls, fixture.provider.releases), (0, 0));
}

#[test]
fn missing_or_unknown_costs_refuse_gain_while_unrequested_energy_stays_unknown() {
    for profile in [
        Costs::Empty,
        Costs::MissingStage,
        Costs::UnknownCpu,
        Costs::UnknownOutcome,
        Costs::UnknownEnvelope,
    ] {
        let fixture = Fixture::new(profile);
        let before = fixture.holdout_bytes();
        assert!(fixture.freeze().is_err());
        assert_eq!(fixture.holdout_bytes(), before);
        assert_eq!((fixture.provider.calls, fixture.provider.releases), (0, 0));
    }
    let mut fixture = Fixture::new(Costs::Complete);
    checked(fixture.freeze());
    fixture
        .registration
        .comparison
        .cost_coverage
        .required_metrics
        .push(CellRequiredCostMetricV1::Energy);
    assert!(fixture.freeze().is_err());
    fixture
        .registration
        .comparison
        .cost_coverage
        .required_metrics = vec![CellRequiredCostMetricV1::Wall];
    assert!(fixture.freeze().is_err());
}

#[test]
fn same_snapshot_but_changed_journal_cut_is_rejected_before_provider() {
    let mut fixture = Fixture::new(Costs::Complete);
    let plan = checked(fixture.freeze());
    let snapshot = checked(fixture.candidate.snapshot()).clone();
    let before = fixture.holdout_bytes();
    checked(fixture.candidate.resume());
    checked(fixture.candidate.drain());
    assert_eq!(fixture.candidate.snapshot(), Ok(&snapshot));
    assert!(matches!(
        fixture.run(&plan),
        Err(CellEvaluationErrorV1::Binding(
            "Cell journal changed after registration"
        ))
    ));
    assert_eq!(fixture.holdout_bytes(), before);
    assert_eq!((fixture.provider.calls, fixture.provider.releases), (0, 0));
}

#[test]
fn changed_costs_or_unclosed_owner_cannot_reuse_a_frozen_comparison() {
    let mut fixture = Fixture::new(Costs::Complete);
    let plan = checked(fixture.freeze());
    checked(fixture.candidate.record_cost(CellCostEntryV2 {
        event_id: [99; 32],
        identity: checked(fixture.candidate.task_cost()).identity(),
        stage: CellCostStageV2::Recovery,
        outcome: CellCostOutcomeV2::Succeeded,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: CellCostMetricsV2 {
            wall_micros: Some(1),
            cpu_micros: Some(1),
            ..CellCostMetricsV2::default()
        },
    }));
    let before = fixture.holdout_bytes();
    assert!(fixture.run(&plan).is_err());
    checked(fixture.candidate.resume());
    assert!(fixture.freeze().is_err());
    assert_eq!(fixture.holdout_bytes(), before);
    assert_eq!((fixture.provider.calls, fixture.provider.releases), (0, 0));
}

#[test]
fn different_task_and_unknown_holdout_release_remain_fail_closed() {
    let mut fixture = Fixture::new(Costs::Complete);
    let other = journal(
        fixture.directory.path(),
        "other-task",
        Costs::Complete,
        [18; 32],
    );
    let before = fixture.holdout_bytes();
    assert!(
        freeze_cell_evaluation_plan_v1(
            fixture.registration.clone(),
            CellEvaluationJournalsV1 {
                candidate: &fixture.candidate,
                fixed_expert: &fixture.candidate
            },
            &fixture.candidate_temporal,
            &fixture.baseline_temporal
        )
        .is_err()
    );
    assert!(
        freeze_cell_evaluation_plan_v1(
            fixture.registration.clone(),
            CellEvaluationJournalsV1 {
                candidate: &fixture.candidate,
                fixed_expert: &other
            },
            &fixture.candidate_temporal,
            &fixture.baseline_temporal
        )
        .is_err()
    );
    assert_eq!(fixture.holdout_bytes(), before);
    let plan = checked(fixture.freeze());
    fixture.provider.inputs = None;
    assert!(fixture.run(&plan).is_err());
    let consumed = fixture.holdout_bytes();
    assert_ne!(consumed, before);
    assert_eq!(fixture.provider.releases, 1);
    assert!(fixture.run(&plan).is_err());
    assert_eq!(fixture.provider.releases, 1);
    assert_eq!(fixture.holdout_bytes(), consumed);
}

#[test]
fn signatures_for_another_fair_budget_cannot_publish_this_result() {
    let mut original = Fixture::new(Costs::Complete);
    let plan = checked(original.freeze());
    let receipt = checked(original.run(&plan));
    let (context, evidence, verifier) = signed(&original.runner, &receipt);
    let mut changed = Fixture::new(Costs::Complete);
    changed
        .registration
        .comparison
        .candidate
        .cumulative
        .compute_units += 1;
    changed
        .registration
        .comparison
        .fixed_expert
        .cumulative
        .compute_units += 1;
    let other_plan = checked(changed.freeze());
    assert_ne!(
        plan.product_plan().frozen_plan.plan_digest,
        other_plan.product_plan().frozen_plan.plan_digest
    );
    let other = checked(changed.run(&other_plan));
    let mut sink = FileSink {
        file: file(&changed.directory.path().join("publication")),
        publications: 0,
    };
    assert!(
        changed
            .runner
            .qualify_and_persist(
                &other,
                CellEvaluationQualificationRequestV1 {
                    context: &context,
                    evidence: &evidence,
                    timing: ProductTimingEvidenceV1::Qualification,
                    verifier: &verifier,
                    now: 50,
                },
                &mut sink
            )
            .is_err()
    );
    assert_eq!(
        (sink.publications, checked(sink.file.metadata()).len()),
        (0, 0)
    );
}
