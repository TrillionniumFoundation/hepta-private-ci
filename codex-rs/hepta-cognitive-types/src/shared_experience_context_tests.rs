use std::collections::BTreeSet;
use std::fmt::Debug;

use crate::contract::ContractErrorCodeV1;
use crate::contract::Validated;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::shared_experience::SharedExperienceOwnerCutV2;
use crate::shared_experience::SharedExperiencePublicationV2;
use crate::shared_experience::SharedExperienceSourceKindV2;
use crate::shared_experience::SharedExperienceUseClassV2;
use crate::shared_experience::SharedExperienceUseDispositionV2;
use crate::shared_experience::SharedExperienceUseGrantV2;
use crate::shared_experience::SharedExperienceUseReceiptV2;
use crate::shared_experience_context::FinalSharedExperienceUseV2;
use crate::wire::canonical_contract_digest_v1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Ok(value) => panic!("unexpected success: {value:?}"),
        Err(error) => error,
    }
}

fn id(value: &str) -> ContractIdV1 {
    must(ContractIdV1::new(value))
}

fn digest(character: char) -> ContractDigestV1 {
    must(ContractDigestV1::parse(
        &std::iter::repeat_n(character, 64).collect::<String>(),
    ))
}

fn generation(value: u64) -> ContractGenerationV1 {
    must(ContractGenerationV1::new(value))
}

