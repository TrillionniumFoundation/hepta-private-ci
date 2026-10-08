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
        "active_tip_chainwork_hex": format!("{}05", "00".repeat(63)),
        "active_chain_member": true, "active_depth": 2,
        "active_work_depth_hex": format!("{}04", "00".repeat(63)),
        "active_membership_sql_lookups": 2,
        "active_membership_sql_budget": 1024,
        "generation": 3,
        "local_target_only": true, "global_absence_authority": false,
        "confirmation_authority": false, "finality_authority": false,
        "execution_authority": false, "production_activation": false
    }})
}

fn parse(value: &Value) -> Option<crate::AutomationEffectChainObservation> {
    parse_pon_chain_observation(value, 1, &format!("{}01", "00".repeat(63)))
}

#[test]
fn pon_depth_must_equal_height_difference_under_the_signed_policy() {
    let value = observation();
    assert!(parse(&value).is_some());
    for depth in [0, 1, 3, u64::MAX] {
        let mut changed = value.clone();
        changed["result"]["active_depth"] = json!(depth);
        assert!(parse(&changed).is_none(), "forged depth accepted");
    }
}

#[test]
fn pon_tip_identity_height_and_work_must_describe_one_active_block() {
    let mut value = observation();
    value["result"]["block_height"] = json!(7);
    value["result"]["active_depth"] = json!(0);
    value["result"]["block_chainwork_hex"] = value["result"]["active_tip_chainwork_hex"].clone();
    value["result"]["active_work_depth_hex"] = json!("00".repeat(64));
    assert!(parse(&value).is_none(), "wrong active tip identity accepted");

    value["result"]["block"] = value["result"]["active_tip"].clone();
    assert!(parse(&value).is_some());
    value["result"]["active_chain_member"] = json!(false);
    value["result"]["active_depth"] = Value::Null;
    value["result"]["active_work_depth_hex"] = Value::Null;
    assert!(parse(&value).is_none(), "tip cannot report itself inactive");
}

#[test]
fn pon_inconsistent_work_delta_does_not_receive_confirmation_credit() {
    let mut value = observation();
    value["result"]["active_work_depth_hex"] = json!(format!("{}03", "00".repeat(63)));
    assert!(parse(&value).is_none());
    value["result"]["active_work_depth_hex"] = json!(format!("{}04", "00".repeat(63)));
    value["result"]["active_tip_height"] = json!(4);
    assert!(parse(&value).is_none(), "underflowing ancestry accepted");
}

#[test]
fn pon_inactive_fork_and_absent_packet_are_non_authoritative() {
    let mut value = observation();
    value["result"]["active_chain_member"] = json!(false);
    value["result"]["active_depth"] = Value::Null;
    value["result"]["active_work_depth_hex"] = Value::Null;
    value["result"]["block_height"] = json!(9);
    let inactive = parse(&value).expect("inactive side branch");
    assert!(!inactive.active_chain_member && inactive.stored_exact);
    assert!(!inactive.confirmation_policy_satisfied);
    assert!(!inactive.confirmation_authority && !inactive.finality_authority);
    value["result"]["stored_exact"] = json!(false);
    value["result"]["block_height"] = Value::Null;
    value["result"]["block_chainwork_hex"] = Value::Null;
    value["result"]["active_membership_sql_lookups"] = Value::Null;
    let absent = parse(&value).expect("local absence");
    assert!(!absent.stored_exact && !absent.global_absence_authority);
}

#[tokio::test]
async fn pon_oversized_packet_never_launches_subprocess() {
    let (_directory, adapter) = fixture(
        "#!/bin/sh\necho touched > /dev/null\n",
        Duration::from_millis(200),
    );
    let outcome = tokio::task::spawn_blocking(move || adapter.invoke("submit", &vec![0; 1024 * 1024 + 1]))
        .await
        .unwrap();
    assert!(matches!(outcome, PonInvocation::BeforeStart));
}

#[cfg(target_os = "linux")]
#[test]
fn pon_verified_executable_fd_stays_on_original_object_after_path_swap() {
    use std::os::fd::AsRawFd;
    let (_directory, adapter) = fixture(
        "#!/bin/sh\nprintf original\n",
        Duration::from_secs(2),
    );
    let file = open_verified_binary(&adapter.binary, &adapter.binary_sha256)
        .expect("open exact pinned original");
    let executable = format!("/proc/{}/fd/{}", std::process::id(), file.as_raw_fd());
    let displaced = adapter.store.join("displaced-original");
    fs::rename(&adapter.binary, &displaced).expect("replace original pathname");
    fs::write(&adapter.binary, "#!/bin/sh\nprintf substituted\n").expect("replacement");
    fs::set_permissions(&adapter.binary, fs::Permissions::from_mode(0o700))
        .expect("replacement permissions");

    // A pathname-only spawn at this moment would run "substituted" instead.
    let executed = Command::new(executable).output().expect("descriptor-backed exec");
    assert!(executed.status.success());
    assert_eq!(executed.stdout, b"original");
    assert!(open_verified_binary(&adapter.binary, &adapter.binary_sha256).is_err());
}
