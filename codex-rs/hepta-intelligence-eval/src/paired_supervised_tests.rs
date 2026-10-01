use crate::paired_supervised_estimate::estimate_paired_cut;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::Sink;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::id;
use crate::paired_supervised_test_support::inputs;
use crate::paired_supervised_test_support::runner;
use crate::*;
use codex_hepta_types::FixedQ32;

#[test]
fn paired_supervised_complete_native_trace_qualifies_and_persists_without_authority() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    let mut provider = signing.provider(&plan);
    let mut runner = runner();
    let execution = runner
        .evaluate_registered_paired_supervised(&registration, &mut provider, &signing.verifier, 30)
        .unwrap();
    assert_eq!(execution.estimate().cluster_count(), 128);
    assert_eq!(provider.release_count, 1);
    assert!(!execution.authority().grants_any());
    let context = signing.context();
    let evidence = signing.evaluation(&execution, &context);
    let mut sink = Sink::default();
    let receipt = runner
        .qualify_paired_and_persist(
            &execution,
            &context,
            &evidence,
            &signing.verifier,
            &mut sink,
            30,
        )
        .unwrap();
    assert_eq!(
        receipt.decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert_eq!(sink.calls, 1);
    assert!(!receipt.authority.grants_any());
    receipt.validate_integrity().unwrap();
    let mut tampered = receipt;
    tampered.decision.decision.disposition = IndependentEvaluationDispositionV1::Ineligible;
    assert!(tampered.validate_integrity().is_err());
}

#[test]
fn paired_supervised_native_primary_rejection_keeps_same_durable_evidence_path() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let mut provider = signing.provider(&plan);
    let cut = &mut provider.observations.as_mut().unwrap().cut;
    for row in &mut cut.rows {
        row.candidate.outcome = PairedClassObservationV1::Label {
            class_id: id("SUPPORT"),
            correct: false,
        };
        row.baseline.outcome = PairedClassObservationV1::Label {
            class_id: id("CONTRADICT"),
            correct: true,
        };
    }
    provider.observations.as_mut().unwrap().observer_evidence = signing.sign(
        1,
        &paired_observation_cut_signing_payload_v1(cut).unwrap(),
        22,
    );
    let mut runner = runner();
    let execution = runner
        .evaluate_registered_paired_supervised(
            &signing.register(&plan),
            &mut provider,
            &signing.verifier,
            30,
        )
        .unwrap();
    let context = signing.context();
    let evidence = signing.evaluation(&execution, &context);
    let mut sink = Sink::default();
    let receipt = runner
        .qualify_paired_and_persist(
            &execution,
            &context,
            &evidence,
            &signing.verifier,
            &mut sink,
            30,
        )
        .unwrap();
    assert_eq!(
        receipt.decision.decision.disposition,
        IndependentEvaluationDispositionV1::Ineligible
    );
    assert!(
        receipt
            .decision
            .decision
            .failed_metrics
            .contains(&id("accuracy"))
    );
    assert_eq!(sink.calls, 1);
}

#[test]
fn paired_supervised_reauthenticates_original_registration_before_any_provider_access() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    let mut provider = signing.provider(&plan);
    let mut runner = runner();
    let before = runner.holdout_state_digest();
    assert!(
        runner
            .evaluate_registered_paired_supervised(
                &registration,
                &mut provider,
                &signing.verifier,
                901
            )
            .is_err()
    );
    assert_eq!(provider.metadata_count, 0);
    assert_eq!(provider.release_count, 0);
    assert_eq!(runner.holdout_state_digest(), before);
    let other = SigningFixture::new(true);
    assert!(
        runner
            .evaluate_registered_paired_supervised(
                &registration,
                &mut provider,
                &other.verifier,
                30
            )
            .is_err()
    );
    assert_eq!(provider.metadata_count, 0);
    assert_eq!(runner.holdout_state_digest(), before);
}

#[test]
fn paired_supervised_after_consumption_failure_cannot_release_fresh_holdout_on_replay() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    let mut provider = signing.provider(&plan);
    provider.observations = None;
    let mut runner = runner();
    let before = runner.holdout_state_digest();
    assert!(
        runner
            .evaluate_registered_paired_supervised(
                &registration,
                &mut provider,
                &signing.verifier,
                30
            )
            .is_err()
    );
    let consumed = runner.holdout_state_digest();
    assert_ne!(consumed, before);
    provider.observations = Some(signing.cut(&plan));
    assert!(
        runner
            .evaluate_registered_paired_supervised(
                &registration,
                &mut provider,
                &signing.verifier,
                30
            )
            .is_err()
    );
    assert_eq!(provider.release_count, 1);
    assert_eq!(runner.holdout_state_digest(), consumed);
}

