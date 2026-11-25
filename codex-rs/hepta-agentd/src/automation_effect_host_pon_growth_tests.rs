use super::*;
use serde_json::json;

fn context() -> Context {
    Context {
        namespace: "test-growth".into(),
        network: "11".repeat(32),
        parameters: "22".repeat(32),
        genesis: "33".repeat(32),
    }
}

fn observation() -> Value {
    json!({"result": {
        "schema": OBSERVATION_SCHEMA,
        "packet_profile": PACKET_PROFILE,
        "state_profile": STATE_PROFILE,
        "network": "11".repeat(32), "parameters": "22".repeat(32), "genesis": "33".repeat(32),
        "block": "01".repeat(32), "stored_exact": true,
        "block_height": 5, "block_chainwork_hex": format!("{}01", "00".repeat(63)),
        "active_tip": "02".repeat(32), "active_tip_height": 7,
        "active_tip_chainwork_hex": format!("{}03", "00".repeat(63)),
        "active_chain_member": true, "active_depth": 2,
        "active_work_depth_hex": format!("{}02", "00".repeat(63)),
        "active_membership_sql_lookups": 5, "active_membership_sql_budget": MEMBERSHIP_SQL_BUDGET,
        "generation": 2, "accepted_task": null,
        "local_target_only": true, "global_absence_authority": false,
        "confirmation_authority": false, "finality_authority": false,
        "execution_authority": false, "production_activation": false,
    }})
}

#[test]
fn growth_context_refuses_legacy_cross_context_and_inconsistent_membership() {
    let context = context();
    let min_work = format!("{}01", "00".repeat(63));
    let original = observation();
    let parsed = context
        .parse_observation(&original, 1, &min_work)
        .expect("growth observation");
    assert!(parsed.confirmation_policy_satisfied);
    assert_eq!(parsed.accepted_task, None);
    assert!(super::super::parse_pon_chain_observation(&original, 1, &min_work).is_none());
    for (field, value) in [
        ("schema", json!("pon-native-exact-packet-observation-v3")),
        ("packet_profile", json!("PNP1")),
        ("state_profile", json!("authenticated-v1")),
        ("network", json!("44".repeat(32))),
        ("parameters", json!("44".repeat(32))),
        ("genesis", json!("44".repeat(32))),
        ("active_depth", json!(3)),
        (
            "active_work_depth_hex",
            json!(format!("{}03", "00".repeat(63))),
        ),
        ("active_membership_sql_budget", json!(2048)),
        ("active_membership_sql_lookups", json!(3)),
        ("local_target_only", json!(false)),
        ("global_absence_authority", json!(true)),
        ("confirmation_authority", json!(true)),
        ("finality_authority", json!(true)),
        ("execution_authority", json!(true)),
        ("production_activation", json!(true)),
    ] {
        let mut changed = original.clone();
        changed["result"][field] = value;
        assert!(
            context.parse_observation(&changed, 1, &min_work).is_none(),
            "accepted {field}"
        );
    }
}

#[test]
fn growth_local_absence_and_orphan_never_satisfy_confirmation() {
    let mut value = observation();
    value["result"]["active_chain_member"] = json!(false);
    for field in ["active_depth", "active_work_depth_hex"] {
        value["result"][field] = Value::Null;
    }
    let min_work = format!("{}01", "00".repeat(63));
    let orphan = context()
        .parse_observation(&value, 1, &min_work)
        .expect("stored orphan");
    assert!(orphan.stored_exact);
    assert!(!orphan.confirmation_policy_satisfied);
    value["result"]["stored_exact"] = json!(false);
    for field in [
        "block_height",
        "block_chainwork_hex",
        "active_membership_sql_lookups",
    ] {
        value["result"][field] = Value::Null;
    }
    let absent = context()
        .parse_observation(&value, 1, &min_work)
        .expect("local absence");
    assert!(!absent.stored_exact);
    assert!(!absent.confirmation_policy_satisfied);
    assert!(!absent.global_absence_authority);
    assert_eq!(absent.accepted_task, None);
    // A fresh native growth namespace has generation zero. This can prove
    // only local absence at the independently pinned genesis, never inclusion.
    value["result"]["generation"] = json!(0);
    value["result"]["active_tip"] = json!(context().genesis);
    value["result"]["active_tip_height"] = json!(0);
    value["result"]["active_tip_chainwork_hex"] = json!("00".repeat(64));
    let genesis = context()
        .parse_observation(&value, 1, &min_work)
        .expect("fresh namespace");
    assert!(!genesis.stored_exact && !genesis.confirmation_policy_satisfied);
    assert_eq!(genesis.accepted_task, None);
    // Admission can be durable before first activation. Exact retained bytes
    // reconcile a lost ACK, while the genesis tip remains unchanged.
    value["result"]["stored_exact"] = json!(true);
    value["result"]["block_height"] = json!(1);
    value["result"]["block_chainwork_hex"] = json!(format!("{}01", "00".repeat(63)));
    value["result"]["active_membership_sql_lookups"] = json!(1);
    let retained = context()
        .parse_observation(&value, 1, &min_work)
        .expect("unactivated admission");
    assert!(retained.stored_exact && !retained.active_chain_member);
    assert!(!retained.confirmation_policy_satisfied);
    assert_eq!(retained.accepted_task, None);
    for (field, invalid) in [
        ("active_tip", json!("44".repeat(32))),
        ("active_tip_height", json!(1)),
        (
            "active_tip_chainwork_hex",
            json!(format!("{}01", "00".repeat(63))),
        ),
        ("block_height", json!(0)),
        ("block_chainwork_hex", json!("00".repeat(64))),
        ("active_membership_sql_lookups", json!(3)),
    ] {
        let mut changed = value.clone();
        changed["result"][field] = invalid;
        assert!(
            context()
                .parse_observation(&changed, 1, &min_work)
                .is_none(),
            "accepted genesis {field}"
        );
    }
}

