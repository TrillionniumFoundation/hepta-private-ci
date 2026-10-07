//! Real local pipe/child-process fixtures. These scripts are not Chain nodes,
//! signed operations, model evaluation, or ordinary-product acceptance evidence.
use super::*;
use serde_json::json;
use std::os::unix::fs::PermissionsExt;

fn fixture(script: &str, timeout: Duration) -> (tempfile::TempDir, PonLocalProviderEffectAdapter) {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let binary = root.join("child");
    fs::write(&binary, script).unwrap();
    fs::set_permissions(&binary, fs::Permissions::from_mode(0o700)).unwrap();
    fs::write(root.join("native.sqlite"), b"fixture-not-a-ledger").unwrap();
    let adapter = PonLocalProviderEffectAdapter {
        binary,
        binary_sha256: Sha256Digest::for_bytes(script.as_bytes()),
        store: root,
        state_backend: "authenticated-v1".into(),
        genesis_time: 1,
        evaluation_policy: "fixture".into(),
        task_profile: "fixture".into(),
        model_profile: "fixture".into(),
        workers: 1,
        min_confirmation_depth: 1,
        min_confirmation_work_depth_hex: format!("{}01", "00".repeat(63)),
        timeout,
    };
    (directory, adapter)
}

#[tokio::test]
async fn pon_blocked_stdin_is_part_of_the_original_operation_deadline() {
    let (_directory, adapter) = fixture("#!/bin/sh\nexec sleep 5\n", Duration::from_millis(150));
    let started = Instant::now();
    let outcome =
        tokio::task::spawn_blocking(move || adapter.invoke("submit", &vec![1; 1024 * 1024]))
            .await
            .unwrap();
    assert!(matches!(outcome, PonInvocation::Unknown));
    assert!(
        started.elapsed() < Duration::from_secs(2),
        "stdin escaped original deadline"
    );
}

#[tokio::test]
async fn pon_stderr_limit_cannot_be_hidden_by_small_success_stdout() {
    let script = "#!/bin/sh\ncat >/dev/null\nhead -c 65537 /dev/zero >&2\nprintf '{\"ok\":true}'\n";
    let (_directory, adapter) = fixture(script, Duration::from_secs(2));
    let outcome = tokio::task::spawn_blocking(move || adapter.invoke("packet-status", b"packet"))
        .await
        .unwrap();
    assert!(
        matches!(outcome, PonInvocation::Unknown),
        "stderr overrun was accepted"
    );
}

#[tokio::test]
async fn pon_success_drains_both_pipes_and_observes_stdin_eof() {
    let script = "#!/bin/sh\ncat >/dev/null\nprintf diagnostic >&2\nprintf '{\"ok\":true}'\n";
    let (_directory, adapter) = fixture(script, Duration::from_secs(2));
    let outcome =
        tokio::task::spawn_blocking(move || adapter.invoke("packet-status", &vec![2; 1024 * 1024]))
            .await
            .unwrap();
    match outcome {
        PonInvocation::Value(value) => assert_eq!(value, json!({"ok": true})),
        PonInvocation::Unknown | PonInvocation::BeforeStart => {
            panic!("complete child output was lost")
        }
    }
}

#[tokio::test]
async fn pon_stdout_limit_nonzero_exit_and_partial_json_remain_unknown() {
    for script in [
        "#!/bin/sh\ncat >/dev/null\nhead -c 65537 /dev/zero\n",
        "#!/bin/sh\ncat >/dev/null\nprintf '{\"ok\":true}'\nexit 7\n",
        "#!/bin/sh\ncat >/dev/null\nprintf '{'\n",
    ] {
        let (_directory, adapter) = fixture(script, Duration::from_secs(2));
        let outcome = tokio::task::spawn_blocking(move || adapter.invoke("submit", b"packet"))
            .await
            .unwrap();
        assert!(matches!(outcome, PonInvocation::Unknown));
    }
}

