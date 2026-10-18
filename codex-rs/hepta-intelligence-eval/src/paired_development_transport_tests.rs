//! Synthetic protocol boundaries only, never installed G or physical cost proof.
#![allow(clippy::unwrap_used)]
use super::*;
use crate::fixed_paired_generator_host::measured_contract;
use crate::paired_supervised_test_support::digest;

fn fixture() -> (Encoder, serde_json::Value) {
    let encoder: Encoder = serde_json::from_value(serde_json::json!({
        "socket":"/synthetic-root/encoder.sock","config":{"path":"/synthetic-root/config","digest":digest("config").to_string()},
        "normalization":digest("normalization").to_string(),"tokenizer":digest("tokenizer").to_string(),
        "weights":digest("weights").to_string(),"manifest":digest("physical-nomic-manifest").to_string(),
    })).unwrap();
    let account = |unit: &str, pid: u32, uid: u32| {
        serde_json::json!({
            "unit":unit,"pid":pid,"uid":uid,"start_ticks":99,"cgroup":format!("/system.slice/{unit}"),
            "cpu_usage_usec":30,"memory_current_bytes":40,"memory_peak_bytes":50,
        })
    };
    let producer = account(
        "hepta-native-generator-synthetic.service",
        std::process::id(),
        1000,
    );
    let services = vec![
        account("synthetic-encoder.service", 2, 0),
        account("synthetic-backend.service", 3, 968),
    ];
    let response = serde_json::json!({"schema":"hepta.fixed-nomic-public-development-pair.v1",
        "purpose":PURPOSE,"batch_id":"public-synthetic","pair_id":"pair-1","source_row_sha256":digest("row").to_string(),
        "encoder_config_sha256":encoder.config.digest,"normalization_sha256":encoder.normalization,
        "tokenizer_sha256":encoder.tokenizer,"weights_sha256":encoder.weights,"encoder_manifest_sha256":encoder.manifest,
        "physical_elapsed_micros":12,"measurement_elapsed_micros":13,"features_q24":vec![1;512],
        "cost_context":{"accounting":"entire-encoder-and-backend-service-conservative","producer_before":producer,
            "producer_after":producer,"services_before":services,"services_after":services}});
    (encoder, response)
}
fn valid(encoder: &Encoder, value: serde_json::Value) -> bool {
    serde_json::from_value::<Response>(value)
        .and_then(|response| {
            response
                .validate(
                    encoder,
                    "public-synthetic",
                    "pair-1",
                    &digest("row").to_string(),
                    1000,
                )
                .map_err(serde::de::Error::custom)
        })
        .is_ok()
}
#[test]
fn exact_physical_route_is_not_old_goal_or_child_producer() {
    let (encoder, value) = fixture();
    assert!(valid(&encoder, value.clone()));
    for (field, bad) in [
        ("purpose", serde_json::json!("normalGoal")),
        ("batch_id", serde_json::json!("old-scope")),
        (
            "weights_sha256",
            serde_json::json!(digest("otherweights").to_string()),
        ),
        (
            "encoder_manifest_sha256",
            serde_json::json!(digest("cpu-alias-manifest").to_string()),
        ),
        ("physical_elapsed_micros", serde_json::json!(0)),
        ("measurement_elapsed_micros", serde_json::json!(11)),
        ("features_q24", serde_json::json!(vec![0; 512])),
    ] {
        let mut altered = value.clone();
        altered[field] = bad;
        assert!(!valid(&encoder, altered));
    }
    let mut child = value.clone();
    child["cost_context"]["producer_before"]["pid"] = serde_json::json!(std::process::id() + 1);
    assert!(!valid(&encoder, child));
    let mut goal = value;
    goal["run_tuple"] = serde_json::json!({"run_id":"forbidden"});
    assert!(!valid(&encoder, goal));
}
#[test]
fn entire_service_counters_are_bound_and_missing_or_regressed_facts_reject() {
    let (encoder, value) = fixture();
    for path in [
        "cpu_usage_usec",
        "memory_peak_bytes",
        "start_ticks",
        "uid",
        "cgroup",
    ] {
        let mut altered = value.clone();
        altered["cost_context"]["services_after"][0][path] =
            serde_json::json!(if path == "uid" { 1 } else { 0 });
        assert!(!valid(&encoder, altered));
    }
    let mut missing = value.clone();
    missing["cost_context"]["services_after"][1]
        .as_object_mut()
        .unwrap()
        .remove("cpu_usage_usec");
    assert!(!valid(&encoder, missing));
    let original = serde_json::to_vec(&value).unwrap();
    let mut changed = value;
    changed["cost_context"]["services_after"][1]["cpu_usage_usec"] = serde_json::json!(31);
    assert_ne!(
        measured_contract(digest("root-contract"), &original),
        measured_contract(
            digest("root-contract"),
            &serde_json::to_vec(&changed).unwrap()
        )
    );
}
#[test]
fn duplicate_or_missing_cost_fields_do_not_decode_as_default_zero() {
    let (_, value) = fixture();
    let raw = serde_json::to_string(&value).unwrap();
    let duplicate = raw.replacen(
        "\"cpu_usage_usec\":30",
        "\"cpu_usage_usec\":30,\"cpu_usage_usec\":30",
        1,
    );
    assert!(serde_json::from_str::<Response>(&duplicate).is_err());
    let mut absent = value;
    absent.as_object_mut().unwrap().remove("cost_context");
    assert!(serde_json::from_value::<Response>(absent).is_err());
}
