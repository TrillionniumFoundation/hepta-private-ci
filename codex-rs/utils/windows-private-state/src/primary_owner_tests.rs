use super::CapturedPrimaryOwner;
use super::restriction_value;
use super::validate_primary;
use crate::security::ValidationError;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::DISABLE_MAX_PRIVILEGE;
use windows_sys::Win32::Security::DuplicateTokenEx;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::TOKEN_DUPLICATE;
use windows_sys::Win32::Security::TOKEN_IMPERSONATE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TokenHasRestrictions;
use windows_sys::Win32::Security::TokenImpersonation;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::SetThreadToken;

fn process_token() -> OwnedHandle {
    let mut raw = 0;
    // SAFETY: this test queries/duplicates its own process token only.
    assert_ne!(
        unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_DUPLICATE, &mut raw) },
        0,
        "{}",
        io::Error::last_os_error()
    );
    // SAFETY: successful OpenProcessToken transferred one newly owned handle.
    unsafe { OwnedHandle::from_raw_handle(raw as _) }
}

fn impersonation_token() -> OwnedHandle {
    let original = process_token();
    let mut raw = 0;
    // SAFETY: both token handles remain owned, no inherited attributes are set.
    assert_ne!(
        unsafe {
            DuplicateTokenEx(
                original.as_raw_handle() as HANDLE,
                TOKEN_QUERY | TOKEN_IMPERSONATE,
                ptr::null(),
                SecurityImpersonation,
                TokenImpersonation,
                &mut raw,
            )
        },
        0,
        "{}",
        io::Error::last_os_error()
    );
    // SAFETY: successful duplication transferred one newly owned handle.
    unsafe { OwnedHandle::from_raw_handle(raw as _) }
}

struct Revert;
impl Drop for Revert {
    fn drop(&mut self) {
        // SAFETY: restore only this test thread's prior non-impersonating state.
        assert_ne!(
            unsafe { RevertToSelf() },
            0,
            "{}",
            io::Error::last_os_error()
        );
    }
}

fn impersonate(token: &OwnedHandle) -> Revert {
    // SAFETY: set only this thread's token; token remains live through Revert.
    assert_ne!(
        unsafe { SetThreadToken(ptr::null(), token.as_raw_handle() as HANDLE) },
        0,
        "{}",
        io::Error::last_os_error()
    );
    Revert
}

#[test]
fn actual_elevated_primary_owner_remains_live() {
    for padding in [0, 0x5a, 0xa5, 0xff] {
        for (byte, expected) in [(0, false), (1, true)] {
            let value = u32::from_ne_bytes([byte, padding, padding, padding]);
            assert!(
                matches!(restriction_value(value, /*returned*/ 1), Ok(actual) if actual == expected)
            );
            for returned in [0, 2, 3, 4, u32::MAX] {
                assert!(matches!(
                    restriction_value(value, returned),
                    Err(ValidationError::MalformedDescriptor)
                ));
            }
        }
    }
    for byte in 2..=u8::MAX {
        assert!(matches!(
            restriction_value(u32::from_ne_bytes([byte, 0, 0, 0]), /*returned*/ 1),
            Err(ValidationError::MalformedDescriptor)
        ));
    }
    let process = process_token();
    let mut value = u32::MAX;
    let mut returned = 0;
    // SAFETY: the actual process token is owned and this initialized fixed
    // output has native DWORD alignment and capacity throughout the query.
    let success = unsafe {
        GetTokenInformation(
            process.as_raw_handle() as HANDLE,
            TokenHasRestrictions,
            ptr::from_mut(&mut value).cast(),
            std::mem::size_of::<u32>() as u32,
            &mut returned,
        )
    };
    let error = (success == 0).then(io::Error::last_os_error);
    eprintln!(
        "HEPTA_PRIMARY_FIELD class=21 capacity=4 alignment={} success={success} returned={returned} error={:?}",
        ptr::from_ref(&value) as usize % std::mem::align_of::<u32>(),
        error.as_ref().and_then(io::Error::raw_os_error)
    );
    assert_ne!(success, 0, "{error:?}");
    assert_eq!(returned, 1);
    assert!(matches!(restriction_value(value, returned), Ok(false)));
    let mut owner = CapturedPrimaryOwner::capture()
        .expect("native positive requires the actual elevated unrestricted primary administrator");
    owner.revalidate().expect("unchanged primary owner");
    owner
        .revalidate()
        .expect("same retained token remains live");
}

#[test]
fn same_user_impersonation_cannot_mint_primary_owner() {
    let token = impersonation_token();
    let _restore = impersonate(&token);
    assert!(matches!(
        CapturedPrimaryOwner::capture(),
        Err(ValidationError::PrincipalChanged)
    ));
    assert!(matches!(
        validate_primary(&token),
        Err(ValidationError::PrincipalChanged)
    ));
}

#[test]
fn primary_owner_stays_refused_after_impersonation_is_restored() {
    let mut owner = CapturedPrimaryOwner::capture().expect("native primary owner");
    let token = impersonation_token();
    let restore = impersonate(&token);
    assert!(matches!(
        owner.revalidate(),
        Err(ValidationError::PrincipalChanged)
    ));
    drop(restore);
    assert!(matches!(
        owner.revalidate(),
        Err(ValidationError::PrincipalChanged)
    ));
}

#[test]
fn real_restricted_primary_token_is_refused() {
    let original = process_token();
    // Actual S-1-5-32-544 in aligned owned SID storage, not a supplied owner proof.
    let mut admin = [
        u32::from_ne_bytes([1, 2, 0, 0]),
        u32::from_ne_bytes([0, 0, 0, 5]),
        32,
        544,
    ];
    let disabled = SID_AND_ATTRIBUTES {
        Sid: admin.as_mut_ptr().cast(),
        Attributes: 0,
    };
    let mut raw = 0;
    // SAFETY: all fixed input arrays and output storage stay live during creation.
    assert_ne!(
        unsafe {
            CreateRestrictedToken(
                original.as_raw_handle() as HANDLE,
                DISABLE_MAX_PRIVILEGE,
                /*disablesidcount*/ 1,
                &disabled,
                /*deleteprivilegecount*/ 0,
                ptr::null(),
                /*restrictedsidcount*/ 0,
                ptr::null(),
                &mut raw,
            )
        },
        0,
        "{}",
        io::Error::last_os_error()
    );
    // SAFETY: successful creation transfers one newly owned real primary token.
    let restricted = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    // Prove the actual class-21 true branch independently: another primary
    // policy check must not short-circuit away this filtered-token query.
    assert!(matches!(
        super::has_restrictions(restricted.as_raw_handle() as HANDLE),
        Ok(true)
    ));
    assert!(matches!(
        validate_primary(&restricted),
        Err(ValidationError::PrincipalChanged)
    ));
}
