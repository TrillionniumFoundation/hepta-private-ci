use super::*;
use std::error::Error;
use std::fs;
use std::os::windows::ffi::OsStrExt;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use windows_sys::Win32::Foundation::ERROR_CANT_OPEN_ANONYMOUS;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::ImpersonateAnonymousToken;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_IMPERSONATE;
use windows_sys::Win32::Security::UNPROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::CREATE_NEW;
use windows_sys::Win32::Storage::FileSystem::CreateDirectoryW;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_DELETE_ON_CLOSE;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::System::Threading::SetThreadToken;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;
static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

struct CleanupRoot(PathBuf);

impl Drop for CleanupRoot {
    fn drop(&mut self) {
        // Only these fresh fixture paths; never recurse through a junction.
        let _ = fs::remove_file(self.0.join("object"));
        let _ = fs::remove_dir(self.0.join("object"));
        let _ = fs::remove_file(self.0.join("link"));
        let _ = fs::remove_dir(self.0.join("target"));
        let _ = fs::remove_dir(&self.0);
    }
}

enum Shape {
    File,
    Directory,
    Hardlinked,
    Junction,
}
enum Dacl<'a> {
    Canonical,
    Text(&'a str),
    Null,
}

struct Fixture {
    // Struct fields drop in declaration order: close DELETE_ON_CLOSE first.
    file: File,
    _root: CleanupRoot,
}

fn sid_text(current: &CurrentUser) -> String {
    let bytes = &current.sid.bytes[..current.sid.length];
    let authority = bytes[2..8]
        .iter()
        .fold(0_u64, |value, byte| (value << 8) | u64::from(*byte));
    let mut text = format!("S-1-{authority}");
    for sub in bytes[8..].chunks_exact(4) {
        let value = u32::from_le_bytes([sub[0], sub[1], sub[2], sub[3]]);
        text.push_str(&format!("-{value}"));
    }
    text
}

fn descriptor(text: &str) -> Result<LocalDescriptor> {
    let text: Vec<u16> = text.encode_utf16().chain([0]).collect();
    let mut raw = ptr::null_mut();
    // SAFETY: counted output and NUL-terminated input remain live for this call.
    if unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text.as_ptr(),
            SDDL_REVISION_1,
            &mut raw,
            ptr::null_mut(),
        )
    } == 0
    {
        return Err(io::Error::last_os_error().into());
    }
    Ok(LocalDescriptor(
        NonNull::new(raw).ok_or("missing converted descriptor")?,
    ))
}

fn owned(raw: HANDLE) -> Result<File> {
    if raw == 0 || raw == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: the successful CreateFileW transferred this one live handle.
    Ok(File::from(unsafe {
        OwnedHandle::from_raw_handle(raw as *mut c_void)
    }))
}

