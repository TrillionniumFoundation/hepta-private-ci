//! Actual Root-to-UID60001 filesystem admission; explicit component authority
//! fixtures below are NOT original Root service or live-launch qualification.

use super::*;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

const POINTER: &str = ".cognitive-active-v1";
const LOCK: &str = ".cognitive-store.lock";

#[path = "cognitive_store_material_attempt_tests.rs"]
mod attempt_tests;

struct Fixture {
    case: TempDir,
    _source: TempDir,
    source_layout: HeptaAgentLayout,
    owner_layout: HeptaAgentLayout,
    fleet: PathBuf,
    temporary: PathBuf,
    cut: CognitiveRecoveryAnchor,
}

fn owner_file(path: &Path, bytes: &[u8]) {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap();
    file.set_permissions(std::fs::Permissions::from_mode(0o600))
        .unwrap();
    (&file).write_all(bytes).unwrap();
    std::os::unix::fs::chown(path, Some(60001), /*gid*/ None).unwrap();
    file.sync_all().unwrap();
}

impl Fixture {
    async fn new() -> (Self, VerifiedCognitiveMaterial) {
        codex_sqlite::RootSqliteMaterialRegistration::verify_caller(/*registered_uid*/ 60001)
            .unwrap();
        let parent = std::env::var_os("HEPTA_TEST_ROOT_OWNER_INSTALL_DESTINATION")
            .expect("separate Root0/0711 owner-traversable fixture namespace");
        let case = tempfile::tempdir_in(parent).unwrap();
        std::fs::set_permissions(case.path(), std::fs::Permissions::from_mode(0o711)).unwrap();
        let source_temp = tempfile::tempdir_in(case.path()).unwrap();
        std::fs::set_permissions(source_temp.path(), std::fs::Permissions::from_mode(0o700))
            .unwrap();
        let owner = agent_id(198);
        let source_layout = layout(&source_temp, &owner);
        let (store, _, _) = seeded(&source_temp, &owner).await;
        let cut = store.recovery_anchor().await.unwrap();
        store.close().await;
        let material = CognitiveStore::verify_root_material_candidate(&source_layout, &cut)
            .await
            .unwrap();
        let fleet = case.path().join("owner-fleet");
        let owner_layout = HeptaFleetRoot::parse(fleet.clone())
            .unwrap()
            .layout()
            .agent(&owner);
        // Every ancestor is actual Root0/no022 but searchable by UID60001.
        let mut current = case.path().to_path_buf();
        for name in owner_layout
            .agent_root()
            .strip_prefix(case.path())
            .unwrap()
            .components()
        {
            current.push(name.as_os_str());
            std::fs::create_dir(&current).unwrap();
            std::fs::set_permissions(&current, std::fs::Permissions::from_mode(0o711)).unwrap();
        }
        let temporary = owner_layout.agent_root().join("tmp");
        for root in [
            owner_layout.cognitive_root(),
            owner_layout.home_root(),
            owner_layout.run_root(),
            temporary.as_path(),
        ] {
            std::fs::create_dir(root).unwrap();
            std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700)).unwrap();
            std::os::unix::fs::chown(root, Some(60001), /*gid*/ None).unwrap();
        }
        owner_file(&owner_layout.cognitive_root().join(LOCK), b"");
        for suffix in ["", "-wal", "-shm", "-journal"] {
            owner_file(
                &owner_layout
                    .cognitive_root()
                    .join(format!("cognitive_1.sqlite3{suffix}")),
                b"retired Dirty bytes must remain untouched",
            );
        }
        (
            Self {
                case,
                _source: source_temp,
                source_layout,
                owner_layout,
                fleet,
                temporary,
                cut,
            },
            material,
        )
    }

    fn assert_old_dirty_unchanged(&self) {
        for suffix in ["", "-wal", "-shm", "-journal"] {
            assert_eq!(
                std::fs::read(
                    self.owner_layout
                        .cognitive_root()
                        .join(format!("cognitive_1.sqlite3{suffix}"))
                )
                .unwrap(),
                b"retired Dirty bytes must remain untouched"
            );
        }
    }

    fn child(&self, mode: &str, installed: &Path) -> std::process::Child {
        let test = format!(
            "{}::owner_factory_child",
            module_path!().split_once("::").unwrap().1
        );
        // Only the executable FD crosses the private Root test-ELF namespace.
        // All database/source/lock handles are CLOEXEC; the owner opens its
        // real pathname after setpriv, with no inherited database descriptor.
        Command::new("setpriv")
            .args([
                "--reuid=60001",
                "--regid=60001",
                "--clear-groups",
                "--no-new-privs",
                "/proc/self/fd/0",
                "--exact",
                &test,
                "--ignored",
                "--nocapture",
            ])
            .stdin(Stdio::from(
                File::open(std::env::current_exe().unwrap()).unwrap(),
            ))
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .current_dir(self.owner_layout.home_root())
            .env("TMPDIR", &self.temporary)
            .env("HEPTA_TEST_OWNER_INSTALL_FLEET", &self.fleet)
            .env(
                "HEPTA_TEST_OWNER_INSTALL_SOURCE",
                self.source_layout.cognitive_root(),
            )
            .env(
                "HEPTA_TEST_OWNER_INSTALL_CUT",
                serde_json::to_string(&self.cut).unwrap(),
            )
            .env("HEPTA_TEST_OWNER_INSTALL_PATH", installed)
            .env("HEPTA_TEST_OWNER_INSTALL_MODE", mode)
            .spawn()
            .unwrap()
    }
}

