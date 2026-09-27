use std::collections::BTreeSet;

use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::shared_experience::*;
use crate::wire::canonical_contract_digest_v1;
use crate::wire::decode_wire_v1;
use crate::wire::encode_wire_v1;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("valid id")
}

fn digest(character: char) -> ContractDigestV1 {
    ContractDigestV1::parse(&std::iter::repeat_n(character, 64).collect::<String>())
        .expect("valid digest")
}

fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value).expect("valid generation")
}

fn read_grant() -> SharedExperienceUseGrantV2 {
    SharedExperienceUseGrantV2 {
        grant_id: id("grant:read"),
        use_class: SharedExperienceUseClassV2::RawEvidenceRead {
            consumer_id: id("agent:receiver"),
            consumer_workspace_sha256: digest('1'),
        },
        valid_from_unix_ms: 100,
        expires_at_unix_ms: 1_000,
    }
}

fn training_grant() -> SharedExperienceUseGrantV2 {
    SharedExperienceUseGrantV2 {
        grant_id: id("grant:train"),
        use_class: SharedExperienceUseClassV2::PurposeBoundTraining {
            trainer_id: id("learning.operator"),
            purpose_id: id("purpose:domain-adaptation"),
            parameter_scope_sha256: digest('2'),
            dataset_split_sha256: digest('3'),
        },
        valid_from_unix_ms: 100,
        expires_at_unix_ms: 1_000,
    }
}

fn artifact_grant() -> SharedExperienceUseGrantV2 {
    SharedExperienceUseGrantV2 {
        grant_id: id("grant:artifact"),
        use_class: SharedExperienceUseClassV2::DerivedArtifactUse {
            artifact_id: id("artifact:candidate"),
            artifact_consumer_id: id("agent:receiver"),
            artifact_lineage_sha256: digest('4'),
        },
        valid_from_unix_ms: 100,
        expires_at_unix_ms: 1_000,
    }
}

fn publication() -> SharedExperiencePublicationV2 {
    let mut grants = vec![artifact_grant(), read_grant(), training_grant()];
    grants.sort_by(|left, right| left.grant_id.cmp(&right.grant_id));
    SharedExperiencePublicationV2 {
        publication_operation_id: id("operation:publish"),
        contribution_id: id("contribution:1"),
        source_owner_id: id("agent:source"),
        source_owner_epoch: 7,
        source_kind: SharedExperienceSourceKindV2::CanonicalMemoryEvent,
        source_record_id: id("event:source"),
        source_revision: 9,
        source_record_sha256: digest('5'),
        semantic_content_sha256: digest('6'),
        source_scope_sha256: digest('7'),
        environment_sha256: digest('8'),
        applicability_sha256: digest('9'),
        publication_policy_sha256: digest('a'),
        policy_generation: generation(3),
        destination_scope_ids: BTreeSet::from([id("scope:receiver")]),
        use_grants: grants,
        retention_lineage_sha256: digest('b'),
        correction_of_contribution_id: None,
        observed_at_unix_ms: 100,
        expires_at_unix_ms: Some(2_000),
    }
}

fn owner_cut() -> SharedExperienceOwnerCutV2 {
    SharedExperienceOwnerCutV2 {
        owner_id: id("agent:source"),
        owner_epoch: 7,
        source_frontier: 11,
        memory_frontier: 12,
        learning_frontier: 13,
        deletion_frontier: 2,
        revocation_frontier: 3,
        schema_sha256: digest('c'),
        policy_sha256: digest('d'),
    }
}

fn snapshot() -> SharedExperienceSnapshotV2 {
    SharedExperienceSnapshotV2 {
        snapshot_id: id("snapshot:shared"),
        generation: generation(4),
        purpose_id: id("purpose:domain-adaptation"),
        owner_cuts: vec![owner_cut()],
        contribution_sha256s: BTreeSet::from([digest('e')]),
        dependency_sha256s: BTreeSet::from([digest('f')]),
        unavailable_owner_ids: BTreeSet::new(),
        completeness: SharedExperienceSnapshotCompletenessV2::Complete,
        snapshot_manifest_sha256: digest('1'),
        deletion_frontier_sha256: digest('2'),
        revocation_frontier_sha256: digest('3'),
        created_at_unix_ms: 200,
    }
}

