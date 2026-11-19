use super::*;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::SET_ACCESS;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;

fn fixture() -> (tempfile::TempDir, PathBuf, FilesystemCapabilityPlan) {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("owned fixture: {error}"));
    let home = temporary.path().join("home");
    let root = temporary.path().join("root");
    let other = temporary.path().join("other");
    std::fs::create_dir(&root).unwrap_or_else(|error| panic!("owned directory: {error}"));
    std::fs::create_dir(&other).unwrap_or_else(|error| panic!("second owned directory: {error}"));
    let root =
        dunce::canonicalize(root).unwrap_or_else(|error| panic!("actual fixture root: {error}"));
    let other =
        dunce::canonicalize(other).unwrap_or_else(|error| panic!("second actual root: {error}"));
    let plan = crate::filesystem_capability_plan(&home, &root, &[root.clone(), other], &[])
        .unwrap_or_else(|error| panic!("actual ReadV3 declaration: {error}"));
    (temporary, home, plan)
}

fn grant(plan: &FilesystemCapabilityPlan, access: u32) {
    for (path, sid) in plan.read_root_sids() {
        let sid = LocalSid::from_string(sid)
            .unwrap_or_else(|error| panic!("actual registered SID: {error}"));
        // Force exact SET_ACCESS, including removal of an earlier extra right.
        // The general ensure helper intentionally skips an already sufficient ACE.
        let (previous, descriptor) = unsafe { crate::fetch_dacl_handle(Path::new(path)) }
            .unwrap_or_else(|error| panic!("owned fixture descriptor: {error}"));
        let _descriptor = LocalDescriptor(descriptor);
        let entry = EXPLICIT_ACCESS_W {
            grfAccessPermissions: access,
            grfAccessMode: SET_ACCESS,
            grfInheritance: 3,
            Trustee: TRUSTEE_W {
                TrusteeForm: TRUSTEE_IS_SID,
                ptstrName: sid.as_ptr().cast(),
                ..unsafe { std::mem::zeroed() }
            },
        };
        let mut updated = std::ptr::null_mut();
        // SAFETY: mutate only this test's fresh owned directory, with live ACL/SID.
        assert_eq!(
            unsafe {
                SetEntriesInAclW(
                    /*ccountofexplicitentries*/ 1,
                    &entry,
                    previous,
                    &mut updated,
                )
            },
            0
        );
        let _updated = LocalDescriptor(updated.cast());
        assert!(!updated.is_null());
        assert_eq!(
            unsafe {
                SetNamedSecurityInfoW(
                    crate::to_wide(Path::new(path)).as_mut_ptr(),
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    updated,
                    std::ptr::null_mut(),
                )
            },
            0
        );
    }
}

#[test]
fn actual_readv3_query_retains_same_plan_noninherited_handles_without_acl_repair() {
    let (_temporary, home, plan) = fixture();
    assert!(observe_filesystem_read_acl(&home, &plan).is_err());
    let (first, _) = plan
        .read_root_sids()
        .next()
        .unwrap_or_else(|| panic!("nonempty fixture cohort"));
    let first = PathBuf::from(first);
    let partial =
        crate::filesystem_capability_plan(&home, &first, std::slice::from_ref(&first), &[])
            .unwrap_or_else(|error| panic!("same registry, first-root-only declaration: {error}"));
    grant(&partial, read_role_descriptor::RX);
    assert!(observe_filesystem_read_acl(&home, &plan).is_err());
    grant(&plan, read_role_descriptor::RX);
    let mut proof = observe_filesystem_read_acl(&home, &plan)
        .unwrap_or_else(|error| panic!("actual same-root role readback: {error}"));
    assert_eq!(proof.roots.len(), plan.read_sids().count());
    for root in &proof.roots {
        let mut flags = 0;
        assert_ne!(
            unsafe {
                windows_sys::Win32::Foundation::GetHandleInformation(
                    root.file.as_raw_handle() as _,
                    &mut flags,
                )
            },
            0
        );
        assert_eq!(
            flags & windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT,
            0
        );
        assert_eq!(
            descriptor(&root.file).unwrap_or_else(|error| panic!("same held descriptor: {error}")),
            root.descriptor
        );
    }
    proof
        .revalidate(&home, &plan)
        .unwrap_or_else(|error| panic!("same-plan revalidation: {error}"));
}

#[test]
fn actual_read_role_extra_mutation_and_changed_descriptor_are_sticky_refusals() {
    let (_temporary, home, plan) = fixture();
    for extra in [0x2, 0x40, 0x40000, 0x80000] {
        grant(&plan, read_role_descriptor::RX | extra);
        assert!(observe_filesystem_read_acl(&home, &plan).is_err());
    }
    grant(&plan, read_role_descriptor::RX);
    let mut proof = observe_filesystem_read_acl(&home, &plan)
        .unwrap_or_else(|error| panic!("valid original role: {error}"));
    grant(&plan, read_role_descriptor::RX | 0x40);
    assert!(proof.revalidate(&home, &plan).is_err());
    grant(&plan, read_role_descriptor::RX);
    assert!(proof.revalidate(&home, &plan).is_err());
    observe_filesystem_read_acl(&home, &plan)
        .unwrap_or_else(|error| panic!("fresh observation; no old proof revival: {error}"));
}

#[test]
fn actual_read_role_different_plan_and_registry_change_never_rebind_an_old_proof() {
    let (_temporary, home, plan) = fixture();
    grant(&plan, read_role_descriptor::RX);
    let mut proof = observe_filesystem_read_acl(&home, &plan)
        .unwrap_or_else(|error| panic!("original role: {error}"));
    let mut other = plan.clone();
    other = other
        .with_network_route(Some("S-1-5-21-2-3-4-50".to_owned()))
        .unwrap_or_else(|error| panic!("distinct public declaration: {error}"));
    assert!(proof.revalidate(&home, &other).is_err());
    assert!(proof.revalidate(&home, &plan).is_err());
    let mut proof = observe_filesystem_read_acl(&home, &plan)
        .unwrap_or_else(|error| panic!("fresh original role: {error}"));
    let path = home.join("cap_sid.v3.json");
    let bytes =
        std::fs::read(&path).unwrap_or_else(|error| panic!("actual original registry: {error}"));
    std::fs::write(&path, b"invalid")
        .unwrap_or_else(|error| panic!("owned registry corruption control: {error}"));
    assert!(proof.revalidate(&home, &plan).is_err());
    std::fs::write(&path, bytes)
        .unwrap_or_else(|error| panic!("restore fixture bytes only: {error}"));
    assert!(proof.revalidate(&home, &plan).is_err());
}
