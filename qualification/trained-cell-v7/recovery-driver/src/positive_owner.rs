//! Exact-request research recovery. A signed proposal permits only its original
//! predecessor or original candidate registry, including an unacknowledged
//! CURRENT side effect. No new operation or replayed optimizer update is made.

use crate::owner::digest;
use crate::owner::id;
use crate::owner::manifest;
use crate::owner::request;
use crate::owner::trust;
use crate::report::Inputs;
use crate::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub enum Mode {
    Prepare,
    Execute,
}
pub struct Context {
    pub owner: LearningArtifactOwnerService,
    pub config: LearningArtifactOwnerServiceConfigV1,
    pub baseline: LearningArtifactManifestV2,
    pub candidate: LearningArtifactManifestV2,
    pub request: LearningArtifactPublishRequestV1,
}

// Rebuild the exact intent-derived registry in memory. The caller must not use
// the current owner as the prefix after a crash: CURRENT may already include the
// same candidate, which would create a different request and fail recovery.
fn staged(
    prefix: &ArtifactRegistry,
    withdrawals: &DatasetWithdrawalRegistry,
    request: &LearningArtifactPublishRequestV1,
) -> Result<ArtifactRegistry> {
    let transaction = ArtifactPublicationTransactionV1::begin(
        request.operation_id.clone(),
        request.admission.clone(),
        withdrawals,
        prefix,
        request.expected_registry_predecessor_head,
        request.now,
    )?;
    let full = &request.admission.validated_manifest.manifest;
    let mut result = prefix.clone();
    result.append(ArtifactEvent::Register {
        event_id: id(&format!(
            "artifact-publication:{}",
            transaction.intent().intent_digest
        ))?,
        manifest: ArtifactManifest {
            artifact_id: full.artifact_id.clone(),
            kind: full.kind,
            generation: full.generation,
            predecessor_id: if full.predecessor_ids.len() == 1 {
                full.predecessor_ids.first().cloned()
            } else {
                None
            },
            content_digest: full.bytes_digest,
            objective_digest: full.objective_class_digest,
            support_digest: request.admission.validated_manifest.manifest_digest,
            producer_id: full.producer_id.clone(),
            compatibility_digest: full.compatibility_digest,
            encoded_size_bytes: full.encoded_size_bytes,
        },
    })?;
    Ok(result)
}

pub fn open(
    inputs: &Inputs,
    audits: [Digest32; 3],
    root: &Path,
    issued: u64,
    mode: Mode,
) -> Result<Context> {
    let key = SigningKey::from_bytes(&[33; 32]); // public local fixture owner, never production trust
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("local-qualified-research")?,
        registry_id: id("research-withdrawals")?,
        scope_id: id("v7-qualified-research")?,
    };
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner_trust = ArtifactOwnerTrustV1 {
        registry_id: id("research-artifacts")?,
        withdrawal_scope_digest: scope.digest(),
        minimum_registry_generation: Generation::new(1)?,
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![trust(&key, "research-owner-ephemeral", issued)?],
        head_signers: vec![trust(&key, "research-owner-ephemeral", issued)?],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("research-writer")?,
        producer_id: id("research-bundle-exporter")?,
        registry_id: id("research-artifacts")?,
        withdrawal_scope_digest: scope.digest(),
        signer_id: id("research-owner-ephemeral")?,
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: issued,
        expires_at: issued + 3600,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let baseline = manifest(
        "all12-typed-warmup-v5",
        &inputs.predecessor,
        None,
        inputs,
        issued,
    )?;
    let mut candidate = manifest(
        "all12-typed-candidate-v5",
        &inputs.candidate,
        Some(id("all12-typed-warmup-v5")?),
        inputs,
        issued,
    )?;
    candidate.lineage_digests.extend(audits);
    let initial = ArtifactRegistry::new();
    let baseline_request = request(
        &key,
        &initial,
        &withdrawals,
        baseline.clone(),
        inputs.predecessor.clone(),
        issued,
    )?;
    let baseline_registry = staged(&initial, &withdrawals, &baseline_request)?;
    let candidate_request = request(
        &key,
        &baseline_registry,
        &withdrawals,
        candidate.clone(),
        inputs.candidate.clone(),
        issued,
    )?;
    let candidate_registry = staged(&baseline_registry, &withdrawals, &candidate_request)?;
    let required_current_head = match mode {
        Mode::Prepare => {
            fs::create_dir(root)?;
            None
        }
        Mode::Execute => Some(baseline_request.signed_current_head.clone()),
    };
    let config = LearningArtifactOwnerServiceConfigV1 {
        root: root.to_path_buf(),
        trust: owner_trust,
        writer_lease: lease,
        required_current_head,
        withdrawal_registry: withdrawals,
        storage_binding: digest("ephemeral-research-storage.v1"),
        now: issued,
    };
    let mut owner = LearningArtifactOwnerService::open(config.clone())?;
    match mode {
        Mode::Prepare => {
            ensure(
                !owner.publish(baseline_request)?.authority.grants_any(),
                "baseline granted authority",
            )?;
        }
        Mode::Execute => {
            ensure(
                owner.registry().records() == baseline_registry.records()
                    || owner.registry().records() == candidate_registry.records(),
                "owner differs from the exact signed predecessor/candidate histories",
            )?;
            ensure(
                owner
                    .recovery_required()
                    .is_none_or(|operation| operation == &candidate_request.operation_id),
                "another operation requires recovery",
            )?;
        }
    }
    Ok(Context {
        owner,
        config,
        baseline,
        candidate,
        request: candidate_request,
    })
}
