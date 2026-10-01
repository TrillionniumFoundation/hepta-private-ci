use super::*;

#[path = "neuron_artifact_refresh_fixture_tests.rs"]
mod fixture;
use fixture::*;

#[test]
fn genuine_v2_publication_admits_empty_genesis_without_fake_predecessor() {
    let fixture = Fixture::new();
    let mut admission = fixture.admission();
    assert_eq!(
        admission.validate_initial_generation(&fixture.config),
        Ok(())
    );
    assert_ne!(
        fixture.selections().model.support_digest,
        fixture.config.model_manifest_digest
    );
    admission.selections.model.predecessor_id = Some(id("fabricated.predecessor"));
    assert_eq!(
        admission.validate_initial_generation(&fixture.config),
        Err(NeuronAdmissionError::BindingMismatch)
    );
}

#[test]
fn unrelated_publication_fences_cached_selection_until_external_signed_refresh() {
    let mut fixture = Fixture::new();
    let mut admission = fixture.admission();
    let ingress = admission.selection_refresh_ingress();
    let old = fixture.selections();
    fixture.advance();
    assert!(admission.check(&fixture.config, &fixture.tick()).is_err());
    assert!(ingress.submit_current_selections(old).is_err());
    let fresh = fixture.selections();
    let digest = ingress
        .submit_current_selections(fresh.clone())
        .expect("genuine refreshed signatures");
    assert!(!digest.is_zero());
    assert_eq!(ingress.submit_current_selections(fresh), Ok(digest));
    assert!(
        admission.closed,
        "queued input alone cannot revive a consumer"
    );
    assert_eq!(admission.check(&fixture.config, &fixture.tick()), Ok(()));
    assert!(!admission.closed);
    assert_eq!(admission.check(&fixture.config, &fixture.tick()), Ok(()));
}

#[test]
fn actual_revocation_between_submit_and_consume_cannot_refresh_old_model() {
    let mut fixture = Fixture::new();
    let mut admission = fixture.admission();
    let ingress = admission.selection_refresh_ingress();
    fixture.advance();
    ingress
        .submit_current_selections(fixture.selections())
        .expect("fresh eligible input");
    fixture.revoke_model();
    assert!(admission.check(&fixture.config, &fixture.tick()).is_err());
    assert!(admission.closed);
    assert!(
        ingress
            .submit_current_selections(fixture.selections())
            .is_err()
    );
    assert!(admission.check(&fixture.config, &fixture.tick()).is_err());
}

#[test]
fn same_weights_with_different_cpu_descriptor_or_manifest_preimage_are_rejected() {
    let fixture = Fixture::new();
    let mut config = fixture.config.clone();
    config.model_manifest_digest = descriptor_digest(64);
    assert_eq!(config.weights_digest, fixture.config.weights_digest);
    assert_eq!(
        config.execution_profile_digest_v1(),
        fixture.config.execution_profile_digest_v1()
    );
    assert!(
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&fixture.owner),
            fixture.directory.path(),
            fixture.selector.clone(),
            fixture.selections(),
            Arc::new(Clock),
            &config,
        )
        .is_err()
    );
    let mut mutated = fixture.selections();
    mutated
        .model_artifact_manifest
        .lineage_digests
        .push(config.model_manifest_digest);
    assert!(
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&fixture.owner),
            fixture.directory.path(),
            fixture.selector.clone(),
            mutated,
            Arc::new(Clock),
            &config,
        )
        .is_err(),
        "externally added lineage cannot change authenticated support"
    );
}

#[test]
fn old_support_domain_and_cross_model_refresh_cannot_bypass_native_admission() {
    let mut fixture = Fixture::new();
    let admission = fixture.admission();
    let ingress = admission.selection_refresh_ingress();
    let mut old_support = fixture.selections();
    old_support.model.support_digest = fixture.config.model_manifest_digest;
    fixture.resign(&mut old_support.model);
    assert!(
        ingress
            .submit_current_selections(old_support.clone())
            .is_err()
    );
    assert!(
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&fixture.owner),
            fixture.directory.path(),
            fixture.selector.clone(),
            old_support,
            Arc::new(Clock),
            &fixture.config,
        )
        .is_err(),
        "even an independently signed old support domain cannot override CURRENT"
    );
    fixture.advance();
    let mut cross_model = fixture.selections();
    let unrelated = fixture
        .unrelated
        .as_ref()
        .expect("genuinely published unrelated model");
    cross_model.model = fixture.sign(unrelated);
    cross_model.model_artifact_manifest = unrelated.clone();
    assert!(
        ingress
            .submit_current_selections(cross_model.clone())
            .is_err()
    );
    assert!(
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&fixture.owner),
            fixture.directory.path(),
            fixture.selector.clone(),
            cross_model,
            Arc::new(Clock),
            &fixture.config,
        )
        .is_err()
    );
    let mut tampered = fixture.selections();
    tampered.model.signature[0] ^= 1;
    assert!(ingress.submit_current_selections(tampered).is_err());
}
