//! Native diagnostic candidate only; no production launch or isolation admission.
#![deny(clippy::all)]

use super::*;
use pretty_assertions::assert_eq;
use std::io::ErrorKind;
use std::mem::offset_of;
use std::mem::size_of;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::SE_PRIVILEGE_ENABLED;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;

// Kernel query memory is aligned, bounded, initialized and never escapes as a pointer.
struct TokenBytes {
    words: Vec<usize>,
    length: usize,
}

impl TokenBytes {
    fn query(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> Result<Self> {
        let mut needed = 0;
        // SAFETY: token is owned by the caller; this first call has no output buffer.
        let first = unsafe {
            GetTokenInformation(
                token,
                class,
                std::ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut needed,
            )
        };
        anyhow::ensure!(first == 0 && unsafe { GetLastError() } == ERROR_INSUFFICIENT_BUFFER);
        anyhow::ensure!((4..=65_536).contains(&needed), "invalid token query size");
        let mut result = Self {
            words: vec![0; (needed as usize).div_ceil(size_of::<usize>())],
            length: needed as usize,
        };
        // SAFETY: the aligned zeroed buffer covers the advertised capacity.
        anyhow::ensure!(
            unsafe {
                GetTokenInformation(
                    token,
                    class,
                    result.words.as_mut_ptr().cast(),
                    needed,
                    &mut needed,
                )
            } != 0,
            "token query failed: {}",
            unsafe { GetLastError() }
        );
        anyhow::ensure!(needed as usize <= result.length && needed >= 4);
        result.length = needed as usize;
        Ok(result)
    }

    fn value<T: Copy>(&self, offset: usize) -> Result<T> {
        anyhow::ensure!(
            offset
                .checked_add(size_of::<T>())
                .is_some_and(|end| end <= self.length)
        );
        // SAFETY: checked initialized range; callers use only native integer/pointer structs.
        Ok(
            unsafe {
                std::ptr::read_unaligned(self.words.as_ptr().cast::<u8>().add(offset).cast())
            },
        )
    }

    fn pointed_bytes(&self, pointer: *const u8, length: usize) -> Result<Vec<u8>> {
        let start = pointer as usize;
        let base = self.words.as_ptr() as usize;
        anyhow::ensure!(
            start >= base
                && start
                    .checked_add(length)
                    .is_some_and(|end| end <= base + self.length)
        );
        // SAFETY: the complete pointed range belongs to this initialized query buffer.
        Ok(unsafe { std::slice::from_raw_parts(pointer, length) }.to_vec())
    }

    fn sid(&self, pointer: *mut c_void) -> Result<Vec<u8>> {
        let header = self.pointed_bytes(pointer.cast(), /*length*/ 8)?;
        anyhow::ensure!(header[0] == 1 && header[1] <= 15, "invalid queried SID");
        self.pointed_bytes(pointer.cast(), 8 + usize::from(header[1]) * 4)
    }

    fn groups(&self) -> Result<Vec<Vec<u8>>> {
        let count = self.value::<u32>(/*offset*/ 0)? as usize;
        let offset = offset_of!(TOKEN_GROUPS, Groups);
        anyhow::ensure!(
            count <= self.length.saturating_sub(offset) / size_of::<SID_AND_ATTRIBUTES>()
        );
        let mut result = Vec::new();
        for index in 0..count {
            let entry =
                self.value::<SID_AND_ATTRIBUTES>(offset + index * size_of::<SID_AND_ATTRIBUTES>())?;
            result.push(self.sid(entry.Sid)?);
        }
        result.sort();
        Ok(result)
    }

    fn default_dacl(&self) -> Result<Option<Vec<u8>>> {
        let pointer = self.value::<*const u8>(/*offset*/ 0)?;
        if pointer.is_null() {
            return Ok(None); // A token may legitimately have no default DACL.
        }
        let header = self.pointed_bytes(pointer, /*length*/ 8)?;
        let length = usize::from(u16::from_le_bytes([header[2], header[3]]));
        anyhow::ensure!(length >= 8, "invalid default DACL");
        self.pointed_bytes(pointer, length).map(Some)
    }
}

// Explicit subjects, not a boolean that silently changes a production token.
// The inherited default DACL is left unchanged: IPC/process compatibility is unqualified.
fn candidate(base: &OwnedToken, subjects: &[&LocalSid]) -> Result<OwnedToken> {
    anyhow::ensure!(!subjects.is_empty() && subjects.len() <= 3);
    let mut entries: Vec<_> = subjects
        .iter()
        .map(|sid| SID_AND_ATTRIBUTES {
            Sid: sid.as_ptr(),
            Attributes: 0,
        })
        .collect();
    let mut raw = 0;
    // SAFETY: base and all owned SIDs outlive this synchronous call; success is immediately owned.
    anyhow::ensure!(
        unsafe {
            CreateRestrictedToken(
                base.0,
                DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
                /*disablesidcount*/ 0,
                std::ptr::null(),
                /*deleteprivilegecount*/ 0,
                std::ptr::null(),
                entries.len() as u32,
                entries.as_mut_ptr(),
                &mut raw,
            )
        } != 0,
        "candidate creation failed: {}",
        unsafe { GetLastError() }
    );
    let token = OwnedToken(raw);
    let actual = TokenBytes::query(token.0, TokenRestrictedSids)?.groups()?;
    let mut expected = subjects
        .iter()
        .map(|sid| {
            // SAFETY: LocalSid owns a validated converted SID throughout this copy.
            unsafe {
                std::slice::from_raw_parts(
                    sid.as_ptr().cast::<u8>(),
                    GetLengthSid(sid.as_ptr()) as usize,
                )
            }
            .to_vec()
        })
        .collect::<Vec<_>>();
    expected.sort();
    assert!(actual == expected, "unexpected actual restricting SID set");
    let normal = TokenBytes::query(token.0, TokenGroups)?.groups()?;
    let base_groups = TokenBytes::query(base.0, TokenGroups)?.groups()?;
    assert!(!normal.is_empty() && normal.iter().all(|sid| base_groups.contains(sid)));
    assert!(
        expected.iter().all(|sid| !normal.contains(sid)),
        "capabilities became ambient groups"
    );
    let original = TokenBytes::query(base.0, TokenUser)?;
    let restricted = TokenBytes::query(token.0, TokenUser)?;
    assert!(
        original.sid(original.value::<SID_AND_ATTRIBUTES>(/*offset*/ 0)?.Sid)?
            == restricted.sid(restricted.value::<SID_AND_ATTRIBUTES>(/*offset*/ 0)?.Sid)?
    );
    assert!(
        TokenBytes::query(base.0, TokenDefaultDacl)?.default_dacl()?
            == TokenBytes::query(token.0, TokenDefaultDacl)?.default_dacl()?
    );
    let privileges = TokenBytes::query(token.0, TokenPrivileges)?;
    let count = privileges.value::<u32>(/*offset*/ 0)? as usize;
    let offset = offset_of!(TOKEN_PRIVILEGES, Privileges);
    anyhow::ensure!(
        count <= privileges.length.saturating_sub(offset) / size_of::<LUID_AND_ATTRIBUTES>()
    );
    let mut traverse = LUID {
        LowPart: 0,
        HighPart: 0,
    };
    // SAFETY: valid NUL-terminated privilege name and live output.
    anyhow::ensure!(
        unsafe {
            LookupPrivilegeValueW(
                std::ptr::null(),
                to_wide("SeChangeNotifyPrivilege").as_ptr(),
                &mut traverse,
            )
        } != 0
    );
    for index in 0..count {
        let entry = privileges
            .value::<LUID_AND_ATTRIBUTES>(offset + index * size_of::<LUID_AND_ATTRIBUTES>())?;
        assert!(
            entry.Attributes & SE_PRIVILEGE_ENABLED == 0
                || (entry.Luid.LowPart, entry.Luid.HighPart)
                    == (traverse.LowPart, traverse.HighPart)
        );
    }
    Ok(token)
}

fn open_execute(path: &Path) -> std::io::Result<OwnedHandle> {
    // SAFETY: this existing owned fixture and counted wide path remain live.
    let raw = unsafe {
        CreateFileW(
            to_wide(path).as_ptr(),
            FILE_GENERIC_EXECUTE,
            /*dwsharemode*/ 0,
            std::ptr::null(),
            OPEN_EXISTING,
            /*dwflagsandattributes*/ 0,
            /*htemplatefile*/ 0,
        )
    };
    if raw == 0 || raw == windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE {
        return Err(std::io::Error::last_os_error());
    }
    // SAFETY: successful CreateFileW transferred one live handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) })
}

#[test]
fn native_full_restriction_preserves_reads_and_refuses_parent_delete() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let read = LocalSid::from_string("S-1-5-21-151-252-353-454")?;
    let cap_a = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let cap_b = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let other = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
    let mut everyone = unsafe { world_sid()? };
    // SAFETY: change only this fresh owned fixture. Preserve the original broad parent attack.
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[logon.as_mut_ptr().cast(), everyone.as_mut_ptr().cast()],
            FILE_ALL_ACCESS,
        )?;
        ensure_allow_mask_aces(
            fixture.path(),
            &[read.as_ptr()],
            FILE_GENERIC_READ | FILE_GENERIC_EXECUTE,
        )?;
    }
    let allowed = [
        fixture.path().join("workspace"),
        fixture.path().join("temp"),
    ];
    for (path, cap) in allowed.iter().zip([&cap_a, &cap_b]) {
        std::fs::create_dir(path)?;
        unsafe {
            ensure_allow_write_aces(path, &[cap.as_ptr()])?;
        }
        std::fs::write(path.join("delete.txt"), "inside")?;
        std::fs::create_dir(path.join("delete-dir"))?;
    }
    let outside = fixture.path().join("outside");
    std::fs::create_dir(&outside)?;
    unsafe {
        ensure_allow_write_aces(&outside, &[other.as_ptr()])?;
    }
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    let no_read = candidate(&base, &[&cap_a, &cap_b])?;
    {
        let _impersonation = unsafe { Impersonation::enter(no_read.0)? };
        assert_eq!(
            std::fs::read(outside.join("keep.txt")).unwrap_err().kind(),
            ErrorKind::PermissionDenied
        );
        assert_eq!(
            open_execute(&outside.join("keep.txt")).unwrap_err().kind(),
            ErrorKind::PermissionDenied
        );
    }
    let readonly = candidate(&base, &[&read])?;
    {
        let _impersonation = unsafe { Impersonation::enter(readonly.0)? };
        for path in &allowed {
            assert_eq!(std::fs::read_to_string(path.join("delete.txt"))?, "inside");
            drop(open_execute(&path.join("delete.txt"))?);
            let refused = [
                std::fs::write(path.join("delete.txt"), "bad"),
                std::fs::write(path.join("created.txt"), "bad"),
                std::fs::remove_file(path.join("delete.txt")),
                std::fs::remove_dir(path.join("delete-dir")),
            ]
            .map(|result| result.err().map(|error| error.kind()));
            assert_eq!(refused, [Some(ErrorKind::PermissionDenied); 4]);
        }
    }
    for path in &allowed {
        assert_eq!(
            (
                std::fs::read_to_string(path.join("delete.txt"))?,
                path.join("created.txt").exists(),
                path.join("delete-dir").is_dir()
            ),
            ("inside".to_owned(), false, true)
        );
    }
    let full = candidate(&base, &[&read, &cap_a, &cap_b])?;
    {
        let _impersonation = unsafe { Impersonation::enter(full.0)? };
        for path in &allowed {
            std::fs::write(path.join("created.txt"), "allowed")?;
            std::fs::remove_file(path.join("delete.txt"))?;
            std::fs::remove_dir(path.join("delete-dir"))?;
        }
        let outside_read = std::fs::read_to_string(outside.join("keep.txt"))?;
        drop(open_execute(&outside.join("keep.txt"))?);
        let refused = [
            std::fs::write(outside.join("keep.txt"), "overwritten"),
            std::fs::write(outside.join("created.txt"), "outside"),
            std::fs::remove_file(outside.join("keep.txt")),
            std::fs::remove_dir(outside.join("keep-dir")),
        ]
        .map(|result| result.err().map(|error| error.kind()));
        assert_eq!(refused, [Some(ErrorKind::PermissionDenied); 4]);
        assert_eq!(outside_read, "outside");
    }
    assert_eq!(
        (
            std::fs::read_to_string(outside.join("keep.txt"))?,
            outside.join("created.txt").exists(),
            outside.join("keep-dir").is_dir()
        ),
        ("outside".to_owned(), false, true)
    );
    for path in &allowed {
        assert_eq!(
            (
                std::fs::read_to_string(path.join("created.txt"))?,
                path.join("delete.txt").exists(),
                path.join("delete-dir").exists()
            ),
            ("allowed".to_owned(), false, false)
        );
    }
    println!(
        "HEPTA_FULL_RESTRICTION_CANDIDATE {{\"stage\":\"original_operations_complete\",\"readonly_controls\":true,\"explicit_read_execute\":true,\"production_admitted\":false}}"
    );
    Ok(())
}