#[test]
fn paired_supervised_rejects_censored_complete_cohort_instead_of_dropping_failures() {
    let plan = freeze_paired_supervised_plan_v1(inputs(99)).unwrap();
    let signing = SigningFixture::new(false);
    let mut cut = signing.cut(&plan).cut;
    for index in [79, 84] {
        cut.rows[index].baseline.outcome = PairedClassObservationV1::Censored {
            reason: id("original-native-failure"),
        };
    }
    assert!(matches!(
        estimate_paired_cut(&plan, &cut),
        Err(PairedSupervisedErrorV1::Incomplete {
            tasks: 99,
            censored: 2
        })
    ));
    cut.rows.remove(84);
    cut.rows.remove(79);
    assert!(estimate_paired_cut(&plan, &cut).is_err());
}

#[test]
fn paired_supervised_abstain_is_wrong_class_with_frozen_coverage_not_missing_output() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let mut cut = signing.cut(&plan).cut;
    let original = estimate_paired_cut(&plan, &cut).unwrap();
    cut.rows[0].candidate.outcome = PairedClassObservationV1::Abstain;
    let abstain = estimate_paired_cut(&plan, &cut).unwrap();
    assert_eq!(abstain.candidate_abstentions, 1);
    assert!(abstain.metrics()[0].candidate.lower < original.metrics()[0].candidate.lower);
    for row in cut.rows.iter_mut().take(26) {
        row.candidate.outcome = PairedClassObservationV1::Abstain;
    }
    assert!(estimate_paired_cut(&plan, &cut).is_err());
}

#[test]
fn paired_supervised_refuses_duplicate_subset_or_unknown_original_request_and_runtime() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    for case in 0..5 {
        let mut cut = signing.cut(&plan).cut;
        match case {
            0 => {
                cut.rows[0] = cut.rows[1].clone();
            }
            1 => {
                cut.rows[0].candidate.request_id = id("different-request");
            }
            2 => {
                cut.rows[0].baseline.input_digest = digest("different-input");
            }
            3 => {
                cut.runtime.deployed_baseline_digest = digest("uninstalled-baseline");
            }
            _ => {
                cut.source_graph_digest = digest("subset-graph");
            }
        }
        assert!(estimate_paired_cut(&plan, &cut).is_err(), "case {case}");
    }
}

#[test]
fn paired_supervised_requires_actual_frozen_observed_cost_retention_unlearning_metrics() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    for case in 0..4 {
        let mut cut = signing.cut(&plan).cut;
        match case {
            0 => {
                cut.rows[0].observed_metrics.remove(0);
            }
            1 => {
                cut.rows[0].baseline.original_elapsed_micros = None;
            }
            2 => {
                cut.rows[0].candidate.original_elapsed_micros = Some(11_000);
            }
            _ => {
                cut.rows[0].observed_metrics[1].candidate = None;
            }
        }
        assert!(estimate_paired_cut(&plan, &cut).is_err(), "case {case}");
    }
}

#[test]
fn paired_supervised_authenticates_observer_cut_before_statistics_and_retains_consumption() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let mut provider = signing.provider(&plan);
    provider.observations.as_mut().unwrap().cut.rows[0]
        .baseline
        .outcome = PairedClassObservationV1::Abstain;
    let mut runner = runner();
    let before = runner.holdout_state_digest();
    assert!(
        runner
            .evaluate_registered_paired_supervised(
                &signing.register(&plan),
                &mut provider,
                &signing.verifier,
                30
            )
            .is_err()
    );
    assert_ne!(before, runner.holdout_state_digest());
    assert_eq!(provider.release_count, 1);
}

#[test]
fn paired_supervised_uses_actual_registration_and_execution_times_and_current_observer() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    for case in 0..3 {
        let mut provider = signing.provider(&plan);
        let cut = &mut provider.observations.as_mut().unwrap().cut;
        match case {
            0 => {
                cut.started_at_unix_micros = 11_000;
            }
            1 => {
                cut.finished_at_unix_micros = 31_000;
            }
            _ => {
                cut.rows[0].candidate.finished_at_unix_micros = 23_000;
            }
        }
        provider.observations.as_mut().unwrap().observer_evidence = signing.sign(
            1,
            &paired_observation_cut_signing_payload_v1(cut).unwrap(),
            30,
        );
        assert!(
            runner()
                .evaluate_registered_paired_supervised(
                    &signing.register(&plan),
                    &mut provider,
                    &signing.verifier,
                    30
                )
                .is_err()
        );
    }
}

