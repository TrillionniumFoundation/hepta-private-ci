use super::*;
use crate::ArtifactEvent;
use crate::ArtifactManifest;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactState;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalScopeV1;
use crate::LearningArtifactManifestV2;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::ProvenanceModeV1;
use crate::RegistryHeadWitnessV1;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

fn must<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture: {error:?}"),
    }
}
fn id(value: &str) -> StableId {
    must(StableId::new(value))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn generation(value: u64) -> Generation {
    must(Generation::new(value))
}

struct Fixture {
    directory: TestDirectory,
    config: LearningArtifactOwnerServiceConfigV1,
    publisher: ScientificCandidatePublisherV1,
    request: LearningArtifactPublishRequestV1,
    review: SignedScientificCandidateReviewV1,
    reviewer_key: SigningKey,
}

struct TestDirectory(PathBuf);

impl std::ops::Deref for TestDirectory {
    type Target = Path;
    fn deref(&self) -> &Path {
        &self.0
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn signer(key: &SigningKey, name: &str) -> TrustedArtifactSignerV1 {
    TrustedArtifactSignerV1 {
        signer_id: id(name),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 2,
        valid_from: 1,
        expires_at: 1_000,
        revoked_at: None,
    }
}

fn policy() -> ScientificCandidatePolicyV1 {
    let gate = |name, threshold| ScientificComparisonPolicyV1 {
        comparison_digest: digest(name),
        maximum_upper_bound: threshold,
        minimum_observations: 4,
    };
    ScientificCandidatePolicyV1 {
        protocol_digest: digest("pre-frozen protocol"),
        candidate_definition_digest: digest("predeclared candidate"),
        task: gate("task-vs-myopic paired interval", -0.005),
        retention: gate("old-task-vs-warmup paired interval", 0.02),
        total_cost: gate("complete priced resource ratio", 1.0),
    }
}

fn manifest(name: &str, previous: Option<StableId>) -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id(name),
        kind: ArtifactKind::Parameters,
        generation: generation(if previous.is_some() { 2 } else { 1 }),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![digest("dataset")],
        lineage_digests: vec![digest("independent full report")],
        predecessor_ids: previous.iter().cloned().collect(),
        rollback_predecessor: previous,
        bytes_digest: digest(name),
        encoded_size_bytes: name.len() as u64,
        training_code_digest: digest("code"),
        runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"),
        objective_class_digest: digest("objective"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalizer"),
        producer_id: id("trainer"),
        created_at: 10,
        expires_at: 1_000,
    }
}

// Preview the actual registry append using the existing public transaction and
// registry. The real owner independently reconstructs and checks this head.
fn request(
    key: &SigningKey,
    registry: &ArtifactRegistry,
    withdrawals: &DatasetWithdrawalRegistry,
    manifest: LearningArtifactManifestV2,
) -> LearningArtifactPublishRequestV1 {
    let payload = manifest.artifact_id.as_str().as_bytes().to_vec();
    let operation_id = id(&format!("publish-{}", manifest.artifact_id));
    let admission = must(admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        manifest.clone(),
        20,
    ));
    let predecessor = registry.snapshot().head_digest;
    let transaction = must(ArtifactPublicationTransactionV1::begin(
        operation_id.clone(),
        admission.clone(),
        withdrawals,
        registry,
        predecessor,
        20,
    ));
    let mut staged = registry.clone();
    must(staged.append(ArtifactEvent::Register {
        event_id: id(&format!(
            "artifact-publication:{}",
            transaction.intent().intent_digest
        )),
        manifest: ArtifactManifest {
            artifact_id: manifest.artifact_id,
            kind: manifest.kind,
            generation: manifest.generation,
            predecessor_id: manifest.predecessor_ids.first().cloned(),
            content_digest: manifest.bytes_digest,
            objective_digest: manifest.objective_class_digest,
            support_digest: admission.validated_manifest.manifest_digest,
            producer_id: manifest.producer_id,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
        },
    }));
    let mut signed_current_head = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: must(withdrawals.scope_digest().ok_or("scope")),
        binding: digest("storage"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("artifacts"),
            generation: generation(staged.records().len() as u64),
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("owner"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: 20,
            expires_at: 1_000,
        },
        signature: [0; 64],
    };
    signed_current_head.signature = key.sign(&signed_current_head.signing_bytes()).to_bytes();
    LearningArtifactPublishRequestV1 {
        operation_id,
        admission,
        payload,
        signed_current_head,
        expected_registry_predecessor_head: predecessor,
        now: 20,
    }
}

fn fixture() -> Fixture {
    static SEQUENCE: AtomicU64 = AtomicU64::new(1);
    let serial = SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let directory =
        std::env::temp_dir().join(format!("hepta-science-{}-{serial}", std::process::id()));
    must(fs::create_dir(&directory));
    let owner_key = SigningKey::from_bytes(&[12; 32]);
    let reviewer_key = SigningKey::from_bytes(&[13; 32]);
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    };
    let withdrawal_registry = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let trust = ArtifactOwnerTrustV1 {
        registry_id: id("artifacts"),
        withdrawal_scope_digest: scope.digest(),
        minimum_registry_generation: generation(1),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer(&owner_key, "owner")],
        head_signers: vec![signer(&owner_key, "owner")],
    };
    let mut writer_lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("writer"),
        producer_id: id("trainer"),
        registry_id: id("artifacts"),
        withdrawal_scope_digest: scope.digest(),
        signer_id: id("owner"),
        signing_key_digest: Digest32::of_bytes(&owner_key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 10,
        expires_at: 1_000,
        signature: [0; 64],
    };
    writer_lease.signature = owner_key.sign(&writer_lease.signing_bytes()).to_bytes();
    let config = LearningArtifactOwnerServiceConfigV1 {
        root: directory.clone(),
        trust,
        writer_lease,
        required_current_head: None,
        withdrawal_registry: withdrawal_registry.clone(),
        storage_binding: digest("storage"),
        now: 20,
    };
    let mut service = must(LearningArtifactOwnerService::open(config.clone()));
    let baseline = request(
        &owner_key,
        service.registry(),
        &withdrawal_registry,
        manifest("baseline", None),
    );
    must(service.publish(baseline));
    let request = request(
        &owner_key,
        service.registry(),
        &withdrawal_registry,
        manifest("candidate", Some(id("baseline"))),
    );
    let policy = policy();
    let measurement = |gate: &ScientificComparisonPolicyV1, lower_bound, estimate, upper_bound| {
        ScientificMeasurementStatusV1::Measured(ScientificMeasurementV1 {
            comparison_digest: gate.comparison_digest,
            evidence_digest: digest("measured fixture evidence"),
            observations: 8,
            lower_bound,
            estimate,
            upper_bound,
        })
    };
    let mut review = SignedScientificCandidateReviewV1 {
        reviewer_id: id("reviewer"),
        authority_epoch: 1,
        policy_digest: policy.digest(),
        operation_id: request.operation_id.clone(),
        admission_digest: request.admission.admission_digest,
        expected_registry_predecessor_head: request.expected_registry_predecessor_head,
        report_digest: digest("independent full report"),
        task: measurement(&policy.task, -0.03, -0.02, -0.01),
        retention: measurement(&policy.retention, -0.01, 0.0, 0.01),
        total_cost: measurement(&policy.total_cost, 0.8, 0.9, 1.0),
        issued_at: 20,
        expires_at: 100,
        signature: [0; 64],
    };
    review.signature = reviewer_key.sign(&review.signing_bytes()).to_bytes();
    let publisher = must(ScientificCandidatePublisherV1::new(
        service,
        policy,
        signer(&reviewer_key, "reviewer"),
    ));
    Fixture {
        directory: TestDirectory(directory),
        config,
        publisher,
        request,
        review,
        reviewer_key,
    }
}

