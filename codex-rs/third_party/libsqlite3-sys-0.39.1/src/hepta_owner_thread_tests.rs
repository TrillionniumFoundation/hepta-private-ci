//! A bounded same-user thread-token control. No process token or privilege changes.

use super::support::Vfs;
use crate::hepta_win32_owner_vfs_name;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::ptr;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use windows_sys::Win32::Foundation as foundation;
use windows_sys::Win32::Security as security;
use windows_sys::Win32::System::Threading as threading;

struct RestoreThreadToken {
    _token: OwnedHandle,
    restored: Arc<AtomicBool>,
}

impl Drop for RestoreThreadToken {
    fn drop(&mut self) {
        // SAFETY: This guard exists only on a new dedicated test thread whose
        // prior state was verified to have no impersonation token. The owned
        // duplicate remains live until after restoration. Thread exit is an
        // additional boundary even if the restoration call itself fails.
        let restored = unsafe { threading::SetThreadToken(ptr::null(), 0) } != 0;
        self.restored.store(restored, Ordering::SeqCst);
    }
}

#[test]
fn same_user_thread_token_reuses_policy_and_restores_thread_state() {
    let name = hepta_win32_owner_vfs_name().unwrap();
    let expected = Vfs::Private(name).pointer() as usize;
    let restored = Arc::new(AtomicBool::new(false));
    let observation = Arc::clone(&restored);
    std::thread::spawn(move || {
        let mut existing = 0;
        // SAFETY: Read-only observation of this newly spawned thread.
        assert_eq!(
            unsafe {
                threading::OpenThreadToken(
                    threading::GetCurrentThread(),
                    security::TOKEN_QUERY,
                    1,
                    &mut existing,
                )
            },
            0
        );
        assert_eq!(
            unsafe { foundation::GetLastError() },
            foundation::ERROR_NO_TOKEN
        );
        let mut primary = 0;
        // SAFETY: Query and duplicate only the current process's own token.
        assert_ne!(
            unsafe {
                threading::OpenProcessToken(
                    threading::GetCurrentProcess(),
                    security::TOKEN_QUERY | security::TOKEN_DUPLICATE,
                    &mut primary,
                )
            },
            0
        );
        let primary = unsafe { OwnedHandle::from_raw_handle(primary as _) };
        let mut duplicate = 0;
        // SAFETY: Duplicates the existing same-user token; no privileges or SID
        // membership are enabled or altered and no other account is involved.
        assert_ne!(
            unsafe {
                security::DuplicateTokenEx(
                    primary.as_raw_handle() as _,
                    security::TOKEN_QUERY | security::TOKEN_IMPERSONATE,
                    ptr::null(),
                    security::SecurityImpersonation,
                    security::TokenImpersonation,
                    &mut duplicate,
                )
            },
            0
        );
        {
            let scope = RestoreThreadToken {
                _token: unsafe { OwnedHandle::from_raw_handle(duplicate as _) },
                restored: observation,
            };
            // SAFETY: Only this dedicated thread receives its own duplicated token.
            assert_ne!(
                unsafe { threading::SetThreadToken(ptr::null(), duplicate) },
                0
            );
            let mut present = 0;
            // SAFETY: Confirms the actual thread-token branch is available.
            assert_ne!(
                unsafe {
                    threading::OpenThreadToken(
                        threading::GetCurrentThread(),
                        security::TOKEN_QUERY,
                        1,
                        &mut present,
                    )
                },
                0
            );
            let present = unsafe { OwnedHandle::from_raw_handle(present as _) };
            let actual = hepta_win32_owner_vfs_name().unwrap();
            assert_eq!(Vfs::Private(actual).pointer() as usize, expected);
            assert_eq!(actual, name);
            drop(present);
            drop(scope);
        }
        let mut absent = 0;
        // SAFETY: Verify restoration rather than relying only on thread exit.
        assert_eq!(
            unsafe {
                threading::OpenThreadToken(
                    threading::GetCurrentThread(),
                    security::TOKEN_QUERY,
                    1,
                    &mut absent,
                )
            },
            0
        );
        assert_eq!(
            unsafe { foundation::GetLastError() },
            foundation::ERROR_NO_TOKEN
        );
    })
    .join()
    .expect("same-user thread-token control");
    assert!(
        restored.load(Ordering::SeqCst),
        "RAII restored the original no-token state"
    );
}
