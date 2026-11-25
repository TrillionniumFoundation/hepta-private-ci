//! These experiments characterize the OS boundary; they do not enable a launcher.

#[path = "token_delete_matrix_support.rs"]
mod support;

use anyhow::Result;
use pretty_assertions::assert_eq;
use support::Dacl;
use support::Kind;
use support::RestrictedToken;
use support::Restriction;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;

#[derive(Clone, Copy, Debug)]
enum DeleteGrant {
    Neither,
    Target,
    Parent,
}

#[test]
fn native_delete_distinguishes_target_right_from_parent_delete_child() -> Result<()> {
    let mut completed = 0;
    for mode in [Restriction::WriteOnly, Restriction::Full] {
        let token = RestrictedToken::new(mode)?;
        for kind in [Kind::File, Kind::Directory] {
            for grant in [
                DeleteGrant::Neither,
                DeleteGrant::Target,
                DeleteGrant::Parent,
            ] {
                let fixture = tempfile::tempdir()?;
                let parent = fixture.path().join("parent");
                let target = parent.join("target");
                std::fs::create_dir(&parent)?;
                support::create_target(&target, kind)?;
                let (parent_policy, target_policy) = match grant {
                    DeleteGrant::Neither => (
                        Dacl::Identity(FILE_ALL_ACCESS),
                        Dacl::Identity(FILE_ALL_ACCESS),
                    ),
                    DeleteGrant::Target => (
                        Dacl::Identity(FILE_ALL_ACCESS & !FILE_DELETE_CHILD),
                        Dacl::Capability(DELETE),
                    ),
                    DeleteGrant::Parent => (
                        Dacl::Capability(FILE_DELETE_CHILD),
                        Dacl::Identity(FILE_ALL_ACCESS & !DELETE),
                    ),
                };
                support::set_dacl(&parent, parent_policy)?;
                support::set_dacl(&target, target_policy)?;
                let outcome = token
                    .run(|| support::delete(&target, kind))?
                    .err()
                    .map(|error| error.raw_os_error());
                let expected = match (mode, grant) {
                    (Restriction::Full, DeleteGrant::Neither) => {
                        Some(Some(ERROR_ACCESS_DENIED as i32))
                    }
                    _ => None,
                };
                assert_eq!(
                    (outcome, target.try_exists()?),
                    (expected, expected.is_some()),
                    "mode={mode:?} kind={kind:?} grant={grant:?}"
                );
                fixture.close()?;
                completed += 1;
                eprintln!(
                    "HEPTA_DELETE_MATRIX mode={mode:?} kind={kind:?} grant={grant:?} error={outcome:?}"
                );
            }
        }
    }
    assert_eq!(completed, 12);
    Ok(())
}

#[test]
fn full_restriction_has_a_real_controlled_write_positive_and_outside_negative() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let allowed = fixture.path().join("allowed");
    let outside = fixture.path().join("outside");
    for path in [&allowed, &outside] {
        std::fs::create_dir(path)?;
    }
    support::set_dacl(&allowed, Dacl::InheritableCapability(FILE_ALL_ACCESS))?;
    support::set_dacl(&outside, Dacl::Identity(FILE_ALL_ACCESS))?;
    let existing = allowed.join("existing");
    let protected = outside.join("protected");
    std::fs::write(&existing, b"before")?;
    std::fs::write(&protected, b"unchanged")?;
    support::set_dacl(&existing, Dacl::Capability(FILE_ALL_ACCESS))?;
    support::set_dacl(&protected, Dacl::Identity(FILE_ALL_ACCESS))?;
    let token = RestrictedToken::new(Restriction::Full)?;
    let (read, outside_errors) = token.run(|| -> Result<_> {
        let created = allowed.join("created");
        std::fs::write(&existing, b"after")?;
        std::fs::write(&created, b"created")?;
        let read = (std::fs::read(&existing)?, std::fs::read(&created)?);
        support::delete(&created, Kind::File)?;
        let directory = allowed.join("created-dir");
        std::fs::create_dir(&directory)?;
        support::delete(&directory, Kind::Directory)?;
        let outside_errors = [
            std::fs::write(&protected, b"must not be written"),
            std::fs::write(outside.join("created"), b"must not be created"),
            support::delete(&protected, Kind::File),
        ]
        .map(|result| result.err().map(|error| error.kind()));
        Ok((read, outside_errors))
    })??;
    assert_eq!(read, (b"after".to_vec(), b"created".to_vec()));
    assert_eq!(
        outside_errors,
        [Some(std::io::ErrorKind::PermissionDenied); 3]
    );
    assert_eq!(
        (
            std::fs::read(&existing)?,
            std::fs::read(&protected)?,
            allowed.join("created").try_exists()?,
            allowed.join("created-dir").try_exists()?,
            outside.join("created").try_exists()?
        ),
        (
            b"after".to_vec(),
            b"unchanged".to_vec(),
            false,
            false,
            false
        )
    );
    fixture.close()?;
    Ok(())
}

#[test]
fn null_dacl_is_an_explicit_limit_of_full_restriction() -> Result<()> {
    let token = RestrictedToken::new(Restriction::Full)?;
    let mut completed = 0;
    for kind in [Kind::File, Kind::Directory] {
        for grant in [DeleteGrant::Target, DeleteGrant::Parent] {
            let fixture = tempfile::tempdir()?;
            let parent = fixture.path().join("outside");
            let target = parent.join("target");
            std::fs::create_dir(&parent)?;
            support::create_target(&target, kind)?;
            let (parent_policy, target_policy) = match grant {
                DeleteGrant::Target => (
                    Dacl::Identity(FILE_ALL_ACCESS & !FILE_DELETE_CHILD),
                    Dacl::Null,
                ),
                DeleteGrant::Parent => (Dacl::Null, Dacl::Identity(FILE_ALL_ACCESS & !DELETE)),
                DeleteGrant::Neither => unreachable!(),
            };
            support::set_dacl(&parent, parent_policy)?;
            support::set_dacl(&target, target_policy)?;
            token.run(|| support::delete(&target, kind))??;
            assert!(!target.try_exists()?);
            fixture.close()?;
            completed += 1;
            eprintln!(
                "HEPTA_DELETE_MATRIX full_restriction_null_dacl kind={kind:?} grant={grant:?} deletion=allowed"
            );
        }
    }
    assert_eq!(completed, 4);
    Ok(())
}

#[test]
fn low_integrity_does_not_protect_a_low_outside_null_dacl_object() -> Result<()> {
    let token = RestrictedToken::new(Restriction::Full)?;
    token.lower_integrity()?;
    for kind in [Kind::File, Kind::Directory] {
        let fixture = tempfile::tempdir()?;
        let parent = fixture.path().join("outside-low");
        let target = parent.join("target");
        std::fs::create_dir(&parent)?;
        support::create_target(&target, kind)?;
        support::set_dacl(&parent, Dacl::Null)?;
        support::set_dacl(&target, Dacl::Null)?;
        support::lower_object_integrity(&parent)?;
        support::lower_object_integrity(&target)?;
        token.run(|| support::delete(&target, kind))??;
        assert!(!target.try_exists()?);
        fixture.close()?;
        eprintln!(
            "HEPTA_DELETE_MATRIX full_restriction_low_null_dacl kind={kind:?} deletion=allowed"
        );
    }
    Ok(())
}
