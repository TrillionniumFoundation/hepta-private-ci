use pretty_assertions::assert_eq;
use std::cell::Cell;

use super::*;
use codex_hepta_paths::HeptaFleetRoot;

enum FailedStep {
    Seal,
    SyncDirectory,
    SyncCatalog,
}

struct FaultIo {
    step: FailedStep,
    sync_calls: Cell<usize>,
}

impl PublicationIo for FaultIo {
    fn seal(&self, path: &Path) -> Result<(), FleetRegistryError> {
        if matches!(self.step, FailedStep::Seal) {
            return Err(std::io::Error::other("injected seal failure").into());
        }
        NativePublicationIo.seal(path)
    }

    fn sync(&self, path: &Path) -> Result<(), FleetRegistryError> {
        let count = self.sync_calls.get() + 1;
        self.sync_calls.set(count);
        if matches!(self.step, FailedStep::SyncDirectory) && count == 1
            || matches!(self.step, FailedStep::SyncCatalog) && count == 2
        {
            return Err(std::io::Error::other("injected sync failure").into());
        }
        NativePublicationIo.sync(path)
    }
}

fn fixture() -> (tempfile::TempDir, FleetRegistry, PathBuf) {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp.path().canonicalize().expect("canonical root");
    let registry =
        FleetRegistry::initialize(HeptaFleetRoot::parse(root.join("fleet")).expect("Fleet root"))
            .expect("registry");
    let source = root.join("source-program");
    std::fs::write(&source, b"immutable agentd bytes").expect("source bytes");
    set_mode(&source, /*mode*/ 0o555).expect("read-only source");
    (temp, registry, source)
}

#[test]
fn seal_and_sync_failures_retain_the_renamed_object_without_deleting_an_admitted_release() {
    for step in [
        FailedStep::Seal,
        FailedStep::SyncDirectory,
        FailedStep::SyncCatalog,
    ] {
        let (_temp, registry, source) = fixture();
        let id = ReleaseId::parse("publication-fault").expect("release ID");
        let expected = registry
            .install_release(id.clone(), &source, Vec::new())
            .expect("prepared immutable bytes");
        let root = registry.layout().releases_root().join(id.as_str());
        let staging = root.with_file_name(".fault-staging");
        set_mode(&root, /*mode*/ 0o755).expect("prepare writable publication");
        std::fs::rename(&root, &staging).expect("simulate prepared install before publication");
        let io = FaultIo {
            step,
            sync_calls: Cell::new(0),
        };
        assert!(publish_prepared_directory(&registry.control, &staging, &root, &io).is_err());
        assert!(!staging.exists());
        assert_eq!(
            std::fs::read(&expected.program).expect("renamed object retained"),
            b"immutable agentd bytes"
        );
        if is_writable(&std::fs::metadata(&root).expect("retained root")) {
            assert!(
                resolve_catalog_release(
                    &registry.control,
                    registry.layout().releases_root(),
                    &id,
                    ReleaseRootSeal::Required
                )
                .is_err()
            );
            assert_eq!(
                registry
                    .install_release(id, &source, Vec::new())
                    .expect("pending failure recovers by exact retry"),
                expected
            );
        } else {
            assert_eq!(
                resolve_catalog_release(
                    &registry.control,
                    registry.layout().releases_root(),
                    &id,
                    ReleaseRootSeal::Required
                )
                .expect("already-admissible release was not deleted"),
                expected
            );
        }
        make_tree_removable(&root);
        set_mode(&source, /*mode*/ 0o700).expect("fixture cleanup");
    }
}

#[test]
fn pending_release_is_not_admitted_and_exact_install_retry_seals_it() {
    let (_temp, registry, source) = fixture();
    let id = ReleaseId::parse("pending-seal").expect("release ID");
    let args = vec!["--fixed".to_string()];
    let expected = registry
        .install_release(id.clone(), &source, args.clone())
        .expect("native immutable install");
    let root = registry.layout().releases_root().join(id.as_str());
    set_mode(&root, /*mode*/ 0o755).expect("simulate rename-before-seal crash");
    assert!(
        resolve_catalog_release(
            &registry.control,
            registry.layout().releases_root(),
            &id,
            ReleaseRootSeal::Required
        )
        .is_err()
    );
    assert!(
        registry
            .install_release(id.clone(), &source, vec!["--changed".to_string()])
            .is_err()
    );
    assert!(is_writable(
        &std::fs::metadata(&root).expect("pending directory preserved")
    ));
    assert_eq!(
        registry
            .install_release(id.clone(), &source, args)
            .expect("exact retry recovers pending install"),
        expected
    );
    validate_physical_directory(&root, /*immutable*/ true).expect("sealed publication");
    assert!(matches!(
        registry.install_release(id, &source, Vec::new()),
        Err(FleetRegistryError::Invalid(_))
    ));
    make_tree_removable(&root);
    set_mode(&source, /*mode*/ 0o700).expect("fixture cleanup");
}