fn grant() -> SharedExperienceUseGrantV2 {
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

fn publication() -> SharedExperiencePublicationV2 {
    SharedExperiencePublicationV2 {
        publication_operation_id: id("operation:publish"),
        contribution_id: id("contribution:1"),
        source_owner_id: id("agent:source"),
        source_owner_epoch: 7,
        source_kind: SharedExperienceSourceKindV2::CanonicalMemoryEvent,
        source_record_id: id("event:source"),
        source_revision: 9,
        source_record_sha256: digest('2'),
        semantic_content_sha256: digest('3'),
        source_scope_sha256: digest('4'),
        environment_sha256: digest('5'),
        applicability_sha256: digest('6'),
        publication_policy_sha256: digest('a'),
        policy_generation: generation(3),
        destination_scope_ids: BTreeSet::from([id("scope:receiver")]),
        use_grants: vec![grant()],
        retention_lineage_sha256: digest('7'),
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
        schema_sha256: digest('b'),
        policy_sha256: digest('a'),
    }
}

fn receipt(publication: &SharedExperiencePublicationV2) -> SharedExperienceUseReceiptV2 {
    let publication_sha256 = must(ContractDigestV1::from_digest(must(
        canonical_contract_digest_v1(publication),
    )));
    SharedExperienceUseReceiptV2 {
        use_operation_id: id("operation:read-shared"),
        publication_sha256,
        grant: grant(),
        source_owner_id: id("agent:source"),
        source_revision: 9,
        consumer_id: id("agent:receiver"),
        observed_policy_generation: generation(3),
        observed_revocation_frontier: 3,
        payload_sha256: digest('8'),
        used_at_unix_ms: 500,
        final_use_observed: true,
        disposition: SharedExperienceUseDispositionV2::Delivered,
    }
}

#[test]
fn final_use_context_binds_all_cross_object_frontiers() {
    let publication = must(Validated::new(publication()));
    let receipt = must(Validated::new(receipt(publication.as_inner())));
    let owner_cut = owner_cut();
    let destination = id("scope:receiver");
    let proof = must(FinalSharedExperienceUseV2::new(
        &publication,
        &receipt,
        &owner_cut,
        &destination,
        500,
    ));

    assert!(!proof.context_digest().is_zero());
    assert!(!proof.publication_digest().is_zero());
    assert!(!proof.receipt_digest().is_zero());
    assert_eq!(proof.grant().grant_id, id("grant:read"));
    assert_eq!(
        proof.receipt(),
        must(proof.require_unchanged_owner_cut(&owner_cut))
    );
    assert_eq!(
        SharedExperienceUseDispositionV2::Delivered.wire_token(),
        "delivered"
    );
    assert_eq!(
        SharedExperienceSourceKindV2::CanonicalMemoryEvent.wire_token(),
        "canonical_memory_event"
    );
}

#[test]
fn final_use_context_rejects_substitution_staleness_and_failed_use() {
    let publication_value = publication();
    let publication = must(Validated::new(publication_value.clone()));
    let receipt_value = receipt(&publication_value);
    let receipt = must(Validated::new(receipt_value.clone()));
    let owner_cut = owner_cut();
    let destination = id("scope:receiver");

    let mut wrong_publication_receipt = receipt_value.clone();
    wrong_publication_receipt.publication_sha256 = digest('f');
    let wrong_publication_receipt = must(Validated::new(wrong_publication_receipt));
    let error = must_err(FinalSharedExperienceUseV2::new(
        &publication,
        &wrong_publication_receipt,
        &owner_cut,
        &destination,
        500,
    ));
    assert_eq!(error.code, ContractErrorCodeV1::DigestMismatch);

    let mut substituted_grant_receipt = receipt_value.clone();
    substituted_grant_receipt.grant.use_class = SharedExperienceUseClassV2::RawEvidenceRead {
        consumer_id: id("agent:receiver"),
        consumer_workspace_sha256: digest('9'),
    };
    let substituted_grant_receipt = must(Validated::new(substituted_grant_receipt));
    let error = must_err(FinalSharedExperienceUseV2::new(
        &publication,
        &substituted_grant_receipt,
        &owner_cut,
        &destination,
        500,
    ));
    assert_eq!(error.code, ContractErrorCodeV1::StateConflict);

    let mut stale_cut = owner_cut.clone();
    stale_cut.revocation_frontier += 1;
    let error = must_err(FinalSharedExperienceUseV2::new(
        &publication,
        &receipt,
        &stale_cut,
        &destination,
        500,
    ));
    assert_eq!(error.code, ContractErrorCodeV1::StateConflict);

    let mut policy_drift = owner_cut.clone();
    policy_drift.policy_sha256 = digest('c');
    let error = must_err(FinalSharedExperienceUseV2::new(
        &publication,
        &receipt,
        &policy_drift,
        &destination,
        500,
    ));
    assert_eq!(error.code, ContractErrorCodeV1::DigestMismatch);

    let other_destination = id("scope:other");
    let error = must_err(FinalSharedExperienceUseV2::new(
        &publication,
        &receipt,
        &owner_cut,
        &other_destination,
        500,
    ));
    assert_eq!(error.code, ContractErrorCodeV1::StateConflict);

    let error = must_err(FinalSharedExperienceUseV2::new(
        &publication,
        &receipt,
        &owner_cut,
        &destination,
        501,
    ));
    assert_eq!(error.code, ContractErrorCodeV1::StateConflict);

    let mut rejected = receipt_value;
    rejected.disposition = SharedExperienceUseDispositionV2::Rejected;
    rejected.final_use_observed = false;
    let rejected = must(Validated::new(rejected));
    let error = must_err(FinalSharedExperienceUseV2::new(
        &publication,
        &rejected,
        &owner_cut,
        &destination,
        500,
    ));
    assert_eq!(error.code, ContractErrorCodeV1::StateConflict);
}

#[test]
fn final_use_proof_cannot_be_replayed_after_owner_cut_changes() {
    let publication = must(Validated::new(publication()));
    let receipt = must(Validated::new(receipt(publication.as_inner())));
    let owner_cut = owner_cut();
    let destination = id("scope:receiver");
    let proof = must(FinalSharedExperienceUseV2::new(
        &publication,
        &receipt,
        &owner_cut,
        &destination,
        500,
    ));
    let mut changed = owner_cut.clone();
    changed.source_frontier += 1;
    let error = must_err(proof.require_unchanged_owner_cut(&changed));
    assert_eq!(error.code, ContractErrorCodeV1::StateConflict);
}
