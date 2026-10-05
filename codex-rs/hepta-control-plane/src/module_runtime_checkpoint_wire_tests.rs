use pretty_assertions::assert_eq;

use super::*;

#[test]
fn historical_digest_preimages_restore_and_reencode_exactly() {
    for (bytes, root) in [
        (
            include_bytes!("../fixtures/pr1303_active_v1.bin").as_slice(),
            "7073412f34fdb5cddb411a18106d59cfaba9bf838c78612fc9020c98cf1434d8",
        ),
        (
            include_bytes!("../fixtures/pr1303_retired_fence_v1.bin").as_slice(),
            "72aecba88ce8c7d03f0f85e189918cd26b0246a402598c1874f35a2de17bd63e",
        ),
    ] {
        // Roots are frozen independently from the decoder under test.
        let restored =
            RuntimeModuleRegistryV1::restore_checkpoint_bytes(bytes, root.parse().unwrap())
                .unwrap();
        assert_eq!(restored.checkpoint_bytes(), bytes);
    }
    let bytes = include_bytes!("../fixtures/pr1303_active_v1.bin");
    let root = "7073412f34fdb5cddb411a18106d59cfaba9bf838c78612fc9020c98cf1434d8"
        .parse()
        .unwrap();
    let mut restored = RuntimeModuleRegistryV1::restore_checkpoint_bytes(bytes, root).unwrap();
    assert_eq!(
        restored.active_generation(&id("feature.persisted")),
        Some(generation(2))
    );
    restored
        .rollback_active_to_predecessor_content(
            &id("feature.persisted"),
            generation(2),
            generation(3),
            digest("rollback"),
        )
        .unwrap();
    assert_eq!(
        restored.active_generation(&id("feature.persisted")),
        Some(generation(3))
    );
    restored
        .register_candidate(abi(
            "compact-trigger",
            /*value*/ 1,
            /*previous*/ None,
        ))
        .unwrap();
    let old = abi(
        "feature.persisted",
        /*value*/ 1,
        /*previous*/ None,
    );
    assert_eq!(
        restored.register_candidate(old),
        Err(Error::InvalidGeneration)
    );
}

#[test]
fn decoder_rejects_every_truncation_and_tamper_under_fixed_root() {
    let registry = active();
    let bytes = registry.checkpoint_bytes();
    let root = registry.checkpoint().checkpoint_digest;
    for end in 0..bytes.len() {
        assert!(RuntimeModuleRegistryV1::restore_checkpoint_bytes(&bytes[..end], root).is_err());
    }
    for index in 0..bytes.len() {
        let mut changed = bytes.clone();
        changed[index] ^= 1;
        assert!(RuntimeModuleRegistryV1::restore_checkpoint_bytes(&changed, root).is_err());
    }
    let mut extra = bytes.clone();
    extra.push(0);
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint_bytes(&extra, root).unwrap_err(),
        Error::CheckpointEncoding
    );
    let oversized = vec![0; MAX_RUNTIME_MODULE_CHECKPOINT_BYTES + 1];
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint_bytes(&oversized, root).unwrap_err(),
        Error::Bounds
    );
    let mut count = bytes;
    let offset = b"hepta.runtime-module-registry-checkpoint.v1\0".len();
    count[offset..offset + 8].copy_from_slice(&u64::MAX.to_be_bytes());
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint_bytes(&count, root).unwrap_err(),
        Error::Bounds
    );
}

#[test]
fn rehashed_wire_rejects_unknown_version_tags_and_trailing_fields() {
    let bytes = active().checkpoint_bytes();
    let domain = b"hepta.runtime-module-registry-checkpoint.v1\0";
    let predecessor_tag =
        domain.len() + 8 + 8 + "persisted".len() + 8 + "owner.persisted".len() + 8 + 64;
    for offset in [domain.len() - 2, predecessor_tag, predecessor_tag + 1 + 32] {
        let mut invalid = bytes.clone();
        invalid[offset] = 255;
        let last = invalid.len() - 32;
        let root = Digest32::of_bytes(&invalid[..last]);
        invalid[last..].copy_from_slice(root.as_array());
        assert_eq!(
            RuntimeModuleRegistryV1::restore_checkpoint_bytes(&invalid, root).unwrap_err(),
            Error::CheckpointEncoding
        );
    }
}

#[test]
fn restored_successors_require_pinned_predecessors_and_complete_evidence() {
    let original = codec::decode(include_bytes!("../fixtures/pr1303_active_v1.bin")).unwrap();
    let cases: Vec<InvalidCase> = vec![
        (
            |c| {
                c.records.remove(0);
            },
            Error::UnknownPredecessor,
        ),
        (
            |c| c.records[1].abi.rollback_predecessor_digest = digest("wrong"),
            Error::PredecessorDigestMismatch,
        ),
        (
            |c| c.records[1].handoff_digest = None,
            Error::MissingWriterHandoff,
        ),
        (
            |c| {
                c.records[1].selection_digest = None;
                c.records[1].canary_digest = None;
                c.records[1].handoff_digest = None;
            },
            Error::MissingPromotionEvidence,
        ),
        (
            |c| c.generation_fences[0].greatest_generation = generation(1),
            Error::CheckpointInvalid,
        ),
    ];
    for (mutate, expected) in cases {
        let mut malformed = original.clone();
        mutate(&mut malformed);
        resign(&mut malformed);
        assert_eq!(restore(malformed).unwrap_err(), expected);
    }
}