fn use_receipt() -> SharedExperienceUseReceiptV2 {
    SharedExperienceUseReceiptV2 {
        use_operation_id: id("operation:read-shared"),
        publication_sha256: digest('4'),
        grant: read_grant(),
        source_owner_id: id("agent:source"),
        source_revision: 9,
        consumer_id: id("agent:receiver"),
        observed_policy_generation: generation(3),
        observed_revocation_frontier: 3,
        payload_sha256: digest('5'),
        used_at_unix_ms: 500,
        final_use_observed: true,
        disposition: SharedExperienceUseDispositionV2::Delivered,
    }
}

fn revocation() -> SharedExperienceRevocationReceiptV2 {
    SharedExperienceRevocationReceiptV2 {
        revocation_operation_id: id("operation:revoke-shared"),
        contribution_id: id("contribution:1"),
        publication_sha256: digest('6'),
        source_owner_id: id("agent:source"),
        source_revision: 9,
        predecessor_policy_generation: generation(3),
        next_policy_generation: generation(4),
        revocation_frontier: 4,
        all_uses_revoked: true,
        revoked_use_grant_ids: BTreeSet::new(),
        affected_projection_sha256s: BTreeSet::from([digest('7')]),
        affected_training_dataset_sha256s: BTreeSet::from([digest('8')]),
        affected_artifact_sha256s: BTreeSet::from([digest('9')]),
        pending_offline_owner_ids: BTreeSet::new(),
        source_use_blocked: true,
        training_use_blocked: true,
        artifact_adoption_blocked: true,
        influence_status: SharedExperienceInfluenceStatusV2::Pending,
        influence_proof_sha256: None,
        completeness: SharedExperienceRevocationCompletenessV2::Complete,
    }
}

#[test]
fn shared_experience_v2_roundtrips_and_digest_domains_are_distinct() {
    macro_rules! roundtrip {
        ($value:expr, $type:ty) => {{
            let value: $type = $value;
            value.validate().expect("valid contract");
            let wire = encode_wire_v1(&value).expect("wire");
            assert_eq!(decode_wire_v1::<$type>(&wire).expect("decode"), value);
            canonical_contract_digest_v1(&value).expect("digest")
        }};
    }
    let publication_digest = roundtrip!(publication(), SharedExperiencePublicationV2);
    let snapshot_digest = roundtrip!(snapshot(), SharedExperienceSnapshotV2);
    let use_digest = roundtrip!(use_receipt(), SharedExperienceUseReceiptV2);
    let revocation_digest = roundtrip!(revocation(), SharedExperienceRevocationReceiptV2);
    assert_eq!(
        publication_digest.to_string(),
        "9bae7ba4f327b65832a0f4860c50b10c5ced877eadcea532afb4e973491e882e"
    );
    assert_eq!(
        snapshot_digest.to_string(),
        "9d6c35998edf88d3d283deea10a8eb0df9edae6d6004e92475c39626d86f8128"
    );
    assert_eq!(
        use_digest.to_string(),
        "32133156afa841cd9352853a48d19cacbb9c07df83ce45f3197e5ead6b8eae04"
    );
    assert_eq!(
        revocation_digest.to_string(),
        "01b91dad36e1963c000b7003b74cc2d0cb56d4c36d81ef9b5b3b56d30d55cb1b"
    );
    assert_eq!(
        BTreeSet::from([
            publication_digest,
            snapshot_digest,
            use_digest,
            revocation_digest,
        ])
        .len(),
        4
    );
}

#[test]
fn read_permission_does_not_imply_training_or_artifact_permission() {
    let mut value = publication();
    value.use_grants = vec![read_grant()];
    value.validate().expect("read-only publication is valid");
    assert!(value.use_grants.iter().all(|grant| matches!(
        grant.use_class,
        SharedExperienceUseClassV2::RawEvidenceRead { .. }
    )));
}

#[test]
fn use_grants_are_identity_unique_ordered_and_publication_bounded() {
    let mut duplicate = publication();
    duplicate.use_grants = vec![read_grant(), read_grant()];
    assert!(duplicate.validate().is_err());

    let mut outside_publication = publication();
    outside_publication.use_grants[0].expires_at_unix_ms = 2_001;
    assert!(outside_publication.validate().is_err());
}

#[test]
fn snapshot_completeness_is_explicit_and_fail_closed() {
    let mut partial = snapshot();
    partial.completeness = SharedExperienceSnapshotCompletenessV2::Partial;
    assert!(partial.validate().is_err());
    partial.unavailable_owner_ids.insert(id("agent:offline"));
    partial.validate().expect("explicit partial snapshot");

    let mut unavailable = snapshot();
    unavailable.completeness = SharedExperienceSnapshotCompletenessV2::Unavailable;
    unavailable.owner_cuts.clear();
    unavailable.contribution_sha256s.clear();
    unavailable.unavailable_owner_ids.insert(id("agent:source"));
    unavailable
        .validate()
        .expect("explicit unavailable snapshot");
}

