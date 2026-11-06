use super::*;
use crate::test_support::FixtureValue;
use crate::*;
use codex_hepta_types::AuthorityPosture;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

const WORKER_RECEIPT: &[u8] = b"synthetic task BP fixture with full cost receipt";
static NEXT: AtomicU64 = AtomicU64::new(1);

fn id(text: &str) -> StableId {
    StableId::new(text).fixture("id")
}

fn digest(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

fn generation() -> Generation {
    Generation::new(1).fixture("generation")
}

fn handoff(outcome: &HcsnTrainingOutcomeV1) -> Vec<u8> {
    let b = &outcome.binding;
    let mut bytes = HANDOFF_MAGIC.to_vec();
    bytes.push(match outcome.rule {
        HcsnLearningRuleV1::TaskLossBackpropagation => 0,
        HcsnLearningRuleV1::EligibilityModulation => 1,
        HcsnLearningRuleV1::NduCredit => 2,
    });
    for value in [
        Digest32::of_bytes(b.operation_id.as_str().as_bytes()),
        b.request_digest,
        b.training_code_digest,
        b.runtime_tuple_digest,
        b.graph_digest,
        b.time_profile_digest,
        b.base_checkpoint_digest,
        b.dataset_digest,
        outcome.candidate_digest,
        outcome.gradient_digest,
        outcome.receipt_digest,
    ] {
        bytes.extend_from_slice(value.as_array());
    }
    for value in [
        b.target_generation.get(),
        b.optimizer_steps,
        u64::from(b.logical_cells),
        b.trainable_parameters,
        outcome.completed_optimizer_steps,
        u64::from(outcome.gradient_cells),
        outcome.gradient_parameters,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes
}

struct Fixture {
    root: PathBuf,
    config: LearningArtifactOwnerServiceConfigV1,
    binding: HcsnTrainingBindingV1,
    outcome: HcsnTrainingOutcomeV1,
    request: LearningArtifactPublishRequestV1,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-hcsn-publication-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&root).fixture("create unique test dir");
        let binding = HcsnTrainingBindingV1 {
            operation_id: id("hcsn-training-operation"),
            request_digest: digest("admitted-request-with-owner-epochs"),
            training_code_digest: digest("worker-source"),
            runtime_tuple_digest: digest("runtime"),
            graph_digest: digest("two-hx-cells"),
            time_profile_digest: digest("time-profile"),
            base_checkpoint_digest: digest("base-checkpoint"),
            dataset_digest: digest("dataset"),
            target_generation: generation(),
            optimizer_steps: 2,
            logical_cells: 2,
            trainable_parameters: 40,
        };
        let payload = b"synthetic tensor checkpoint".to_vec();
        let outcome = HcsnTrainingOutcomeV1 {
            binding: binding.clone(),
            rule: HcsnLearningRuleV1::TaskLossBackpropagation,
            candidate_digest: Digest32::of_bytes(&payload),
            gradient_digest: digest("actual-task-gradient-fixture"),
            receipt_digest: Digest32::of_bytes(WORKER_RECEIPT),
            completed_optimizer_steps: 2,
            gradient_parameters: 40,
            gradient_cells: 2,
        };
        let scope = DatasetWithdrawalScopeV1 {
            authority_domain_id: id("test-authority"),
            registry_id: id("withdrawals"),
            scope_id: id("test-scope"),
        };
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
        let key = SigningKey::from_bytes(&[19; 32]);
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("test-signer"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: 1,
            expires_at: 1000,
            revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("artifacts"),
            withdrawal_scope_digest: scope.digest(),
            minimum_registry_generation: generation(),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("test-lease"),
            producer_id: id("worker"),
            registry_id: id("artifacts"),
            withdrawal_scope_digest: scope.digest(),
            signer_id: id("test-signer"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: 1,
            expires_at: 1000,
            signature: [0; 64],
        };
        lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
        let manifest = LearningArtifactManifestV2 {
            artifact_id: id("hcsn-candidate"),
            kind: ArtifactKind::Model,
            generation: generation(),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![binding.dataset_digest],
            lineage_digests: vec![
                binding.request_digest,
                binding.graph_digest,
                binding.time_profile_digest,
                binding.base_checkpoint_digest,
                outcome.gradient_digest,
                outcome.receipt_digest,
                Digest32::of_bytes(&handoff(&outcome)),
            ],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: outcome.candidate_digest,
            encoded_size_bytes: payload.len() as u64,
            training_code_digest: binding.training_code_digest,
            runtime_tuple_digest: binding.runtime_tuple_digest,
            device_profile_digest: digest("cpu"),
            objective_class_digest: digest("task-mse"),
            compatibility_digest: digest("hx-graph-v1"),
            schema_profile_digest: digest("checkpoint-v1"),
            normalization_digest: digest("identity"),
            producer_id: id("worker"),
            created_at: 1,
            expires_at: 1000,
        };
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest,
            10,
        )
        .fixture("manifest admission");
        let host = LearningArtifactOwnerHost::open(&root, trust.clone(), lease.clone(), 10)
            .fixture("preview owner");
        let mut registry = ArtifactRegistry::new();
        let transaction = ArtifactPublicationTransactionV1::begin(
            binding.operation_id.clone(),
            admission.clone(),
            &withdrawals,
            &registry,
            Digest32::ZERO,
            10,
        )
        .fixture("preview transaction");
        host.stage_compatibility_registration(&transaction, &mut registry, 10)
            .fixture("preview registry");
        drop(host);
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: scope.digest(),
            binding: digest("storage"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("artifacts"),
                generation: generation(),
                head_digest: registry.snapshot().head_digest,
                predecessor_head_digest: Digest32::ZERO,
                authority_epoch: 1,
                signer_id: id("test-signer"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: 10,
                expires_at: 1000,
            },
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        let request = LearningArtifactPublishRequestV1 {
            operation_id: binding.operation_id.clone(),
            admission,
            payload,
            signed_current_head: signed,
            expected_registry_predecessor_head: Digest32::ZERO,
            now: 10,
        };
        let config = LearningArtifactOwnerServiceConfigV1 {
            root: root.clone(),
            trust,
            writer_lease: lease,
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: digest("storage"),
            now: 10,
        };
        Self {
            root,
            config,
            binding,
            outcome,
            request,
        }
    }

    fn prepare(&self) -> Result<PreparedHcsnPublicationV1, HcsnCandidateErrorV1> {
        prepare_hcsn_publication_v1(
            &self.binding,
            &handoff(&self.outcome),
            WORKER_RECEIPT,
            self.request.clone(),
        )
    }
}

#[test]
fn task_bp_candidate_uses_fenced_owner_retries_and_reopens() {
    let fixture = Fixture::new();
    let prepared = fixture.prepare().fixture("checked BP handoff");
    let mut owner = LearningArtifactOwnerService::open(fixture.config.clone()).fixture("owner");
    let receipt = prepared.clone().publish(&mut owner).fixture("publish");
    assert_eq!(prepared.publish(&mut owner).fixture("retry"), receipt);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        owner.registry().state(&id("hcsn-candidate")),
        Some(ArtifactState::Candidate)
    );
    drop(owner);
    let mut config = fixture.config.clone();
    config.required_current_head = Some(fixture.request.signed_current_head.clone());
    let reopened = LearningArtifactOwnerService::open(config).fixture("reopen");
    assert_eq!(
        reopened.registry().snapshot().head_digest,
        receipt.registry_head_digest
    );
    assert_eq!(reopened.recovery_required(), None);
}

