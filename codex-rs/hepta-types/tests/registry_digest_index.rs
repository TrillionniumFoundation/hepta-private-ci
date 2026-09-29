use codex_hepta_types::{
    ContractRegistryV1, Digest32, MAX_REGISTRY_ENTRIES_V1, RegistryDefinitionV1,
    RegistryKindV1, StableId,
};

fn definition(index: usize) -> RegistryDefinitionV1 {
    let (kind, identifier) = if index % 2 == 0 {
        (RegistryKindV1::Schema, format!("schema:indexed-{index}"))
    } else {
        (
            RegistryKindV1::Normalization,
            format!("normalization:indexed-{index}"),
        )
    };
    let id = StableId::new(identifier).expect("valid registry identifier");
    RegistryDefinitionV1::new(kind, id, 1, &format!("value={index}"))
        .expect("valid registry definition")
}

#[test]
fn digest_index_resolves_every_canonical_entry_at_capacity() {
    let definitions = (0..MAX_REGISTRY_ENTRIES_V1)
        .map(definition)
        .collect::<Vec<_>>();
    let expected = definitions
        .iter()
        .map(|entry| (entry.kind(), entry.digest(), entry.id().clone()))
        .collect::<Vec<_>>();
    let registry = ContractRegistryV1::new(definitions).expect("valid full registry");

    for (kind, digest, id) in expected {
        let resolved = registry
            .resolve_digest(kind, digest)
            .expect("digest index must resolve the canonical entry");
        assert_eq!(resolved.kind(), kind);
        assert_eq!(resolved.digest(), digest);
        assert_eq!(resolved.id(), &id);
    }

    assert_eq!(
        registry.resolve_digest(RegistryKindV1::Schema, Digest32::ZERO),
        None
    );
    assert_eq!(
        registry.resolve_digest(RegistryKindV1::Normalization, Digest32::ZERO),
        None
    );
}

#[test]
fn digest_index_keeps_kind_in_the_lookup_key() {
    let schema = definition(2);
    let digest = schema.digest();
    let registry = ContractRegistryV1::new(vec![schema]).expect("valid registry");

    assert!(
        registry
            .resolve_digest(RegistryKindV1::Schema, digest)
            .is_some()
    );
    assert_eq!(
        registry.resolve_digest(RegistryKindV1::Normalization, digest),
        None
    );
}