fn bytes_beneath(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut files = BTreeMap::new();
    for entry in must(fs::read_dir(root)) {
        let path = must(entry).path();
        if path.is_dir() {
            files.extend(bytes_beneath(&path));
        } else {
            files.insert(path.clone(), must(fs::read(path)));
        }
    }
    files
}

#[test]
fn accepted_measurements_publish_only_a_candidate_and_preserve_baseline() {
    let mut f = fixture();
    let baseline = f.publisher.registry().manifest(&id("baseline")).cloned();
    let receipt = must(f.publisher.publish(
        f.request.clone(),
        ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone())),
    ));
    assert!(!receipt.publication.authority.grants_any());
    assert_eq!(
        f.publisher.registry().manifest(&id("baseline")).cloned(),
        baseline
    );
    assert_eq!(
        f.publisher.registry().state(&id("candidate")),
        Some(ArtifactState::Candidate)
    );
    assert_eq!(
        must(f.publisher.publish(
            f.request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone()))
        )),
        receipt
    );
    let current = f.request.signed_current_head.clone();
    let config = LearningArtifactOwnerServiceConfigV1 {
        required_current_head: Some(current),
        now: 21,
        ..f.config.clone()
    };
    // Move only the publisher so its OS writer lock is actually released.
    let Fixture {
        publisher,
        request,
        review,
        reviewer_key,
        config: _,
        directory,
    } = f;
    drop(publisher);
    let service = must(LearningArtifactOwnerService::open(config));
    let mut publisher = must(ScientificCandidatePublisherV1::new(
        service,
        policy(),
        signer(&reviewer_key, "reviewer"),
    ));
    assert_eq!(
        must(publisher.publish(
            request,
            ScientificReviewEvidenceV1::Signed(Box::new(review))
        )),
        receipt
    );
    drop(publisher);
    drop(directory);
}

