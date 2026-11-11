//! Component qualification over actual original source files and signatures.
//! Synthetic observations do not establish an independent B experiment.

use std::fs;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::LearningOriginalOwnerErrorV1;
use crate::OriginalProductQualificationErrorV1;
use crate::OriginalProductQualificationOwnerV1;

#[path = "product_qualification_owner_support_tests.rs"]
mod original_support;
use original_support::*;
#[path = "product_qualification_owner_witness_tests.rs"]
mod witness_faults;

#[test]
fn publication_reopens_complete_original_material_without_provider_or_signer() {
    let mut fixture = OriginalQualificationFixture::new();
    assert_eq!(fixture.provider_calls, (1, 1));
    let path = fixture.directory.path().to_path_buf();
    let source_before = fixture.source_bytes();
    let mut owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        witness(file(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    let empty = checked(fs::read(path.join("publication")));
    let first = checked(fixture.publish(&mut owner));
    checked(first.validate_integrity());
    let first_time = clock();
    let original = checked(fs::read(path.join("publication")));
    let original_witness = checked(fs::read(path.join("publication-witness")));
    assert_ne!(original, empty);
    for signature in [
        fixture.evidence.generator_plan.signature,
        fixture.evidence.evaluator_bundle.signature,
    ] {
        assert!(
            original
                .windows(signature.len())
                .any(|bytes| bytes == signature)
        );
    }
    std::thread::sleep(std::time::Duration::from_millis(1100));
    assert!(clock() > first_time);
    assert_eq!(checked(fixture.publish(&mut owner)), first);
    assert_eq!(checked(fixture.readback(&mut owner)), first);
    assert_eq!(checked(fs::read(path.join("publication"))), original);
    assert_eq!(fixture.source_bytes(), source_before);
    drop(owner);

    // The saved signatures and context must come from the original publication,
    // not from these discarded caller inputs. All source owners are also dropped.
    fixture.evidence.generator_plan.signature.fill(0);
    fixture.evidence.evaluator_bundle.signature.fill(0);
    fixture.context.generator.principal_id = id("discarded-caller-context");
    let mut fixture = fixture.reopen_sources();
    let mut recovered = checked(OriginalProductQualificationOwnerV1::recover(
        existing(&path.join("publication")),
        witness(existing(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    assert_eq!(checked(fixture.readback(&mut recovered)), first);
    assert_eq!(checked(fixture.readback(&mut recovered)), first);
    assert_eq!(checked(fs::read(path.join("publication"))), original);
    assert_eq!(
        checked(fs::read(path.join("publication-witness"))),
        original_witness
    );
    assert_eq!(fixture.source_bytes(), source_before);
    drop(recovered);

    // An acknowledged complete witness cannot be paired with an older owner file.
    checked(fs::write(path.join("publication"), empty));
    assert!(
        OriginalProductQualificationOwnerV1::recover(
            existing(&path.join("publication")),
            witness(existing(&path.join("publication-witness"))),
            digest("publication-namespace"),
        )
        .is_err()
    );
}

#[test]
fn missing_forged_and_longitudinal_material_never_claims_a_publication() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let mut owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        witness(file(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    let before =
        ["publication", "publication-witness"].map(|name| checked(fs::read(path.join(name))));
    assert!(matches!(
        fixture.readback(&mut owner),
        Err(OriginalProductQualificationErrorV1::Owner(
            LearningOriginalOwnerErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing)
        ))
    ));
    let evidence = fixture.evidence.clone();
    fixture.evidence.generator_plan.signature[0] ^= 1;
    assert!(fixture.publish(&mut owner).is_err());
    fixture.evidence = evidence.clone();
    fixture.evidence.evaluator_bundle.signature[0] ^= 1;
    assert!(fixture.publish(&mut owner).is_err());
    fixture.evidence = evidence;
    fixture.context.generator.principal_id = id("foreign-generator");
    assert!(fixture.publish(&mut owner).is_err());
    fixture.plan.frozen_plan.claim_scope = EvaluationClaimScopeV1::SystemLongitudinal;
    assert!(matches!(
        fixture.publish(&mut owner),
        Err(OriginalProductQualificationErrorV1::Binding(
            "Qualification/v2 scope"
        ))
    ));
    assert_eq!(
        ["publication", "publication-witness"].map(|name| checked(fs::read(path.join(name)))),
        before
    );
}

#[test]
fn valid_but_conflicting_material_cannot_replace_an_acknowledged_publication() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let mut owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        witness(file(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    let first = checked(fixture.publish(&mut owner));
    let before =
        ["publication", "publication-witness"].map(|name| checked(fs::read(path.join(name))));
    fixture
        .context
        .retention_receipt_digests
        .push(digest("additional-retention"));
    fixture.sign_context();
    let material = fixture.material();
    checked(fixture.runner.original_qualification_decision(
        &material,
        &fixture.context,
        &fixture.evidence,
        &fixture.verifier,
        clock(),
    ));
    assert!(matches!(
        fixture.publish(&mut owner),
        Err(OriginalProductQualificationErrorV1::Binding(
            "conflicting complete qualification material"
        ))
    ));
    assert_eq!(checked(fixture.readback(&mut owner)), first);
    assert_eq!(
        ["publication", "publication-witness"].map(|name| checked(fs::read(path.join(name)))),
        before
    );
}

#[test]
fn complete_material_exceeding_original_capacity_is_rejected_before_claim() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let mut owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        witness(file(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    let before =
        ["publication", "publication-witness"].map(|name| checked(fs::read(path.join(name))));
    fixture.context.retention_receipt_digests = (0..4096)
        .map(|i| digest(&format!("retention-{i}")))
        .collect();
    fixture.sign_context();
    let material = fixture.material();
    // The original signatures and decision are valid; the bound is the refusal.
    checked(fixture.runner.original_qualification_decision(
        &material,
        &fixture.context,
        &fixture.evidence,
        &fixture.verifier,
        clock(),
    ));
    assert!(matches!(
        fixture.publish(&mut owner),
        Err(OriginalProductQualificationErrorV1::Evaluation(
            ProductEvaluationError::Binding("qualification record capacity")
        ))
    ));
    assert_eq!(
        ["publication", "publication-witness"].map(|name| checked(fs::read(path.join(name)))),
        before
    );
}

#[test]
fn recovery_rechecks_current_trust_and_original_complete_source_bytes() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let mut owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        witness(file(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    let first = checked(fixture.publish(&mut owner));
    let original = checked(fs::read(path.join("publication")));
    let verifier = fixture.verifier.clone();
    let mut revoked = fixture.trust.clone();
    revoked.signers[1].revoked_at = Some(clock() - 1);
    fixture.verifier = checked(LearningEvidenceVerifierV1::new(revoked));
    assert!(fixture.readback(&mut owner).is_err());
    fixture.verifier = verifier;
    let material = fixture.material();
    let mut replaced = material.envelope().to_vec();
    let last = replaced.len() - 1;
    replaced[last] ^= 1;
    // A different completion at the same original execution key is a conflict.
    assert!(
        fixture
            .executions
            .complete(material.key(), &replaced)
            .is_err()
    );
    assert_eq!(checked(fixture.readback(&mut owner)), first);
    assert_eq!(checked(fs::read(path.join("publication"))), original);
}

#[test]
fn missing_pending_or_replaced_actual_execution_never_qualifies() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let material = fixture.material();
    let replacement = checked(LockedFileProductEvaluationExecutionStoreV1::create(
        file(&path.join("wrong-execution-owner")),
        digest("execution-file"),
    ));
    let _original = std::mem::replace(&mut fixture.executions, replacement);
    let mut owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        witness(file(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    let before =
        ["publication", "publication-witness"].map(|name| checked(fs::read(path.join(name))));
    assert!(fixture.publish(&mut owner).is_err());
    assert_eq!(
        checked(fixture.executions.claim(material.key())),
        ProductEvaluationExecutionClaimV1::Claimed
    );
    assert!(matches!(
        fixture.publish(&mut owner),
        Err(OriginalProductQualificationErrorV1::Execution(
            ProductEvaluationExecutionErrorV1::Pending
        ))
    ));
    let mut replaced = material.envelope().to_vec();
    let last = replaced.len() - 1;
    replaced[last] ^= 1;
    checked(fixture.executions.complete(material.key(), &replaced));
    assert!(fixture.publish(&mut owner).is_err());
    assert_eq!(
        ["publication", "publication-witness"].map(|name| checked(fs::read(path.join(name)))),
        before
    );
}

#[test]
fn recovery_rejects_empty_witness_namespace_mismatch_and_corrupt_owner_bytes() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let mut owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        witness(file(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    checked(fixture.publish(&mut owner));
    drop(owner);
    assert!(
        OriginalProductQualificationOwnerV1::recover(
            existing(&path.join("publication")),
            witness(file(&path.join("empty-witness"))),
            digest("publication-namespace"),
        )
        .is_err()
    );
    assert!(
        OriginalProductQualificationOwnerV1::recover(
            existing(&path.join("publication")),
            witness(existing(&path.join("publication-witness"))),
            digest("foreign-namespace"),
        )
        .is_err()
    );
    let mut corrupt = checked(fs::read(path.join("publication")));
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    checked(fs::write(path.join("publication"), corrupt));
    assert!(
        OriginalProductQualificationOwnerV1::recover(
            existing(&path.join("publication")),
            witness(existing(&path.join("publication-witness"))),
            digest("publication-namespace"),
        )
        .is_err()
    );
}
