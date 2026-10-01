use super::*;
fn digest(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}
fn requests() -> (Value, Value, Value, Value) {
    let original = serde_json::json!({"schema":"hepta.fixed-custody-calibration-request.v1","operation":"review",
        "trust_config_path":"/protected/original-trust.json","ledger_directory":"/protected/ledger","witness_directory":"/protected/witness",
        "calibration_pairs_path":"/protected/private-calibration.jsonl","calibration_pairs_digest":digest("original-calibration").to_string(),
        "native_inputs_path":"/protected/actual-numeric-inputs.jsonl","source_mapping_path":"/protected/actual-source-map.jsonl",
        "candidate_manifest_path":"/protected/frozen-candidate.json","candidate_weights_path":"/protected/frozen-candidate.bin",
        "baseline_manifest_path":"/protected/training-only-majority.json","baseline_weights_path":"/protected/training-only-majority.bin",
        "generator_private_key_path":"/generator-private/generator.seed","predecessor_descriptor_path":null,
        "work_directory":"/protected/old-work","public_contract_path":"/protected/old-public-contract.json","receipt_path":"/protected/old-rejection.json"});
    let mut current = original.clone();
    current["schema"] = "hepta.fixed-custody-calibration-request.v2".into();
    current["cycle_program_approval_path"] = "/protected/current-approval.json".into();
    current["work_directory"] = "/protected/new-work".into();
    current["public_contract_path"] = "/protected/new-public-contract.json".into();
    current["receipt_path"] = "/protected/new-rejection.json".into();
    current["publication_directory"] = "/protected/publications/cycle-v2".into();
    let old_eval = serde_json::json!({"schema":"hepta.fixed-calibration-evaluator-config.v1","program_digest":digest("actual-fixed-evaluator").to_string(),
        "observer_program_digest":digest("old-observer").to_string(),"uid":994,"gid":978,"private_key_path":"/evaluator-private/evaluator.seed",
        "minimum_primary_improvement_q32":0,"scope_digest":digest("same-calibration-scope").to_string(),"candidate_weights_digest":digest("same-failed-candidate").to_string(),
        "publication_path":"/protected/publications/original-cut.json","ledger_path":"/protected/publications/original-ledger.bin",
        "inaccessible_paths":["/gold","/generator-private","/root-private","/observer-private","/other-evaluator"]});
    let mut new_eval = old_eval.clone();
    new_eval["schema"] = "hepta.fixed-calibration-evaluator-config.v2".into();
    new_eval["observer_program_digest"] = digest("current-fixed-observer").to_string().into();
    new_eval["publication_path"] =
        "/protected/publications/cycle-v2/signed-calibration-cut.json".into();
    new_eval["ledger_path"] = "/protected/publications/cycle-v2/ledger-readonly.bin".into();
    (original, current, old_eval, new_eval)
}
#[test]
fn fixed_calibration_cycle_accepts_only_new_artifacts_on_same_actual_model_source_key_and_history()
{
    let (original, current, old_eval, new_eval) = requests();
    let (publication, uid, gid) = validate_requests(
        &original,
        &current,
        &old_eval,
        &new_eval,
        digest("current-fixed-observer"),
        digest("actual-fixed-evaluator"),
    )
    .unwrap();
    assert_eq!(
        publication,
        PathBuf::from("/protected/publications/cycle-v2")
    );
    assert_eq!((uid, gid), (994, 978));
}
#[test]
fn fixed_calibration_cycle_refuses_gold_model_trust_and_durable_history_substitution() {
    let (original, current, old_eval, new_eval) = requests();
    for field in [
        "calibration_pairs_path",
        "calibration_pairs_digest",
        "candidate_manifest_path",
        "candidate_weights_path",
        "baseline_manifest_path",
        "baseline_weights_path",
        "trust_config_path",
        "generator_private_key_path",
        "native_inputs_path",
        "source_mapping_path",
        "ledger_directory",
        "witness_directory",
    ] {
        let mut changed = current.clone();
        changed[field] = "/substituted".into();
        assert!(
            validate_requests(
                &original,
                &changed,
                &old_eval,
                &new_eval,
                digest("current-fixed-observer"),
                digest("actual-fixed-evaluator")
            )
            .is_err(),
            "{field}"
        );
    }
}
#[test]
fn fixed_calibration_cycle_never_initializes_replaces_old_execution_or_reuses_old_publication() {
    let (original, current, old_eval, new_eval) = requests();
    for field in [
        "operation",
        "work_directory",
        "public_contract_path",
        "receipt_path",
    ] {
        let mut changed = current.clone();
        changed[field] = if field == "operation" {
            "initialize".into()
        } else {
            original[field].clone()
        };
        assert!(
            validate_requests(
                &original,
                &changed,
                &old_eval,
                &new_eval,
                digest("current-fixed-observer"),
                digest("actual-fixed-evaluator")
            )
            .is_err(),
            "{field}"
        );
    }
    for field in ["publication_path", "ledger_path"] {
        let mut changed = new_eval.clone();
        changed[field] = old_eval[field].clone();
        assert!(
            validate_requests(
                &original,
                &current,
                &old_eval,
                &changed,
                digest("current-fixed-observer"),
                digest("actual-fixed-evaluator")
            )
            .is_err(),
            "{field}"
        );
    }
}
#[test]
fn fixed_calibration_cycle_cannot_change_independent_evaluator_private_key_identity_or_frozen_threshold()
 {
    let (original, current, old_eval, new_eval) = requests();
    for field in [
        "private_key_path",
        "minimum_primary_improvement_q32",
        "uid",
        "gid",
        "scope_digest",
        "candidate_weights_digest",
        "inaccessible_paths",
        "program_digest",
    ] {
        let mut changed = new_eval.clone();
        changed[field] = Value::Null;
        assert!(
            validate_requests(
                &original,
                &current,
                &old_eval,
                &changed,
                digest("current-fixed-observer"),
                digest("actual-fixed-evaluator")
            )
            .is_err(),
            "{field}"
        );
    }
    let mut changed = new_eval;
    changed["observer_program_digest"] = digest("unmeasured-observer").to_string().into();
    assert!(
        validate_requests(
            &original,
            &current,
            &old_eval,
            &changed,
            digest("current-fixed-observer"),
            digest("actual-fixed-evaluator")
        )
        .is_err()
    );
}
#[test]
fn cycle_accepts_the_actual_offline_producer_schema_and_rejects_ambiguous_authority() {
    let ids = vec!["scifact.calibration.0".to_owned()];
    let actual = serde_json::json!({
        "schema":"hepta.cpu-neuron.offline-observation.v1",
        "request_id":"scifact.calibration.0","executed_at_ms":101,
        "terminal_observed":true,"succeeded":true,
        "authority_grants_any":false,"qualified":false
    });
    let stream = |value: &Value| format!("{value}\n").into_bytes();
    assert!(require_fresh_native_stream(&stream(&actual), &ids, 100, 110).is_ok());
    for field in ["schema", "authority_grants_any"] {
        let mut missing = actual.clone();
        missing.as_object_mut().unwrap().remove(field);
        assert!(require_fresh_native_stream(&stream(&missing), &ids, 100, 110).is_err());
    }
    for (field, value) in [
        ("schema", Value::from("unadmitted.offline.v2")),
        ("authority_grants_any", Value::from(true)),
        ("authority", Value::from(false)),
        ("authority", Value::from(true)),
    ] {
        let mut changed = actual.clone();
        changed[field] = value;
        assert!(require_fresh_native_stream(&stream(&changed), &ids, 100, 110).is_err());
    }
}