#[test]
fn missing_and_each_failed_measurement_leave_all_owner_bytes_unchanged() {
    let mut f = fixture();
    let before = bytes_beneath(&f.directory);
    assert!(matches!(
        f.publisher
            .publish(f.request.clone(), ScientificReviewEvidenceV1::Missing),
        Err(ScientificCandidateReviewError::MissingReview)
    ));
    for index in 0..3 {
        for unavailable in [false, true] {
            let mut review = f.review.clone();
            let slot = match index {
                0 => &mut review.task,
                1 => &mut review.retention,
                _ => &mut review.total_cost,
            };
            if unavailable {
                *slot = ScientificMeasurementStatusV1::Unavailable;
            } else if let ScientificMeasurementStatusV1::Measured(value) = slot {
                value.upper_bound = 9.0;
            }
            review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
            assert!(
                f.publisher
                    .publish(
                        f.request.clone(),
                        ScientificReviewEvidenceV1::Signed(Box::new(review))
                    )
                    .is_err()
            );
            assert_eq!(bytes_beneath(&f.directory), before);
        }
    }
    assert_eq!(f.publisher.registry().records().len(), 1);
}

#[test]
fn every_signed_field_and_measurement_is_covered_by_signature() {
    let mut f = fixture();
    let before = bytes_beneath(&f.directory);
    let mut variants = Vec::new();
    macro_rules! mutate {
        ($field:ident, $value:expr) => {{
            let mut r = f.review.clone();
            r.$field = $value;
            variants.push(r);
        }};
    }
    mutate!(reviewer_id, id("other"));
    mutate!(operation_id, id("other-operation"));
    mutate!(authority_epoch, 2);
    mutate!(policy_digest, digest("other-policy"));
    mutate!(admission_digest, digest("other-admission"));
    mutate!(expected_registry_predecessor_head, digest("other-head"));
    mutate!(report_digest, digest("other-report"));
    mutate!(issued_at, 19);
    mutate!(expires_at, 99);
    mutate!(signature, [0; 64]);
    for index in 0..3 {
        for field in 0..7 {
            let mut r = f.review.clone();
            let slot = match index {
                0 => &mut r.task,
                1 => &mut r.retention,
                _ => &mut r.total_cost,
            };
            if field == 6 {
                *slot = ScientificMeasurementStatusV1::Unavailable;
            } else if let ScientificMeasurementStatusV1::Measured(value) = slot {
                match field {
                    0 => value.comparison_digest = digest("other-comparison"),
                    1 => value.evidence_digest = digest("other-evidence"),
                    2 => value.observations += 1,
                    3 => value.lower_bound -= 0.001,
                    4 => value.estimate += 0.001,
                    _ => value.upper_bound += 0.001,
                }
            }
            variants.push(r);
        }
    }
    for review in variants {
        assert!(
            review.signature != f.review.signature
                || review.signing_bytes() != f.review.signing_bytes()
        );
        assert!(
            f.publisher
                .publish(
                    f.request.clone(),
                    ScientificReviewEvidenceV1::Signed(Box::new(review))
                )
                .is_err()
        );
        assert_eq!(bytes_beneath(&f.directory), before);
    }
}

