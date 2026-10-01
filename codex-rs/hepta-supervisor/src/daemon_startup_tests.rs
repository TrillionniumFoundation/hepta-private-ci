use std::os::unix::fs::PermissionsExt;

use anyhow::Result;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::owner::SingleInstanceLock;
use super::run_supervisord_inner;
use crate::SupervisorError;

struct Fixture {
    temp: tempfile::TempDir,
    root: HeptaFleetRoot,
    registry: FleetRegistry,
    agent: codex_hepta_contracts::AgentId,
}

impl Fixture {
    fn new() -> Result<Self> {
        let temp = tempfile::Builder::new()
            .prefix("hsup-startup-")
            .tempdir_in("/tmp")?;
        let base = temp.path().canonicalize()?;
        let root = HeptaFleetRoot::parse(base.join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = base.join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        Ok(Self {
            temp,
            root,
            registry,
            agent,
        })
    }
}

#[tokio::test]
async fn losing_daemon_does_not_migrate_legacy_fleet_directories() -> Result<()> {
    let fixture = Fixture::new()?;
    let layout = fixture.registry.layout().agent(&fixture.agent);
    std::fs::remove_dir(layout.matrix_secrets_root())?;
    std::fs::remove_dir(layout.matrix_root())?;
    let owner = SingleInstanceLock::acquire(fixture.registry.layout().supervisor_lock())?;
    let owner_bytes = std::fs::read(fixture.registry.layout().supervisor_lock())?;

    let error = run_supervisord_inner(
        fixture.root.clone(),
        CancellationToken::new(),
        /*production_grant_verifier*/ None,
    )
    .await
    .expect_err("a losing daemon must reject before migration");
    assert!(matches!(
        error,
        SupervisorError::Io(ref error) if error.kind() == std::io::ErrorKind::AddrInUse
    ));
    assert!(!layout.matrix_root().exists());
    assert!(!layout.matrix_secrets_root().exists());
    assert_eq!(
        std::fs::read(fixture.registry.layout().supervisor_lock())?,
        owner_bytes,
    );
    drop(owner);

    // The winner keeps migration available, but only while retaining its owner.
    let owner = SingleInstanceLock::acquire_for_fleet(&fixture.root)?;
    FleetRegistry::open_existing(fixture.root.clone())?;
    assert_eq!(
        [layout.matrix_root(), layout.matrix_secrets_root()]
            .map(|path| std::fs::metadata(path)
                .map(|metadata| metadata.permissions().mode() & 0o777))
            .into_iter()
            .collect::<std::io::Result<Vec<_>>>()?,
        vec![0o700, 0o700],
    );
    assert!(SingleInstanceLock::acquire_for_fleet(&fixture.root).is_err());
    drop(owner);
    Ok(())
}

#[tokio::test]
async fn losing_daemon_does_not_chmod_existing_matrix_directories() -> Result<()> {
    let fixture = Fixture::new()?;
    let layout = fixture.registry.layout().agent(&fixture.agent);
    let paths = [layout.matrix_root(), layout.matrix_secrets_root()];
    for path in paths {
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))?;
    }
    let _owner = SingleInstanceLock::acquire(fixture.registry.layout().supervisor_lock())?;
    let error = run_supervisord_inner(
        fixture.root.clone(),
        CancellationToken::new(),
        /*production_grant_verifier*/ None,
    )
    .await
    .expect_err("a losing daemon must reject before tightening permissions");
    assert!(matches!(
        error,
        SupervisorError::Io(ref error) if error.kind() == std::io::ErrorKind::AddrInUse
    ));
    assert_eq!(
        paths
            .map(|path| std::fs::metadata(path)
                .map(|metadata| metadata.permissions().mode() & 0o777))
            .into_iter()
            .collect::<std::io::Result<Vec<_>>>()?,
        vec![0o755, 0o755],
    );
    Ok(())
}

#[tokio::test]
async fn registry_open_failure_releases_startup_owner_without_serving() -> Result<()> {
    let fixture = Fixture::new()?;
    std::fs::write(
        fixture
            .registry
            .layout()
            .agents_root()
            .join("invalid-agent"),
        b"invalid",
    )?;
    run_supervisord_inner(
        fixture.root.clone(),
        CancellationToken::new(),
        /*production_grant_verifier*/ None,
    )
    .await
    .expect_err("invalid registry must fail startup");
    assert!(!fixture.registry.layout().supervisor_socket().exists());
    SingleInstanceLock::acquire_for_fleet(&fixture.root)?;
    Ok(())
}

#[test]
fn startup_rejects_symlink_fleet_geometry_before_creating_an_external_lock() -> Result<()> {
    let fixture = Fixture::new()?;
    let outside = fixture.temp.path().join("outside");
    std::fs::create_dir(&outside)?;
    let run = fixture.registry.layout().run_root();
    std::fs::rename(run, fixture.temp.path().join("original-run"))?;
    std::os::unix::fs::symlink(&outside, run)?;

    let error = SingleInstanceLock::acquire_for_fleet(&fixture.root)
        .err()
        .expect("symlink run root must be rejected before opening the owner file");
    assert!(matches!(
        error,
        SupervisorError::Io(ref error) if error.kind() == std::io::ErrorKind::InvalidInput
    ));
    assert!(!outside.join("supervisor.lock").exists());
    Ok(())
}
