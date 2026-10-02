//! Synthetic transport/identity tests; these do not certify a real withdrawal.
#![allow(clippy::unwrap_used)]
use super::*;
use pretty_assertions::assert_eq;

fn fixture() -> (ProbeBinding, serde_json::Value) {
    let pin = |name: &str| Digest32::of_bytes(name.as_bytes()).to_string();
    let binding = ProbeBinding {
        probe: Probe {
            schema: "hepta.cpu-neuron.dataset-withdrawal-current-probe.v1".into(),
            withdrawal_request: Source {
                path: "/original/request.json".into(),
                digest: pin("request"),
            },
            current_owner: Source {
                path: "/original/current-owner.json".into(),
                digest: pin("current"),
            },
        },
        targets: ["source-artifact", "descendant-artifact"]
            .into_iter()
            .map(|id| StableId::new(id).unwrap())
            .collect(),
        lineage_id: "original-lineage".into(),
        source_record_id: "original-record".into(),
        artifact_id: "source-artifact".into(),
    };
    let value = serde_json::json!({
        "schema":"hepta.cpu-neuron.dataset-withdrawal-inspection.v1",
        "request_digest":binding.probe.withdrawal_request.digest,"current_owner_digest":binding.probe.current_owner.digest,
        "observed_at_ms":101,"current_read_digest":pin("read"),"current_head_digest":pin("head"),"withdrawal_head":pin("withdrawals"),
        "source_ack":{"lineage_id":"original-lineage","source_record_id":"original-record","source_event_digest":pin("event"),
            "dataset_snapshot_id":"original-dataset","dataset_digest":pin("dataset"),"artifact_id":"source-artifact",
            "sequence":4,"event_digest":pin("unlearning"),"chain_digest":pin("chain")},
        "artifact_ack":{"operation_id":"original-lineage","phase":"Acknowledged","admission_digest":pin("admission"),
            "publication_intent_digest":pin("intent"),"registry_head":pin("registry"),"witness_digest":pin("witness"),
            "acknowledged_at":99,"state_digest":pin("state")},
        "delivery_denials":[
            {"artifact_id":"source-artifact","role":"source","gate":"RevalidatingCandidate::with_current","result":"Ineligible","accepted":false,"consumer_invoked":false},
            {"artifact_id":"descendant-artifact","role":"descendant","gate":"RevalidatingCandidate::with_current","result":"Ineligible","accepted":false,"consumer_invoked":false}],
        "model_weight_forgetting_claimed":false,
    });
    (binding, value)
}
fn line(value: &serde_json::Value) -> Vec<u8> {
    (serde_json::to_string(value).unwrap() + "\n").into_bytes()
}

#[test]
fn original_acknowledged_source_and_complete_actual_denials_are_required() {
    let (binding, original) = fixture();
    let value = parse(&line(&original), &binding, 100, 102).unwrap();
    assert_eq!(value.delivery_denial_fraction().unwrap(), FixedQ32::ONE);
    for (field, changed) in [
        (
            "request_digest",
            serde_json::json!(Digest32::of_bytes(b"other-request").to_string()),
        ),
        (
            "current_owner_digest",
            serde_json::json!(Digest32::of_bytes(b"old-owner").to_string()),
        ),
        ("observed_at_ms", serde_json::json!(99)),
        ("model_weight_forgetting_claimed", serde_json::json!(true)),
        (
            "withdrawal_head",
            serde_json::json!(Digest32::ZERO.to_string()),
        ),
        ("qualified", serde_json::json!(true)),
    ] {
        let mut changed_value = original.clone();
        changed_value[field] = changed;
        assert!(
            parse(&line(&changed_value), &binding, 100, 102).is_err(),
            "{field}"
        );
    }
    for (section, field, changed) in [
        ("source_ack", "sequence", serde_json::json!(0)),
        (
            "source_ack",
            "source_record_id",
            serde_json::json!("other-record"),
        ),
        (
            "source_ack",
            "append_disposition",
            serde_json::json!("appended"),
        ),
        ("artifact_ack", "phase", serde_json::json!("Prepared")),
        ("artifact_ack", "acknowledged_at", serde_json::json!(103)),
        (
            "artifact_ack",
            "operation_id",
            serde_json::json!("other-lineage"),
        ),
    ] {
        let mut changed_value = original.clone();
        changed_value[section][field] = changed;
        assert!(
            parse(&line(&changed_value), &binding, 100, 102).is_err(),
            "{section}.{field}"
        );
    }
    for field in ["accepted", "consumer_invoked"] {
        let mut changed = original.clone();
        changed["delivery_denials"][0][field] = true.into();
        assert!(parse(&line(&changed), &binding, 100, 102).is_err());
    }
    let mut missing = original.clone();
    missing["delivery_denials"].as_array_mut().unwrap().pop();
    assert!(parse(&line(&missing), &binding, 100, 102).is_err());
    let mut duplicate = original.clone();
    duplicate["delivery_denials"][1] = duplicate["delivery_denials"][0].clone();
    assert!(parse(&line(&duplicate), &binding, 100, 102).is_err());
    let bytes = line(&original);
    assert!(parse(&bytes[..bytes.len() - 1], &binding, 100, 102).is_err());
    assert!(parse(&[bytes.clone(), bytes].concat(), &binding, 100, 102).is_err());
}

#[test]
fn current_reinspection_cannot_replace_the_original_ack_or_frontier() {
    let (binding, value) = fixture();
    let before = parse(&line(&value), &binding, 100, 102).unwrap();
    let mut next = value;
    next["observed_at_ms"] = 103.into();
    let after = parse(&line(&next), &binding, 102, 104).unwrap();
    assert!(after.same_original_facts(&before));
    next["current_read_digest"] = Digest32::of_bytes(b"new-frontier").to_string().into();
    assert!(
        !parse(&line(&next), &binding, 102, 104)
            .unwrap()
            .same_original_facts(&before)
    );
}

#[test]
fn original_ledger_ack_may_name_a_genuine_revoked_descendant() {
    let (mut binding, mut value) = fixture();
    binding.artifact_id = "descendant-artifact".into();
    value["source_ack"]["artifact_id"] = "descendant-artifact".into();
    let parsed = parse(&line(&value), &binding, 100, 102).unwrap();
    assert_eq!(parsed.source_ack.artifact_id, "descendant-artifact");
    assert_eq!(parsed.delivery_denials[1].role, "descendant");
}

#[test]
fn shared_withdrawal_cannot_become_many_independent_task_samples() {
    use crate::TaskSourceRecordV1;
    use crate::TaskSourceScopeV1;
    use crate::paired_supervised_test_support::digest;
    use crate::paired_supervised_test_support::id;
    use crate::paired_supervised_test_support::inputs;
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
    let original = source.freeze().unwrap();
    require_independent_clusters(&original).unwrap();
    for record in &mut source.source_records[2..] {
        record.dependency_ids.push(id("one-original-withdrawal"));
    }
    // The original native source graph derives one cluster and retains its
    // prespecified minimum. No provider call or holdout CAS is needed.
    let frozen = source.freeze().unwrap();
    assert_eq!(
        frozen.policy.minimum_independent_clusters,
        original.policy.minimum_independent_clusters
    );
    assert!(require_independent_clusters(&frozen).is_err());
}
