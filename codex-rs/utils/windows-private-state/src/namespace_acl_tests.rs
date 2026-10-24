use super::TRUSTED_INSTALLER_SID;
use super::validate;
use crate::security::CurrentUser;
use crate::security::ValidationError;

const WORLD: &[u8] = &[1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0];

fn descriptor(user: &CurrentUser, mask: u32, flags: u8) -> Vec<u8> {
    descriptor_for_owner_and_trustee(user.sid_bytes(), WORLD, mask, flags)
}

fn descriptor_for_owner_and_trustee(owner: &[u8], trustee: &[u8], mask: u32, flags: u8) -> Vec<u8> {
    // Parser-only controls: these bytes never construct a namespace capability.
    let mut bytes = vec![0; 20];
    bytes[0] = 1;
    bytes[2..4].copy_from_slice(&0x9004_u16.to_le_bytes());
    bytes[4..8].copy_from_slice(&20_u32.to_le_bytes());
    bytes.extend_from_slice(owner);
    let offset = bytes.len();
    bytes[16..20].copy_from_slice(&(offset as u32).to_le_bytes());
    let acl_bytes = 8 + 8 + owner.len() + 8 + trustee.len();
    bytes.extend_from_slice(&[2, 0]);
    bytes.extend_from_slice(&(acl_bytes as u16).to_le_bytes());
    bytes.extend_from_slice(&[2, 0, 0, 0]);
    for (trustee, access, ace_flags) in [(owner, 0x001f_01ff, 0), (trustee, mask, flags)] {
        bytes.extend_from_slice(&[0, ace_flags]);
        bytes.extend_from_slice(&((trustee.len() + 8) as u16).to_le_bytes());
        bytes.extend_from_slice(&access.to_le_bytes());
        bytes.extend_from_slice(trustee);
    }
    bytes
}

#[test]
fn ancestor_parser_distinguishes_new_sibling_creation_from_existing_mutation() {
    let user = CurrentUser::capture_effective().expect("actual user for parser controls");
    validate(&descriptor(&user, /*mask*/ 0x0012_00ad, /*flags*/ 0), &user)
        .expect("read/traverse plus only ADD_SUBDIRECTORY on the ancestor");
    for mask in [
        0x2,
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
        assert!(
            matches!(
                validate(&descriptor(&user, mask, /*flags*/ 0), &user),
                Err(ValidationError::NonCanonicalDacl)
            ),
            "untrusted mask {mask:#x}"
        );
    }
}

#[test]
fn inherited_effective_mutator_is_not_treated_as_inherit_only() {
    let user = CurrentUser::capture_effective().expect("actual user");
    validate(&descriptor(&user, /*mask*/ 0x1000_0000, /*flags*/ 8), &user).expect(
        "inherit-only does not apply to this ancestor; private creation must block inheritance",
    );
    for flags in [0, 0x10] {
        assert!(matches!(
            validate(&descriptor(&user, /*mask*/ 0x40, flags), &user),
            Err(ValidationError::NonCanonicalDacl)
        ));
    }
}

#[test]
fn unknown_owner_and_ace_forms_do_not_grant_namespace_admission() {
    let user = CurrentUser::capture_effective().expect("actual user");
    let mut bytes = descriptor(&user, /*mask*/ 1, /*flags*/ 0);
    // Point owner to the actual WORLD SID inside the final ACE.
    let world = bytes.len() - WORLD.len();
    bytes[4..8].copy_from_slice(&(world as u32).to_le_bytes());
    assert!(matches!(
        validate(&bytes, &user),
        Err(ValidationError::WrongOwner)
    ));
    let mut bytes = descriptor(&user, /*mask*/ 1, /*flags*/ 0);
    let last_ace = bytes.len() - WORLD.len() - 8;
    bytes[last_ace] = 5;
    assert!(matches!(
        validate(&bytes, &user),
        Err(ValidationError::NonCanonicalDacl)
    ));
}

