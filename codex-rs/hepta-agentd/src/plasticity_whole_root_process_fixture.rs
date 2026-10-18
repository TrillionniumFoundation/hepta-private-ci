//! Actual Root client / non-Root original owner process qualification only.
//! All records are synthetic fixture data, never installed model authority.
use super::*;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

const CHILD_DIRECTORY: &str = "HEPTA_TEST_COMPLETED_WHOLE_CHILD_DIRECTORY";
const CHILD_UID: u32 = 65534;
const TEST: &str = "plasticity_runtime::lifetime_tests::clock_tests::whole_observation_tests::completed_large_original_row_uses_the_actual_owner_and_root_socket_without_new_writes";

pub(super) fn child_directory() -> Option<PathBuf> {
    std::env::var_os(CHILD_DIRECTORY).map(PathBuf::from)
}

struct FixtureChild(Option<Child>);
impl Drop for FixtureChild {
    fn drop(&mut self) {
        if let Some(mut child) = self.0.take() {
            // This is a disposable test process, never a production owner.
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

pub(super) async fn read_from_actual_non_root_child() {
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let directory = tempfile::tempdir().expect("Root fixture directory");
    let path = directory.path();
    let c_path = std::ffi::CString::new(path.as_os_str().as_encoded_bytes()).expect("fixture path");
    assert_eq!(
        unsafe { libc::chown(c_path.as_ptr(), CHILD_UID, CHILD_UID) },
        0
    );
    fs::set_permissions(path, fs::Permissions::from_mode(0o700)).expect("private child directory");
    // The workspace may be private to its actual user. Execute the identical
    // Root-owned test ELF from the private disposable child directory.
    let executable = path.join("original-owner-test");
    fs::copy(std::env::current_exe().expect("test ELF"), &executable).expect("same test ELF");
    fs::set_permissions(&executable, fs::Permissions::from_mode(0o555))
        .expect("immutable test ELF");
    let child = Command::new(&executable)
        .args(["--exact", TEST, "--nocapture", "--test-threads=1"])
        .env_clear()
        .env(CHILD_DIRECTORY, path)
        .env("TMPDIR", path)
        .env("RUST_MIN_STACK", "8388608")
        .current_dir(path)
        .uid(CHILD_UID)
        .gid(CHILD_UID)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("actual non-Root original owner child");
    let pid = child.id();
    let mut child = FixtureChild(Some(child));
    let deadline = Instant::now() + Duration::from_secs(10);
    while !path.join("ready").exists() {
        assert!(
            Instant::now() < deadline,
            "non-Root owner readiness deadline"
        );
        assert!(
            child
                .0
                .as_mut()
                .expect("child")
                .try_wait()
                .expect("child status")
                .is_none(),
            "non-Root owner exited before readiness"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let packet = fs::read(path.join("original-completed.packet")).expect("whole original packet");
    assert!(packet.len() > crate::MAX_CONTROL_FRAME_BYTES as usize);
    let expected = DurableCompletedProposalV1::from_bytes(&packet).expect("original row codec");
    let agent = fs::read_to_string(path.join("agent-id")).expect("fixture original identity");
    let client = crate::AgentdClient::new(
        path.join("owner.sock"),
        codex_hepta_contracts::AgentId::parse(&agent).expect("agent identity"),
        1,
    )
    .expect("Root reader")
    .with_peer_process(CHILD_UID, pid)
    .expect("actual independent non-Root peer");
    let result = tokio::time::timeout(
        Duration::from_secs(10),
        client.plasticity_completed_proposal(expected.proposal.proposal_id.clone()),
    )
    .await
    .expect("whole actual socket deadline")
    .expect("actual Root whole response");
    // Runtime generation and process spawn generation are independently bound.
    assert_eq!(result, (2, Some(expected)));
    fs::write(path.join("stop"), b"retire disposable fixture").expect("request fixture retirement");
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Some(status) = child
            .0
            .as_mut()
            .expect("child")
            .try_wait()
            .expect("child retirement")
        {
            let output = child
                .0
                .take()
                .expect("child")
                .wait_with_output()
                .expect("actual child receipt");
            assert!(
                status.success(),
                "non-Root original owner failed: {} {}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            );
            break;
        }
        assert!(
            Instant::now() < deadline,
            "actual original owner retirement deadline"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

pub(super) async fn serve_child(directory: PathBuf) {
    assert_eq!(unsafe { libc::geteuid() }, CHILD_UID);
    let (mut fixture, expected, paths) = large_original_row();
    let reads = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let observed_reads = reads.clone();
    fixture.owner.clock = Box::new(move || {
        observed_reads.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Ok(50)
    });
    let before: Vec<_> = paths
        .iter()
        .map(|path| fs::read(path).expect("before"))
        .collect();
    let cancellation = CancellationToken::new();
    let owner = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        fixture.state.clone(),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let packet = fixture
        .handle
        .observe_completed_proposal(expected.proposal.proposal_id.clone())
        .await
        .expect("same bounded original owner")
        .expect("actual original row");
    assert_eq!(
        DurableCompletedProposalV1::from_bytes(&packet).expect("whole row"),
        expected
    );
    let server = crate::AgentdControlServer::bind(
        directory.join("owner.sock"),
        fixture.state.clone(),
        cancellation.clone(),
    )
    .await
    .expect("actual non-Root original server");
    let serving = tokio::spawn(server.run());
    fs::write(directory.join("original-completed.packet"), packet)
        .expect("fixture full expected bytes");
    fs::write(
        directory.join("agent-id"),
        fixture.state.identity().agent_id.to_string(),
    )
    .expect("fixture identity");
    fs::write(directory.join("ready"), b"original owner serving").expect("ready after actual bind");
    let deadline = Instant::now() + Duration::from_secs(30);
    while !directory.join("stop").exists() {
        assert!(
            Instant::now() < deadline,
            "Root reader did not complete its fixture"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    cancellation.cancel();
    serving.await.expect("server join").expect("server retired");
    owner.await.expect("writer join").expect("writer retired");
    assert_eq!(reads.load(std::sync::atomic::Ordering::SeqCst), 2);
    assert_eq!(
        paths
            .iter()
            .map(|path| fs::read(path).expect("after"))
            .collect::<Vec<_>>(),
        before
    );
}
