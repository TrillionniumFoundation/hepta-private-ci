use super::*;

fn definition(kind: RegistryKindV1, id: &str, body: &[u8]) -> RegistryDefinitionV1 {
    RegistryDefinitionV1::new(kind, id, "application/hepta+json", 1, body)
        .expect("registry definition")
}

#[test]
fn registry_resolves_digest_to_exact_stable_definition() {
    let schema = definition(
        RegistryKindV1::Schema,
        "schema:numeric-signal-v1",
        br#"{"rank":4,"row_major":true}"#,
    );
    let expected = schema.clone();
    let mut registry = SchemaNormalizationRegistryV1::new();
    let digest = registry.register(schema).expect("register schema");
    assert_eq!(
        registry
            .resolve(RegistryKindV1::Schema, digest)
            .expect("resolve schema"),
        &expected
    );
    assert_eq!(registry.register(expected), Ok(digest));
    assert_eq!(registry.len(), 1);
}

#[test]
fn registry_binds_kind_namespace_and_version() {
    assert_eq!(
        RegistryDefinitionV1::new(
            RegistryKindV1::Schema,
            "normalization:zscore-v1",
            "application/hepta+json",
            1,
            b"{}",
        ),
        Err(RegistryError::Identity(IdentityError::NamespaceMismatch))
    );
    assert_eq!(
        RegistryDefinitionV1::new(
            RegistryKindV1::Schema,
            "schema:test-v1",
            "application/hepta+json",
            0,
            b"{}",
        ),
        Err(RegistryError::ZeroSchemaVersion)
    );

    let normalization = definition(
        RegistryKindV1::Normalization,
        "normalization:zscore-v1",
        br#"{"mean":"0","stddev":"1"}"#,
    );
    let mut registry = SchemaNormalizationRegistryV1::new();
    let digest = registry
        .register(normalization)
        .expect("register normalization");
    assert_eq!(
        registry.resolve(RegistryKindV1::Schema, digest),
        Err(RegistryError::KindMismatch)
    );
    assert_eq!(
        registry.resolve(
            RegistryKindV1::Normalization,
            Digest32::of_bytes(b"missing")
        ),
        Err(RegistryError::UnknownDigest)
    );
}

#[test]
fn registry_capacity_is_bounded() {
    let mut registry = SchemaNormalizationRegistryV1::new();
    for index in 0..MAX_REGISTRY_ENTRIES_V1 {
        let id = format!("schema:item-{index}");
        let body = index.to_be_bytes();
        registry
            .register(definition(RegistryKindV1::Schema, &id, &body))
            .expect("entry within bound");
    }
    assert_eq!(registry.len(), MAX_REGISTRY_ENTRIES_V1);
    let overflow = definition(RegistryKindV1::Schema, "schema:overflow", b"overflow");
    assert_eq!(registry.register(overflow), Err(RegistryError::Capacity));
}