#[test]
fn growth_contract_binds_context_and_refuses_legacy_configuration_fields() {
    let value = json!({
        "schema_version":4, "provider_kind":PROVIDER_KIND,
        "provider_scope":"pon", "destination_id":"growth", "final_use_scope_sha256":"01".repeat(32),
        "chain_binary":"/chain", "chain_binary_sha256":"02".repeat(32), "chain_store":"/store",
        "chain_growth_namespace":"growth", "chain_network_sha256":"11".repeat(32),
        "chain_parameters_sha256":"22".repeat(32), "chain_genesis_sha256":"33".repeat(32),
        "chain_genesis_time":1, "chain_min_confirmation_depth":1,
        "chain_min_confirmation_work_depth_hex":format!("{}01", "00".repeat(63)), "timeout_ms":30000,
        "contract_id":"growth-contract", "contract_sha256":"03".repeat(32), "contract_authority_epoch":1,
        "contract_signature_hex":"04".repeat(64), "contract_verifying_key_hex":"05".repeat(32),
        "final_use_signer_id":"owner", "final_use_verifying_key_hex":"06".repeat(32),
        "final_use_revocations_file":"/revocations.json"
    });
    let config: HostFileV4 = serde_json::from_value(value.clone()).expect("v4 config");
    let original = contract_digest(&config).expect("contract digest");
    for field in [
        "chain_growth_namespace",
        "chain_network_sha256",
        "chain_parameters_sha256",
        "chain_genesis_sha256",
        "final_use_scope_sha256",
    ] {
        let mut changed = value.clone();
        changed[field] = json!("44".repeat(32));
        let config = serde_json::from_value(changed).expect("changed config");
        assert_ne!(
            contract_digest(&config).expect("changed digest"),
            original,
            "unbound {field}"
        );
    }
    for field in [
        "chain_state_backend",
        "chain_evaluation_policy",
        "chain_task_profile",
        "chain_model_profile",
        "chain_workers",
    ] {
        let mut changed = value.clone();
        changed[field] = json!("legacy");
        assert!(
            serde_json::from_value::<HostFileV4>(changed).is_err(),
            "accepted {field}"
        );
    }
}

#[test]
fn growth_adapter_uses_only_growth_cli_context() {
    let adapter = PonLocalProviderEffectAdapter {
        binary: PathBuf::from("/chain"),
        binary_sha256: Sha256Digest::for_bytes(b"fixture"),
        store: PathBuf::from("/store"),
        genesis_time: 1,
        profile: PonLocalProfile::Growth(context()),
        min_confirmation_depth: 1,
        min_confirmation_work_depth_hex: format!("{}01", "00".repeat(63)),
        timeout: Duration::from_secs(30),
    };
    for operation in ["submit", "packet-status"] {
        let command = adapter.command(operation, &adapter.binary);
        let args: Vec<_> = command
            .get_args()
            .map(|arg| arg.to_string_lossy().into_owned())
            .collect();
        assert_eq!(
            args,
            vec![
                format!("growth-{operation}"),
                "--development".into(),
                "--store".into(),
                "/store".into(),
                "--growth-namespace".into(),
                "test-growth".into(),
                "--genesis-time".into(),
                "1".into(),
                "--packet-stdin".into()
            ]
        );
    }
}
