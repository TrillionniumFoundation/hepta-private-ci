#![allow(clippy::expect_used, clippy::unwrap_used)]
use super::*;

fn config(root: bool) -> Configuration {
    let pin = Digest32::of_bytes(b"fixture public source").to_string();
    let source = serde_json::json!({"path":"/fixture/protected/source", "digest":pin});
    let value = serde_json::json!({
        "schema":if root {"hepta.cpu-neuron.self-iteration-root-custody-observation.v1"} else {"hepta.cpu-neuron.self-iteration-observation.v1"},
        "baseline_deployment":source,
        "learning_trust":source,
        "canonical_envelope_digest":pin,
        "observer":{"id":"fixture-observer","uid":if root {0} else {4},"gid":if root {0} else {4},"public_key_hex":"00".repeat(32),"credential_digest":pin,"private_key_path":"/fixture/observer/key"},
        "consumer":{"path":"/fixture/g/input","uid":1},
        "evaluation":{"path":"/fixture/e/input","uid":2},
        "selection":{"path":"/fixture/s/input","uid":if root {0} else {3}},
        "canary":source,
        "inaccessible_paths":if root {Vec::<&str>::new()} else {vec!["/fixture/private/a","/fixture/private/b","/fixture/private/c","/fixture/private/d","/fixture/private/e"]},
        "root_custody":if root {serde_json::json!({"program":source,"trust_configuration":source,"cycle_approval":null})} else {serde_json::Value::Null}
    });
    serde_json::from_value(value).unwrap()
}

#[test]
fn root_observation_cannot_enter_the_original_non_root_purpose() {
    let original = config(false);
    validate_purpose(&original, false).unwrap();
    assert!(validate_purpose(&original, true).is_err());
    let root = config(true);
    validate_purpose(&root, true).unwrap();
    assert!(validate_purpose(&root, false).is_err());
    let mut old_root = config(false);
    old_root.observer.uid = 0;
    assert!(validate_purpose(&old_root, false).is_err());
    let mut old_missing_denial = config(false);
    old_missing_denial.inaccessible_paths.pop();
    assert!(validate_purpose(&old_missing_denial, false).is_err());
}

#[test]
fn root_observation_requires_an_explicit_root_owner_and_independent_effect_roles() {
    let mut missing = config(true);
    missing.root_custody = None;
    assert!(validate_purpose(&missing, true).is_err());
    let mut wrong_owner = config(true);
    wrong_owner.observer.gid = 4;
    assert!(validate_purpose(&wrong_owner, true).is_err());
    let mut shared_effect = config(true);
    shared_effect.evaluation.uid = shared_effect.consumer.uid;
    assert!(validate_purpose(&shared_effect, true).is_err());
    let mut root_generator = config(true);
    root_generator.consumer.uid = 0;
    assert!(validate_purpose(&root_generator, true).is_err());
    // Root Selector is admitted only through its original independent physical
    // program and signed controller/key/principal checks in observe_inner.
    validate_purpose(&config(true), true).unwrap();
}
