//! Real test-only tokens; never a production factory or launch admission.
use super::*;
use codex_windows_sandbox::ensure_allow_mask_aces;
use codex_windows_sandbox::filesystem_capability_plan;
use codex_windows_sandbox::get_current_token_for_restriction;
use pretty_assertions::assert_eq;
use std::mem::offset_of;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::ERROR_NO_TOKEN;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::IsTokenRestricted;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

fn probe_token(plan: &FilesystemCapabilityPlan) -> OwnedHandle {
    let raw = unsafe { get_current_token_for_restriction() }.unwrap();
    let base = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    assert_eq!(unsafe { IsTokenRestricted(base.as_raw_handle() as _) }, 0);
    let sids: Vec<_> = plan
        .read_sids()
        .map(|sid| LocalSid::from_string(sid).unwrap())
        .collect();
    let entries: Vec<_> = sids
        .iter()
        .map(|sid| SID_AND_ATTRIBUTES {
            Sid: sid.as_ptr(),
            Attributes: 0,
        })
        .collect();
    let mut raw = 0;
    // DISABLE_MAX_PRIVILEGE | LUA_TOKEN, explicitly no WRITE_RESTRICTED and
    // no default-DACL mutation or ambient restricting SID fallback.
    assert_ne!(
        unsafe {
            CreateRestrictedToken(
                base.as_raw_handle() as _,
                /*flags*/ 0x01 | 0x04,
                /*disablesidcount*/ 0,
                std::ptr::null(),
                /*deleteprivilegecount*/ 0,
                std::ptr::null(),
                entries.len() as _,
                entries.as_ptr(),
                &mut raw,
            )
        },
        0
    );
    let token = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    let mut needed = 0;
    assert_eq!(
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenRestrictedSids,
                std::ptr::null_mut(),
                /*tokeninformationlength*/ 0,
                &mut needed,
            )
        },
        0
    );
    assert_eq!(unsafe { GetLastError() }, ERROR_INSUFFICIENT_BUFFER);
    assert!((8..=65_536).contains(&needed));
    let mut words = vec![0_usize; (needed as usize).div_ceil(size_of::<usize>())];
    let capacity = needed;
    assert_ne!(
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenRestrictedSids,
                words.as_mut_ptr().cast(),
                capacity,
                &mut needed,
            )
        },
        0
    );
    assert!(needed <= capacity);
    let count = unsafe { *words.as_ptr().cast::<u32>() } as usize;
    let offset = offset_of!(TOKEN_GROUPS, Groups);
    assert!(count <= (needed as usize).saturating_sub(offset) / size_of::<SID_AND_ATTRIBUTES>());
    let start = words.as_ptr() as usize;
    let end = start.checked_add(needed as usize).unwrap();
    let mut actual = Vec::new();
    for index in 0..count {
        let group = unsafe {
            std::ptr::read_unaligned(
                words
                    .as_ptr()
                    .cast::<u8>()
                    .add(offset + index * size_of::<SID_AND_ATTRIBUTES>())
                    .cast::<SID_AND_ATTRIBUTES>(),
            )
        };
        let sid = group.Sid as usize;
        assert!(sid >= start && sid.checked_add(8).is_some_and(|last| last <= end));
        let count = unsafe { *(sid as *const u8).add(1) };
        assert!(count <= 15);
        let length = 8 + usize::from(count) * 4;
        assert!(sid.checked_add(length).is_some_and(|last| last <= end));
        actual.push(unsafe { std::slice::from_raw_parts(sid as *const u8, length) }.to_vec());
    }
    let mut expected: Vec<_> = sids
        .iter()
        .map(|sid| {
            unsafe {
                std::slice::from_raw_parts(
                    sid.as_ptr().cast::<u8>(),
                    GetLengthSid(sid.as_ptr()) as usize,
                )
            }
            .to_vec()
        })
        .collect();
    actual.sort();
    expected.sort();
    assert_eq!(actual, expected);
    token
}

fn read_under(token: &OwnedHandle, path: &Path) -> std::io::Result<Vec<u8>> {
    let mut previous = 0;
    let opened = unsafe {
        OpenThreadToken(
            GetCurrentThread(),
            TOKEN_QUERY,
            /*openasself*/ 1,
            &mut previous,
        )
    };
    let error = unsafe { GetLastError() };
    if opened != 0 {
        unsafe { CloseHandle(previous) };
    }
    assert_eq!(
        (opened, error),
        (0, ERROR_NO_TOKEN),
        "probe requires a fresh test thread"
    );
    assert_ne!(
        unsafe { ImpersonateLoggedOnUser(token.as_raw_handle() as _) },
        0
    );
    // Capture the actual operation before asserting, and restore before returning.
    let result = std::fs::read(path);
    assert_ne!(unsafe { RevertToSelf() }, 0);
    result
}

fn read_subjects(plan: &FilesystemCapabilityPlan) -> ReadAclSubjects {
    ReadAclSubjects {
        normal_identity: LocalSid::from_string("S-1-1-0").unwrap(),
        ambient_rx: [
            LocalSid::from_string("S-1-5-32-545").unwrap(),
            LocalSid::from_string("S-1-5-11").unwrap(),
            LocalSid::from_string("S-1-1-0").unwrap(),
        ],
        restrictive_rx: plan
            .read_root_sids()
            .map(|(root, sid)| (root.to_owned(), LocalSid::from_string(sid).unwrap()))
            .collect(),
    }
}

#[test]
fn existing_native_token_cannot_gain_a_later_disjoint_read_root() {
    let fixture = tempfile::tempdir().unwrap();
    let home = fixture.path().join("home");
    let roots = [fixture.path().join("a"), fixture.path().join("b")];
    for root in &roots {
        std::fs::create_dir(root).unwrap();
        std::fs::write(root.join("data"), b"exact-root").unwrap();
    }
    let roots = roots.map(|path| dunce::canonicalize(path).unwrap());
    let everyone = LocalSid::from_string("S-1-1-0").unwrap();
    unsafe { ensure_allow_mask_aces(fixture.path(), &[everyone.as_ptr()], FILE_ALL_ACCESS) }
        .unwrap();
    let first = filesystem_capability_plan(&home, fixture.path(), &roots[..1], &[]).unwrap();
    let mut log = Vec::new();
    let prepared =
        prepare_roots(first.clone(), &roots[..1], read_subjects(&first), &mut log).unwrap();
    let old = probe_token(&first);
    assert_eq!(
        read_under(&old, &roots[0].join("data")).unwrap(),
        b"exact-root"
    );
    assert_eq!(
        read_under(&old, &roots[1].join("data")).unwrap_err().kind(),
        std::io::ErrorKind::PermissionDenied
    );
    drop(prepared);
    let second = filesystem_capability_plan(&home, fixture.path(), &roots, &[]).unwrap();
    let _prepared =
        prepare_roots(second.clone(), &roots, read_subjects(&second), &mut log).unwrap();
    let new = probe_token(&second);
    assert_eq!(
        read_under(&old, &roots[0].join("data")).unwrap(),
        b"exact-root"
    );
    assert_eq!(
        read_under(&old, &roots[1].join("data")).unwrap_err().kind(),
        std::io::ErrorKind::PermissionDenied
    );
    assert_eq!(
        read_under(&new, &roots[1].join("data")).unwrap(),
        b"exact-root"
    );
}
