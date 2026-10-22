use super::eligible;
use windows_sys::Win32::System::SystemServices::SE_GROUP_ENABLED;
use windows_sys::Win32::System::SystemServices::SE_GROUP_ENABLED_BY_DEFAULT;
use windows_sys::Win32::System::SystemServices::SE_GROUP_OWNER;
use windows_sys::Win32::System::SystemServices::SE_GROUP_USE_FOR_DENY_ONLY;

#[test]
fn owner_candidate_requires_current_enabled_owner_non_deny_and_distinct_user() {
    let admitted = (SE_GROUP_OWNER | SE_GROUP_ENABLED) as u32;
    assert!(eligible(admitted, false));
    assert!(!eligible(admitted, true));
    assert!(!eligible(SE_GROUP_OWNER as u32, false));
    assert!(!eligible(SE_GROUP_ENABLED as u32, false));
    assert!(!eligible(
        (SE_GROUP_OWNER | SE_GROUP_ENABLED_BY_DEFAULT) as u32,
        false
    ));
    assert!(!eligible(
        admitted | SE_GROUP_USE_FOR_DENY_ONLY as u32,
        false
    ));
    assert!(!eligible(0, false));
}
