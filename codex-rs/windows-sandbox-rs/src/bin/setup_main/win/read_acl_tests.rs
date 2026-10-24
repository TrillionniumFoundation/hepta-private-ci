use super::*;
use codex_windows_sandbox::add_deny_write_ace;
use codex_windows_sandbox::ensure_allow_mask_aces;
use codex_windows_sandbox::filesystem_capability_plan;
use pretty_assertions::assert_eq;

fn subjects(plan: &FilesystemCapabilityPlan) -> ReadAclSubjects {
    ReadAclSubjects {
        // Explicit broad normal-side fixture; this never replaces a restrictive SID.
        normal_identity: LocalSid::from_string("S-1-1-0").unwrap(),
        ambient_rx: [
            LocalSid::from_string("S-1-5-32-545").unwrap(),
            LocalSid::from_string("S-1-5-11").unwrap(),
            LocalSid::from_string("S-1-1-0").unwrap(),
        ],
        restrictive_rx: plan
            .capability_sids(FilesystemCapabilityRole::Read)
            .into_iter()
            .map(|sid| LocalSid::from_string(sid).unwrap())
            .collect(),
    }
}

fn acl_bytes(file: &File) -> Vec<u8> {
    let (_descriptor, dacl) = descriptor(file).unwrap();
    let mut information: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
    assert_ne!(
        unsafe {
            GetAclInformation(
                dacl,
                &mut information as *mut _ as _,
                size_of::<ACL_SIZE_INFORMATION>() as _,
                AclSizeInformation,
            )
        },
        0
    );
    assert!(information.AclBytesInUse <= u16::MAX.into());
    // SAFETY: initialized bytes in this held descriptor's actual ACL.
    unsafe { std::slice::from_raw_parts(dacl.cast::<u8>(), information.AclBytesInUse as usize) }
        .to_vec()
}

#[test]
fn broad_normal_rx_cannot_skip_same_plan_restrictive_readback() {
    let fixture = tempfile::tempdir().unwrap();
    let home = fixture.path().join("home");
    let root = fixture.path().join("runtime");
    std::fs::create_dir(&root).unwrap();
    let root = dunce::canonicalize(root).unwrap();
    let plan = filesystem_capability_plan(&home, &root, std::slice::from_ref(&root), &[]).unwrap();
    let normal = LocalSid::from_string("S-1-1-0").unwrap();
    // SAFETY: mutate only this fresh owned fixture; retain the broad-identity control.
    unsafe { ensure_allow_mask_aces(&root, &[normal.as_ptr()], FILE_ALL_ACCESS) }.unwrap();
    let held = open_root(&root, QUERY).unwrap();
    assert_eq!(
        readback(&held, &subjects(&plan)).unwrap(),
        (true, vec![false])
    );
    let mut log = Vec::new();
    let prepared = prepare_roots(
        plan.clone(),
        std::slice::from_ref(&root),
        subjects(&plan),
        &mut log,
    )
    .unwrap();
    assert_eq!((&prepared._plan, prepared._held_roots.len()), (&plan, 1));
    for root in &prepared._held_roots {
        let mut flags = 0;
        assert_ne!(
            unsafe {
                windows_sys::Win32::Foundation::GetHandleInformation(
                    root.as_raw_handle() as _,
                    &mut flags,
                )
            },
            0
        );
        assert_eq!(
            flags & windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT,
            0
        );
    }
    assert_eq!(
        readback(&held, &subjects(&plan)).unwrap(),
        (true, vec![true])
    );
    // A competing request does not mistake a live mutex for this plan's completion.
    assert!(
        prepare_roots(
            plan.clone(),
            std::slice::from_ref(&root),
            subjects(&plan),
            &mut log
        )
        .is_err()
    );
    let observed = acl_bytes(&held);
    drop(prepared);
    let repeated = prepare_roots(
        plan.clone(),
        std::slice::from_ref(&root),
        subjects(&plan),
        &mut log,
    )
    .unwrap();
    assert_eq!(acl_bytes(&held), observed);
    drop(repeated);
    // Generic write-deny overlaps SYNCHRONIZE. A matching RX allow must not mask it.
    let identities = subjects(&plan);
    unsafe { add_deny_write_ace(&root, identities.restrictive_rx[0].as_ptr()) }.unwrap();
    assert!(readback(&held, &subjects(&plan)).is_err());
    let denied = acl_bytes(&held);
    let identities = subjects(&plan);
    assert!(prepare_roots(plan, std::slice::from_ref(&root), identities, &mut log).is_err());
    assert_eq!(acl_bytes(&held), denied);
}
