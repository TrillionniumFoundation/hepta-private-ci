use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
#[ignore = "requires sudo: production Root publisher and protected listener"]
async fn root_publication_precedes_listener_and_live_or_failed_bind_stays_closed()
-> anyhow::Result<()> {
    if rustix::process::geteuid().as_raw() != 0 {
        let result = std::process::Command::new("sudo")
            .arg("-n")
            .arg(std::env::current_exe()?)
            .args(["--exact", "local_model_authority::startup::tests::root_publication_precedes_listener_and_live_or_failed_bind_stays_closed", "--ignored", "--nocapture"])
            .output()?;
        anyhow::ensure!(
            result.status.success(),
            "{} {}",
            String::from_utf8_lossy(&result.stdout),
            String::from_utf8_lossy(&result.stderr)
        );
        anyhow::ensure!(
            String::from_utf8_lossy(&result.stdout).contains("1 passed"),
            "Root case did not execute"
        );
        return Ok(());
    }
    let directory = tempfile::Builder::new()
        .prefix("hepta-model-publisher-q-")
        .tempdir_in("/var/lib")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o750))?;
    std::os::unix::fs::chown(directory.path(), Some(0), Some(975))?;
    let mut config = super::super::tests::config();
    config.issuer_socket = directory.path().join("issuer.sock");
    config.process_identity_file = directory.path().join("identity.json");
    config.socket_gid = 975;
    let trust_directory = directory.path().join("trust");
    std::fs::create_dir(&trust_directory)?;
    std::fs::set_permissions(&trust_directory, std::fs::Permissions::from_mode(0o700))?;
    let head = codex_hepta_contracts::FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let initial = codex_hepta_contracts::FinalUseFrontier::for_initial_head(&head)?;
    let frontier =
        store::ProtectedFrontier::open(&trust_directory, initial, /*state_is_empty*/ true)?;
    assert!(!config.issuer_socket.exists());
    assert!(
        store::ProtectedFrontier::open(&trust_directory, initial, /*state_is_empty*/ true).is_err()
    );
    let frontier_bytes = std::fs::read(trust_directory.join("frontier.json"))?;
    // Prepare the old dead inode before launching workloads. Its permissions
    // must not introduce a fixture-only bind window ahead of the real stage.
    let stale = std::os::unix::net::UnixListener::bind(&config.issuer_socket)?;
    std::fs::set_permissions(
        &config.issuer_socket,
        std::fs::Permissions::from_mode(0o660),
    )?;
    std::os::unix::fs::chown(&config.issuer_socket, Some(0), Some(975))?;
    drop(stale);
    std::fs::write(
        &config.process_identity_file,
        b"previous closed publication",
    )?;
    // These are real original workload UIDs/G975, observing cold publication.
    // EACCES is deliberately not retryable; only absent/refused sockets wait.
    let client_code = r#"import json,os,socket,stat,struct,sys,time
p=json.load(sys.stdin);deadline=time.monotonic()+30
while True:
 s=socket.socket(socket.AF_UNIX);s.settimeout(1)
 try:s.connect(p['socket']);break
 except (FileNotFoundError,ConnectionRefusedError):
  s.close();assert time.monotonic()<deadline;time.sleep(.001)
peer=struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
metadata=os.lstat(p['socket']);identity=json.load(open(p['identity']))
assert peer[1]==0 and identity['pid']==peer[0]
assert metadata.st_uid==0 and metadata.st_gid==975 and stat.S_IMODE(metadata.st_mode)==0o660
assert os.getgid()==975 and os.getgroups()==[975]
print(json.dumps({'uid':os.getuid(),'peer_uid':peer[1],'published_identity_pid':identity['pid']}))
"#;
    let mut clients = Vec::new();
    for uid in [986, 969] {
        let mut child = std::process::Command::new("/usr/bin/setpriv")
            .args([
                "--reuid",
                &uid.to_string(),
                "--regid",
                "975",
                "--groups",
                "975",
                "/usr/bin/python3",
                "-c",
                client_code,
            ])
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()?;
        use std::io::Write;
        child.stdin.take().context("client stdin absent")?.write_all(&serde_json::to_vec(&serde_json::json!({"socket":config.issuer_socket,"identity":config.process_identity_file}))?)?;
        clients.push((uid, child));
    }
    let listener = publish_listener(&config)?;
    for (uid, child) in clients {
        let result = child.wait_with_output()?;
        anyhow::ensure!(
            result.status.success(),
            "UID{uid} cold publication failed: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        let value: serde_json::Value = serde_json::from_slice(&result.stdout)?;
        assert_eq!(value["uid"], uid);
        assert_eq!(value["peer_uid"], 0);
    }
    assert!(
        store::ProtectedFrontier::open(&trust_directory, initial, /*state_is_empty*/ true).is_err()
    );
    assert_eq!(
        std::fs::read(trust_directory.join("frontier.json"))?,
        frontier_bytes
    );
    let bytes = store::read_protected(&config.process_identity_file, 4096, /*private*/ false)?;
    let identity: codex_hepta_contracts::ModelIssuerProcessIdentity =
        serde_json::from_slice(&bytes)?;
    assert_eq!(
        (identity.schema_version, identity.pid),
        (1, std::process::id())
    );
    assert_eq!(
        identity.executable_sha256,
        format!("{:x}", Sha256::digest(std::fs::read("/proc/self/exe")?))
    );
    let connected = std::os::unix::net::UnixStream::connect(&config.issuer_socket)?;
    let peer = rustix::net::sockopt::socket_peercred(&connected)?;
    assert_eq!(
        (peer.uid.as_raw(), peer.pid.as_raw_pid()),
        (0, std::process::id() as i32)
    );
    let socket_inode = std::fs::symlink_metadata(&config.issuer_socket)?.ino();
    // The actual production stage cannot overwrite an old live owner.
    assert!(publish_listener(&config).is_err());
    assert_eq!(std::fs::read(&config.process_identity_file)?, bytes);
    assert_eq!(
        std::fs::symlink_metadata(&config.issuer_socket)?.ino(),
        socket_inode
    );
    drop(connected);
    drop(listener);
    // Same startup stage removes only the now-dead socket and publishes before
    // rebinding; no signer, clock, frontier or grant owner is invoked here.
    let recovered = publish_listener(&config)?;
    assert_eq!(std::fs::read(&config.process_identity_file)?, bytes);
    drop(recovered);
    config.issuer_socket = directory.path().join("x".repeat(200));
    assert!(publish_listener(&config).is_err());
    assert!(!config.issuer_socket.exists());
    assert_eq!(std::fs::read(&config.process_identity_file)?, bytes);
    assert_eq!(
        std::fs::read(trust_directory.join("frontier.json"))?,
        frontier_bytes
    );
    drop(frontier);
    Ok(())
}
