use super::ManagedTokenSnapshot;
use super::sid;
use pretty_assertions::assert_eq;

fn source() -> (Vec<u8>, Vec<u8>) {
    (
        sid(/*authority*/ 5, &[21, 10, 20, 30, 1001]),
        sid(/*authority*/ 5, &[21, 10, 20, 30, 1002]),
    )
}

fn ordinary() -> ManagedTokenSnapshot {
    let (user, managed_group) = source();
    ManagedTokenSnapshot {
        version: [10, 0, 42, 0, 11, 0],
        user,
        groups: vec![
            (sid(/*authority*/ 5, &[32, 545]), 7),
            (managed_group, 7),
            (sid(/*authority*/ 5, &[5, 0, 42]), 0xC000_0007),
            (sid(/*authority*/ 16, &[8192]), 0x60),
        ],
        privileges: vec![
            ("SeChangeNotifyPrivilege".into(), 3),
            ("SeShutdownPrivilege".into(), 0),
        ],
        default_dacl: Some(vec![2, 0, 8, 0, 0, 0, 0, 0]),
        primary: 1,
        filtered: 0,
        app_container: 0,
        elevated: 0,
        elevation_type: 1,
        restricting_count: 0,
    }
}

#[test]
fn accepts_bounded_ordinary_readback_without_creating_a_credential() {
    let (user, group) = source();
    assert_eq!(ordinary().validate(&user, &group).is_ok(), true);
}

#[test]
fn refuses_arbitrary_user_and_managed_group_substitution() {
    let (user, group) = source();
    assert!(ordinary().validate(&group, &user).is_err());
    assert!(
        ordinary()
            .validate(&user, &sid(/*authority*/ 5, &[21, 10, 20, 30, 1003]))
            .is_err()
    );
}

#[test]
fn refuses_filtered_elevated_impersonation_appcontainer_and_limiting_tokens() {
    let (user, group) = source();
    for field in 0..6 {
        let mut actual = ordinary();
        match field {
            0 => actual.primary = 2,
            1 => actual.filtered = 1,
            2 => actual.app_container = 1,
            3 => actual.elevated = 1,
            4 => actual.elevation_type = 3,
            5 => actual.restricting_count = 1,
            _ => unreachable!(),
        }
        assert!(actual.validate(&user, &group).is_err());
    }
}

#[test]
fn refuses_admin_deny_only_service_foreign_and_nearby_group_sids() {
    let (user, group) = source();
    for bad in [
        sid(/*authority*/ 5, &[32, 544]),
        sid(/*authority*/ 5, &[32, 547]),
        sid(/*authority*/ 5, &[80, 123]),
        sid(/*authority*/ 5, &[21, 10, 20, 30, 1003]),
        sid(/*authority*/ 16, &[12288]),
    ] {
        for attributes in [7, 0x10] {
            let mut actual = ordinary();
            actual.groups.push((bad.clone(), attributes));
            assert!(actual.validate(&user, &group).is_err());
        }
    }
}

#[test]
fn refuses_logon_cohort_for_another_authentication_and_duplicate_or_missing_groups() {
    let (user, group) = source();
    let mut actual = ordinary();
    actual.version[2] += 1;
    assert!(actual.validate(&user, &group).is_err());
    let mut actual = ordinary();
    actual.groups.push((group.clone(), 7));
    assert!(actual.validate(&user, &group).is_err());
    let mut actual = ordinary();
    actual.groups[2].1 = 0x8000_0007;
    assert!(actual.validate(&user, &group).is_err());
    for index in 0..3 {
        let mut actual = ordinary();
        actual.groups.remove(index);
        assert!(actual.validate(&user, &group).is_err());
    }
}

#[test]
fn refuses_unbounded_groups_privileges_and_absent_default_dacl() {
    let (user, group) = source();
    let mut actual = ordinary();
    actual.groups.resize(129, (sid(/*authority*/ 1, &[0]), 7));
    assert!(actual.validate(&user, &group).is_err());
    let mut actual = ordinary();
    actual
        .privileges
        .resize(6, ("SeChangeNotifyPrivilege".into(), 3));
    assert!(actual.validate(&user, &group).is_err());
    for dacl in [None, Some(vec![0; 7]), Some(vec![0; 65_537])] {
        let mut actual = ordinary();
        actual.default_dacl = dacl;
        assert!(actual.validate(&user, &group).is_err());
    }
}

#[test]
fn refuses_extra_and_enabled_nonordinary_privileges() {
    let (user, group) = source();
    for (name, attributes) in [
        ("SeDebugPrivilege", 0),
        ("SeBackupPrivilege", 2),
        ("SeShutdownPrivilege", 2),
        ("SeChangeNotifyPrivilege", 0x40),
    ] {
        let mut actual = ordinary();
        actual.privileges = vec![(name.into(), attributes)];
        assert!(actual.validate(&user, &group).is_err());
    }
}

#[test]
fn instance_modifiedid_dacl_and_group_changes_are_not_continuous_readback() {
    let (user, group) = source();
    for field in 0..4 {
        let original = ordinary();
        let mut changed = ordinary();
        match field {
            0 => changed.version[0] += 1,
            1 => changed.version[4] += 1,
            2 => changed.default_dacl.as_mut().unwrap().push(0),
            3 => changed.groups[0].1 = 0,
            _ => unreachable!(),
        }
        assert!(
            changed
                .validate_continuity(&original, &user, &group)
                .is_err()
        );
    }
}
