use super::*;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    checked(validate_id(value, IdProfileV1::Stable))
}

#[test]
fn registry_resolves_digest_to_stable_definition() {
    let normalization = checked(ContractDefinitionV1::new(
        ContractDefinitionKindV1::Normalization,
        id("normalization:unit-range-v1"),
        1,
        b"offset=0;scale=1;range=closed",
    ));
    let digest = normalization.digest();
    let registry = checked(ContractRegistryV1::new(vec![normalization.clone()]));
    let resolved = registry.require(ContractDefinitionKindV1::Normalization, digest);
    let Ok(resolved) = resolved else {
        panic!("registered normalization digest did not resolve");
    };
    assert_eq!(resolved, &normalization);
    assert_eq!(resolved.body(), b"offset=0;scale=1;range=closed");

    let v2 = checked(ContractDefinitionV1::new(
        ContractDefinitionKindV1::Normalization,
        id("normalization:unit-range-v1"),
        2,
        b"offset=0;scale=1;range=closed",
    ));
    assert_ne!(normalization.digest(), v2.digest());
}

#[test]
fn registry_rejects_duplicate_identity_and_wrong_kind() {
    let definition = checked(ContractDefinitionV1::new(
        ContractDefinitionKindV1::Normalization,
        id("normalization:duplicate-v1"),
        1,
        b"stable",
    ));
    assert_eq!(
        ContractRegistryV1::new(vec![definition.clone(), definition.clone()]),
        Err(ContractRegistryError::DuplicateIdentity)
    );

    let registry = checked(ContractRegistryV1::new(vec![definition.clone()]));
    assert_eq!(
        registry.require(ContractDefinitionKindV1::Schema, definition.digest()),
        Err(ContractRegistryError::WrongKind)
    );
    assert_eq!(
        registry.require(
            ContractDefinitionKindV1::Normalization,
            Digest32::of_bytes(b"unknown")
        ),
        Err(ContractRegistryError::UnknownDigest)
    );
}

#[test]
fn definition_body_and_registry_total_are_bounded() {
    let oversized = vec![0_u8; MAX_DEFINITION_BYTES_V1 + 1];
    assert_eq!(
        ContractDefinitionV1::new(
            ContractDefinitionKindV1::Schema,
            id("schema:oversized-v1"),
            1,
            &oversized,
        ),
        Err(ContractRegistryError::Body(BoundedValueError::TooLarge {
            actual: MAX_DEFINITION_BYTES_V1 + 1,
            maximum: MAX_DEFINITION_BYTES_V1,
        }))
    );
    assert_eq!(
        ContractDefinitionV1::new(
            ContractDefinitionKindV1::Schema,
            id("schema:zero-version"),
            0,
            b"x",
        ),
        Err(ContractRegistryError::ZeroVersion)
    );
}
