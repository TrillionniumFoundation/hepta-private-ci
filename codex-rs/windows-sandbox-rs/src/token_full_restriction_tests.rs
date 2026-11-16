//! Native mechanism probes for a fully restricted token on owned fixture objects.
//! These tests do not change the production token policy, admit a sandbox, or
//! launch a process with the diagnostic token. In particular, they do not prove
//! that production DLL loading, named pipes, or read-root ACLs support this mode.

use super::Impersonation;
use super::OwnedToken;
use crate::acl::ensure_allow_mask_aces;
use crate::acl::ensure_allow_write_aces;
use crate::delete_permission_matrix::DeleteMatrix;
use crate::delete_permission_matrix::DeleteOutcome;
use crate::delete_permission_matrix::DeleteRoute;
use crate::token::DISABLE_MAX_PRIVILEGE;
use crate::token::LUA_TOKEN;
use crate::token::LocalSid;
use crate::token::enable_single_privilege;
use crate::token::get_current_token_for_restriction;
use crate::token::get_user_sid_bytes;
use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use std::fs;
use std::io::ErrorKind;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

enum FixtureUser {
    Excluded,
    Included,
}

fn full_restricted_fixture_token(
    base: &OwnedToken,
    capabilities: &[&LocalSid],
    fixture_user: FixtureUser,
) -> Result<OwnedToken> {
    ensure!(!capabilities.is_empty(), "fixture requires a capability");
    // The source is the current host's token. Including its user below probes
    // only owned objects whose matrix ACLs contain Everyone, not that user.
    // It must not be mistaken for a dedicated sandbox-account admission test.
    let mut user = unsafe { get_user_sid_bytes(base.0)? };
    let mut entries: Vec<_> = capabilities
        .iter()
        .map(|sid| SID_AND_ATTRIBUTES {
            Sid: sid.as_ptr(),
            Attributes: 0,
        })
        .collect();
    if matches!(fixture_user, FixtureUser::Included) {
        entries.push(SID_AND_ATTRIBUTES {
            Sid: user.as_mut_ptr().cast(),
            Attributes: 0,
        });
    }
    let mut raw = 0;
    // SAFETY: base and all SID buffers remain owned throughout this call. The
    // new handle belongs to the guard immediately after successful creation.
    // Omission of WRITE_RESTRICTED is the sole enforcement-mode experiment.
    ensure!(
        unsafe {
            CreateRestrictedToken(
                base.0,
                DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
                /*disablesidcount*/ 0,
                std::ptr::null(),
                /*deleteprivilegecount*/ 0,
                std::ptr::null(),
                entries.len() as u32,
                entries.as_ptr(),
                &mut raw,
            )
        } != 0,
        "CreateRestrictedToken: {}",
        std::io::Error::last_os_error()
    );
    let token = OwnedToken(raw);
    // SAFETY: the owned token remains live; production also retains only this
    // traversal privilege. No backup, restore, or ownership privilege is added.
    unsafe { enable_single_privilege(token.0, "SeChangeNotifyPrivilege")? };
    Ok(token)
}