fn observation() -> Value {
    json!({"result": {
        "schema": "pon-native-exact-packet-observation-v3",
        "block": "01".repeat(32), "stored_exact": true, "block_height": 5,
        "block_chainwork_hex": format!("{}01", "00".repeat(63)),
        "active_tip": "02".repeat(32), "active_tip_height": 7,
        "active_tip_chainwork_hex": format!("{}03", "00".repeat(63)),
        "active_chain_member": true, "active_depth": 2,
        "active_work_depth_hex": format!("{}02", "00".repeat(63)),
        "active_membership_sql_lookups": 2, "active_membership_sql_budget": 1024,
        "generation": 3, "local_target_only": true, "global_absence_authority": false,
        "confirmation_authority": false, "finality_authority": false,
        "execution_authority": false, "production_activation": false
    }})
}

fn parse(value: &Value) -> Option<crate::AutomationEffectChainObservation> {
    parse_pon_chain_observation(value, 1, &format!("{}01", "00".repeat(63)))
}

#[test]
fn pon_depth_must_equal_actual_height_difference_not_a_plausible_number() {
    let value = observation();
    assert!(parse(&value).unwrap().confirmation_policy_satisfied);
    for depth in [0, 1, 3, u64::MAX] {
        let mut changed = value.clone();
        changed["result"]["active_depth"] = json!(depth);
        assert!(parse(&changed).is_none(), "forged height depth accepted");
    }
    let mut changed = value;
    changed["result"]["active_work_depth_hex"] = json!("00".repeat(64));
    assert!(parse(&changed).is_none(), "forged work depth accepted");
}

#[test]
fn pon_tip_identity_and_height_cannot_describe_two_different_active_blocks() {
    let mut value = observation();
    value["result"]["block_height"] = json!(7);
    value["result"]["active_depth"] = json!(0);
    value["result"]["block_chainwork_hex"] = value["result"]["active_tip_chainwork_hex"].clone();
    value["result"]["active_work_depth_hex"] = json!("00".repeat(64));
    assert!(parse(&value).is_none());
    value["result"]["block"] = value["result"]["active_tip"].clone();
    assert!(!parse(&value).unwrap().confirmation_policy_satisfied);
    value["result"]["active_chain_member"] = json!(false);
    value["result"]["active_depth"] = Value::Null;
    value["result"]["active_work_depth_hex"] = Value::Null;
    assert!(parse(&value).is_none());
}

#[test]
fn pon_inactive_fork_and_absent_packet_keep_non_authoritative_shapes() {
    let mut value = observation();
    value["result"]["active_chain_member"] = json!(false);
    value["result"]["active_depth"] = Value::Null;
    value["result"]["active_work_depth_hex"] = Value::Null;
    value["result"]["block_height"] = json!(9);
    let inactive = parse(&value).unwrap();
    assert!(inactive.stored_exact && !inactive.active_chain_member);
    assert!(!inactive.confirmation_policy_satisfied && !inactive.execution_authority);
    value["result"]["stored_exact"] = json!(false);
    for field in [
        "block_height",
        "block_chainwork_hex",
        "active_membership_sql_lookups",
    ] {
        value["result"][field] = Value::Null;
    }
    let absent = parse(&value).unwrap();
    assert!(!absent.stored_exact && !absent.global_absence_authority);
    value["result"]["generation"] = json!(0);
    assert!(parse(&value).is_none());
}

#[test]
fn pon_distinct_active_ancestor_cannot_have_zero_required_work_distance() {
    let mut value = observation();
    value["result"]["block_chainwork_hex"] = value["result"]["active_tip_chainwork_hex"].clone();
    value["result"]["active_work_depth_hex"] = json!("00".repeat(64));
    assert!(parse(&value).is_none());
}

#[tokio::test]
async fn pon_descendant_held_pipe_cannot_extend_the_exchange_deadline() {
    // This trusted fixture descendant exits by itself. The adapter claims
    // bounded pipe handling, not arbitrary descendant supervision.
    let script = "#!/bin/sh\ncat >/dev/null\nsleep 1 &\nprintf '{\"ok\":true}'\nexit 0\n";
    let (_directory, adapter) = fixture(script, Duration::from_millis(150));
    let outcome = tokio::task::spawn_blocking(move || adapter.invoke("submit", b"packet"))
        .await
        .unwrap();
    assert!(matches!(outcome, PonInvocation::Unknown));
}