#[test]
fn credit_and_local_plasticity_are_not_task_gradients() {
    let mut fixture = Fixture::new();
    for rule in [
        HcsnLearningRuleV1::NduCredit,
        HcsnLearningRuleV1::EligibilityModulation,
    ] {
        fixture.outcome.rule = rule;
        assert_eq!(
            fixture.prepare().err(),
            Some(HcsnCandidateErrorV1::LearningRuleMismatch)
        );
    }
}

#[test]
fn payload_receipt_or_model_identity_changes_are_rejected_before_writing() {
    let mut fixture = Fixture::new();
    fixture.outcome.binding.base_checkpoint_digest = digest("different-model");
    assert_eq!(
        fixture.prepare().err(),
        Some(HcsnCandidateErrorV1::RequestMismatch)
    );
    fixture.outcome.binding = fixture.binding.clone();
    fixture.outcome.receipt_digest = digest("altered-cost-receipt");
    assert_eq!(
        fixture.prepare().err(),
        Some(HcsnCandidateErrorV1::IncompleteBackpropagation)
    );
    fixture.outcome.receipt_digest = Digest32::of_bytes(WORKER_RECEIPT);
    fixture.request.payload.push(0);
    assert_eq!(
        fixture.prepare().err(),
        Some(HcsnCandidateErrorV1::PayloadMismatch)
    );
}

