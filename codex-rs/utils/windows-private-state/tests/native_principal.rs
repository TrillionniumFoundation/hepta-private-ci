#![cfg(windows)]

#[path = "../src/token_test_fixture.rs"]
mod token_test_fixture;
#[path = "../src/token_test_observation.rs"]
mod token_test_observation;

use codex_utils_windows_private_state::principal::CapturedPrincipal;
use codex_utils_windows_private_state::security::CurrentUser;
use codex_utils_windows_private_state::security::ValidationError;
use std::error::Error;
use std::ffi::c_void;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use windows_sys::Win32::Foundation::ERROR_CANT_OPEN_ANONYMOUS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::AdjustTokenPrivileges;
use windows_sys::Win32::Security::DuplicateTokenEx;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::TOKEN_ADJUST_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_DUPLICATE;
use windows_sys::Win32::Security::TOKEN_IMPERSONATE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenImpersonation;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::SetThreadToken;

type Result<T = ()> = std::result::Result<T, Box<dyn Error + Send + Sync>>;

fn isolated(test: fn() -> Result) -> Result {
    std::thread::spawn(test)
        .join()
        .map_err(|_| io::Error::other("principal fixture thread panicked"))?
}

struct RestoreThread;

impl Drop for RestoreThread {
    fn drop(&mut self) {
        // Each fixture runs on its own new thread, whose original context is
        // the process token. Never modify the process token or another thread.
        assert!(unsafe { RevertToSelf() } != 0 || std::thread::panicking());
    }
}

fn duplicate(level: i32) -> Result<OwnedHandle> {
    let mut raw = 0;
    // SAFETY: the process pseudo-handle and output storage are live.
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_DUPLICATE, &mut raw) }
        == 0
    {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: successful open transfers a newly owned, non-inherited handle.
    let process = unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) };
    // SAFETY: this creates a separate token object; only that fixture object
    // receives impersonation and mutation rights, never CapturedPrincipal.
    if unsafe {
        DuplicateTokenEx(
            process.as_raw_handle() as HANDLE,
            TOKEN_QUERY | TOKEN_IMPERSONATE | TOKEN_ADJUST_PRIVILEGES,
            ptr::null(),
            level,
            TokenImpersonation,
            &mut raw,
        )
    } == 0
    {
        return Err(io::Error::last_os_error().into());
    }
    Ok(unsafe { OwnedHandle::from_raw_handle(raw as *mut c_void) })
}

fn install(token: &OwnedHandle) -> Result {
    // SAFETY: the fixture token stays live and only this isolated thread changes.
    if unsafe { SetThreadToken(ptr::null(), token.as_raw_handle() as HANDLE) } == 0 {
        return Err(io::Error::last_os_error().into());
    }
    Ok(())
}

fn statistics(token: &OwnedHandle) -> Result<TOKEN_STATISTICS> {
    let mut result: TOKEN_STATISTICS = unsafe { std::mem::zeroed() };
    let mut length = 0;
    // SAFETY: query the live fixture token into fixed-size initialized storage.
    if unsafe {
        GetTokenInformation(
            token.as_raw_handle() as HANDLE,
            TokenStatistics,
            (&mut result as *mut TOKEN_STATISTICS).cast(),
            size_of::<TOKEN_STATISTICS>() as u32,
            &mut length,
        )
    } == 0
    {
        return Err(io::Error::last_os_error().into());
    }
    assert_eq!(length as usize, size_of::<TOKEN_STATISTICS>());
    Ok(result)
}

#[test]
fn native_same_effective_token_revalidates() -> Result {
    isolated(|| {
        let mut process = CapturedPrincipal::capture_effective()?;
        process.revalidate_effective()?;
        let token = duplicate(SecurityImpersonation)?;
        let _restore = RestoreThread;
        install(&token)?;
        let mut thread = CapturedPrincipal::capture_effective()?;
        thread.revalidate_effective()?;
        Ok(())
    })
}

#[test]
fn native_same_sid_replacement_is_refused_and_cannot_revive() -> Result {
    isolated(|| {
        let first = duplicate(SecurityImpersonation)?;
        let second = duplicate(SecurityImpersonation)?;
        let _restore = RestoreThread;
        install(&first)?;
        let mut captured = CapturedPrincipal::capture_effective()?;
        let original_user = CurrentUser::capture_effective()?;
        install(&second)?;
        assert!(original_user == CurrentUser::capture_effective()?);
        assert!(
            statistics(&first)?.TokenId.LowPart != statistics(&second)?.TokenId.LowPart
                || statistics(&first)?.TokenId.HighPart != statistics(&second)?.TokenId.HighPart
        );
        assert!(matches!(
            captured.revalidate_effective(),
            Err(ValidationError::PrincipalChanged)
        ));
        install(&first)?;
        assert!(matches!(
            captured.revalidate_effective(),
            Err(ValidationError::PrincipalChanged)
        ));
        Ok(())
    })
}

#[test]
fn native_held_token_modification_is_refused() -> Result {
    isolated(|| {
        let token = duplicate(SecurityImpersonation)?;
        let _restore = RestoreThread;
        install(&token)?;
        let mut captured = CapturedPrincipal::capture_effective()?;
        let before = statistics(&token)?;
        let original_user = CurrentUser::capture_effective()?;
        // SAFETY: disable privileges only in the separately duplicated fixture
        // token. Standard Windows process tokens contain enabled privileges;
        // a fixture without an actual modification fails instead of skipping.
        if unsafe {
            AdjustTokenPrivileges(
                token.as_raw_handle() as HANDLE,
                /*disableallprivileges*/ 1,
                ptr::null(),
                /*bufferlength*/ 0,
                ptr::null_mut(),
                ptr::null_mut(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error().into());
        }
        let changed = statistics(&token)?;
        assert!(original_user == CurrentUser::capture_effective()?);
        assert_eq!(
            (before.TokenId.LowPart, before.TokenId.HighPart),
            (changed.TokenId.LowPart, changed.TokenId.HighPart)
        );
        assert!(
            (before.ModifiedId.LowPart, before.ModifiedId.HighPart)
                != (changed.ModifiedId.LowPart, changed.ModifiedId.HighPart)
        );
        assert!(matches!(
            captured.revalidate_effective(),
            Err(ValidationError::PrincipalChanged)
        ));
        Ok(())
    })
}

#[test]
fn native_degraded_and_unqueryable_thread_tokens_never_fall_back() -> Result {
    isolated(|| {
        let mut original = CapturedPrincipal::capture_effective()?;
        let identification = duplicate(windows_sys::Win32::Security::SecurityIdentification)?;
        let anonymous = token_test_fixture::anonymous_level_token()?;
        let _restore = RestoreThread;
        install(&identification)?;
        assert!(matches!(
            CapturedPrincipal::capture_effective(),
            Err(ValidationError::PrincipalChanged)
        ));
        install(&anonymous)?;
        let observed = original.revalidate_effective();
        token_test_observation::observe(&observed);
        assert!(
            matches!(observed, Err(ValidationError::Os(error)) if error.raw_os_error() == Some(ERROR_CANT_OPEN_ANONYMOUS as i32))
        );
        drop(_restore);
        assert!(matches!(
            original.revalidate_effective(),
            Err(ValidationError::PrincipalChanged)
        ));
        Ok(())
    })
}