#[test]
fn cycle_requires_actual_fresh_whole_native_source_stream_not_cached_or_success_subset() {
    let ids = vec!["original-a".to_owned(), "original-b".to_owned()];
    let stream = |second: Value| {
        format!("{}\n{}\n",serde_json::json!({"schema":"hepta.cpu-neuron.offline-observation.v1","request_id":"original-a","executed_at_ms":101,"terminal_observed":true,"succeeded":true,"authority_grants_any":false,"qualified":false}),second).into_bytes()
    };
    let good = serde_json::json!({"schema":"hepta.cpu-neuron.offline-observation.v1","request_id":"original-b","executed_at_ms":102,"terminal_observed":true,"succeeded":true,"authority_grants_any":false,"qualified":false});
    assert!(require_fresh_native_stream(&stream(good.clone()), &ids, 100, 110).is_ok());
    for (field, value) in [
        ("request_id", Value::from("original-a")),
        ("executed_at_ms", Value::from(99)),
        ("executed_at_ms", Value::from(111)),
        ("succeeded", Value::from(false)),
        ("terminal_observed", Value::from(false)),
        ("authority_grants_any", Value::from(true)),
        ("qualified", Value::from(true)),
    ] {
        let mut bad = good.clone();
        bad[field] = value;
        assert!(
            require_fresh_native_stream(&stream(bad), &ids, 100, 110).is_err(),
            "{field}"
        );
    }
    assert!(require_fresh_native_stream(&stream(good.clone()), &ids[..1], 100, 110).is_err());
    let mut incomplete = stream(good);
    incomplete.pop();
    assert!(require_fresh_native_stream(&incomplete, &ids, 100, 110).is_err());
    assert!(original_input_ids(b"{\"request_id\":\"a\"}\n{\"request_id\":\"a\"}\n").is_err());
}
