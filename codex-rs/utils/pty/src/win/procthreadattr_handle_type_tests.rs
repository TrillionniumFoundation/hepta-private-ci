use super::HPCON;
use super::ProcThreadAttributeList;
use anyhow::Error;
use winapi::ctypes::c_void;

#[test]
fn winapi_attribute_payload_signature() {
    // Compile-only regression: the Win32 ABI expects winapi's c_void.
    let _update: unsafe fn(
        &mut ProcThreadAttributeList,
        usize,
        *mut c_void,
        usize,
    ) -> Result<(), Error> = ProcThreadAttributeList::update;
    let _set_pty: fn(&mut ProcThreadAttributeList, HPCON) -> Result<(), Error> =
        ProcThreadAttributeList::set_pty;
}