#[test]
fn paired_supervised_independent_evaluator_cannot_share_observer_controller() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(true);
    let mut runner = runner();
    let execution = runner
        .evaluate_registered_paired_supervised(
            &signing.register(&plan),
            &mut signing.provider(&plan),
            &signing.verifier,
            30,
        )
        .unwrap();
    let context = signing.context();
    let evidence = signing.evaluation(&execution, &context);
    let mut sink = Sink::default();
    assert!(
        runner
            .qualify_paired_and_persist(
                &execution,
                &context,
                &evidence,
                &signing.verifier,
                &mut sink,
                30
            )
            .is_err()
    );
    assert_eq!(sink.calls, 0);
}

#[test]
fn paired_supervised_rejects_old_ope_signature_zero_receipts_and_missing_publication_ack() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let mut runner = runner();
    let execution = runner
        .evaluate_registered_paired_supervised(
            &signing.register(&plan),
            &mut signing.provider(&plan),
            &signing.verifier,
            30,
        )
        .unwrap();
    let mut context = signing.context();
    let mut sink = Sink::default();
    context.unlearning_receipt_digest = Digest32::ZERO;
    assert!(paired_evaluation_signing_payload_v1(&execution, &context).is_err());
    context = signing.context();
    context.retention_receipt_digests.clear();
    assert!(paired_evaluation_signing_payload_v1(&execution, &context).is_err());
    context = signing.context();
    let mut evidence = signing.evaluation(&execution, &context);
    let roles: Vec<_> = plan
        .metrics
        .iter()
        .map(|m| MetricRoleContractV2 {
            metric_id: m.contract.metric_id.clone(),
            role: m.role,
        })
        .collect();
    evidence.evaluator_bundle = signing.sign(
        2,
        &evaluation_signing_payload_v2(
            &runner
                .paired_qualification_bundle(&execution, &context)
                .unwrap(),
            &roles,
        )
        .unwrap(),
        25,
    );
    assert!(
        runner
            .qualify_paired_and_persist(
                &execution,
                &context,
                &evidence,
                &signing.verifier,
                &mut sink,
                30
            )
            .is_err()
    );
    assert_eq!(sink.calls, 0);
    sink.return_zero = true;
    assert!(
        runner
            .qualify_paired_and_persist(
                &execution,
                &context,
                &signing.evaluation(&execution, &context),
                &signing.verifier,
                &mut sink,
                30
            )
            .is_err()
    );
}

#[test]
fn paired_supervised_plan_binds_roles_ranges_alphabet_and_exact_final_membership() {
    let base = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    for case in 0..4 {
        let mut plan = base.clone();
        match case {
            0 => {
                plan.metrics[0].role = MetricRoleV2::NonInferiority {
                    maximum_regression: FixedQ32::ONE,
                }
            }
            1 => plan.metrics[0].contract.safety_floor = None,
            2 => plan.policy.output_alphabet.push(id("OTHER")),
            _ => {
                plan.tasks.pop_first();
            }
        }
        assert!(plan.validate().is_err());
    }
    let mut partial = inputs(128);
    partial.tasks.pop();
    assert!(freeze_paired_supervised_plan_v1(partial).is_err());
    let mut changed = inputs(128);
    changed.base_plan.claim_scope = EvaluationClaimScopeV1::SystemLongitudinal;
    assert!(freeze_paired_supervised_plan_v1(changed).is_err());
}

#[test]
fn paired_supervised_full_graph_unscored_bridge_forbids_training_final_dependency_leak() {
    let mut value = inputs(128);
    let mut records: Vec<_> = (0..130)
        .map(|index| TaskSourceRecordV1 {
            source_file_digest: digest("synthetic-source-file"),
            source_row_index: index + 1,
            source_record_digest: digest(&format!("row-{index}")),
            task_id: id(&format!("task-{index}")),
            dependency_ids: vec![id(&format!("doc-{index}"))],
        })
        .collect();
    records.push(TaskSourceRecordV1 {
        source_file_digest: digest("synthetic-source-file"),
        source_row_index: 131,
        source_record_digest: digest("unscored-bridge"),
        task_id: id("unscored-bridge"),
        dependency_ids: vec![id("doc-0"), id("doc-2")],
    });
    value.unscored_source_records = vec![digest("unscored-bridge")];
    value.source = FrozenTaskSourceLineageV1::freeze(
        &TaskSourceScopeV1 {
            objective_digest: digest("paired-objective"),
            task_definition_digest: digest("paired-task-contract"),
            source_archive_digest: digest("synthetic-source-archive"),
        },
        &records,
    )
    .unwrap();
    assert!(freeze_paired_supervised_plan_v1(value).is_err());
}
