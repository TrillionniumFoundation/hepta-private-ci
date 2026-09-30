use std::error::Error;
use std::io;

use codex_hepta_types::ContractRegistryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::MAX_REGISTRY_ENTRIES_V1;
use codex_hepta_types::RegistryDefinitionV1;
use codex_hepta_types::RegistryKindV1;
use codex_hepta_types::StableId;

fn definition(index: usize) -> Result<RegistryDefinitionV1, Box<dyn Error>> {
    let (kind, identifier) = if index.is_multiple_of(2) {
        (RegistryKindV1::Schema, format!("schema:indexed-{index}"))
    } else {
        (
            RegistryKindV1::Normalization,
            format!("normalization:indexed-{index}"),
        )
    };
    let id = StableId::new(identifier)?;
    Ok(RegistryDefinitionV1::new(
        kind,
        id,
        1,
        &format!("value={index}"),
    )?)
}

#[test]
fn digest_index_resolves_every_canonical_entry_at_capacity() -> Result<(), Box<dyn Error>> {
    let definitions = (0..MAX_REGISTRY_ENTRIES_V1)
        .map(definition)
        .collect::<Result<Vec<_>, _>>()?;
    let expected = definitions
        .iter()
        .map(|entry| (entry.kind(), entry.digest(), entry.id().clone()))
        .collect::<Vec<_>>();
    let registry = ContractRegistryV1::new(definitions)?;

    for (kind, digest, id) in expected {
        let resolved = registry.resolve_digest(kind, digest).ok_or_else(|| {
            io::Error::other(format!(
                "digest index did not resolve {kind:?} entry {digest:?}"
            ))
        })?;
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
    Ok(())
}

#[test]
fn digest_index_keeps_kind_in_the_lookup_key() -> Result<(), Box<dyn Error>> {
    let schema = definition(2)?;
    let digest = schema.digest();
    let registry = ContractRegistryV1::new(vec![schema])?;

    assert!(
        registry
            .resolve_digest(RegistryKindV1::Schema, digest)
            .is_some()
    );
    assert_eq!(
        registry.resolve_digest(RegistryKindV1::Normalization, digest),
        None
    );
    Ok(())
}
