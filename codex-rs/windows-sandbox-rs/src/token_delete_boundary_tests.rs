use super::*;
use pretty_assertions::assert_eq;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

#[path = "token_delete_control_tests.rs"]
mod control_reference;
#[path = "token_owner_boundary_tests.rs"]
mod owner_boundary;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DeleteAuthority {
    Neither,
    TargetOnly,
    ParentOnly,
    Both,
}

const AUTHORITIES: [DeleteAuthority; 4] = [
    DeleteAuthority::Neither,
    DeleteAuthority::TargetOnly,
    DeleteAuthority::ParentOnly,
    DeleteAuthority::Both,
];

#[derive(Clone, Copy, Debug)]
enum TokenMode {
    WorkspaceToken,
    ExplicitReadPlan,
}

#[derive(Debug, Eq, PartialEq)]
enum NativeResult<T> {
    Allowed(T),
    Error {
        kind: std::io::ErrorKind,
        win32: Option<i32>,
    },
}

fn observe<T>(result: std::io::Result<T>) -> NativeResult<T> {
    match result {
        Ok(value) => NativeResult::Allowed(value),
        Err(error) => NativeResult::Error {
            kind: error.kind(),
            win32: error.raw_os_error(),
        },
    }
}

fn denied<T>() -> NativeResult<T> {
    NativeResult::Error {
        kind: std::io::ErrorKind::PermissionDenied,
        win32: Some(ERROR_ACCESS_DENIED as i32),
    }
}

#[derive(Debug, Eq, PartialEq)]
struct BoundaryObservation {
    authority: DeleteAuthority,
    ordinary_delete_file: NativeResult<()>,
    ordinary_delete_dir: NativeResult<()>,
    outside_read: NativeResult<String>,
    outside_write: NativeResult<()>,
    outside_create: NativeResult<()>,
    outside_delete_file: NativeResult<()>,
    outside_delete_dir: NativeResult<()>,
    outside_rename_into_workspace: NativeResult<()>,
    inside_write: NativeResult<()>,
    inside_create: NativeResult<()>,
    inside_delete_file: NativeResult<()>,
    inside_delete_dir: NativeResult<()>,
    inside_rename: NativeResult<()>,
    final_files: Vec<(String, Option<String>)>,
    final_dirs: Vec<(String, bool)>,
}

// Every ACL is replaced, protected, and non-inheriting. In particular, a target
// cannot accidentally acquire DELETE from the temporary directory's old ACL.
fn replace_fixture_dacl(path: &Path, grants: &[(*mut c_void, u32)]) -> Result<()> {
    let entries: Vec<_> = grants
        .iter()
        .map(|(sid, mask)| EXPLICIT_ACCESS_W {
            grfAccessPermissions: *mask,
            grfAccessMode: GRANT_ACCESS,
            grfInheritance: 0,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: std::ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: sid.cast(),
            },
        })
        .collect();
    let mut acl = std::ptr::null_mut();
    // SAFETY: fixture paths and validated SIDs outlive both copying APIs. The
    // new ACL has no inherited or previously existing ACEs and is always freed.
    let code = unsafe {
        let code = SetEntriesInAclW(
            entries.len() as u32,
            entries.as_ptr(),
            std::ptr::null_mut(),
            &mut acl,
        );
        let code = if code == ERROR_SUCCESS {
            SetNamedSecurityInfoW(
                to_wide(path).as_ptr() as *mut u16,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                acl,
                std::ptr::null_mut(),
            )
        } else {
            code
        };
        if !acl.is_null() {
            LocalFree(acl as HLOCAL);
        }
        code
    };
    anyhow::ensure!(
        code == ERROR_SUCCESS,
        "replace fixture DACL for {}: {code}",
        path.display()
    );
    Ok(())
}

struct BoundaryFixture {
    root: tempfile::TempDir,
    user: Vec<u8>,
    paths: Vec<PathBuf>,
}