impl Fixture {
    fn new(current: &CurrentUser, shape: Shape, dacl: Dacl<'_>) -> Result<Self> {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let sequence = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        let root_path = std::env::temp_dir().join(format!(
            "hepta-owner-{}-{nonce}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&root_path)?; // A collision fails before owning any cleanup path.
        let root = CleanupRoot(root_path);
        let path = root.0.join("object");
        let path_wide: Vec<u16> = path.as_os_str().encode_wide().chain([0]).collect();
        let sid = sid_text(current);
        let canonical = descriptor(&format!("O:{sid}D:P(A;;FA;;;{sid})"))?;
        let attributes = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: canonical.0.as_ptr(),
            bInheritHandle: 0,
        };
        let directory = matches!(shape, Shape::Directory | Shape::Junction);
        if directory {
            let target = if matches!(shape, Shape::Junction) {
                root.0.join("target")
            } else {
                path.clone()
            };
            let target_wide: Vec<u16> = target.as_os_str().encode_wide().chain([0]).collect();
            // SAFETY: create only this fresh test directory with the live descriptor.
            if unsafe { CreateDirectoryW(target_wide.as_ptr(), &attributes) } == 0 {
                return Err(io::Error::last_os_error().into());
            }
            if matches!(shape, Shape::Junction) {
                // Same fixture model as the original native probes; no symlink privilege.
                let output = Command::new("cmd.exe")
                    .args(["/D", "/C", "mklink", "/J"])
                    .arg(&path)
                    .arg(&target)
                    .output()?;
                assert!(
                    output.status.success(),
                    "junction fixture preparation failed: {output:?}"
                );
            }
        } else {
            // SAFETY: FILE_CREATE_NEW, explicit descriptor and no inherited handle.
            drop(owned(unsafe {
                CreateFileW(
                    path_wide.as_ptr(),
                    FILE_ALL_ACCESS,
                    /*dwsharemode*/ 0,
                    &attributes,
                    CREATE_NEW,
                    /*dwflagsandattributes*/ 0,
                    /*htemplatefile*/ 0,
                )
            })?);
            if matches!(shape, Shape::Hardlinked) {
                fs::hard_link(&path, root.0.join("link"))?;
            }
        }
        // The already private object is reopened only in this non-authoritative
        // fixture. No SHARE_DELETE fallback, global ACL change or owner takeover.
        let flags =
            FILE_FLAG_DELETE_ON_CLOSE | FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT;
        // SAFETY: this fresh fixture path and security attributes remain live.
        let file = owned(unsafe {
            CreateFileW(
                path_wide.as_ptr(),
                FILE_ALL_ACCESS,
                /*dwsharemode*/ 0,
                &attributes,
                OPEN_EXISTING,
                flags,
                /*htemplatefile*/ 0,
            )
        })?;
        if !matches!(dacl, Dacl::Canonical) {
            let mut present = 1;
            let mut defaulted = 0;
            let mut raw_dacl = ptr::null_mut();
            let mut control = SE_DACL_PROTECTED;
            let mut revision = 0;
            let target;
            if let Dacl::Text(text) = dacl {
                target = descriptor(text)?;
                // SAFETY: only inspect the complete still-owned converted descriptor.
                assert_ne!(
                    unsafe {
                        GetSecurityDescriptorDacl(
                            target.0.as_ptr(),
                            &mut present,
                            &mut raw_dacl,
                            &mut defaulted,
                        )
                    },
                    0
                );
                assert_ne!(
                    unsafe {
                        GetSecurityDescriptorControl(target.0.as_ptr(), &mut control, &mut revision)
                    },
                    0
                );
                assert_ne!(present, 0, "DACL fixture must be present");
            }
            let protection = if control & SE_DACL_PROTECTED != 0 {
                PROTECTED_DACL_SECURITY_INFORMATION
            } else {
                UNPROTECTED_DACL_SECURITY_INFORMATION
            };
            // SAFETY: change only the fresh owned test object through its held
            // handle. Original granted DELETE remains for cleanup after readback.
            let code = unsafe {
                SetSecurityInfo(
                    file.as_raw_handle() as HANDLE,
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION | protection,
                    ptr::null_mut(),
                    ptr::null_mut(),
                    raw_dacl,
                    ptr::null_mut(),
                )
            };
            if code != 0 {
                return Err(io::Error::from_raw_os_error(code as i32).into());
            }
        }
        Ok(Self { file, _root: root })
    }
}

#[test]
fn native_owner_only_readback_is_valid_for_file_and_directory() -> Result {
    let current = CurrentUser::capture_effective()?;
    for (shape, kind) in [
        (Shape::File, ObjectKind::SingleLinkFile),
        (Shape::Directory, ObjectKind::Directory),
    ] {
        let fixture = Fixture::new(&current, shape, Dacl::Canonical)?;
        let descriptor = LocalDescriptor::read(&fixture.file)?;
        let bytes = descriptor.bytes()?;
        // Verify the OWNER|DACL serialization assumption on actual Windows.
        assert_eq!(
            (dword(bytes, /*offset*/ 8)?, dword(bytes, /*offset*/ 12)?),
            (0, 0)
        );
        assert_eq!(
            validate_owner_descriptor(&fixture.file, &current, kind)?.identity,
            mechanism::identity(&fixture.file)?
        );
    }
    Ok(())
}

#[test]
fn native_rejects_existing_unsafe_dacls_without_repair() -> Result {
    let current = CurrentUser::capture_effective()?;
    let sid = sid_text(&current);
    let cases = [
        "D:P".to_string(),
        format!("D:(A;;FA;;;{sid})"),
        format!("D:P(A;CI;FA;;;{sid})"),
        format!("D:P(A;;FR;;;{sid})"),
        format!("D:P(A;;FA;;;{sid})(A;;FR;;;{sid})"),
        "D:P(A;;FA;;;WD)".to_string(),
        "D:P(A;;FA;;;BU)".to_string(),
        "D:P(A;;FA;;;AU)".to_string(),
        format!("D:P(A;;FA;;;{sid})(A;;FA;;;SY)"),
        format!("D:P(A;;FA;;;{sid})(A;;FA;;;BA)"),
    ];
    for dacl in std::iter::once(Dacl::Null).chain(cases.iter().map(|text| Dacl::Text(text))) {
        let fixture = Fixture::new(&current, Shape::Directory, dacl)?;
        let before = LocalDescriptor::read(&fixture.file)?.bytes()?.to_vec();
        assert!(validate_owner_descriptor(&fixture.file, &current, ObjectKind::Directory).is_err());
        assert_eq!(LocalDescriptor::read(&fixture.file)?.bytes()?, before);
    }
    Ok(())
}