struct OwnedChild(std::process::Child);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn complete(child: std::process::Child) {
    let mut child = OwnedChild(child);
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        if let Some(status) = child.0.try_wait().unwrap() {
            assert!(status.success(), "actual owner child: {status}");
            return;
        }
        assert!(
            Instant::now() < deadline,
            "bounded actual owner recovery child"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[tokio::test]
#[ignore = "requires actual Root0 plus independent Root0/0711 owner-install test namespace"]
async fn root_installed_material_cold_opens_as_actual_owner_and_recovers_each_new_generation() {
    let (fixture, material) = Fixture::new().await;
    let installed = material
        .install_for_registered_owner(&fixture.owner_layout, &fixture.cut)
        .unwrap();
    assert_eq!(installed.anchor(), &fixture.cut);
    installed.verify_unchanged().unwrap();
    let installed_path = installed.path().to_path_buf();
    assert_eq!(std::fs::metadata(&installed_path).unwrap().uid(), 60001);
    assert_eq!(
        resolve_active_database_path(fixture.owner_layout.cognitive_root()).unwrap(),
        installed_path
    );
    complete(fixture.child("locked", &installed_path));
    installed.verify_unchanged().unwrap();
    // In production only original Root's independently checked Current/token
    // and publisher retirement can authorize this launch release.
    drop(installed);
    complete(fixture.child("recover", &installed_path));
    assert!(installed_path.exists());
    assert_ne!(
        resolve_active_database_path(fixture.owner_layout.cognitive_root()).unwrap(),
        installed_path
    );
    fixture.assert_old_dirty_unchanged();
    assert!(fixture.case.path().exists());
}

#[tokio::test]
#[ignore = "requires actual Root0 plus independent Root0/0711 owner-install test namespace"]
async fn root_install_refuses_wrong_cut_and_invalid_original_pointer_without_activation() {
    let (fixture, material) = Fixture::new().await;
    let before = std::fs::read_dir(fixture.owner_layout.cognitive_root())
        .unwrap()
        .count();
    let mut wrong = fixture.cut.clone();
    wrong.state_digest = Sha256Digest::for_bytes(b"different independent Current");
    assert!(matches!(
        material.install_for_registered_owner(&fixture.owner_layout, &wrong),
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert_eq!(
        std::fs::read_dir(fixture.owner_layout.cognitive_root())
            .unwrap()
            .count(),
        before
    );
    owner_file(
        &fixture.owner_layout.cognitive_root().join(POINTER),
        b"unregistered.sqlite3\n",
    );
    let material =
        CognitiveStore::verify_retained_root_material(&fixture.source_layout, &fixture.cut)
            .await
            .unwrap();
    assert!(
        material
            .install_for_registered_owner(&fixture.owner_layout, &fixture.cut)
            .is_err()
    );
    assert_eq!(
        std::fs::read(fixture.owner_layout.cognitive_root().join(POINTER)).unwrap(),
        b"unregistered.sqlite3\n"
    );
    fixture.assert_old_dirty_unchanged();
}

#[tokio::test]
#[ignore = "controlled actual UID60001 child; never invoke without its Root parent"]
async fn owner_factory_child() {
    let status = std::fs::read_to_string("/proc/thread-self/status").unwrap();
    let value = |name: &str| {
        status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .unwrap()
            .trim()
    };
    assert_eq!(
        value("Uid:").split_whitespace().collect::<Vec<_>>(),
        ["60001"; 4]
    );
    assert_eq!(
        value("Gid:").split_whitespace().collect::<Vec<_>>(),
        ["60001"; 4]
    );
    assert_eq!(u64::from_str_radix(value("CapEff:"), 16).unwrap(), 0);
    assert_eq!(value("NoNewPrivs:"), "1");
    assert!(value("Groups:").is_empty());
    let root_source = PathBuf::from(std::env::var_os("HEPTA_TEST_OWNER_INSTALL_SOURCE").unwrap());
    assert!(std::fs::read(root_source.join("cognitive_1.sqlite3")).is_err());
    let cut: CognitiveRecoveryAnchor =
        serde_json::from_str(&std::env::var("HEPTA_TEST_OWNER_INSTALL_CUT").unwrap()).unwrap();
    let fleet = HeptaFleetRoot::parse(PathBuf::from(
        std::env::var_os("HEPTA_TEST_OWNER_INSTALL_FLEET").unwrap(),
    ))
    .unwrap();
    let layout = fleet.layout().agent(&cut.owner_agent_id);
    for fd in std::fs::read_dir("/proc/self/fd").unwrap() {
        if let Ok(path) = std::fs::read_link(fd.unwrap().path()) {
            assert!(
                !path.starts_with(layout.cognitive_root()),
                "owner database or lock descriptor leaked"
            );
            assert!(
                !path.starts_with(&root_source),
                "Root source descriptor leaked"
            );
        }
    }
    let installed = PathBuf::from(std::env::var_os("HEPTA_TEST_OWNER_INSTALL_PATH").unwrap());
    let authority = recovery_authority(&cut.owner_agent_id);
    let result = CognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        &authority,
        &RecoveryVerifier,
    )
    .await;
    if std::env::var("HEPTA_TEST_OWNER_INSTALL_MODE").as_deref() == Ok("locked") {
        let error = result
            .err()
            .expect("Root capability must retain original exclusive fence");
        assert!(
            matches!(&error, CognitiveRecoveryError::Unavailable(message) if message.contains("cannot fence active store handles")),
            "{error}"
        );
        return;
    }
    let recovered = result.expect("actual owner original exact-current recovery");
    assert_ne!(recovered.path(), installed);
    assert_eq!(recovered.recovery_anchor().await.unwrap(), cut);
    let first = recovered.path().to_path_buf();
    let access = CognitiveAccess::agent_private(cut.owner_agent_id.clone());
    recovered
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "owner-install-followup",
                "actual owner write",
            ),
        )
        .await
        .unwrap();
    let advanced = recovered.recovery_anchor().await.unwrap();
    assert_ne!(advanced, cut);
    recovered.close().await;
    let reopened = CognitiveStore::open(&layout).await.unwrap();
    assert_eq!(reopened.path(), first);
    assert_eq!(reopened.recovery_anchor().await.unwrap(), advanced);
    reopened.close().await;
    let next = CognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&advanced),
        &authority,
        &RecoveryVerifier,
    )
    .await
    .unwrap();
    assert_ne!(next.path(), first);
    assert_ne!(next.path(), installed);
    assert_eq!(next.recovery_anchor().await.unwrap(), advanced);
    assert!(first.exists() && installed.exists());
    next.close().await;
}