impl BoundaryFixture {
    fn restore(&mut self) -> Result<()> {
        let user = self.user.as_mut_ptr().cast();
        // Restore children first, including files created or moved by either
        // token. WRITE_DAC is explicit for the host; no sandbox token survives
        // in an impersonation scope when this cleanup executes.
        for path in self.paths.iter().rev() {
            match std::fs::symlink_metadata(path) {
                Ok(_) => replace_fixture_dacl(path, &[(user, FILE_ALL_ACCESS)])?,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
        }
        self.paths.clear();
        Ok(())
    }
}

impl Drop for BoundaryFixture {
    fn drop(&mut self) {
        if let Err(error) = self.restore() {
            eprintln!("native DELETE fixture cleanup failed: {error:#}");
        }
    }
}

// This is an in-process native comparison, not a new production token API or
// proof that arbitrary shell startup, registry, IPC, or full-disk reads work.
unsafe fn explicit_read_plan_token(
    base: HANDLE,
    user: *mut c_void,
    read: *mut c_void,
    write: *mut c_void,
) -> Result<OwnedToken> {
    let mut sids = [read, write].map(|sid| SID_AND_ATTRIBUTES {
        Sid: sid,
        Attributes: 0,
    });
    let mut token = 0;
    let ok = unsafe {
        CreateRestrictedToken(
            base,
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
            /*disablesidcount*/ 0,
            std::ptr::null(),
            /*deleteprivilegecount*/ 0,
            std::ptr::null(),
            sids.len() as u32,
            sids.as_mut_ptr(),
            &mut token,
        )
    };
    anyhow::ensure!(
        ok != 0,
        "create complete restricted comparison token: {}",
        unsafe { GetLastError() }
    );
    let token = OwnedToken(token);
    // User grants satisfy the ordinary check; only explicit capabilities can
    // satisfy the restricted check. No broad identity enters that second list.
    unsafe {
        set_default_dacl(token.0, &[user, write])?;
        enable_single_privilege(token.0, "SeChangeNotifyPrivilege")?;
    }
    Ok(token)
}

fn observe_boundary(authority: DeleteAuthority, mode: TokenMode) -> Result<BoundaryObservation> {
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let read = LocalSid::from_string("S-1-5-21-491-592-693-794")?;
    let write = LocalSid::from_string("S-1-5-21-492-593-694-795")?;
    let mut fixture = BoundaryFixture {
        root: tempfile::tempdir()?,
        user: unsafe { get_user_sid_bytes(base.0)? },
        paths: Vec::new(),
    };
    let outcome = (|| -> Result<BoundaryObservation> {
        let outside = fixture.root.path().join("outside");
        let inside = fixture.root.path().join("workspace");
        for parent in [&outside, &inside] {
            fixture.paths.push(parent.clone());
            std::fs::create_dir(parent)?;
            for name in [
                "keep.txt",
                "delete.txt",
                "rename.txt",
                "host-delete.txt",
                "reference-delete.txt",
            ] {
                let path = parent.join(name);
                fixture.paths.push(path.clone());
                std::fs::write(path, name)?;
            }
            for name in ["delete-dir", "host-delete-dir", "reference-delete-dir"] {
                let path = parent.join(name);
                fixture.paths.push(path.clone());
                std::fs::create_dir(path)?;
            }
            for name in ["created.txt", "renamed.txt", "stolen.txt"] {
                fixture.paths.push(parent.join(name));
            }
        }
        let user = fixture.user.as_mut_ptr().cast();
        let ordinary = FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | WRITE_DAC;
        let parent_delete = match authority {
            DeleteAuthority::ParentOnly | DeleteAuthority::Both => FILE_DELETE_CHILD,
            DeleteAuthority::Neither | DeleteAuthority::TargetOnly => 0,
        };
        let target_delete = match authority {
            DeleteAuthority::TargetOnly | DeleteAuthority::Both => DELETE,
            DeleteAuthority::Neither | DeleteAuthority::ParentOnly => 0,
        };
        let mut acl_observations = Vec::new();
        for path in &fixture.paths {
            match std::fs::symlink_metadata(path) {
                Ok(_) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                Err(error) => return Err(error.into()),
            }
            let grants = if path.starts_with(&inside) {
                [
                    (user, FILE_ALL_ACCESS),
                    (
                        write.as_ptr(),
                        FILE_GENERIC_READ
                            | FILE_GENERIC_WRITE
                            | FILE_GENERIC_EXECUTE
                            | DELETE
                            | FILE_DELETE_CHILD,
                    ),
                ]
            } else {
                let delete = if path == &outside {
                    parent_delete
                } else {
                    target_delete
                };
                [
                    (user, ordinary | delete),
                    (read.as_ptr(), FILE_GENERIC_READ | FILE_GENERIC_EXECUTE),
                ]
            };
            replace_fixture_dacl(path, &grants)?;
            acl_observations.push((
                path.strip_prefix(fixture.root.path())?.to_path_buf(),
                control_reference::verify_fixture_acl(path, &grants)?,
            ));
        }
        let token = unsafe {
            match mode {
                TokenMode::WorkspaceToken => OwnedToken(
                    create_workspace_write_token_with_caps_from(base.0, &[write.as_ptr()])?,
                ),
                TokenMode::ExplicitReadPlan => {
                    explicit_read_plan_token(base.0, user, read.as_ptr(), write.as_ptr())?
                }
            }
        };
        // A reference token has the subject's ordinary identity and privileges,
        // but no restricting SIDs. Its controls must still deny Neither and
        // allow all three granted routes; raw host results remain diagnostic.
        let (ordinary_delete_file, ordinary_delete_dir) =
            control_reference::observe_reference_deletions(
                base.0,
                token.0,
                &outside,
                mode,
                authority,
                &acl_observations,
            )?;
        let mut observation = {
            let _impersonation = unsafe { Impersonation::enter(token.0)? };
            BoundaryObservation {
                authority,
                ordinary_delete_file,
                ordinary_delete_dir,
                outside_read: observe(std::fs::read_to_string(outside.join("keep.txt"))),
                outside_write: observe(std::fs::write(outside.join("keep.txt"), "changed")),
                outside_create: observe(std::fs::write(outside.join("created.txt"), "new")),
                outside_delete_file: observe(std::fs::remove_file(outside.join("delete.txt"))),
                outside_delete_dir: observe(std::fs::remove_dir(outside.join("delete-dir"))),
                outside_rename_into_workspace: observe(std::fs::rename(
                    outside.join("rename.txt"),
                    inside.join("stolen.txt"),
                )),
                inside_write: observe(std::fs::write(inside.join("keep.txt"), "changed")),
                inside_create: observe(std::fs::write(inside.join("created.txt"), "new")),
                inside_delete_file: observe(std::fs::remove_file(inside.join("delete.txt"))),
                inside_delete_dir: observe(std::fs::remove_dir(inside.join("delete-dir"))),
                inside_rename: observe(std::fs::rename(
                    inside.join("rename.txt"),
                    inside.join("renamed.txt"),
                )),
                final_files: Vec::new(),
                final_dirs: Vec::new(),
            }
        };
        for name in [
            "outside/keep.txt",
            "outside/delete.txt",
            "outside/rename.txt",
            "outside/created.txt",
            "workspace/keep.txt",
            "workspace/created.txt",
            "workspace/delete.txt",
            "workspace/rename.txt",
            "workspace/renamed.txt",
            "workspace/stolen.txt",
        ] {
            let content = match std::fs::read_to_string(fixture.root.path().join(name)) {
                Ok(content) => Some(content),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
                Err(error) => return Err(error.into()),
            };
            observation.final_files.push((name.to_owned(), content));
        }
        for name in ["outside/delete-dir", "workspace/delete-dir"] {
            observation
                .final_dirs
                .push((name.to_owned(), fixture.root.path().join(name).is_dir()));
        }
        Ok(observation)
    })();
    let cleanup = fixture.restore();
    let observation = outcome?;
    cleanup?;
    // Bypass libtest's capture so a later process timeout still retains every
    // completed route, the actual Win32 errors, and exact resulting contents.
    writeln!(
        std::io::stderr().lock(),
        "native DELETE boundary {mode:?}: {observation:#?}"
    )?;
    Ok(observation)
}

fn expected_boundary(authority: DeleteAuthority) -> BoundaryObservation {
    let ordinary_delete = || match authority {
        DeleteAuthority::Neither => denied(),
        DeleteAuthority::TargetOnly | DeleteAuthority::ParentOnly | DeleteAuthority::Both => {
            NativeResult::Allowed(())
        }
    };
    BoundaryObservation {
        authority,
        ordinary_delete_file: ordinary_delete(),
        ordinary_delete_dir: ordinary_delete(),
        outside_read: NativeResult::Allowed("keep.txt".to_owned()),
        outside_write: denied(),
        outside_create: denied(),
        outside_delete_file: denied(),
        outside_delete_dir: denied(),
        outside_rename_into_workspace: denied(),
        inside_write: NativeResult::Allowed(()),
        inside_create: NativeResult::Allowed(()),
        inside_delete_file: NativeResult::Allowed(()),
        inside_delete_dir: NativeResult::Allowed(()),
        inside_rename: NativeResult::Allowed(()),
        final_files: [
            ("outside/keep.txt", Some("keep.txt")),
            ("outside/delete.txt", Some("delete.txt")),
            ("outside/rename.txt", Some("rename.txt")),
            ("outside/created.txt", None),
            ("workspace/keep.txt", Some("changed")),
            ("workspace/created.txt", Some("new")),
            ("workspace/delete.txt", None),
            ("workspace/rename.txt", None),
            ("workspace/renamed.txt", Some("rename.txt")),
            ("workspace/stolen.txt", None),
        ]
        .map(|(path, content)| (path.to_owned(), content.map(str::to_owned)))
        .into(),
        final_dirs: vec![
            ("outside/delete-dir".to_owned(), true),
            ("workspace/delete-dir".to_owned(), false),
        ],
    }
}

#[test]
fn workspace_token_confines_each_native_delete_authorization_route() -> Result<()> {
    let actual = AUTHORITIES
        .map(|authority| observe_boundary(authority, TokenMode::WorkspaceToken))
        .into_iter()
        .collect::<Result<Vec<_>>>()?;
    assert_eq!(actual, AUTHORITIES.map(expected_boundary));
    Ok(())
}

#[test]
fn explicit_read_plan_preserves_native_reads_and_confines_mutations() -> Result<()> {
    let actual = AUTHORITIES
        .map(|authority| observe_boundary(authority, TokenMode::ExplicitReadPlan))
        .into_iter()
        .collect::<Result<Vec<_>>>()?;
    assert_eq!(actual, AUTHORITIES.map(expected_boundary));
    Ok(())
}
