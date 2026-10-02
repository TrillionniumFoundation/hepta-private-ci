//! Real Fleet calls cross a deterministic regular-file-to-FIFO rename cut.

use std::cell::RefCell;
use std::io;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use crate::AgentManifest;
use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::ReleaseId;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

struct Swap {
    path: PathBuf,
    fifo: PathBuf,
    fired: Arc<AtomicBool>,
}

thread_local! {
    static SWAP: RefCell<Option<Swap>> = const { RefCell::new(None) };
}

pub(super) fn after_metadata(path: &Path) -> io::Result<()> {
    let swap = SWAP.with(|cut| {
        let mut cut = cut.borrow_mut();
        if cut.as_ref().is_some_and(|swap| swap.path == path) {
            cut.take()
        } else {
            None
        }
    });
    if let Some(swap) = swap {
        // Catalog validation already accepted the sealed parent. Permit only
        // the fixture's rename at this later, exact descriptor-open boundary.
        let parent = path
            .parent()
            .ok_or_else(|| io::Error::other("cut parent"))?;
        std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700))?;
        std::fs::rename(swap.fifo, path)?;
        swap.fired.store(true, Ordering::SeqCst);
    }
    Ok(())
}

fn fifo_cut<T>(path: &Path, fixture_root: &Path, operation: impl FnOnce() -> T) -> TestResult<T> {
    // Keep the precreated FIFO outside closed-world release directories, on
    // the fixture's same filesystem so that rename cannot cross devices.
    let fifo_directory = tempfile::tempdir_in(fixture_root)?;
    let fifo = fifo_directory.path().join("replacement-fifo");
    let created = std::process::Command::new("mkfifo").arg(&fifo).status()?;
    assert!(created.success(), "mkfifo fixture creation");
    let fired = Arc::new(AtomicBool::new(false));
    SWAP.with(|cut| {
        assert!(
            cut.borrow_mut()
                .replace(Swap {
                    path: path.to_path_buf(),
                    fifo,
                    fired: Arc::clone(&fired),
                })
                .is_none()
        );
    });
    let (done, completed) = mpsc::channel();
    let watchdog_path = path.to_path_buf();
    let watchdog = std::thread::spawn(move || -> io::Result<bool> {
        match completed.recv_timeout(Duration::from_secs(/*secs*/ 1)) {
            Ok(()) | Err(mpsc::RecvTimeoutError::Disconnected) => Ok(false),
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // A writer releases only the old blocking reader. Hold it
                // through completion so that the failing test also terminates.
                let writer = std::fs::OpenOptions::new()
                    .read(true)
                    .write(true)
                    .custom_flags(libc::O_NONBLOCK | libc::O_NOFOLLOW | libc::O_CLOEXEC)
                    .open(watchdog_path)?;
                let completed = completed.recv_timeout(Duration::from_secs(/*secs*/ 5));
                drop(writer);
                completed.map_err(io::Error::other)?;
                Ok(true)
            }
        }
    });
    let result = operation();
    SWAP.with(|cut| {
        cut.borrow_mut().take();
    });
    let _ = done.send(());
    let released = watchdog
        .join()
        .map_err(|_| io::Error::other("FIFO watchdog panicked"))??;
    assert!(
        fired.load(Ordering::SeqCst),
        "production metadata cut was not reached"
    );
    assert!(!released, "control open required a watchdog writer");
    Ok(result)
}

fn assert_descriptor_rejection<T>(result: Result<T, FleetRegistryError>) {
    assert!(
        matches!(result, Err(FleetRegistryError::Corrupt(ref message))
        if message.starts_with("opened control path is not a bounded regular file:"))
    );
}

struct Fixture {
    _temporary: tempfile::TempDir,
    registry: FleetRegistry,
    record: crate::AgentRecord,
    source: PathBuf,
    release: ReleaseId,
}

impl Fixture {
    fn new() -> TestResult<Self> {
        let temporary = tempfile::tempdir()?;
        let base = temporary.path().canonicalize()?;
        let root = HeptaFleetRoot::parse(base.join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = base.join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let record = registry.register(AgentManifest::new(
            agent,
            WorkspaceBinding::new(workspace, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let source = base.join("source-program");
        std::fs::write(&source, b"reviewed program contents")?;
        let release = ReleaseId::parse("descriptor-fifo-cut")?;
        registry.install_release(release.clone(), &source, Vec::new())?;
        registry.allow_release(&record.manifest.agent_id, &release)?;
        Ok(Self {
            _temporary: temporary,
            registry,
            record,
            source,
            release,
        })
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let root = self
            .registry
            .layout()
            .releases_root()
            .join(self.release.as_str());
        for directory in [&root, &root.join("bin")] {
            let _ = std::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700));
        }
    }
}

#[test]
fn registry_fifo_swap_after_metadata_is_rejected_without_watchdog_release() -> TestResult {
    let fixture = Fixture::new()?;
    let path = fixture.record.layout.agent_config();
    let run_root = fixture.record.layout.run_root();
    let history = std::fs::read_dir(run_root)?.count();
    let result = fifo_cut(path, fixture._temporary.path(), || fixture.registry.load())?;
    assert_descriptor_rejection(result);
    assert!(!std::fs::symlink_metadata(path)?.file_type().is_file());
    assert_eq!(std::fs::read_dir(run_root)?.count(), history);
    Ok(())
}

#[test]
fn catalog_fifo_swap_after_metadata_is_rejected_without_watchdog_release() -> TestResult {
    // Exercise bounded catalog JSON, program hashing and install-time source
    // copying through the same actual descriptor opener, not a mirror reader.
    for endpoint in ["catalog", "digest", "source"] {
        let fixture = Fixture::new()?;
        let root = fixture
            .registry
            .layout()
            .releases_root()
            .join(fixture.release.as_str());
        let marker = fixture
            .record
            .layout
            .releases_root()
            .join(format!("allow-{}.json", fixture.release));
        let allowance = std::fs::read(&marker)?;
        match endpoint {
            "catalog" => {
                let path = root.join("release.json");
                let result = fifo_cut(&path, fixture._temporary.path(), || {
                    fixture
                        .registry
                        .allow_release(&fixture.record.manifest.agent_id, &fixture.release)
                })?;
                assert_descriptor_rejection(result);
            }
            "digest" => {
                let path = root.join("bin/hepta-agentd");
                let result = fifo_cut(&path, fixture._temporary.path(), || {
                    fixture
                        .registry
                        .resolve_release(&fixture.record.manifest.agent_id, &fixture.release)
                })?;
                assert_descriptor_rejection(result);
            }
            "source" => {
                let replacement = ReleaseId::parse("source-cut-target")?;
                let result = fifo_cut(&fixture.source, fixture._temporary.path(), || {
                    fixture.registry.install_release(
                        replacement.clone(),
                        &fixture.source,
                        Vec::new(),
                    )
                })?;
                assert_descriptor_rejection(result);
                assert!(
                    !fixture
                        .registry
                        .layout()
                        .releases_root()
                        .join(replacement.as_str())
                        .exists()
                );
            }
            _ => unreachable!("fixed endpoints"),
        }
        assert_eq!(std::fs::read(&marker)?, allowance, "{endpoint}");
        assert_eq!(
            fixture
                .registry
                .load()?
                .agent(&fixture.record.manifest.agent_id),
            Some(&fixture.record),
            "{endpoint}"
        );
    }
    Ok(())
}