fn reject_rehashed(mut bytes: Vec<u8>, expected: Error) {
    let last = bytes.len() - 32;
    let root = Digest32::of_bytes(&bytes[..last]);
    bytes[last..].copy_from_slice(root.as_array());
    assert_eq!(
        RuntimeModuleRegistryV1::restore_checkpoint_bytes(&bytes, root).unwrap_err(),
        expected
    );
}

#[test]
fn rehashed_wire_rejects_noncanonical_fences_and_sets() {
    let mut registry = active();
    bootstrap(&mut registry, abi("z", /*value*/ 1, /*previous*/ None));
    let mut bytes = registry.checkpoint_bytes();
    let sizes = registry
        .checkpoint()
        .generation_fences
        .iter()
        .map(|f| 24 + f.module_id.as_str().len())
        .collect::<Vec<_>>();
    let start = bytes.len() - 32 - sizes.iter().sum::<usize>();
    bytes[start..start + sizes.iter().sum::<usize>()].rotate_left(sizes[0]);
    reject_rehashed(bytes, Error::CheckpointEncoding);

    let mut pattern = 2_u64.to_be_bytes().to_vec();
    for value in [b"aaa", b"bbb"] {
        pattern.extend_from_slice(&3_u64.to_be_bytes());
        pattern.extend_from_slice(value);
    }
    for effect in [false, true] {
        let mut registry = RuntimeModuleRegistryV1::new();
        let mut candidate = abi("sets", /*value*/ 1, /*previous*/ None);
        let values = BTreeSet::from([id("aaa"), id("bbb")]);
        if effect {
            candidate.effect_scope = values;
        } else {
            candidate.authoritative_domains = values;
        }
        bootstrap(&mut registry, candidate);
        let bytes = registry.checkpoint_bytes();
        let start = bytes
            .windows(pattern.len())
            .position(|value| value == pattern)
            .unwrap();
        let mut duplicate = bytes.clone();
        duplicate[start + pattern.len() - 3..start + pattern.len()].copy_from_slice(b"aaa");
        reject_rehashed(duplicate, Error::CheckpointEncoding);
        let mut reversed = bytes;
        reversed[start + 16..start + 19].copy_from_slice(b"bbb");
        reversed[start + pattern.len() - 3..start + pattern.len()].copy_from_slice(b"aaa");
        reject_rehashed(reversed, Error::CheckpointEncoding);
    }
}

#[test]
fn rehashed_wire_checks_nested_counts_and_id_lengths_before_allocation() {
    let bytes = active().checkpoint_bytes();
    let record_start = b"hepta.runtime-module-registry-checkpoint.v1\0".len() + 8;
    let dependency_count =
        record_start + 8 + "persisted".len() + 8 + "owner.persisted".len() + 8 + 64 + 1 + 32 + 1;
    for (offset, value) in [
        (record_start, 129_u64),
        (dependency_count, 65),
        (dependency_count, u64::MAX),
    ] {
        let mut invalid = bytes.clone();
        invalid[offset..offset + 8].copy_from_slice(&value.to_be_bytes());
        reject_rehashed(invalid, Error::Bounds);
    }
}

#[test]
fn maximum_sized_valid_abi_roundtrips_without_truncation() {
    let ids = |prefix: &str, count| {
        (0..count)
            .map(|index| id(&format!("{prefix}-{index:03}-{}", "x".repeat(120))))
            .collect::<Vec<_>>()
    };
    let mut candidate = abi("max", /*value*/ 1, /*previous*/ None);
    candidate.module_id = id(&"m".repeat(128));
    candidate.owner_id = id(&"o".repeat(128));
    candidate.dependencies = ids("dep", /*count*/ 64);
    candidate.input_ports = ids("inp", /*count*/ 64);
    candidate.output_ports = ids("out", /*count*/ 64);
    candidate.authoritative_domains = ids("dom", /*count*/ 32).into_iter().collect();
    candidate.effect_scope = ids("eff", /*count*/ 32).into_iter().collect();
    let mut registry = RuntimeModuleRegistryV1::new();
    bootstrap(&mut registry, candidate);
    let checkpoint = registry.checkpoint();
    let bytes = registry.checkpoint_bytes();
    let restored =
        RuntimeModuleRegistryV1::restore_checkpoint_bytes(&bytes, checkpoint.checkpoint_digest)
            .unwrap();
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(restored.checkpoint_bytes(), bytes);
}
