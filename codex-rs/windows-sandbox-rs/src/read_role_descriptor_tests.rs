use super::RX;
use super::RootKind;
use super::validate;

const OWNER: &[u8] = &[1, 2, 0, 0, 0, 0, 0, 5, 21, 0, 0, 0, 1, 0, 0, 0];
const ROLE: &[u8] = &[1, 2, 0, 0, 0, 0, 0, 5, 21, 0, 0, 0, 2, 0, 0, 0];
const OTHER: &[u8] = &[1, 2, 0, 0, 0, 0, 0, 5, 21, 0, 0, 0, 3, 0, 0, 0];

fn descriptor(owner: &[u8], entries: &[(&[u8], u32, u8, u8)]) -> Vec<u8> {
    let mut bytes = vec![1, 0, 4, 128];
    bytes.extend_from_slice(&20_u32.to_le_bytes());
    bytes.extend_from_slice(&[0; 8]);
    bytes.extend_from_slice(&((20 + owner.len()) as u32).to_le_bytes());
    bytes.extend_from_slice(owner);
    let length = 8 + entries
        .iter()
        .map(|(sid, _, _, _)| sid.len() + 8)
        .sum::<usize>();
    bytes.extend_from_slice(&[2, 0]);
    bytes.extend_from_slice(&(length as u16).to_le_bytes());
    bytes.extend_from_slice(&(entries.len() as u16).to_le_bytes());
    bytes.extend_from_slice(&[0; 2]);
    for (sid, mask, flags, kind) in entries {
        bytes.extend_from_slice(&[*kind, *flags]);
        bytes.extend_from_slice(&((sid.len() + 8) as u16).to_le_bytes());
        bytes.extend_from_slice(&mask.to_le_bytes());
        bytes.extend_from_slice(sid);
    }
    bytes
}

#[test]
fn exact_rx_requires_same_root_role_and_recursive_directory_scope() {
    let directory = descriptor(OWNER, &[(ROLE, RX, 3, 0)]);
    validate(&directory, ROLE, &[OTHER.to_vec()], RootKind::Directory)
        .unwrap_or_else(|error| panic!("same-root recursive RX: {error}"));
    validate(
        &descriptor(OWNER, &[(ROLE, RX, 0, 0)]),
        ROLE,
        &[],
        RootKind::File,
    )
    .unwrap_or_else(|error| panic!("same-root file RX: {error}"));
    for flags in [0, 1, 2, 8, 11, 19] {
        assert!(
            validate(
                &descriptor(OWNER, &[(ROLE, RX, flags, 0)]),
                ROLE,
                &[],
                RootKind::Directory
            )
            .is_err()
        );
    }
    for mask in [RX & !1, RX & !0x20, 0] {
        assert!(
            validate(
                &descriptor(OWNER, &[(ROLE, mask, 3, 0)]),
                ROLE,
                &[],
                RootKind::Directory
            )
            .is_err()
        );
    }
    assert!(validate(&directory, OTHER, &[ROLE.to_vec()], RootKind::Directory).is_err());
    let cross_root = descriptor(OWNER, &[(ROLE, RX, 3, 0), (OTHER, RX, 3, 0)]);
    assert!(validate(&cross_root, ROLE, &[OTHER.to_vec()], RootKind::Directory).is_err());
}

#[test]
fn read_role_never_grants_mutation_even_through_inherit_only() {
    for extra in [
        0x2,
        0x4,
        0x10,
        0x40,
        0x100,
        0x10000,
        0x40000,
        0x80000,
        0x1000_0000,
        0x4000_0000,
        0x0200_0000,
        0x0100_0000,
    ] {
        for flags in [0, 3, 8, 11] {
            let bytes = descriptor(OWNER, &[(ROLE, RX, 3, 0), (ROLE, RX | extra, flags, 0)]);
            assert!(validate(&bytes, ROLE, &[], RootKind::Directory).is_err());
        }
    }
}

#[test]
fn descriptor_truncation_owner_deny_and_unknown_forms_cannot_supply_a_proof() {
    let complete = descriptor(OWNER, &[(ROLE, RX, 3, 0)]);
    for length in 0..complete.len() {
        assert!(validate(&complete[..length], ROLE, &[], RootKind::Directory).is_err());
    }
    assert!(
        validate(
            &descriptor(ROLE, &[(ROLE, RX, 3, 0)]),
            ROLE,
            &[],
            RootKind::Directory
        )
        .is_err()
    );
    for kind in [1, 2, 5, 9, 17] {
        let bytes = descriptor(OWNER, &[(ROLE, RX, 3, 0), (OWNER, RX, 0, kind)]);
        assert!(validate(&bytes, ROLE, &[], RootKind::Directory).is_err());
    }
    let mut excessive = complete.clone();
    excessive.resize(65_537, 0);
    assert!(validate(&excessive, ROLE, &[], RootKind::Directory).is_err());
    let mut excessive = complete;
    let acl = 20 + OWNER.len();
    excessive[acl + 4..acl + 6].copy_from_slice(&1025_u16.to_le_bytes());
    assert!(validate(&excessive, ROLE, &[], RootKind::Directory).is_err());
}
