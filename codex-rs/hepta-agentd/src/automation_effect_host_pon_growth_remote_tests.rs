use super::super::Sha256Digest;
use super::*;
use serde_json::json;
use std::path::PathBuf;

fn transport() -> Transport {
    Transport {
        context: pon_growth::Context {
            namespace: "live-test".into(),
            network: "11".repeat(32),
            parameters: "22".repeat(32),
            genesis: "33".repeat(32),
        },
        peer: "127.0.0.1:8123".parse().unwrap(),
        server_public: "44".repeat(32),
        resource_profile: "55".repeat(32),
        admission_bits: 8,
        admission_ttl_ms: 2000,
        credential: pon_process::CredentialPin {
            source: PathBuf::from("/operator/secret"),
            sha256: Sha256Digest::for_bytes(b"test"),
            public_key: [6; 32],
            snapshot_root: PathBuf::from("/owner/snapshots"),
        },
    }
}

fn status() -> Value {
    json!({
        "schema":pon_growth::OBSERVATION_SCHEMA, "packet_profile":"PNP2", "state_profile":"permanent-account-growth-native-v2",
        "network":"11".repeat(32), "parameters":"22".repeat(32), "genesis":"33".repeat(32),
        "block":"66".repeat(32), "stored_exact":false, "block_height":null, "block_chainwork_hex":null,
        "active_tip":"33".repeat(32), "active_tip_height":0, "active_tip_chainwork_hex":"00".repeat(64),
        "active_chain_member":false, "active_depth":null, "active_work_depth_hex":null,
        "active_membership_sql_lookups":null, "active_membership_sql_budget":8193,
        "generation":0, "accepted_task":null, "local_target_only":true,
        "global_absence_authority":false, "confirmation_authority":false, "finality_authority":false,
        "execution_authority":false, "production_activation":false,
    })
}

fn wrapper(operation: &str, value: Value) -> Value {
    json!({
        "schema":WRAPPER_SCHEMA, "transport_profile":TRANSPORT_PROFILE,
        "resource_profile":"55".repeat(32), "server_public":"44".repeat(32),
        "network":"11".repeat(32), "parameters":"22".repeat(32), "genesis":"33".repeat(32),
        "operation":operation, "verified_signed_response":true, "production_activation":false,
        "response":{"ok":true, "value":value, "solve_trials":1, "solve_elapsed_ns":1, "body_bytes_sent":1,
            "public_network_ready":false, "identity_authority":false},
    })
}

#[test]
fn live_result_requires_fixed_target_context_and_verified_success() {
    let transport = transport();
    let original = wrapper("growth_packet_status_v1", status());
    let normalized = transport
        .normalize("packet-status", original.clone())
        .expect("verified wrapper");
    let observation = transport
        .context
        .parse_observation(
            &normalized,
            /*min_depth*/ 1,
            &format!("{}01", "00".repeat(63)),
        )
        .expect("exact genesis observation");
    assert!(
        !observation.stored_exact
            && !observation.confirmation_policy_satisfied
            && !observation.global_absence_authority
    );
    assert_eq!(observation.accepted_task, None);
    for (field, invalid) in [
        ("schema", json!("pon-native-exact-packet-observation-v3")),
        (
            "transport_profile",
            json!("public-protected-development-v1"),
        ),
        ("server_public", json!("77".repeat(32))),
        ("resource_profile", json!("77".repeat(32))),
        ("network", json!("77".repeat(32))),
        ("parameters", json!("77".repeat(32))),
        ("genesis", json!("77".repeat(32))),
        ("operation", json!("growth_submit_v1")),
        ("verified_signed_response", json!(false)),
        ("production_activation", json!(true)),
    ] {
        let mut changed = original.clone();
        changed[field] = invalid;
        assert!(
            transport.normalize("packet-status", changed).is_none(),
            "accepted {field}"
        );
    }
    for (field, invalid) in [
        ("ok", json!(false)),
        ("public_network_ready", json!(true)),
        ("identity_authority", json!(true)),
        ("solve_trials", json!(-1)),
    ] {
        let mut changed = original.clone();
        changed["response"][field] = invalid;
        assert!(
            transport.normalize("packet-status", changed).is_none(),
            "accepted reply {field}"
        );
    }
    let mut changed = original.clone();
    changed["response"]["value"]["network"] = json!("77".repeat(32));
    assert!(transport.normalize("packet-status", changed).is_none());
    let mut changed = original;
    changed["response"]["value"]["active_membership_sql_budget"] = json!(1024);
    let normalized = transport
        .normalize("packet-status", changed)
        .expect("outer wrapper only");
    assert!(
        transport
            .context
            .parse_observation(
                &normalized,
                /*min_depth*/ 1,
                &format!("{}01", "00".repeat(63))
            )
            .is_none()
    );
}

#[test]
fn live_submit_ack_cannot_upgrade_to_confirmation_or_an_authority_claim() {
    let transport = transport();
    let value = json!({
        "schema":"pon-native-growth-submit-v1", "packet_profile":"PNP2", "state_profile":"permanent-account-growth-native-v2",
        "network":"11".repeat(32), "parameters":"22".repeat(32), "genesis":"33".repeat(32),
        "block":"66".repeat(32), "admitted":true, "active":"77".repeat(32), "generation":1,
        "physical_execution":false, "production_activation":false,
    });
    let original = wrapper("growth_submit_v1", value);
    let normalized = transport
        .normalize("submit", original.clone())
        .expect("durable submit");
    assert!(
        transport
            .context
            .parse_observation(
                &normalized,
                /*min_depth*/ 1,
                &format!("{}01", "00".repeat(63))
            )
            .is_none()
    );
    assert!(
        transport
            .normalize("packet-status", original.clone())
            .is_none()
    );
    for (field, invalid) in [
        ("admitted", json!(false)),
        ("physical_execution", json!(true)),
        ("production_activation", json!(true)),
        ("generation", json!("1")),
        ("block", json!("bad")),
    ] {
        let mut changed = original.clone();
        changed["response"]["value"][field] = invalid;
        assert!(
            transport.normalize("submit", changed).is_none(),
            "accepted submit {field}"
        );
    }
}

#[test]
fn live_command_uses_fixed_transport_without_local_store_or_recovery() {
    let transport = transport();
    let command = transport.command(
        "submit",
        Path::new("/sealed/chain"),
        /*genesis_time*/ 123,
    );
    let args: Vec<_> = command
        .get_args()
        .map(|arg| arg.to_string_lossy().into_owned())
        .collect();
    assert_eq!(
        args,
        vec![
            "push".to_string(),
            "--development".into(),
            "--admission-profile".into(),
            TRANSPORT_PROFILE.into(),
            "--growth-namespace".into(),
            "live-test".into(),
            "--genesis-time".into(),
            "123".into(),
            "--peer".into(),
            "127.0.0.1:8123".into(),
            "--server-public".into(),
            "44".repeat(32),
            "--admission-bits".into(),
            "8".into(),
            "--admission-ttl-ms".into(),
            "2000".into(),
            "--resource-profile-sha256".into(),
            "55".repeat(32),
            "--packet-stdin".into()
        ]
    );
}