#[test]
fn full_restriction_blocks_all_four_owned_delete_routes() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let host = DeleteMatrix::new(&fixture.path().join("host"))?;
    let restricted = DeleteMatrix::new(&fixture.path().join("restricted"))?;
    host.assert_same_acls(&restricted);
    let host_errors = crate::delete_permission_control::native(&host)?;
    let host_outcomes = host.finish("full-restriction-ordinary-control")?;
    let routes = [
        DeleteRoute::Neither,
        DeleteRoute::TargetOnly,
        DeleteRoute::ParentOnly,
        DeleteRoute::Both,
    ];
    assert_eq!(
        host_errors,
        vec![
            [Some((ErrorKind::PermissionDenied, Some(5))); 2],
            [None; 2],
            [None; 2],
            [None; 2],
        ]
    );
    assert_eq!(
        host_outcomes,
        routes.map(|route| DeleteOutcome {
            route,
            file_deleted: route != DeleteRoute::Neither,
            directory_deleted: route != DeleteRoute::Neither,
        })
    );

    let capability = LocalSid::from_string("S-1-5-21-171-272-373-475")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let allowed = fixture.path().join("allowed");
    fs::create_dir(&allowed)?;
    // Only the owned positive-control directory receives grants. Matrix ACLs
    // remain byte-identical and are checked again after every native attempt.
    unsafe {
        ensure_allow_mask_aces(&allowed, &[everyone.as_ptr()], FILE_ALL_ACCESS)?;
        ensure_allow_write_aces(&allowed, &[capability.as_ptr()])?;
    }
    let allowed_file = allowed.join("file");
    let allowed_directory = allowed.join("directory");
    fs::write(&allowed_file, "allowed")?;
    fs::create_dir(&allowed_directory)?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let token = full_restricted_fixture_token(&base, &[&capability], FixtureUser::Included)?;
    let (errors, diagnostic) = {
        // SAFETY: token remains owned for this scope. Every accessed path is
        // inside the fixture; no child receives this token or a fixture handle.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        let diagnostic = restricted.access_diagnostics();
        fs::write(&allowed_file, "modified")?;
        fs::remove_file(&allowed_file)?;
        fs::remove_dir(&allowed_directory)?;
        let errors: Vec<_> = restricted
            .paths()
            .map(|(file, directory)| {
                [fs::remove_file(file), fs::remove_dir(directory)].map(|result| {
                    result
                        .err()
                        .map(|error| (error.kind(), error.raw_os_error()))
                })
            })
            .collect();
        (errors, diagnostic)
    };
    let outcomes = restricted.finish("full-restriction-owned-object-probe")?;
    eprintln!("full_restriction_delete errors={errors:?} outcomes={outcomes:?}");
    assert_eq!(
        errors,
        vec![[Some((ErrorKind::PermissionDenied, Some(5))); 2]; 4],
        "{diagnostic}"
    );
    assert_eq!(
        outcomes,
        routes.map(|route| DeleteOutcome {
            route,
            file_deleted: false,
            directory_deleted: false,
        }),
        "{diagnostic}"
    );
    assert!(!allowed_file.exists());
    assert!(!allowed_directory.exists());
    Ok(())
}

#[test]
fn full_restriction_requires_read_capability_without_granting_write() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let capability = LocalSid::from_string("S-1-5-21-171-272-373-476")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    // Model an ambient readable root: the ordinary pass has full access, while
    // the restricting pass receives a read ACE on exactly one existing file.
    unsafe {
        ensure_allow_mask_aces(fixture.path(), &[everyone.as_ptr()], FILE_ALL_ACCESS)?;
    }
    let readable = fixture.path().join("readable");
    let ambient_only = fixture.path().join("ambient-only");
    fs::write(&readable, "readable original")?;
    fs::write(&ambient_only, "ambient original")?;
    unsafe {
        ensure_allow_mask_aces(&readable, &[capability.as_ptr()], FILE_GENERIC_READ)?;
    }
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let token = full_restricted_fixture_token(&base, &[&capability], FixtureUser::Excluded)?;
    let (contents, errors) = {
        // SAFETY: only the owned fixture paths are accessed under this token.
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        let contents = fs::read_to_string(&readable)?;
        let errors = [
            fs::read_to_string(&ambient_only).map(|_| ()),
            fs::write(&readable, "must not replace"),
            fs::remove_file(&readable),
        ]
        .map(|result| {
            result
                .err()
                .map(|error| (error.kind(), error.raw_os_error()))
        });
        (contents, errors)
    };
    eprintln!("full_restriction_read errors={errors:?}");
    assert_eq!(contents, "readable original");
    assert_eq!(errors, [Some((ErrorKind::PermissionDenied, Some(5))); 3]);
    assert_eq!(fs::read_to_string(&readable)?, "readable original");
    assert_eq!(fs::read_to_string(&ambient_only)?, "ambient original");
    Ok(())
}