#[test]
fn forged_payload_manifest_policy_and_expiry_reject_before_owner_write() {
    let mut f = fixture();
    let before = bytes_beneath(&f.directory);
    let mut variants = Vec::new();
    let mut wrong = f.request.clone();
    wrong.payload.push(1);
    variants.push(wrong);
    let mut wrong = f.request.clone();
    wrong.admission.validated_manifest.manifest.generation = generation(1);
    variants.push(wrong);
    let mut wrong = f.request.clone();
    wrong.admission.validated_manifest.manifest.bytes_digest = digest("substituted");
    variants.push(wrong);
    let mut wrong = f.request.clone();
    wrong.expected_registry_predecessor_head = Digest32::ZERO;
    variants.push(wrong);
    let mut wrong = f.request.clone();
    wrong.now = 101;
    variants.push(wrong);
    for request in variants {
        assert!(
            f.publisher
                .publish(
                    request,
                    ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone()))
                )
                .is_err()
        );
        assert_eq!(bytes_beneath(&f.directory), before);
    }
    f.publisher.policy.total_cost.maximum_upper_bound = 2.0;
    assert!(
        f.publisher
            .publish(
                f.request.clone(),
                ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone()))
            )
            .is_err()
    );
    assert_eq!(bytes_beneath(&f.directory), before);
}

#[test]
fn current_source_withdrawal_rejects_previously_signed_candidate() {
    let mut f = fixture();
    let before = bytes_beneath(&f.directory);
    let previous_frontier = f.publisher.service.withdrawal_registry().clone();
    let mut withdrawn = previous_frontier.clone();
    must(withdrawn.append(DatasetWithdrawalNoticeV1 {
        notice_id: id("withdraw"),
        dataset_digest: digest("dataset"),
        source_tombstone_digest: digest("tombstone"),
        authority_id: id("source-authority"),
        credential_chain_digest: digest("credential"),
        signing_key_digest: digest("key"),
        authority_epoch: 1,
        issued_at: 20,
    }));
    must(f.publisher.install_withdrawal_frontier(withdrawn));
    assert!(
        f.publisher
            .install_withdrawal_frontier(previous_frontier)
            .is_err()
    );
    assert!(matches!(
        f.publisher.publish(
            f.request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone()))
        ),
        Err(ScientificCandidateReviewError::Admission)
    ));
    assert_eq!(bytes_beneath(&f.directory), before);
}

#[test]
fn correctly_signed_invalid_metrics_still_fail_each_numeric_gate() {
    let mut f = fixture();
    let before = bytes_beneath(&f.directory);
    for index in 0..3 {
        for defect in 0..6 {
            let mut review = f.review.clone();
            let slot = match index {
                0 => &mut review.task,
                1 => &mut review.retention,
                _ => &mut review.total_cost,
            };
            if let ScientificMeasurementStatusV1::Measured(value) = slot {
                match defect {
                    0 => value.lower_bound = f64::NAN,
                    1 => value.estimate = f64::INFINITY,
                    2 => value.lower_bound = value.estimate + 1.0,
                    3 => value.observations = 0,
                    4 => value.evidence_digest = Digest32::ZERO,
                    _ => value.comparison_digest = digest("unregistered comparison"),
                }
            }
            review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
            assert!(matches!(
                f.publisher.publish(
                    f.request.clone(),
                    ScientificReviewEvidenceV1::Signed(Box::new(review))
                ),
                Err(ScientificCandidateReviewError::GateFailed(_))
            ));
            assert_eq!(bytes_beneath(&f.directory), before);
        }
    }
    let mut review = f.review.clone();
    if let ScientificMeasurementStatusV1::Measured(value) = &mut review.total_cost {
        value.lower_bound = -1.0;
    }
    review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
    assert!(matches!(
        f.publisher.publish(
            f.request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(review))
        ),
        Err(ScientificCandidateReviewError::GateFailed("total_cost"))
    ));
    assert_eq!(bytes_beneath(&f.directory), before);
}

