//! Synthetic graph/assignment tests; no real cohort, authority or withdrawal.
#![allow(clippy::unwrap_used)]
use super::*;
use crate::TaskSourceRecordV1;
use crate::TaskSourceScopeV1;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::id;
use crate::paired_supervised_test_support::inputs;
use pretty_assertions::assert_eq;

fn fixture() -> (Multiple, PairedReviewSourcePlanV1) {
    let original = inputs(6);
    let mut source = PairedReviewSourcePlanV1 {
        base_plan: original.base_plan,
        source_scope: TaskSourceScopeV1 {
            objective_digest: digest("paired-objective"),
            task_definition_digest: digest("paired-task-contract"),
            source_archive_digest: digest("synthetic-source-archive"),
        },
        source_records: (0..8)
            .map(|index| TaskSourceRecordV1 {
                source_file_digest: digest("synthetic-source-file"),
                source_row_index: index + 1,
                source_record_digest: digest(&format!("row-{index}")),
                task_id: id(&format!("task-{index}")),
                dependency_ids: vec![id(&format!("doc-{index}"))],
            })
            .collect(),
        folds: original.folds,
        unscored_source_records: original.unscored_source_records,
        tasks: original.tasks,
        runtime: original.runtime,
        policy: original.policy,
        metrics: original.metrics,
    };
    let observations: Vec<_> = (0..2)
        .map(|index| {
            let dependencies = ["artifact", "event", "input", "source", "support"].map(|kind| {
                format!(
                    "withdrawal.v2.{kind}.{}",
                    digest(&format!("{kind}-{index}"))
                )
            });
            Observation {
                withdrawal_request_digest: digest(&format!("original-request-{index}")).to_string(),
                provider: withdrawal::Config {
                    program: Source {
                        path: "/original/owner".into(),
                        digest: digest("same-pinned-owner-program").to_string(),
                    },
                    probe: Source {
                        path: format!("/original/probe-{index}").into(),
                        digest: digest(&format!("probe-{index}")).to_string(),
                    },
                },
                causal_dependencies: dependencies.into_iter().collect(),
            }
        })
        .collect();
    let assignments = source
        .tasks
        .iter()
        .enumerate()
        .map(|(index, task)| {
            let observation = &observations[index / 3];
            let record = source
                .source_records
                .iter_mut()
                .find(|record| record.source_record_digest == task.source_record_digest)
                .unwrap();
            record
                .dependency_ids
                .extend(observation.dependencies().unwrap());
            Assignment {
                evaluation_record_digest: task.source_record_digest.to_string(),
                withdrawal_request_digest: observation.withdrawal_request_digest.clone(),
            }
        })
        .collect();
    (
        Multiple {
            schema: "hepta.paired-withdrawal-observations.v2".into(),
            observations,
            assignments,
        },
        source,
    )
}
fn synchronize(config: &Multiple, source: &mut PairedReviewSourcePlanV1) {
    for record in &mut source.source_records {
        record
            .dependency_ids
            .retain(|id| !id.as_str().starts_with("withdrawal.v2."));
    }
    for assignment in &config.assignments {
        let observation = config
            .observations
            .iter()
            .find(|observation| {
                observation.withdrawal_request_digest == assignment.withdrawal_request_digest
            })
            .unwrap();
        let record = source
            .source_records
            .iter_mut()
            .find(|record| {
                record.source_record_digest.to_string() == assignment.evaluation_record_digest
            })
            .unwrap();
        record
            .dependency_ids
            .extend(observation.dependencies().unwrap());
    }
}
#[test]
fn distinct_actual_causes_can_supply_two_clusters_under_the_same_authority_prefix() {
    let (config, source) = fixture();
    let assignments = config.assignment_map(&source).unwrap();
    assert_eq!(
        assignments.values().copied().collect::<BTreeSet<_>>(),
        BTreeSet::from([0, 1])
    );
    let frozen = source.freeze().unwrap();
    assert_eq!(frozen.policy.minimum_independent_clusters, 2);
    withdrawal::require_independent_clusters(&frozen).unwrap();
    // The common program/CURRENT authority is verified on real invocation,
    // and does not become an unrelated statistical source dependency.
    assert_eq!(
        config.observations[0].provider.program,
        config.observations[1].provider.program
    );
}
#[test]
fn renamed_requests_sharing_real_source_or_artifact_events_remain_one_cluster() {
    for kind in ["source", "support", "event", "artifact", "input"] {
        let (mut config, mut source) = fixture();
        let shared = config.observations[0]
            .causal_dependencies
            .iter()
            .find(|value| value.starts_with(&format!("withdrawal.v2.{kind}.")))
            .unwrap()
            .clone();
        let other = config.observations[1]
            .causal_dependencies
            .iter_mut()
            .find(|value| value.starts_with(&format!("withdrawal.v2.{kind}.")))
            .unwrap();
        *other = shared;
        synchronize(&config, &mut source);
        config.assignment_map(&source).unwrap();
        let frozen = source.freeze().unwrap();
        assert_eq!(frozen.policy.minimum_independent_clusters, 2);
        assert!(
            withdrawal::require_independent_clusters(&frozen).is_err(),
            "{kind}"
        );
    }
}
#[test]
fn foreign_duplicate_unused_or_unbound_observation_assignments_fail_before_cas() {
    let (mut config, source) = fixture();
    config.assignments[1].evaluation_record_digest =
        config.assignments[0].evaluation_record_digest.clone();
    assert!(config.assignment_map(&source).is_err());
    let (mut config, source) = fixture();
    config.assignments[0].withdrawal_request_digest =
        digest("not-an-original-observation").to_string();
    assert!(config.assignment_map(&source).is_err());
    let (mut config, mut source) = fixture();
    for assignment in &mut config.assignments {
        assignment.withdrawal_request_digest =
            config.observations[0].withdrawal_request_digest.clone();
    }
    synchronize(&config, &mut source);
    assert!(config.assignment_map(&source).is_err());
    let (config, mut source) = fixture();
    source.source_records[2].dependency_ids.pop();
    assert!(config.assignment_map(&source).is_err());
    let (mut config, source) = fixture();
    config.observations[1].withdrawal_request_digest =
        config.observations[0].withdrawal_request_digest.clone();
    assert!(config.assignment_map(&source).is_err());
}
#[test]
fn causal_ids_cannot_be_zero_noncanonical_unknown_kind_or_authority_metadata() {
    let (mut config, source) = fixture();
    for value in [
        format!("withdrawal.v2.source.{}", Digest32::ZERO),
        "withdrawal.v2.clock.current".into(),
        format!(
            "withdrawal.v2.source.{}",
            digest("x").to_string().to_uppercase()
        ),
    ] {
        config.observations[0].causal_dependencies[2] = value;
        assert!(config.assignment_map(&source).is_err());
    }
}

