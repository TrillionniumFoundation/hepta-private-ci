use super::*;
use pretty_assertions::assert_eq;
use std::io::Write as _;
use windows_sys::Win32::Foundation::ERROR_FILE_NOT_FOUND;
use windows_sys::Win32::Foundation::ERROR_PATH_NOT_FOUND;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Security::Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OwnerCase {
    ImplicitWriteDac,
    ExplicitWriteDac,
    OwnerRightsWithHostWriteDac,
}

const OWNER_CASES: [OwnerCase; 3] = [
    OwnerCase::ImplicitWriteDac,
    OwnerCase::ExplicitWriteDac,
    OwnerCase::OwnerRightsWithHostWriteDac,
];

struct LocalAllocation(*mut c_void);

impl Drop for LocalAllocation {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ObjectState {
    owner_is_token_user: bool,
    owner_and_dacl_sddl: String,
    contents: String,
}

fn object_state(path: &Path, token_user: *mut c_void) -> Result<Option<ObjectState>> {
    let mut owner = std::ptr::null_mut();
    let mut descriptor = std::ptr::null_mut();
    let information = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    let code = unsafe {
        GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            information,
            &mut owner,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    let descriptor = LocalAllocation(descriptor);
    if matches!(code, ERROR_FILE_NOT_FOUND | ERROR_PATH_NOT_FOUND) {
        return Ok(None);
    }
    anyhow::ensure!(code == ERROR_SUCCESS, "read fixture security: {code}");
    anyhow::ensure!(!owner.is_null(), "fixture security has no owner SID");
    let owner_is_token_user = unsafe { EqualSid(owner, token_user) != 0 };
    let mut sddl = std::ptr::null_mut();
    let mut length = 0;
    let converted = unsafe {
        ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor.0,
            /*requestedstringsdrevision*/ 1,
            information,
            &mut sddl,
            &mut length,
        )
    };
    let sddl = LocalAllocation(sddl.cast());
    anyhow::ensure!(converted != 0, "serialize fixture security: {}", unsafe {
        GetLastError()
    });
    anyhow::ensure!(
        !sddl.0.is_null() && length > 0,
        "empty fixture security serialization"
    );
    let wide = unsafe { std::slice::from_raw_parts(sddl.0.cast::<u16>(), length as usize) };
    anyhow::ensure!(wide.last() == Some(&0), "unterminated fixture SDDL");
    Ok(Some(ObjectState {
        owner_is_token_user,
        owner_and_dacl_sddl: String::from_utf16(&wide[..wide.len() - 1])?,
        contents: std::fs::read_to_string(path)?,
    }))
}

fn request_write_dac(path: &Path) -> NativeResult<()> {
    let handle = unsafe {
        CreateFileW(
            to_wide(path).as_ptr(),
            WRITE_DAC,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            std::ptr::null_mut(),
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            /*htemplatefile*/ 0,
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return observe(Err(std::io::Error::from_raw_os_error(unsafe {
            GetLastError() as i32
        })));
    }
    unsafe { CloseHandle(handle) };
    NativeResult::Allowed(())
}

// The same validated ACL is used for the host positive control and the
// impersonated operation. It grants both ordinary and restricted identities
// DELETE, so a successful rewrite can be followed by a real native deletion.
fn reauthorization_acl(user: *mut c_void, write: *mut c_void) -> Result<LocalAllocation> {
    let entries = [user, write].map(|sid| EXPLICIT_ACCESS_W {
        grfAccessPermissions: FILE_ALL_ACCESS,
        grfAccessMode: GRANT_ACCESS,
        grfInheritance: 0,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: sid.cast(),
        },
    });
    let mut acl = std::ptr::null_mut();
    let code = unsafe {
        SetEntriesInAclW(
            entries.len() as u32,
            entries.as_ptr(),
            std::ptr::null_mut(),
            &mut acl,
        )
    };
    let acl = LocalAllocation(acl.cast());
    anyhow::ensure!(code == ERROR_SUCCESS, "create reauthorization ACL: {code}");
    Ok(acl)
}

fn reauthorize(path: &Path, acl: &LocalAllocation) -> NativeResult<()> {
    let code = unsafe {
        SetNamedSecurityInfoW(
            to_wide(path).as_ptr() as *mut u16,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            acl.0.cast(),
            std::ptr::null_mut(),
        )
    };
    observe(if code == ERROR_SUCCESS {
        Ok(())
    } else {
        Err(std::io::Error::from_raw_os_error(code as i32))
    })
}

#[derive(Debug, Eq, PartialEq)]
struct OwnerObservation {
    case: OwnerCase,
    initial: ObjectState,
    host_initial: ObjectState,
    host_write_dac: NativeResult<()>,
    host_reauthorize: NativeResult<()>,
    host_delete: NativeResult<()>,
    host_final: Option<ObjectState>,
    read: NativeResult<String>,
    baseline_delete: NativeResult<()>,
    baseline_final: Option<ObjectState>,
    write_dac: NativeResult<()>,
    reauthorize: NativeResult<()>,
    after_reauthorize: Option<ObjectState>,
    delete_after_reauthorize: NativeResult<()>,
    final_state: Option<ObjectState>,
}

fn observe_owner_boundary(
    case: OwnerCase,
    mode: TokenMode,
) -> Result<(OwnerObservation, OwnerObservation)> {
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let read = LocalSid::from_string("S-1-5-21-591-692-793-894")?;
    let write = LocalSid::from_string("S-1-5-21-592-693-794-895")?;
    let owner_rights = LocalSid::from_string("S-1-3-4")?;
    let mut fixture = BoundaryFixture {
        root: tempfile::tempdir()?,
        user: unsafe { get_user_sid_bytes(base.0)? },
        paths: Vec::new(),
    };
    let outcome = (|| -> Result<(OwnerObservation, OwnerObservation)> {
        let parent = fixture.root.path().join("outside");
        fixture.paths.push(parent.clone());
        std::fs::create_dir(&parent)?;
        let subject = parent.join("subject.txt");
        let control = parent.join("host-control.txt");
        let baseline = parent.join("baseline-delete.txt");
        let user = fixture.user.as_mut_ptr().cast();
        for path in [&subject, &control, &baseline] {
            fixture.paths.push(path.clone());
            std::fs::write(path, "original")?;
            // Explicitly select TokenUser, rather than assuming that an
            // administrator's default token owner is the user rather than a group.
            let code = unsafe {
                SetNamedSecurityInfoW(
                    to_wide(path).as_ptr() as *mut u16,
                    SE_FILE_OBJECT,
                    OWNER_SECURITY_INFORMATION,
                    user,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                )
            };
            anyhow::ensure!(code == ERROR_SUCCESS, "set fixture TokenUser owner: {code}");
            let ordinary_mask = match case {
                OwnerCase::ImplicitWriteDac => FILE_GENERIC_READ,
                OwnerCase::ExplicitWriteDac | OwnerCase::OwnerRightsWithHostWriteDac => {
                    FILE_GENERIC_READ | WRITE_DAC
                }
            };
            let mut grants = vec![(user, ordinary_mask), (read.as_ptr(), FILE_GENERIC_READ)];
            if matches!(case, OwnerCase::OwnerRightsWithHostWriteDac) {
                // This suppresses implicit owner grants while retaining an
                // explicit host WRITE_DAC positive control. It affects only
                // this owned fixture, never arbitrary host files.
                grants.push((owner_rights.as_ptr(), READ_CONTROL));
            }
            replace_fixture_dacl(path, &grants)?;
            let state = object_state(path, user)?
                .ok_or_else(|| anyhow!("owner fixture unexpectedly missing"))?;
            anyhow::ensure!(
                state.owner_is_token_user,
                "fixture owner differs from TokenUser"
            );
        }
        // No parent DELETE_CHILD can make the post-rewrite deletion succeed
        // independently of the target ACL. Host cleanup retains WRITE_DAC.
        replace_fixture_dacl(
            &parent,
            &[
                (
                    user,
                    FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | WRITE_DAC,
                ),
                (read.as_ptr(), FILE_GENERIC_READ | FILE_GENERIC_EXECUTE),
            ],
        )?;
        let initial = object_state(&subject, user)?
            .ok_or_else(|| anyhow!("subject fixture missing before probe"))?;
        let host_initial = object_state(&control, user)?
            .ok_or_else(|| anyhow!("host fixture missing before probe"))?;
        let acl = reauthorization_acl(user, write.as_ptr())?;
        let host_write_dac = request_write_dac(&control);
        let host_reauthorize = reauthorize(&control, &acl);
        let host_delete = observe(std::fs::remove_file(&control));
        let host_final = object_state(&control, user)?;
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
        let (read_result, baseline_delete, write_dac, rewrite) = {
            let _impersonation = unsafe { Impersonation::enter(token.0)? };
            (
                observe(std::fs::read_to_string(&subject)),
                observe(std::fs::remove_file(&baseline)),
                request_write_dac(&subject),
                reauthorize(&subject, &acl),
            )
        };
        let after_reauthorize = object_state(&subject, user)?;
        let delete_after_reauthorize = {
            let _impersonation = unsafe { Impersonation::enter(token.0)? };
            observe(std::fs::remove_file(&subject))
        };
        let actual = OwnerObservation {
            case,
            initial: initial.clone(),
            host_initial,
            host_write_dac,
            host_reauthorize,
            host_delete,
            host_final,
            read: read_result,
            baseline_delete,
            baseline_final: object_state(&baseline, user)?,
            write_dac,
            reauthorize: rewrite,
            after_reauthorize,
            delete_after_reauthorize,
            final_state: object_state(&subject, user)?,
        };
        let expected = OwnerObservation {
            case,
            initial: initial.clone(),
            host_initial: initial.clone(),
            host_write_dac: NativeResult::Allowed(()),
            host_reauthorize: NativeResult::Allowed(()),
            host_delete: NativeResult::Allowed(()),
            host_final: None,
            read: NativeResult::Allowed("original".to_owned()),
            baseline_delete: denied(),
            baseline_final: Some(initial.clone()),
            write_dac: denied(),
            reauthorize: denied(),
            after_reauthorize: Some(initial.clone()),
            delete_after_reauthorize: denied(),
            final_state: Some(initial),
        };
        Ok((actual, expected))
    })();
    let cleanup = fixture.restore();
    let pair = outcome?;
    cleanup?;
    writeln!(
        std::io::stderr().lock(),
        "native owner boundary {mode:?}: {:#?}",
        pair.0
    )?;
    Ok(pair)
}

#[test]
fn workspace_token_denies_owner_dacl_reauthorization() -> Result<()> {
    let (actual, expected): (Vec<_>, Vec<_>) = OWNER_CASES
        .map(|case| observe_owner_boundary(case, TokenMode::WorkspaceToken))
        .into_iter()
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .unzip();
    assert_eq!(actual, expected);
    Ok(())
}

#[test]
fn explicit_read_plan_denies_owner_dacl_reauthorization() -> Result<()> {
    let (actual, expected): (Vec<_>, Vec<_>) = OWNER_CASES
        .map(|case| observe_owner_boundary(case, TokenMode::ExplicitReadPlan))
        .into_iter()
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .unzip();
    assert_eq!(actual, expected);
    Ok(())
}
