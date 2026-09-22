use super::*;
use crate::IdProfileV1;
use crate::NumericProfileDefinitionV1;
use crate::NumericProfileV1;
use crate::validate_id;

fn id(value: &str, profile: IdProfileV1) -> StableId {
    validate_id(value, profile).unwrap_or_else(|error| panic!("valid registry id: {error}"))
}

fn definition(kind: RegistryKindV1, name: &str, version: u32, text: &str) -> RegistryDefinitionV1 {
    let profile = match kind {
        RegistryKindV1::Schema => IdProfileV1::Schema,
        RegistryKindV1::Normalization => IdProfileV1::Normalization,
    };
    RegistryDefinitionV1::new(kind, id(name, profile), version, text)
        .unwrap_or_else(|error| panic!("valid definition: {error}"))
}

#[test]
fn immutable_registry_resolves_exact_definition_and_numeric_profile() {
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
    let profile = NumericProfileDefinitionV1::canonical(NumericProfileV1::HnmfPpmTowardZero)
        .unwrap_or_else(|error| panic!("numeric profile fixture: {error}"));
    let normalization_digest = normalization.digest();
    let registry = ContractRegistryV1::new_with_numeric_profiles(
        vec![schema, normalization.clone()],
        vec![profile.clone()],
    )
    .unwrap_or_else(|error| panic!("registry fixture: {error}"));

    assert_eq!(
        registry.require_normalization(normalization_digest),
        Ok(&normalization)
    );
    assert_eq!(
        registry.require_numeric_profile(NumericProfileV1::HnmfPpmTowardZero),
        Ok(&profile)
    );
    assert!(
        !registry
            .registry_digest()
            .unwrap_or(Digest32::ZERO)
            .is_zero()
    );
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
    let p1 = NumericProfileDefinitionV1::canonical(NumericProfileV1::HnmfPpmTowardZero)
        .unwrap_or_else(|error| panic!("profile fixture: {error}"));
    let p2 = NumericProfileDefinitionV1::canonical(NumericProfileV1::SignedQ24NearestTiesEven)
        .unwrap_or_else(|error| panic!("profile fixture: {error}"));
    let first = ContractRegistryV1::new_with_numeric_profiles(
        vec![left.clone(), right.clone()],
        vec![p1.clone(), p2.clone()],
    )
    .unwrap_or_else(|error| panic!("first fixture: {error}"));
    let second = ContractRegistryV1::new_with_numeric_profiles(vec![right, left], vec![p2, p1])
        .unwrap_or_else(|error| panic!("second fixture: {error}"));
    assert_eq!(first.registry_digest(), second.registry_digest());

    let changed = definition(RegistryKindV1::Schema, "schema:a", 2, "field=a:u64");
    assert_ne!(changed.digest(), first.entries()[0].digest());
}

#[test]
fn definition_kind_is_bound_to_identifier_namespace() {
    let wrong = StableId::new("normalization:a")
        .unwrap_or_else(|error| panic!("stable id fixture: {error}"));
    assert_eq!(
        RegistryDefinitionV1::new(RegistryKindV1::Schema, wrong, 1, "x"),
        Err(RegistryError::Identity(IdentityError::NonCanonical))
    );
}

#[test]
fn registry_rejects_duplicate_identity_profile_version_capacity_and_aggregate_bytes() {
    assert_eq!(
        RegistryDefinitionV1::new(
            RegistryKindV1::Schema,
            id("schema:a", IdProfileV1::Schema),
            0,
            "definition",
        ),
        Err(RegistryError::InvalidVersion)
    );

    let entry = definition(RegistryKindV1::Schema, "schema:a", 1, "definition");
    assert_eq!(
        ContractRegistryV1::new(vec![entry.clone(), entry.clone()]),
        Err(RegistryError::DuplicateDefinition)
    );

    let profile = NumericProfileDefinitionV1::canonical(NumericProfileV1::HnmfPpmTowardZero)
        .unwrap_or_else(|error| panic!("profile fixture: {error}"));
    assert_eq!(
        ContractRegistryV1::new_with_numeric_profiles(Vec::new(), vec![profile.clone(), profile]),
        Err(RegistryError::DuplicateNumericProfile)
    );

    assert_eq!(
        ContractRegistryV1::new(vec![entry; MAX_REGISTRY_ENTRIES_V1 + 1]),
        Err(RegistryError::TooManyEntries)
    );

    let chunk = "x".repeat(MAX_REGISTRY_DEFINITION_BYTES_V1);
    let mut definitions = Vec::new();
    for index in 0..=MAX_REGISTRY_AGGREGATE_DEFINITION_BYTES_V1 / MAX_REGISTRY_DEFINITION_BYTES_V1 {
        definitions.push(definition(
            RegistryKindV1::Schema,
            &format!("schema:item-{index}"),
            1,
            &chunk,
        ));
    }
    assert_eq!(
        ContractRegistryV1::new(definitions),
        Err(RegistryError::TooMuchDefinitionData)
    );
}