#[test]
fn same_native_feature_new_requests_and_registrations_do_not_create_two_clusters() {
    let (mut config, mut source) = fixture();
    let feature_bytes = vec![1_i64; 512]
        .into_iter()
        .flat_map(i64::to_be_bytes)
        .collect::<Vec<_>>();
    let input = Digest32::of_bytes(&feature_bytes);
    for (index, observation) in config.observations.iter_mut().enumerate() {
        // Complete original G numeric envelopes differ in request and time,
        // but their actual model-independent Q24 input is exactly identical.
        let pin = digest("same-immutable-model").to_string();
        let numeric = serde_json::json!({
            "schema":"hepta.cpu-neuron.offline-observation.v1",
            "request_id":format!("new-request-{index}"),"executed_at_ms":101+index,
            "input_line_digest":digest(&format!("request-input-{index}")).to_string(),
            "input_digest":input.to_string(),"model_manifest_digest":pin,
            "runtime_digest":pin,"weights_digest":pin,"encoder_digest":pin,"head_digest":pin,
            "terminal_observed":true,"succeeded":true,"qualified":false,"authority_grants_any":false,
            "drive_q24":vec![0_i64;10],"prediction_q24":vec![0_i64;10],
            "latency_micros":12,"resident_bytes":1024,"transient_allocation_bytes":128});
        let line = serde_json::to_string(&numeric).unwrap() + "\n";
        let support = Digest32::of_bytes(line.as_bytes());
        let inputs = codex_hepta_learning_ledger::original_numeric_input_causes_v1(
            line.as_bytes(),
            &BTreeMap::from([(support, digest("same-immutable-model"))]),
        )
        .unwrap();
        assert_eq!(inputs[&support], input);
        *observation
            .causal_dependencies
            .iter_mut()
            .find(|value| value.starts_with("withdrawal.v2.support."))
            .unwrap() = format!("withdrawal.v2.support.{support}");
        *observation
            .causal_dependencies
            .iter_mut()
            .find(|value| value.starts_with("withdrawal.v2.input."))
            .unwrap() = format!("withdrawal.v2.input.{}", inputs[&support]);
    }
    synchronize(&config, &mut source);
    config.assignment_map(&source).unwrap();
    let frozen = source.freeze().unwrap();
    assert_eq!(frozen.policy.minimum_independent_clusters, 2);
    assert!(withdrawal::require_independent_clusters(&frozen).is_err());
}
