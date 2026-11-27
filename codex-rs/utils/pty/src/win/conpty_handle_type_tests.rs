use super::RawConPty;
use pretty_assertions::assert_eq;
use std::os::windows::io::RawHandle;

#[test]
fn winapi_pseudoconsole_handle_can_bridge_std_raw_handle() {
    let original = std::ptr::NonNull::<u8>::dangling().as_ptr();
    let native: winapi::um::winnt::HANDLE = original.cast();
    let bridged: RawHandle = native.cast();
    assert_eq!(bridged.cast::<u8>(), original);
    let _accessor: fn(&RawConPty) -> RawHandle = RawConPty::pseudoconsole_handle;
}
