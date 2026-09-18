use std::error::Error;

use super::*;

#[test]
fn selects_highest_common_version() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &[WireVersion::V1, WireVersion::V2],
        &[WireVersion::V1, WireVersion::V2],
        &[],
    )?;
    assert_eq!(negotiated.version(), WireVersion::V2);
    Ok(())
}

#[test]
fn metadata_binding_requirement_prevents_v1_downgrade() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &[WireVersion::V1, WireVersion::V2],
        &[WireVersion::V1, WireVersion::V2],
        &[WireCapability::MetadataBoundIntegrity],
    )?;
    assert_eq!(negotiated.version(), WireVersion::V2);

    assert_eq!(
        negotiate(
            &[WireVersion::V1, WireVersion::V2],
            &[WireVersion::V1],
            &[WireCapability::MetadataBoundIntegrity],
        ),
        Err(NegotiationError::NoCompatibleVersion)
    );
    Ok(())
}

#[test]
fn transcript_binding_is_order_stable_and_role_sensitive() -> Result<(), Box<dyn Error>> {
    let first = negotiate(
        &[WireVersion::V2, WireVersion::V1, WireVersion::V2],
        &[WireVersion::V1, WireVersion::V2],
        &[WireCapability::MetadataBoundIntegrity],
    )?;
    let reordered = negotiate(
        &[WireVersion::V1, WireVersion::V2],
        &[WireVersion::V2, WireVersion::V1, WireVersion::V1],
        &[WireCapability::MetadataBoundIntegrity],
    )?;
    assert_eq!(first.binding_digest(), reordered.binding_digest());

    let reversed_roles = negotiate(
        &[WireVersion::V1, WireVersion::V2],
        &[WireVersion::V2],
        &[WireCapability::MetadataBoundIntegrity],
    )?;
    let original_roles = negotiate(
        &[WireVersion::V2],
        &[WireVersion::V1, WireVersion::V2],
        &[WireCapability::MetadataBoundIntegrity],
    )?;
    assert_ne!(
        reversed_roles.binding_digest(),
        original_roles.binding_digest()
    );
    Ok(())
}
