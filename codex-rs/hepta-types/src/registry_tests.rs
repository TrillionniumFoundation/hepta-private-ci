use super::*;
use crate::IdProfileV1;
use crate::validate_id;

fn id(value: &str) -> StableId {
    validate_id(value, IdProfileV1::Namespaced)
        .unwrap_or_else(|error| panic!("valid registry id: {error}"))
}

fn definition(
    kind: RegistryKindV1,
    name: &str,
    version: u32,
    text: &str,
) -> RegistryDefinitionV1 {
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
    let registry =
        ContractRegistryV1::new(vec![schema, normalization.clone()]).expect("registry");
    let resolved = registry
        .normalization_definition(normalization_digest)
        .expect("normalization by digest");
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
    assert!(!registry.registry_digest().expect("registry digest").is_zero());
}

#[test]
fn registry_digest_is_insertion_order_independent_and_definition_sensitive() {
    let left = definition(
        RegistryKindV1::Schema,
        "schema:a",
        1,
        "field=a:u64",
    );
    let right = definition(
        RegistryKindV1::Normalization,
        "normalization:b",
        1,
        "identity",
    );
    let first =
        ContractRegistryV1::new(vec![left.clone(), right.clone()]).expect("first registry");
    let second = ContractRegistryV1::new(vec![right, left]).expect("second registry");
    assert_eq!(first.registry_digest(), second.registry_digest());

    let changed = definition(
        RegistryKindV1::Schema,
        "schema:a",
        2,
        "field=a:u64",
    );
    assert_ne!(changed.digest(), first.entries()[0].digest());
}

#[test]
fn registry_rejects_duplicate_identity_invalid_version_and_capacity() {
    assert_eq!(
        RegistryDefinitionV1::new(
            RegistryKindV1::Schema,
            id("schema:a"),
            0,
            "definition"
        ),
        Err(RegistryError::InvalidVersion)
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