#[test]
fn missing_truncated_and_unbounded_acl_are_refused() {
    let user = CurrentUser::capture_effective().expect("actual user");
    let mut missing = descriptor(&user, /*mask*/ 1, /*flags*/ 0);
    missing[16..20].fill(0);
    assert!(validate(&missing, &user).is_err());
    let mut truncated = descriptor(&user, /*mask*/ 1, /*flags*/ 0);
    truncated.pop();
    assert!(validate(&truncated, &user).is_err());
    let mut count = descriptor(&user, /*mask*/ 1, /*flags*/ 0);
    let acl = 20 + user.sid_bytes().len();
    count[acl + 4..acl + 6].copy_from_slice(&257_u16.to_le_bytes());
    assert!(validate(&count, &user).is_err());
}

#[test]
fn exact_trustedinstaller_owner_and_maintenance_ace_are_namespace_only() {
    let user = CurrentUser::capture_effective().expect("actual user for namespace parser controls");
    let owned = descriptor_for_owner_and_trustee(
        TRUSTED_INSTALLER_SID,
        WORLD,
        /*mask*/ 0x0012_00ad,
        /*flags*/ 0,
    );
    validate(&owned, &user).expect("exact OS-maintained namespace owner");
    let maintenance = descriptor_for_owner_and_trustee(
        user.sid_bytes(),
        TRUSTED_INSTALLER_SID,
        /*mask*/ 0x001f_01ff,
        /*flags*/ 0,
    );
    validate(&maintenance, &user).expect("exact OS-maintained namespace maintenance trustee");
}

#[test]
fn nearby_service_sids_never_gain_namespace_owner_or_mutator_trust() {
    let user = CurrentUser::capture_effective().expect("actual user for namespace parser controls");
    // Keep the service authority and S-1-5-80 prefix: every hash-bit neighbor
    // must be refused both as owner and as an effective mutating trustee.
    for index in 12..TRUSTED_INSTALLER_SID.len() {
        for bit in 0..8 {
            let mut foreign = TRUSTED_INSTALLER_SID.to_vec();
            foreign[index] ^= 1 << bit;
            let owner = descriptor_for_owner_and_trustee(
                &foreign, WORLD, /*mask*/ 1, /*flags*/ 0,
            );
            assert!(matches!(
                validate(&owner, &user),
                Err(ValidationError::WrongOwner)
            ));
            let trustee = descriptor_for_owner_and_trustee(
                user.sid_bytes(),
                &foreign,
                /*mask*/ 0x001f_01ff,
                /*flags*/ 0,
            );
            assert!(matches!(
                validate(&trustee, &user),
                Err(ValidationError::NonCanonicalDacl)
            ));
        }
    }
}

#[test]
fn trustedinstaller_owned_namespace_keeps_foreign_mutation_and_shape_refusals() {
    let user = CurrentUser::capture_effective().expect("actual user for namespace parser controls");
    for mask in [
        0x2,
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
        let bytes =
            descriptor_for_owner_and_trustee(TRUSTED_INSTALLER_SID, WORLD, mask, /*flags*/ 0);
        assert!(matches!(
            validate(&bytes, &user),
            Err(ValidationError::NonCanonicalDacl)
        ));
    }
    let valid = descriptor_for_owner_and_trustee(
        TRUSTED_INSTALLER_SID,
        WORLD,
        /*mask*/ 1,
        /*flags*/ 0,
    );
    for length in 0..valid.len() {
        assert!(validate(&valid[..length], &user).is_err());
    }
    for ace_type in [2, 5, 9, 17] {
        let mut bytes = valid.clone();
        let final_ace = bytes.len() - WORLD.len() - 8;
        bytes[final_ace] = ace_type;
        assert!(matches!(
            validate(&bytes, &user),
            Err(ValidationError::NonCanonicalDacl)
        ));
    }
}
