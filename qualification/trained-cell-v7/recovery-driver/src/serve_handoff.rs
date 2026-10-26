//! Read-only actual typed serving after externally signed research admission.
//! A distinct local selector exercises current-view selection and rollback;
//! no production selector or dispatch authority is installed.

use crate::*;
use codex_hepta_neuron::TrainingHandoffBundleV7;
use codex_hepta_neuron::TrainingHandoffErrorV7;
use codex_hepta_neuron::training_handoff_compatibility_digest_v7;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn selection(
    owner: &LearningArtifactOwnerService,
    trust: &ArtifactOwnerTrustV1,
    manifest: &LearningArtifactManifestV2,
    now: u64,
) -> Result<VerifiedArtifactSelectionV1> {
    let key = SigningKey::from_bytes(&[35; 32]);
    let current = owner.current_registry_view(now)?;
    let compact = owner
        .registry()
        .manifest(&manifest.artifact_id)
        .ok_or("published compact manifest missing")?;
    let mut signed = SignedArtifactSelectionV1 {
        selection_id: owner::id(&format!("research-select:{}", manifest.artifact_id))?,
        artifact_id: manifest.artifact_id.clone(),
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: trust.withdrawal_scope_digest,
        registry_head_digest: current.receipt().head_digest,
        current_witness_digest: current.witness_digest(),
        current_trust_digest: current.trust_digest(),
        artifact_kind: compact.kind,
        artifact_generation: compact.generation,
        predecessor_id: compact.predecessor_id.clone(),
        content_digest: compact.content_digest,
        objective_digest: compact.objective_digest,
        support_digest: compact.support_digest,
        compatibility_digest: compact.compatibility_digest,
        encoded_size_bytes: compact.encoded_size_bytes,
        selector_id: owner::id("local-research-selector")?,
        selector_credential_digest: owner::digest(
            "local read-only research selector; no production authority",
        ),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        issued_at: now,
        expires_at: now + 300,
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let verifier = ArtifactSelectionVerifierV1::new(
        ArtifactSelectionTrustV1 {
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: trust.withdrawal_scope_digest,
            minimum_authority_epoch: 1,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: owner::id("local-research-selector")?,
                verifying_key: key.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 1,
                valid_from: now,
                expires_at: now + 300,
                revoked_at: None,
            }],
        },
        trust,
    )?;
    Ok(verifier.verify(&signed, &current, now)?)
}

fn files(
    root: &Path,
    owner: &LearningArtifactOwnerService,
    manifest: &LearningArtifactManifestV2,
    now: u64,
) -> Result<(std::fs::File, std::fs::File)> {
    let receipt = owner.current_registry_view(now)?.receipt();
    Ok((
        std::fs::File::open(root.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        )))?,
        std::fs::File::open(root.join("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.bytes_digest
        )))?,
    ))
}

fn decode(
    bytes: &[u8],
    manifest: &ArtifactManifest,
    predecessor: Option<Digest32>,
) -> std::result::Result<TrainingHandoffBundleV7, TrainingHandoffErrorV7> {
    let bundle = TrainingHandoffBundleV7::decode(bytes, manifest.content_digest)?;
    if bundle.artifact_id() != &manifest.artifact_id
        || bundle.generation() != manifest.generation
        || bundle.content_digest() != manifest.content_digest
        || bundle.protocol_digest() != manifest.objective_digest
        || bundle.predecessor_digest() != predecessor
        || bytes.len() as u64 != manifest.encoded_size_bytes
        || manifest.compatibility_digest != training_handoff_compatibility_digest_v7()
    {
        return Err(TrainingHandoffErrorV7::Binding);
    }
    Ok(bundle)
}

pub fn roundtrip(
    mut config: LearningArtifactOwnerServiceConfigV1,
    required: SignedCurrentArtifactHeadV1,
    baseline: LearningArtifactManifestV2,
    candidate: LearningArtifactManifestV2,
    inputs: &parity::Inputs,
    now: u64,
) -> Result<Value> {
    config.required_current_head = Some(required);
    config.now = now;
    let owner = LearningArtifactOwnerService::open(config.clone())?;
    ensure(
        owner.recovery_required().is_none() && owner.registry().records().len() == 2,
        "published owner did not reopen completely",
    )?;
    let before = owner::inventory(&config.root)?;
    let head = owner.current_registry_view(now)?.receipt().head_digest;
    let (snapshot, payload) = files(&config.root, &owner, &candidate, now)?;
    let mut typed = OwnerTypedSelectedCandidateV5::load(
        snapshot,
        payload,
        selection(&owner, &config.trust, &candidate, now)?,
        OwnerCandidateContextV5 {
            owner: &owner,
            manifest: &candidate,
            now,
        },
        training_handoff_compatibility_digest_v7(),
        |bytes, manifest| decode(bytes, manifest, Some(baseline.bytes_digest)),
    )?;
    let candidate_parity = parity::compare_handoff(inputs, 1, &mut typed, &owner, now)?;
    let candidate_dump = typed.with_owner(&owner, now, handoff_dump::dump)??;
    let (snapshot, payload) = files(&config.root, &owner, &baseline, now)?;
    typed.rollback_to_predecessor(
        snapshot,
        payload,
        selection(&owner, &config.trust, &baseline, now)?,
        OwnerCandidateContextV5 {
            owner: &owner,
            manifest: &baseline,
            now,
        },
        |bytes, manifest| decode(bytes, manifest, None),
    )?;
    let predecessor_parity = parity::compare_handoff(inputs, 0, &mut typed, &owner, now)?;
    let baseline_dump = typed.with_owner(&owner, now, handoff_dump::dump)??;
    let exports = [
        write_dump(&config.root, "candidate", &candidate_dump)?,
        write_dump(&config.root, "predecessor", &baseline_dump)?,
    ];
    ensure(
        owner::inventory(&config.root)? == before
            && owner.current_registry_view(now)?.receipt().head_digest == head,
        "read-only serving/rollback changed owner history",
    )?;
    Ok(
        json!({"required_current_reopen":true,"candidate":candidate_parity,"predecessor_after_explicit_rollback":predecessor_parity,
        "owner_bytes_unchanged_during_serving_and_rollback":true,"registry_history_unchanged":true,
        "checkpoint_exports":exports,"rollback_scope":"select exact immutable serving+optimizer+controller predecessor; no optimizer execution or owner-history rewrite","production_activation":false}),
    )
}

fn write_dump(owner_root: &Path, role: &str, value: &Value) -> Result<Value> {
    use std::io::Write;
    let name = format!("checkpoint-{role}.json");
    let path = owner_root
        .parent()
        .ok_or("owner parent missing")?
        .join(&name);
    let bytes = serde_json::to_vec_pretty(value)?;
    match fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
    {
        Ok(mut file) => {
            file.write_all(&bytes)?;
            file.sync_all()?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            ensure(fs::read(&path)? == bytes, "checkpoint export changed")?
        }
        Err(error) => return Err(error.into()),
    }
    Ok(json!({"role":role,"file":name,"sha256":Digest32::of_bytes(&bytes).to_string()}))
}