#[test]
fn validly_readmitted_stale_generation_and_registry_parent_cannot_write() {
    let mut f = fixture();
    let before = bytes_beneath(&f.directory);
    let mut request = f.request.clone();
    let mut manifest = request.admission.validated_manifest.manifest.clone();
    manifest.generation = generation(1);
    request.admission = must(admit_manifest_at_withdrawal_head_v3(
        f.publisher.service.withdrawal_registry(),
        request.admission.withdrawal_head_digest,
        manifest,
        20,
    ));
    let mut review = f.review.clone();
    review.admission_digest = request.admission.admission_digest;
    review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
    assert!(matches!(
        f.publisher.publish(
            request,
            ScientificReviewEvidenceV1::Signed(Box::new(review))
        ),
        Err(ScientificCandidateReviewError::Predecessor)
    ));
    let mut request = f.request.clone();
    request.expected_registry_predecessor_head = digest("old registry head");
    let mut review = f.review.clone();
    review.expected_registry_predecessor_head = request.expected_registry_predecessor_head;
    review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
    assert!(matches!(
        f.publisher.publish(
            request,
            ScientificReviewEvidenceV1::Signed(Box::new(review))
        ),
        Err(ScientificCandidateReviewError::Predecessor)
    ));
    assert_eq!(bytes_beneath(&f.directory), before);
}

#[test]
fn independent_host_reviewer_trust_cannot_be_replaced_by_request() {
    let mut f = fixture();
    let before = bytes_beneath(&f.directory);
    let mut review = f.review.clone();
    review.signature = SigningKey::from_bytes(&[88; 32])
        .sign(&review.signing_bytes())
        .to_bytes();
    assert!(matches!(
        f.publisher.publish(
            f.request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(review))
        ),
        Err(ScientificCandidateReviewError::Signature)
    ));
    let mut review = f.review.clone();
    review.reviewer_id = id("trainer");
    review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
    assert!(matches!(
        f.publisher.publish(
            f.request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(review))
        ),
        Err(ScientificCandidateReviewError::ReviewerAuthority)
    ));
    f.publisher.reviewer.revoked_at = Some(20);
    assert!(matches!(
        f.publisher.publish(
            f.request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone()))
        ),
        Err(ScientificCandidateReviewError::ReviewerAuthority)
    ));
    assert_eq!(bytes_beneath(&f.directory), before);
}

#[test]
fn frozen_task_margin_is_strict_while_retention_and_cost_limits_are_inclusive() {
    let mut f = fixture();
    let before = bytes_beneath(&f.directory);
    let mut review = f.review.clone();
    if let ScientificMeasurementStatusV1::Measured(value) = &mut review.task {
        value.upper_bound = f.publisher.policy.task.maximum_upper_bound;
    }
    review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
    assert!(matches!(
        f.publisher.publish(
            f.request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(review))
        ),
        Err(ScientificCandidateReviewError::GateFailed("task"))
    ));
    assert_eq!(bytes_beneath(&f.directory), before);
    let mut review = f.review.clone();
    if let ScientificMeasurementStatusV1::Measured(value) = &mut review.retention {
        value.upper_bound = f.publisher.policy.retention.maximum_upper_bound;
    }
    review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
    must(f.publisher.publish(
        f.request.clone(),
        ScientificReviewEvidenceV1::Signed(Box::new(review)),
    ));
    assert_eq!(
        f.publisher.registry().state(&id("candidate")),
        Some(ArtifactState::Candidate)
    );
}

#[test]
fn acknowledged_artifact_rejects_different_operation_even_with_a_fresh_signature() {
    let mut f = fixture();
    let receipt = must(f.publisher.publish(
        f.request.clone(),
        ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone())),
    ));
    let before = bytes_beneath(&f.directory);
    let mut request = f.request.clone();
    request.operation_id = id("different-operation");
    assert!(matches!(
        f.publisher.publish(
            request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone()))
        ),
        Err(ScientificCandidateReviewError::ReviewBinding)
    ));
    assert_eq!(bytes_beneath(&f.directory), before);
    let mut review = f.review.clone();
    review.operation_id = request.operation_id.clone();
    review.signature = f.reviewer_key.sign(&review.signing_bytes()).to_bytes();
    assert!(matches!(
        f.publisher.publish(
            request,
            ScientificReviewEvidenceV1::Signed(Box::new(review))
        ),
        Err(ScientificCandidateReviewError::Predecessor)
    ));
    assert_eq!(bytes_beneath(&f.directory), before);
    assert_eq!(
        must(f.publisher.publish(
            f.request.clone(),
            ScientificReviewEvidenceV1::Signed(Box::new(f.review.clone()))
        )),
        receipt
    );
}
