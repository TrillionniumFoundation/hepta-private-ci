use super::*;

#[test]
fn non_root_gateway_composition_cannot_open_owner_policy() {
    assert_ne!(
        unsafe { libc::geteuid() },
        0,
        "ordinary caller fixture requires a non-root user"
    );
    let error = RootGatewayPeerV1::open(Path::new("/no-such-hepta-owner-policy"))
        .err()
        .expect("ordinary user cannot borrow Root enrollment");
    assert!(error.to_string().contains("requires Root"));
}

#[tokio::test]
#[ignore = "requires Root and an independent root-owned Linux cgroup"]
async fn root_gateway_peer_reuses_enrollment_and_fences_changed_policy() -> anyhow::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    use std::process::Command;
    use std::time::Duration;
    use tokio::net::UnixListener;

    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "actual Root fixture required"
    );
    let cgroup = crate::controller_peer::tests::RootCgroup::new()?;
    let directory = tempfile::Builder::new()
        .prefix("hepta-chat-peer-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o755))?;
    let policy_path = directory.path().join("policy.json");
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
    let mut policy = serde_json::json!({
        "version": 1, "workload_uid": 986, "workload_gid": 975,
        "agent_workload_uids": {agent.to_string(): 969},
        "cgroup_root": "hepta-chat-test-workloads",
        "resource_authority_frontier": "/run/unused-chat-test-frontier",
        "process_thread_reserve": 32,
        "matrix_resources": {
            "cpu_millis": 0, "memory_bytes": 0, "accelerator_millis": 0,
            "concurrent_turns": 0, "tool_processes": 0, "turn_queue_slots": 0
        },
        "controller_principal": {
            "uid": 1000, "gid": 1000, "desktop_uid": 1000,
            "gateway_executable": Path::new("/usr/bin/python3").canonicalize()?,
            "gateway_cgroup": cgroup.relative()
        }
    });
    std::fs::write(&policy_path, serde_json::to_vec(&policy)?)?;
    std::fs::set_permissions(&policy_path, std::fs::Permissions::from_mode(0o400))?;
    let gate = RootGatewayPeerV1::open(&policy_path)?;
    assert_eq!(gate.agent_workload_uid(&agent)?, 969);
    assert_eq!(gate.socket_group(), 1000);
    let socket = directory.path().join("ctl");
    let listener = UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o666))?;
    let peer_source = r#"
import ctypes,os,socket,sys
if sys.argv[2] != '-':
 with open(sys.argv[2]+'/cgroup.procs','w') as f:f.write(str(os.getpid()))
os.setgroups([]);os.setgid(1000);os.setuid(int(sys.argv[3]))
assert ctypes.CDLL(None).prctl(4,1)==0
s=socket.socket(socket.AF_UNIX);s.settimeout(3);s.connect(sys.argv[1])
try:s.recv(1)
except ConnectionResetError:pass
"#;
    for (uid, group, admitted) in [
        (1000, Some(&cgroup.0), true),
        (1000, None, false),
        (1001, Some(&cgroup.0), false),
    ] {
        let mut child = Command::new("/usr/bin/python3")
            .args(["-c", peer_source])
            .arg(&socket)
            .arg(group.map(|path| path.as_os_str()).unwrap_or("-".as_ref()))
            .arg(uid.to_string())
            .spawn()?;
        let (stream, _) = tokio::time::timeout(Duration::from_secs(2), listener.accept()).await??;
        assert_eq!(gate.verify(&stream).is_ok(), admitted);
        if admitted {
            policy["process_thread_reserve"] = serde_json::json!(33);
            std::fs::write(&policy_path, serde_json::to_vec(&policy)?)?;
            assert!(
                gate.verify(&stream).is_err(),
                "changed Root policy cannot silently rebind"
            );
            policy["process_thread_reserve"] = serde_json::json!(32);
            std::fs::write(&policy_path, serde_json::to_vec(&policy)?)?;
        }
        drop(stream);
        assert!(child.wait()?.success());
    }
    // A workload principal cannot be configured as the credential-owning gateway.
    policy["controller_principal"]["uid"] = serde_json::json!(969);
    std::fs::write(&policy_path, serde_json::to_vec(&policy)?)?;
    assert!(RootGatewayPeerV1::open(&policy_path).is_err());
    Ok(())
}
