use super::*;
use crate::release_authority_tests::Fixture;
use pretty_assertions::assert_eq;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

#[test]
fn trust_configuration_reads_actual_current_owner_and_preserves_mode_rejection() -> TestResult {
    let fixture = Fixture::new()?;
    let path = fixture.publisher.config_path();
    let bytes = std::fs::read(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o644))?;
    let file = std::fs::File::open(path)?;
    let metadata = file.metadata()?;
    let effective_uid = rustix::process::geteuid().as_raw();
    assert_eq!(metadata.uid(), effective_uid);
    assert_eq!(
        FleetReleaseTrustConfig::read(path)?.initial_root_sha256,
        fixture.publisher.config().initial_root_sha256
    );
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o664))?;
    assert!(FleetReleaseTrustConfig::read(path).is_err());
    assert_eq!(std::fs::read(path)?, bytes);
    Ok(())
}

#[test]
fn trust_configuration_refuses_foreign_inode_owner_before_parsing_trust_inputs() -> TestResult {
    let fixture = Fixture::new()?;
    let path = fixture.publisher.config_path();
    let bytes = std::fs::read(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o644))?;
    let file = std::fs::File::open(path)?;
    let metadata = file.metadata()?;
    let effective_uid = rustix::process::geteuid().as_raw();
    assert_eq!(metadata.uid(), effective_uid);
    let foreign_uid = if effective_uid == 1 { 2 } else { 1 };
    if effective_uid == 0 {
        // A root-owned trust file remains readable for another daemon user.
        assert_eq!(
            FleetReleaseTrustConfig::read_for_effective_uid(path, foreign_uid)?.initial_root_sha256,
            fixture.publisher.config().initial_root_sha256
        );
        // A root test can also exercise the public reader against an actual
        // foreign-owned inode. Only this fixture's own file is changed.
        std::os::unix::fs::chown(path, Some(foreign_uid), /*gid*/ None)?;
        assert!(FleetReleaseTrustConfig::read(path).is_err());
    } else {
        // The actual opened inode belongs to a different user than this
        // explicit reader context. Production always obtains its context
        // directly from geteuid; no configuration field can supply it.
        assert!(FleetReleaseTrustConfig::read_for_effective_uid(path, foreign_uid).is_err());
        assert_eq!(
            FleetReleaseTrustConfig::read(path)?.initial_root_sha256,
            fixture.publisher.config().initial_root_sha256
        );
    }
    assert_eq!(std::fs::read(path)?, bytes);
    Ok(())
}
