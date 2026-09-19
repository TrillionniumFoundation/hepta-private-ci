use super::*;
use crate::IdProfileV1;
use crate::validate_id;

fn id(value: &str) -> StableId {
    validate_id(value, IdProfileV1::Namespaced)
        .unwrap_or_else(|error| panic!("valid registry id: {error}"))
}

fn definition(kind: RegistryKindV1, name: &str, version: u32, text: &str) -> RegistryDefinitionV1 {
    RegistryDefinitionV1::new(kind, id(name), version, text)
        .unwrap_or_else(|error| panic!("valid definition: {error}"))
}

#[test]
fn immutable_registry_resolves_digest_to_exact_definition() {
    let normalization = definition(
        RegistryKindV1::Normalization,
        "normalization:unit-range",
        1,
        "clamp=none;scale=identity;range=-1..1",
    );
    let schema = definition(
        RegistryKindV1::Schema,
        "schema:numeric-signal",
        1,
        "row-major;i64;rank<=4;elements<=4096",
    );
    let normalization_digest = normalization.digest();
    let registry = ContractRegistryV1::new(vec![schema, normalization.clone()]);
    let Ok(registry) = registry else {
        panic!("registry fixture should be valid");
    };
    let resolved = registry.normalization_definition(normalization_digest);
    let Some(resolved) = resolved else {
        panic!("normalization digest should resolve");
    };
    assert_eq!(resolved, &normalization);
    assert_eq!(
        registry
            .resolve(
                RegistryKindV1::Normalization,
                normalization.id(),
                normalization.version()
            )
            .map(RegistryDefinitionV1::digest),
        Some(normalization_digest)
    );
    let registry_digest = registry.registry_digest();
    let Ok(registry_digest) = registry_digest else {
        panic!("valid registry should have a canonical digest");
    };
    assert!(!registry_digest.is_zero());
}

#[test]
fn registry_digest_is_insertion_order_independent_and_definition_sensitive() {
    let left = definition(RegistryKindV1::Schema, "schema:a", 1, "field=a:u64");
    let right = definition(
        RegistryKindV1::Normalization,
        "normalization:b",
        1,
        "identity",
    );
    let first = ContractRegistryV1::new(vec![left.clone(), right.clone()]);
    let Ok(first) = first else {
        panic!("first registry fixture should be valid");
    };
    let second = ContractRegistryV1::new(vec![right, left]);
    let Ok(second) = second else {
        panic!("second registry fixture should be valid");
    };
    assert_eq!(first.registry_digest(), second.registry_digest());

    let changed = definition(RegistryKindV1::Schema, "schema:a", 2, "field=a:u64");
    assert_ne!(changed.digest(), first.entries()[0].digest());
}

#[test]
fn registry_rejects_duplicate_identity_invalid_version_and_capacity() {
    assert_eq!(
        RegistryDefinitionV1::new(RegistryKindV1::Schema, id("schema:a"), 0, "definition"),
        Err(RegistryError::InvalidVersion)
    );

    let legacy_id = StableId::new("schema");
    let Ok(legacy_id) = legacy_id else {
        panic!("legacy stable ID fixture should be valid");
    };
    assert_eq!(
        RegistryDefinitionV1::new(RegistryKindV1::Schema, legacy_id, 1, "definition"),
        Err(RegistryError::Identity(IdentityError::NonCanonical))
    );

    let entry = definition(RegistryKindV1::Schema, "schema:a", 1, "definition");
    assert_eq!(
        ContractRegistryV1::new(vec![entry.clone(), entry.clone()]),
        Err(RegistryError::DuplicateDefinition)
    );
    assert_eq!(
        ContractRegistryV1::new(vec![entry; MAX_REGISTRY_ENTRIES_V1 + 1]),
        Err(RegistryError::TooManyEntries)
    );
}
