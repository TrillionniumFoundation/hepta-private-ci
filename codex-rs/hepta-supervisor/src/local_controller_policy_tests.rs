use super::*;

fn policy() -> Policy {
    Policy {
        version: 1,
        workload_uid: 65534,
        workload_gid: 65534,
        cgroup_root: "hepta-fixture".into(),
        resource_authority_frontier: PathBuf::from("/var/lib/hepta-frontier"),
        process_thread_reserve: 32,
        matrix_resources: ResourceVectorV1::default(),
        self_iteration_config_directory: None,
        observer_principal: None,
        controller_principal: Some(crate::controller_peer::ControllerPrincipal {
            uid: 65533,
            gid: 65533,
            desktop_uid: 1000,
            gateway_executable: PathBuf::from("/usr/bin/python3.12"),
            gateway_cgroup: "/hepta-controller-fixture".into(),
        }),
    }
}

#[test]
fn shared_workload_credentials_cannot_enable_lifecycle_control() {
    let good = policy();
    assert!(good.validate_controller_isolation().is_ok());
    for field in ["uid", "gid", "desktop_uid"] {
        let mut bad = policy();
        let principal = bad.controller_principal.as_mut().unwrap();
        match field {
            "uid" => principal.uid = bad.workload_uid,
            "gid" => principal.gid = bad.workload_gid,
            "desktop_uid" => principal.desktop_uid = bad.workload_uid,
            _ => unreachable!(),
        }
        assert!(bad.validate_controller_isolation().is_err());
    }
    let mut disabled = good;
    disabled.controller_principal = None;
    assert!(disabled.validate_controller_isolation().is_ok());
}

#[tokio::test]
#[ignore = "requires sudo: root-owned production directory permissions and independent kernel peer UID"]
async fn independent_gateway_uid_traverses_only_enrolled_socket() -> anyhow::Result<()> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    use std::process::Command;
    if unsafe { libc::geteuid() } != 0 {
        let output=Command::new("sudo").args(["-n"]).arg(std::env::current_exe()?)
            .args(["--exact","local_fleet_host::controller_policy_tests::independent_gateway_uid_traverses_only_enrolled_socket","--ignored","--nocapture"]).output()?;
        anyhow::ensure!(
            output.status.success(),
            "root qualification failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        anyhow::ensure!(
            String::from_utf8_lossy(&output.stdout).contains("1 passed"),
            "root qualification did not execute"
        );
        return Ok(());
    }
    let temp = tempfile::Builder::new()
        .prefix("hepta-uid-path-")
        .tempdir_in("/var/lib")?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o755))?;
    let registry = FleetRegistry::initialize(codex_hepta_paths::HeptaFleetRoot::parse(
        temp.path().join("fleet"),
    )?)?;
    let policy = policy();
    policy.validate_controller_isolation()?;
    containment::protect_registry(&registry, &policy)?;
    assert_eq!(
        std::fs::metadata(registry.layout().fleet_root().as_path())?.mode() & 0o777,
        0o751
    );
    assert_eq!(
        std::fs::metadata(registry.layout().agents_root())?.mode() & 0o777,
        0o750
    );
    let directory = registry.layout().run_root().join("controller");
    std::fs::create_dir(&directory)?;
    let socket = directory.join("ctl");
    let listener = tokio::net::UnixListener::bind(&socket)?;
    for path in [&directory, &socket] {
        let path = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())?;
        anyhow::ensure!(
            unsafe { libc::chown(path.as_ptr(), 0, 65533) } == 0,
            "fixture chown"
        );
    }
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o750))?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o660))?;
    let cgroup = crate::controller_peer::tests::RootCgroup::new()?;
    let mut enrollment = policy.controller_principal.clone().unwrap();
    enrollment.gateway_executable = std::path::Path::new("/usr/bin/python3").canonicalize()?;
    enrollment.gateway_cgroup = cgroup.relative();
    let gate = crate::controller_peer::ControllerPeerGate::open(enrollment, &policy.cgroup_root)?;
    let code = r#"import ctypes,os,socket,sys
with open(sys.argv[5]+'/cgroup.procs','w') as f:f.write(str(os.getpid()))
os.setgroups([]);os.setgid(int(sys.argv[3]));os.setuid(int(sys.argv[2]));assert ctypes.CDLL(None).prctl(4,1)==0
s=socket.socket(socket.AF_UNIX)
try:
 s.connect(sys.argv[1]);s.sendall(b'positive');s.recv(1);result='connected'
except PermissionError: result='denied'
try:os.listdir(sys.argv[4]);private='visible'
except PermissionError:private='private'
print(result+' '+private)
"#;
    for (uid, gid, expected) in [
        (65533, 65533, "connected private"),
        (65532, 65532, "denied private"),
        (65534, 65534, "denied visible"),
    ] {
        let peer = Command::new("/usr/bin/python3")
            .args(["-c", code])
            .arg(&socket)
            .arg(uid.to_string())
            .arg(gid.to_string())
            .arg(registry.layout().agents_root())
            .arg(&cgroup.0)
            .stdout(std::process::Stdio::piped())
            .spawn()?;
        if uid == 65533 {
            let (mut stream, _) =
                tokio::time::timeout(Duration::from_secs(5), listener.accept()).await??;
            assert_eq!(stream.peer_cred()?.uid(), 65533);
            gate.verify(&stream)?;
            use tokio::io::AsyncWriteExt;
            stream.write_all(b"x").await?;
            drop(stream);
        }
        let output = peer.wait_with_output()?;
        anyhow::ensure!(output.status.success(), "UID fixture child failed");
        assert_eq!(String::from_utf8(output.stdout)?.trim(), expected);
    }
    drop(listener);
    std::fs::remove_file(&socket)?;
    let mut disabled = policy;
    disabled.controller_principal = None;
    containment::protect_registry(&registry, &disabled)?;
    assert_eq!(
        std::fs::metadata(registry.layout().fleet_root().as_path())?.mode() & 0o777,
        0o750
    );
    Ok(())
}
