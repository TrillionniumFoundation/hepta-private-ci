//! Active lease codecs use bounded descriptor reads, independently of sockets.

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::*;

#[derive(Clone, Copy)]
enum LeaseKind {
    Main,
    Matrix,
}

impl LeaseKind {
    fn path(self, root: &Path) -> std::path::PathBuf {
        match self {
            Self::Main => lease_path(root),
            Self::Matrix => root.join("supervisor-matrix-process.json"),
        }
    }

    fn publish(self, root: &Path) -> Result<()> {
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let release_id = ReleaseId::parse("bounded-lease")?;
        let identity = ProcessIdentity::new(/*system_id*/ 42, "bounded-lease-owner")?;
        match self {
            Self::Main => write_lease(
                root,
                &ProcessLease {
                    schema_version: PROCESS_LEASE_SCHEMA_VERSION,
                    agent_id,
                    spawn_generation: 1,
                    release_id,
                    identity,
                },
            )?,
            Self::Matrix => write_matrix_lease(
                &self.path(root),
                &MatrixProcessLease {
                    schema_version: MATRIX_PROCESS_LEASE_SCHEMA_VERSION,
                    agent_id,
                    attached_agent_generation: 1,
                    release_id,
                    binding_revision: 1,
                    binding_digest: Sha256Digest::for_bytes(b"binding"),
                    process_incarnation: "bounded-matrix".to_string(),
                    plane_epoch: 1,
                    identity,
                },
            )?,
        }
        Ok(())
    }

    fn read(self, root: &Path) -> Result<bool, SupervisorError> {
        match self {
            Self::Main => read_lease(root).map(|lease| lease.is_some()),
            Self::Matrix => read_matrix_lease(&self.path(root)).map(|lease| lease.is_some()),
        }
    }
}

#[test]
fn lease_readers_preserve_missing_and_round_trip_published_records() -> Result<()> {
    for kind in [LeaseKind::Main, LeaseKind::Matrix] {
        let root = tempfile::tempdir()?;
        assert!(!kind.read(root.path())?);
        kind.publish(root.path())?;
        assert!(kind.read(root.path())?);
        let before = std::fs::read(kind.path(root.path()))?;
        assert!(kind.publish(root.path()).is_err());
        assert_eq!(std::fs::read(kind.path(root.path()))?, before);
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn lease_publications_are_owner_only_and_durably_single_link() -> Result<()> {
    use std::os::unix::fs::MetadataExt;
    for kind in [LeaseKind::Main, LeaseKind::Matrix] {
        let root = tempfile::tempdir()?;
        kind.publish(root.path())?;
        let metadata = std::fs::symlink_metadata(kind.path(root.path()))?;
        // SAFETY: geteuid has no arguments and returns the effective owner UID.
        let owner = unsafe { libc::geteuid() };
        assert_eq!(
            (metadata.mode() & 0o777, metadata.nlink(), metadata.uid()),
            (0o600, 1, owner)
        );
        assert_eq!(std::fs::read_dir(root.path())?.count(), 1);
        assert!(kind.read(root.path())?);
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn lease_publication_unlinks_staging_before_directory_acknowledgement() -> Result<()> {
    use std::os::unix::fs::MetadataExt;
    for kind in [LeaseKind::Main, LeaseKind::Matrix] {
        let root = tempfile::tempdir()?;
        let staging = root.path().join(".staging");
        let destination = kind.path(root.path());
        std::fs::write(&staging, b"retained lease publication")?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let result = publish_lease_with(
            &staging,
            &destination,
            &agent,
            "lease_test",
            |parent, _component| {
                assert!(!staging.exists());
                assert_eq!(std::fs::metadata(&destination)?.nlink(), 1);
                assert_eq!(std::fs::read_dir(parent)?.count(), 1);
                Err(std::io::Error::other("injected directory acknowledgement failure").into())
            },
        );
        assert!(result.is_err());
        assert_eq!(std::fs::read(destination)?, b"retained lease publication");
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn lease_readers_reject_hardlinks_symlinks_and_writable_records() -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    for kind in [LeaseKind::Main, LeaseKind::Matrix] {
        let root = tempfile::tempdir()?;
        kind.publish(root.path())?;
        let path = kind.path(root.path());
        let alias = root.path().join("lease-alias");
        std::fs::hard_link(&path, &alias)?;
        assert!(kind.read(root.path()).is_err());
        std::fs::remove_file(&alias)?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(/*mode*/ 0o660))?;
        assert!(kind.read(root.path()).is_err());
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(/*mode*/ 0o600))?;
        assert!(kind.read(root.path())?);
        std::fs::rename(&path, &alias)?;
        std::os::unix::fs::symlink(&alias, &path)?;
        assert!(kind.read(root.path()).is_err());
        assert!(std::fs::symlink_metadata(&path)?.file_type().is_symlink());
    }
    Ok(())
}

#[test]
fn lease_readers_reject_oversized_and_torn_records() -> Result<()> {
    for kind in [LeaseKind::Main, LeaseKind::Matrix] {
        let root = tempfile::tempdir()?;
        kind.publish(root.path())?;
        let path = kind.path(root.path());
        std::fs::write(&path, vec![b'x'; MAX_LEASE_BYTES + 1])?;
        assert!(kind.read(root.path()).is_err());
        assert_eq!(
            std::fs::metadata(&path)?.len(),
            (MAX_LEASE_BYTES + 1) as u64
        );
        std::fs::write(&path, b"{")?;
        assert!(kind.read(root.path()).is_err());
        assert_eq!(std::fs::read(&path)?, b"{");
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn fifo_lease_inputs_are_rejected_without_a_writer() -> Result<()> {
    use std::os::unix::ffi::OsStrExt;
    for kind in [LeaseKind::Main, LeaseKind::Matrix] {
        let root = tempfile::tempdir()?;
        let path = kind.path(root.path());
        let name = std::ffi::CString::new(path.as_os_str().as_bytes())?;
        // SAFETY: name is NUL-terminated; mkfifo acquires no process handle.
        if unsafe { libc::mkfifo(name.as_ptr(), 0o600) } != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        assert!(kind.read(root.path()).is_err());
    }
    Ok(())
}
