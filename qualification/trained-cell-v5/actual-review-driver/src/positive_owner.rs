//! A local research owner with a separately installed external reviewer key.
//! This owner key is public fixture material; no production trust is installed.

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

pub fn open(
    inputs: &Inputs,
    audits: [Digest32; 3],
    root: &Path,
    issued: u64,
    mode: Mode,
) -> Result<Context> {
    let owner_key = SigningKey::from_bytes(&[33; 32]);
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("local-qualified-research")?,
        registry_id: id("research-withdrawals")?,
        scope_id: id("v6-qualified-research")?,
    };
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner_trust = ArtifactOwnerTrustV1 {
        registry_id: id("research-artifacts")?,
        withdrawal_scope_digest: scope.digest(),
        minimum_registry_generation: Generation::new(1)?,
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![trust(&owner_key, "research-owner-ephemeral", issued)?],
        head_signers: vec![trust(&owner_key, "research-owner-ephemeral", issued)?],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("research-writer")?,
        producer_id: id("research-bundle-exporter")?,
        registry_id: id("research-artifacts")?,
        withdrawal_scope_digest: scope.digest(),
        signer_id: id("research-owner-ephemeral")?,
        signing_key_digest: Digest32::of_bytes(&owner_key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: issued,
        expires_at: issued + 3600,
        signature: [0; 64],
    };
    lease.signature = owner_key.sign(&lease.signing_bytes()).to_bytes();
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
    let baseline_request = request(
        &owner_key,
        &ArtifactRegistry::new(),
        &withdrawals,
        baseline.clone(),
        inputs.predecessor.clone(),
        issued,
    )?;
    let expected_head = baseline_request.signed_current_head.clone();
    let required_current_head = match mode {
        Mode::Prepare => {
            fs::create_dir(root)?;
            None
        }
        Mode::Execute => Some(expected_head.clone()),
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
        Mode::Execute => ensure(
            owner.registry().records().len() == 1
                && owner.registry().snapshot().head_digest == expected_head.witness.head_digest,
            "prepared owner changed or proposal already executed",
        )?,
    }
    let candidate_request = request(
        &owner_key,
        owner.registry(),
        owner.withdrawal_registry(),
        candidate.clone(),
        inputs.candidate.clone(),
        issued,
    )?;
    Ok(Context {
        owner,
        config,
        baseline,
        candidate,
        request: candidate_request,
    })
}