#[test]
fn native_rejects_wrong_expected_sid_and_unsafe_object_shapes() -> Result {
    let current = CurrentUser::capture_effective()?;
    let fixture = Fixture::new(&current, Shape::File, Dacl::Canonical)?;
    let other = CurrentUser {
        sid: Sid::read(&[1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0])?,
    }; // Everyone, not a captured user.
    assert!(
        current.sid != other.sid,
        "fixture needs a genuinely different SID"
    );
    let before = LocalDescriptor::read(&fixture.file)?.bytes()?.to_vec();
    assert!(matches!(
        validate_owner_descriptor(&fixture.file, &other, ObjectKind::SingleLinkFile),
        Err(ValidationError::WrongOwner)
    ));
    assert_eq!(LocalDescriptor::read(&fixture.file)?.bytes()?, before);
    for (shape, kind) in [
        (Shape::File, ObjectKind::Directory),
        (Shape::Directory, ObjectKind::SingleLinkFile),
        (Shape::Hardlinked, ObjectKind::SingleLinkFile),
        (Shape::Junction, ObjectKind::Directory),
    ] {
        let fixture = Fixture::new(&current, shape, Dacl::Canonical)?;
        assert!(matches!(
            validate_owner_descriptor(&fixture.file, &current, kind),
            Err(ValidationError::UnsafeObject)
        ));
    }
    Ok(())
}

#[test]
fn native_readback_parser_rejects_altered_forms_and_every_truncation() -> Result {
    let current = CurrentUser::capture_effective()?;
    let fixture = Fixture::new(&current, Shape::File, Dacl::Canonical)?;
    let original = LocalDescriptor::read(&fixture.file)?.bytes()?.to_vec();
    validate_descriptor(&original, &current)?;
    for length in 0..original.len() {
        assert!(
            validate_descriptor(&original[..length], &current).is_err(),
            "accepted truncation at {length}"
        );
    }
    let acl = dword(&original, /*offset*/ 16)? as usize;
    let ace = acl + 8;
    let mut cases = vec![
        (0, vec![2]),
        (2, SE_SELF_RELATIVE.to_le_bytes().to_vec()),
        (4, 0_u32.to_le_bytes().to_vec()),
        (16, 0_u32.to_le_bytes().to_vec()),
        (acl, vec![4]),
        (acl + 2, 7_u16.to_le_bytes().to_vec()),
        (acl + 4, 2_u16.to_le_bytes().to_vec()),
        (ace + 2, 4_u16.to_le_bytes().to_vec()),
        (ace + 4, 0_u32.to_le_bytes().to_vec()),
        (ace + 8, vec![0]),
        (ace + 9, vec![255]),
    ];
    cases.extend([1, 5, 9, 255].map(|kind| (ace, vec![kind]))); // Deny/object/callback/unknown.
    cases.extend([1, 2, 8, 16].map(|flags| (ace + 1, vec![flags]))); // Inherit/only/inherited.
    for (offset, replacement) in cases {
        let mut bytes = original.clone();
        bytes[offset..offset + replacement.len()].copy_from_slice(&replacement);
        assert!(
            validate_descriptor(&bytes, &current).is_err(),
            "accepted alteration at {offset}"
        );
    }
    assert_eq!(LocalDescriptor::read(&fixture.file)?.bytes()?, original);
    Ok(())
}

#[test]
fn native_unqueryable_thread_token_never_falls_back_to_process_user() -> Result {
    struct RestoreThread(Option<OwnedHandle>);
    impl Drop for RestoreThread {
        fn drop(&mut self) {
            // SAFETY: restore only this same test thread's prior token, retaining
            // its owned handle throughout. Also runs when an assertion panics.
            let restored = unsafe {
                match &self.0 {
                    Some(token) => SetThreadToken(ptr::null(), token.as_raw_handle() as HANDLE),
                    None => RevertToSelf(),
                }
            };
            assert!(
                restored != 0 || std::thread::panicking(),
                "restore fixture thread identity"
            );
        }
    }
    let before = CurrentUser::capture_effective()?;
    let mut raw = 0;
    // SAFETY: inspect only the current thread; a successful result is owned.
    let previous = if unsafe {
        OpenThreadToken(
            GetCurrentThread(),
            TOKEN_QUERY | TOKEN_IMPERSONATE,
            /*openasself*/ 1,
            &mut raw,
        )
    } != 0
    {
        // SAFETY: this successful open transferred one live token handle.
        Some(unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) })
    } else {
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(ERROR_NO_TOKEN as i32) {
            return Err(error.into());
        }
        None
    };
    let restore = RestoreThread(previous);
    // SAFETY: impersonate only this test thread; the guard restores its old token.
    if unsafe { ImpersonateAnonymousToken(GetCurrentThread()) } == 0 {
        return Err(io::Error::last_os_error().into());
    }
    let observed = CurrentUser::capture_effective();
    drop(restore);
    assert!(
        matches!(observed, Err(ValidationError::Os(error)) if error.raw_os_error() == Some(ERROR_CANT_OPEN_ANONYMOUS as i32))
    );
    assert!(CurrentUser::capture_effective()?.sid == before.sid);
    Ok(())
}