#[test]
fn use_receipt_binds_permission_class_consumer_and_final_use() {
    let mut wrong_consumer = use_receipt();
    wrong_consumer.consumer_id = id("agent:other");
    assert!(wrong_consumer.validate().is_err());

    let mut wrong_disposition = use_receipt();
    wrong_disposition.disposition = SharedExperienceUseDispositionV2::ArtifactAdopted;
    assert!(wrong_disposition.validate().is_err());

    let mut no_final_use = use_receipt();
    no_final_use.final_use_observed = false;
    assert!(no_final_use.validate().is_err());
}

#[test]
fn revocation_never_claims_complete_or_removed_without_evidence() {
    let mut incomplete = revocation();
    incomplete
        .pending_offline_owner_ids
        .insert(id("agent:offline"));
    assert!(incomplete.validate().is_err());
    incomplete.completeness = SharedExperienceRevocationCompletenessV2::Partial;
    incomplete.validate().expect("explicit partial revocation");

    let mut unsupported = revocation();
    unsupported.influence_status = SharedExperienceInfluenceStatusV2::ProvedRemoved;
    assert!(unsupported.validate().is_err());
    unsupported.influence_proof_sha256 = Some(digest('a'));
    unsupported.validate().expect("proved removal has proof");
}

#[test]
fn shared_negative_cross_language_wire_vectors_are_rejected() {
    let corpus: serde_json::Value = serde_json::from_str(include_str!(
        "../../../qualification/cognitive-types-v2/negative-vectors.json"
    ))
    .expect("negative corpus");
    for case in corpus["cases"].as_array().expect("cases") {
        let wire = case["wire"].as_str().expect("wire").as_bytes();
        let error = match case["contract"].as_str().expect("contract") {
            "SharedExperiencePublicationV2" => {
                decode_wire_v1::<SharedExperiencePublicationV2>(wire).map(|_| ())
            }
            "SharedExperienceSnapshotV2" => {
                decode_wire_v1::<SharedExperienceSnapshotV2>(wire).map(|_| ())
            }
            "SharedExperienceUseReceiptV2" => {
                decode_wire_v1::<SharedExperienceUseReceiptV2>(wire).map(|_| ())
            }
            "SharedExperienceRevocationReceiptV2" => {
                decode_wire_v1::<SharedExperienceRevocationReceiptV2>(wire).map(|_| ())
            }
            other => panic!("unknown contract {other}"),
        }
        .expect_err("negative wire must reject");
        assert!(
            error
                .to_string()
                .contains(case["expectedErrorContains"].as_str().expect("error")),
            "{}: {error}",
            case["name"]
        );
    }
}

#[test]
fn expired_attempt_is_recordable_but_cannot_claim_success() {
    let mut receipt = use_receipt();
    receipt.used_at_unix_ms = receipt.grant.expires_at_unix_ms;
    assert!(receipt.validate().is_err());
    receipt.disposition = SharedExperienceUseDispositionV2::Rejected;
    receipt.final_use_observed = false;
    let bytes = encode_wire_v1(&receipt).expect("expired rejection record");
    assert_eq!(
        decode_wire_v1::<SharedExperienceUseReceiptV2>(&bytes).expect("decode"),
        receipt
    );
}

#[test]
fn source_domains_and_structured_permission_mutations_remain_distinct() {
    let original = publication();
    let original_digest = canonical_contract_digest_v1(&original).expect("original");
    let mut legacy = original.clone();
    legacy.source_kind = SharedExperienceSourceKindV2::OwnerMemoryRevision;
    assert_ne!(
        canonical_contract_digest_v1(&legacy).expect("owner domain"),
        original_digest
    );
    for revision in 1..=64 {
        let mut value = original.clone();
        value.source_revision = revision;
        value.publication_operation_id = id(&format!("operation:publish:{revision}"));
        let bytes = encode_wire_v1(&value).expect("structured V2 encode");
        assert_eq!(
            decode_wire_v1::<SharedExperiencePublicationV2>(&bytes).expect("decode"),
            value
        );
        value.use_grants[0].grant_id = value.use_grants[1].grant_id.clone();
        assert!(encode_wire_v1(&value).is_err());
    }
}
