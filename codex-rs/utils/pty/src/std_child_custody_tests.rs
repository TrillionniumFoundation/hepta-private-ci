use super::StdChildCustody;
use pretty_assertions::assert_eq;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

const FIXTURE: &str = "std_child_custody::tests::native_child_fixture";
const ROLE: &str = "CODEX_STD_CUSTODY_FIXTURE_ROLE";
const ROOT: &str = "CODEX_STD_CUSTODY_FIXTURE_ROOT";
#[cfg(unix)]
const PARENT_GROUP: &str = "CODEX_STD_CUSTODY_FIXTURE_PARENT_GROUP";
static NEXT_ROOT: AtomicU64 = AtomicU64::new(0);

struct FixtureRoot(PathBuf);

impl FixtureRoot {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "codex-std-child-custody-{}-{}",
            std::process::id(),
            NEXT_ROOT.fetch_add(1, Ordering::Relaxed)
        ));
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(&path).expect("exclusive fixture directory");
        Self(path)
    }
}

impl Drop for FixtureRoot {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn fixture_command(role: &str, root: &Path) -> Command {
    let mut command = Command::new(std::env::current_exe().expect("current test executable"));
    command
        .args(["--ignored", "--exact", FIXTURE, "--nocapture"])
        .env(ROLE, role)
        .env(ROOT, root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command
}

fn wait_for(mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while !condition() {
        assert!(Instant::now() < deadline, "native fixture did not reach its terminal state");
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[cfg(unix)]
struct DescendantIdentity(libc::pid_t);

#[cfg(unix)]
impl DescendantIdentity {
    fn open(pid: u32) -> Self {
        let pid = libc::pid_t::try_from(pid).expect("native child pid fits pid_t");
        assert_eq!(unsafe { libc::kill(pid, 0) }, 0);
        Self(pid)
    }

    fn gone(&self) -> bool {
        let result = unsafe { libc::kill(self.0, 0) };
        result == -1 && std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH)
    }
}

#[cfg(windows)]
struct DescendantIdentity(std::os::windows::io::OwnedHandle);

#[cfg(windows)]
impl DescendantIdentity {
    fn open(pid: u32) -> Self {
        use std::os::windows::io::FromRawHandle;
        let handle = unsafe {
            winapi::um::processthreadsapi::OpenProcess(
                winapi::um::winnt::SYNCHRONIZE,
                /*bInheritHandle*/ 0,
                pid,
            )
        };
        assert!(!handle.is_null(), "capture the live descendant identity");
        Self(unsafe { std::os::windows::io::OwnedHandle::from_raw_handle(handle.cast()) })
    }

    fn gone(&self) -> bool {
        use std::os::windows::io::AsRawHandle;
        unsafe {
            winapi::um::synchapi::WaitForSingleObject(
                self.0.as_raw_handle().cast(),
                /*dwMilliseconds*/ 0,
            ) == winapi::um::winbase::WAIT_OBJECT_0
        }
    }
}

fn descendant(root: &Path) -> DescendantIdentity {
    let ready = root.join("ready.pid");
    wait_for(|| ready.exists());
    let pid = std::fs::read_to_string(ready)
        .expect("read actual descendant pid")
        .parse()
        .expect("parse actual descendant pid");
    DescendantIdentity::open(pid)
}

#[test]
fn normal_leader_exit_cleans_descendants_and_preserves_an_unrelated_owner() {
    let unrelated_root = FixtureRoot::new();
    let mut unrelated = StdChildCustody::spawn(&mut fixture_command("hold", &unrelated_root.0))
        .expect("spawn independent owner");
    let unrelated_identity = descendant(&unrelated_root.0);
    let root = FixtureRoot::new();
    let mut owned = StdChildCustody::spawn(&mut fixture_command("leader", &root.0))
        .expect("spawn owned leader");
    let child = descendant(&root.0);
    std::fs::write(root.0.join("release"), b"exit").expect("release the original leader");
    let mut terminal = None;
    wait_for(|| {
        terminal = owned.try_wait().expect("poll owned leader");
        terminal.is_some()
    });
    assert!(terminal.expect("actual exit").success());
    assert_eq!(owned.try_wait().expect("repeat actual exit"), terminal);
    wait_for(|| child.gone());
    assert!(!unrelated_identity.gone());
    assert_eq!(unrelated.try_wait().expect("poll independent owner"), None);
    unrelated.kill_and_wait().expect("clean up independent owner");
    wait_for(|| unrelated_identity.gone());
}

#[test]
fn explicit_cleanup_kills_the_live_leader_and_its_descendant() {
    let root = FixtureRoot::new();
    let mut owned = StdChildCustody::spawn(&mut fixture_command("leader", &root.0))
        .expect("spawn owned leader");
    let child = descendant(&root.0);
    let terminal = owned.kill_and_wait().expect("clean up live owned tree");
    assert!(!terminal.success());
    assert_eq!(owned.try_wait().expect("repeat cleanup status"), Some(terminal));
    wait_for(|| child.gone());
}

#[test]
fn dropping_the_owner_cleans_its_live_descendant() {
    let root = FixtureRoot::new();
    let owned = StdChildCustody::spawn(&mut fixture_command("leader", &root.0))
        .expect("spawn owned leader");
    let child = descendant(&root.0);
    drop(owned);
    wait_for(|| child.gone());
}

#[cfg(unix)]
#[test]
fn explicit_cleanup_reaps_the_actual_child_after_it_moves_out_of_the_owned_group() {
    let root = FixtureRoot::new();
    let parent_group = unsafe { libc::getpgrp() };
    let mut command = fixture_command("moved-direct", &root.0);
    command.env(PARENT_GROUP, parent_group.to_string());
    let mut owned = StdChildCustody::spawn(&mut command).expect("spawn actual owned child");
    let child = descendant(&root.0);
    assert_eq!(child.0, owned.child.id() as libc::pid_t);
    assert_eq!(unsafe { libc::getpgid(child.0) }, parent_group);
    let status = owned.kill_and_wait().expect("reap the retained direct child after group migration");
    assert!(!status.success());
    assert_eq!(owned.try_wait().expect("repeated terminal observation"), Some(status));
    wait_for(|| child.gone());
}

#[cfg(target_os = "macos")]
#[test]
fn solo_exited_leader_is_reaped_and_keeps_its_actual_exit_status() {
    let unrelated_root = FixtureRoot::new();
    let mut unrelated = StdChildCustody::spawn(&mut fixture_command("hold", &unrelated_root.0))
        .expect("spawn an unrelated owner");
    let unrelated_identity = descendant(&unrelated_root.0);
    let root = FixtureRoot::new();
    let mut owned = StdChildCustody::spawn(&mut fixture_command("solo-exit", &root.0))
        .expect("spawn the actual solo child");
    wait_for(|| owned.peek_exit().expect("observe actual exit without reaping"));
    let terminal = owned.try_wait().expect("reap the retained solo zombie")
        .expect("the actual child has exited");
    assert_eq!(terminal.code(), Some(7));
    assert_eq!(owned.try_wait().expect("repeat the actual status"), Some(terminal));
    assert_eq!(owned.kill_and_wait().expect("repeated cleanup returns cached status"), terminal);
    assert!(!unrelated_identity.gone());
    assert_eq!(unrelated.try_wait().expect("unrelated owner remains live"), None);
    unrelated.kill_and_wait().expect("clean up the unrelated owner");
    wait_for(|| unrelated_identity.gone());
}

#[test]
#[ignore = "native child fixture, invoked only through the owning test executable"]
fn native_child_fixture() {
    let root = PathBuf::from(std::env::var_os(ROOT).expect("owning parent supplies fixture root"));
    match std::env::var(ROLE).expect("owning parent supplies fixture role").as_str() {
        #[cfg(target_os = "macos")]
        "solo-exit" => std::process::exit(7),
        "hold" => {
            std::fs::write(root.join("ready.pending"), std::process::id().to_string())
                .expect("publish actual fixture pid");
            std::fs::rename(root.join("ready.pending"), root.join("ready.pid"))
                .expect("publish the complete pid before the parent reads it");
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        "leader" => {
            // This child intentionally inherits the containing group/job and outlives its leader.
            // It is retained by StdChildCustody in the original parent, not by this helper handle.
            let _child = fixture_command("hold", &root).spawn().expect("spawn actual descendant");
            wait_for(|| root.join("release").exists());
        }
        #[cfg(target_os = "macos")]
        "two-descendants" => {
            for name in ["first", "second"] {
                let child_root = root.join(name);
                std::fs::create_dir(&child_root).expect("create descendant fixture root");
                let _child = fixture_command("hold", &child_root).spawn()
                    .expect("spawn an actual group member");
            }
            wait_for(|| root.join("release").exists());
        }
        #[cfg(unix)]
        "moved-direct" => {
            let parent_group = std::env::var(PARENT_GROUP).unwrap().parse::<libc::pid_t>().unwrap();
            assert_eq!(unsafe { libc::setpgid(/*pid*/ 0, parent_group) }, 0);
            std::fs::write(root.join("ready.pending"), std::process::id().to_string()).unwrap();
            std::fs::rename(root.join("ready.pending"), root.join("ready.pid")).unwrap();
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        role => panic!("unknown fixture role: {role}"),
    }
}

#[cfg(target_os = "macos")]
#[path = "std_child_custody_macos_tests.rs"]
mod macos_tests;