#[test]
fn pending_bundle_retry_requires_both_exact_programs_before_sealing() {
    let (temp, registry, source) = fixture();
    let matrix = temp
        .path()
        .canonicalize()
        .expect("canonical root")
        .join("matrixd-source");
    std::fs::write(&matrix, b"immutable matrixd bytes").expect("matrixd source");
    let id = ReleaseId::parse("pending-bundle").expect("release ID");
    let expected = registry
        .install_release_bundle(
            id.clone(),
            &source,
            Vec::new(),
            Some(&matrix),
            vec!["--matrix".to_string()],
        )
        .expect("bundle install");
    let root = registry.layout().releases_root().join(id.as_str());
    set_mode(&root, /*mode*/ 0o755).expect("pending root");
    std::fs::write(&matrix, b"other matrixd bytes").expect("different retry source");
    assert!(
        registry
            .install_release_bundle(
                id.clone(),
                &source,
                Vec::new(),
                Some(&matrix),
                vec!["--matrix".to_string()]
            )
            .is_err()
    );
    assert!(is_writable(
        &std::fs::metadata(&root).expect("pending directory preserved")
    ));
    std::fs::write(&matrix, b"immutable matrixd bytes").expect("exact retry source");
    assert_eq!(
        registry
            .install_release_bundle(
                id,
                &source,
                Vec::new(),
                Some(&matrix),
                vec!["--matrix".to_string()]
            )
            .expect("recover exact bundle"),
        expected
    );
    make_tree_removable(&root);
    set_mode(&source, /*mode*/ 0o700).expect("fixture cleanup");
}

#[test]
fn cleanup_never_removes_a_different_directory_at_the_same_path() {
    let (temp, _registry, source) = fixture();
    let path = temp.path().join("owned-staging");
    let retained = temp.path().join("retained-staging");
    std::fs::create_dir(&path).expect("owned staging");
    let owned = std::fs::symlink_metadata(&path).expect("owned identity");
    std::fs::rename(&path, &retained).expect("retain actual owned directory");
    std::fs::create_dir(&path).expect("concurrent directory");
    let marker = path.join("other-install");
    std::fs::write(&marker, b"keep me").expect("other install bytes");
    cleanup_owned_tree(&path, &owned);
    assert_eq!(
        std::fs::read(marker).expect("unrelated directory retained"),
        b"keep me"
    );
    cleanup_owned_tree(&retained, &owned);
    assert!(!retained.exists());
    set_mode(&source, /*mode*/ 0o700).expect("fixture cleanup");
}

#[test]
fn malformed_pending_release_is_preserved_until_an_exact_repair_retry() {
    let (_temp, registry, source) = fixture();
    let id = ReleaseId::parse("pending-repair").expect("release ID");
    registry
        .install_release(id.clone(), &source, Vec::new())
        .expect("native install");
    let root = registry.layout().releases_root().join(id.as_str());
    set_mode(&root, /*mode*/ 0o755).expect("pending root");
    let extra = root.join("unexpected");
    std::fs::write(&extra, b"operator review required").expect("unknown entry");
    assert!(
        registry
            .install_release(id.clone(), &source, Vec::new())
            .is_err()
    );
    assert_eq!(
        std::fs::read(&extra).expect("unknown object retained"),
        b"operator review required"
    );
    assert!(
        resolve_catalog_release(
            &registry.control,
            registry.layout().releases_root(),
            &id,
            ReleaseRootSeal::Required
        )
        .is_err()
    );
    std::fs::remove_file(extra).expect("operator repairs unexpected entry");
    registry
        .install_release(id, &source, Vec::new())
        .expect("retry seals repaired valid candidate");
    validate_physical_directory(&root, /*immutable*/ true).expect("sealed repaired candidate");
    make_tree_removable(&root);
    set_mode(&source, /*mode*/ 0o700).expect("fixture cleanup");
}