#[test]
fn partial_steps_or_disconnected_cells_cannot_be_published_as_complete() {
    let mut fixture = Fixture::new();
    fixture.outcome.completed_optimizer_steps = 1;
    assert_eq!(
        fixture.prepare().err(),
        Some(HcsnCandidateErrorV1::IncompleteBackpropagation)
    );
    fixture.outcome.completed_optimizer_steps = 2;
    fixture.outcome.gradient_cells = 1;
    assert_eq!(
        fixture.prepare().err(),
        Some(HcsnCandidateErrorV1::IncompleteBackpropagation)
    );
    fixture.outcome.gradient_cells = 2;
    fixture.outcome.gradient_parameters = 39;
    assert_eq!(
        fixture.prepare().err(),
        Some(HcsnCandidateErrorV1::IncompleteBackpropagation)
    );
}

#[test]
fn publication_still_revalidates_owner_authority() {
    let fixture = Fixture::new();
    let prepared = fixture.prepare().fixture("prepare");
    let mut config = fixture.config.clone();
    config.trust.writer_signers[0].revoked_at = Some(5);
    assert!(LearningArtifactOwnerService::open(config).is_err());
    let mut owner = LearningArtifactOwnerService::open(fixture.config.clone()).fixture("owner");
    let mut request = fixture.request.clone();
    request.signed_current_head.signature[0] ^= 1;
    let invalid = prepare_hcsn_publication_v1(
        &fixture.binding,
        &handoff(&fixture.outcome),
        WORKER_RECEIPT,
        request,
    )
    .fixture("content checks do not replace signatures");
    assert!(invalid.publish(&mut owner).is_err());
    // The same stable operation can reconcile its durable partial publication.
    assert!(prepared.publish(&mut owner).is_ok());
}

#[test]
fn handoff_rejects_unknown_schema_trailing_data_and_operation_rebinding() {
    let fixture = Fixture::new();
    let bytes = handoff(&fixture.outcome);
    assert_eq!(
        decode_hcsn_handoff_v1(&fixture.binding.operation_id, &bytes).fixture("decode"),
        fixture.outcome
    );
    let mut extra = bytes.clone();
    extra.push(0);
    assert_eq!(
        decode_hcsn_handoff_v1(&fixture.binding.operation_id, &extra).err(),
        Some(HcsnCandidateErrorV1::InvalidHandoff)
    );
    assert_eq!(
        decode_hcsn_handoff_v1(&id("another-operation"), &bytes).err(),
        Some(HcsnCandidateErrorV1::RequestMismatch)
    );
    let mut unknown = bytes;
    unknown[HANDOFF_MAGIC.len()] = 9;
    assert_eq!(
        decode_hcsn_handoff_v1(&fixture.binding.operation_id, &unknown).err(),
        Some(HcsnCandidateErrorV1::InvalidHandoff)
    );
}

#[test]
fn withdrawal_after_preparation_blocks_publication() {
    let fixture = Fixture::new();
    let prepared = fixture.prepare().fixture("prepare before withdrawal");
    let mut owner = LearningArtifactOwnerService::open(fixture.config.clone()).fixture("owner");
    let mut withdrawals = fixture.config.withdrawal_registry.clone();
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdraw-after-training"),
            dataset_digest: fixture.binding.dataset_digest,
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("test-authority"),
            credential_chain_digest: digest("credentials"),
            signing_key_digest: digest("notice-key"),
            authority_epoch: 1,
            issued_at: 10,
        })
        .fixture("withdraw dataset");
    owner
        .install_withdrawal_frontier(withdrawals)
        .fixture("new frontier");
    assert!(prepared.publish(&mut owner).is_err());
    assert_eq!(owner.registry().state(&id("hcsn-candidate")), None);
}
