use std::io;
use std::ptr;

use windows_sys::Win32::Foundation::PSID;
use windows_sys::Win32::Security::CreateWellKnownSid;
use windows_sys::Win32::Security::WELL_KNOWN_SID_TYPE;
use windows_sys::Win32::Security::WinLocalSystemSid;
use windows_sys::Win32::Security::WinNullSid;
use windows_sys::Win32::Security::WinWorldSid;

struct TestSid([u32; 17]);

impl TestSid {
    fn new(kind: WELL_KNOWN_SID_TYPE) -> Self {
        let mut sid = Self([0; 17]);
        let mut size = std::mem::size_of_val(&sid.0) as u32;
        // SAFETY: the aligned owned buffer has SECURITY_MAX_SID_SIZE bytes.
        let result = unsafe {
            CreateWellKnownSid(kind, ptr::null_mut(), sid.0.as_mut_ptr().cast(), &mut size)
        };
        assert_ne!(result, 0, "create synthetic well-known SID");
        assert!(size as usize <= std::mem::size_of_val(&sid.0));
        sid
    }

    fn as_ptr(&self) -> PSID {
        self.0.as_ptr() as PSID
    }
}

#[test]
fn matching_complete_sids_pass_the_existing_owner_gate() {
    let peer = TestSid::new(WinWorldSid);
    let owner = TestSid::new(WinWorldSid);
    // SAFETY: both complete SIDs are valid and their buffers remain alive.
    unsafe { super::platform::ensure_matching_user_sids(peer.as_ptr(), owner.as_ptr()) }
        .expect("equal complete SIDs should pass");
}

#[test]
fn different_complete_sids_still_fail_closed() {
    let peer = TestSid::new(WinWorldSid);
    let owner = TestSid::new(WinLocalSystemSid);
    // SAFETY: both complete SIDs are valid and their buffers remain alive.
    let error =
        unsafe { super::platform::ensure_matching_user_sids(peer.as_ptr(), owner.as_ptr()) }
            .expect_err("a different SID must not authorize the peer");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
}

#[test]
fn equal_final_rid_does_not_authorize_a_different_sid_authority() {
    // Both S-1-1-0 (World) and S-1-0-0 (Null) end in RID zero.
    let peer = TestSid::new(WinWorldSid);
    let owner = TestSid::new(WinNullSid);
    // SAFETY: both complete SIDs are valid and their buffers remain alive.
    let error =
        unsafe { super::platform::ensure_matching_user_sids(peer.as_ptr(), owner.as_ptr()) }
            .expect_err("matching final RID cannot replace complete SID equality");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
}
