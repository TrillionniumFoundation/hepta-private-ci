use super::*;

fn definition(kind: RegistryKindV1, id: &str, content: &[u8]) -> RegistryDefinitionV1 {
    RegistryDefinitionV1::new(kind, id, 1, Digest32::of_bytes(content)).expect("definition")
}

#[test]
fn registry_resolves_digest_to_stable_definition() {
    let schema = definition(RegistryKindV1::Schema, "schema:numeric-signal", b"schema-v1");
    let normalization = definition(
        RegistryKindV1::Normalization,
        "normalization:unit-scale",
        b"normalization-v1",
    );
    let schema_digest = schema.definition_digest;
    let schema_id = schema.id.clone();
    let registry = DefinitionRegistryV1::new(vec![schema.clone(), normalization]).expect("registry");
    assert_eq!(registry.resolve(schema_digest), Some(&schema));
    assert_eq!(registry.digest_for_id(&schema_id), Some(schema_digest));
    assert_eq!(registry.len(), 2);
}

#[test]
fn registry_rejects_namespace_zero_and_duplicates() {
    assert_eq!(
        RegistryDefinitionV1::new(
            RegistryKindV1::Schema,
            "receipt:not-a-schema",
            1,
            Digest32::of_bytes(b"x"),
        ),
        Err(RegistryErrorV1::InvalidId)
    );
    assert_eq!(
        RegistryDefinitionV1::new(
            RegistryKindV1::Schema,
            "schema:x",
            0,
            Digest32::of_bytes(b"x"),
        ),
        Err(RegistryErrorV1::ZeroVersion)
    );
    assert_eq!(
        RegistryDefinitionV1::new(RegistryKindV1::Schema, "schema:x", 1, Digest32::ZERO),
        Err(RegistryErrorV1::ZeroDigest)
    );

    let one = definition(RegistryKindV1::Schema, "schema:one", b"same");
    let same_digest = RegistryDefinitionV1::new(
        RegistryKindV1::Schema,
        "schema:two",
        1,
        one.definition_digest,
    )
    .expect("second");
    assert_eq!(
        DefinitionRegistryV1::new(vec![one, same_digest]),
        Err(RegistryErrorV1::DuplicateDigest)
    );
}
