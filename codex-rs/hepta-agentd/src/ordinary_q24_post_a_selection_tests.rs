//! The independent Selector signs only the actual published registry/payload.
//! File appearance below is a scheduling hint, never a publication receipt.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Duration;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::post_a_artifact_inputs;
use super::post_a_launch::RunningOrdinaryPostA;
use super::post_a_plan::OriginalPostAPlan;
use crate::cell_q24_publication_driver::validation::Decision;

pub(super) struct OriginalSelectedArtifactData {
    pub(super) selection: SignedArtifactSelectionV1,
    pub(super) manifest: CellBackendManifestV2,
    pub(super) registry: RegistrySnapshotReceipt,
}

/// Await the original writer's complete Acknowledged-format data before asking
/// the strict reader to validate it. A partial create-only record is not read
/// as a completed publication and does not trigger an owner reopen or repair.
pub(super) async fn wait_for_original_publication(
    running: &RunningOrdinaryPostA,
    decision: &Decision,
) -> anyhow::Result<()> {
    anyhow::ensure!(
        decision.adopts(),
        "retention creates no Artifact publication"
    );
    let operation = Digest32::of_bytes(decision.artifact_operation.as_str().as_bytes());
    let path = running
        .plan
        .root
        .publication_inputs
        .artifact_root
        .join("transactions")
        .join(format!("{operation}-4.checkpoint"));
    loop {
        running.require_live()?;
        match OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(&path)
        {
            Ok(mut file) => {
                let metadata = file.metadata()?;
                anyhow::ensure!(
                    metadata.is_file()
                        && metadata.nlink() == 1
                        && metadata.uid() == 60001
                        && metadata.gid() == 60001
                        && metadata.mode() == 0o100600
                        && metadata.len() <= 16 * 1024,
                    "actual Artifact checkpoint file differs"
                );
                let mut bytes = Vec::new();
                Read::by_ref(&mut file)
                    .take(16 * 1024 + 1)
                    .read_to_end(&mut bytes)?;
                anyhow::ensure!(bytes.len() <= 16 * 1024, "Artifact checkpoint data bound");
                if bytes.last() == Some(&b'\n')
                    && bytes.iter().filter(|b| **b == b'\n').count() == 13
                {
                    let text = std::str::from_utf8(&bytes)?;
                    let lines: Vec<_> = text.lines().collect();
                    anyhow::ensure!(
                        lines.len() == 13
                            && lines[0] == "HEPTA-ARTIFACT-CHECKPOINT-V1"
                            && lines[1] == decision.artifact_operation.as_str()
                            && lines[2] == "4"
                            && lines[10] != "-"
                            && lines[11] != "-"
                            && lines[12] != "-",
                        "actual Artifact scheduling record differs"
                    );
                    // No receipt is constructed from these fields. The next
                    // step uses the original authenticated CURRENT reader and
                    // its actual registry/withdrawal codecs, without retries.
                    return running.require_live();
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

pub(super) fn sign_original_selection(
    plan: &OriginalPostAPlan,
    decision: &Decision,
    expected_current: &SignedCurrentArtifactHeadV1,
) -> anyhow::Result<OriginalSelectedArtifactData> {
    decision.require_root_publication()?;
    let inputs = &plan.root.publication_inputs;
    let now = crate::authbus_ingress::now_ms()?;
    let reader = post_a_artifact_inputs::original_reader(inputs, now)?;
    let current = reader.read_original_registry(now)?;
    anyhow::ensure!(
        current.receipt().head_digest == expected_current.witness.head_digest,
        "actual Artifact owner did not publish the expected signed head"
    );
    let registry = post_a_artifact_inputs::read_registry(inputs, current.receipt())?;
    let candidate = registry
        .manifest(&decision.bundle.artifact_id)
        .filter(|value| {
            registry.is_eligible(&value.artifact_id)
                && value.kind == ArtifactKind::Model
                && value.generation == decision.bundle.generation
        })
        .ok_or_else(|| anyhow::anyhow!("actual selected original Artifact is unavailable"))?;
    let payload = read_candidate_payload(
        open_original_data(&inputs.artifact_root.join("payloads").join(format!(
            "{}-{}.bin",
            candidate.artifact_id, candidate.content_digest
        )))?,
        &registry,
        &candidate.artifact_id,
    )?;
    let manifest: CellBackendManifestV2 = serde_json::from_slice(&payload)?;
    anyhow::ensure!(
        serde_json::to_vec(&manifest)? == payload,
        "actual selected manifest is not canonical"
    );
    crate::cell_composed_q24::validate_manifest(&decision.bundle, &manifest)?;
    let key = SigningKey::from_bytes(&[62; 32]);
    let selector = inputs
        .selector_trust
        .selectors
        .iter()
        .find(|value| value.id == "test-independent-selector")
        .ok_or_else(|| anyhow::anyhow!("original independent Selector absent"))?;
    let expires = post_a_artifact_inputs::original_expiry(plan, now)?.min(selector.expires_at);
    anyhow::ensure!(
        selector.verifying_key == key.verifying_key().to_bytes()
            && selector.id != candidate.producer_id.as_str()
            && selector.revoked_at.is_none()
            && now >= selector.valid_from
            && now < expires,
        "original independent Selector role/key/window differs"
    );
    let mut signed = SignedArtifactSelectionV1 {
        selection_id: StableId::new("ordinary-original-next-task-selection")?,
        artifact_id: candidate.artifact_id.clone(),
        registry_id: StableId::new(&inputs.selector_trust.registry_id)?,
        withdrawal_scope_digest: Digest32::from_array(inputs.selector_trust.withdrawal_scope),
        registry_head_digest: current.receipt().head_digest,
        current_witness_digest: current.witness_digest(),
        current_trust_digest: current.trust_digest(),
        artifact_kind: candidate.kind,
        artifact_generation: candidate.generation,
        predecessor_id: candidate.predecessor_id.clone(),
        content_digest: candidate.content_digest,
        objective_digest: candidate.objective_digest,
        support_digest: candidate.support_digest,
        compatibility_digest: candidate.compatibility_digest,
        encoded_size_bytes: candidate.encoded_size_bytes,
        selector_id: StableId::new(&selector.id)?,
        selector_credential_digest: Digest32::of_bytes(b"test-selector-credential"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: selector.minimum_authority_epoch,
        issued_at: now,
        expires_at: expires,
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let verifier = inputs
        .selector_trust
        .original_selector(&inputs.owner_trust.original_owner_trust()?)?;
    verifier.verify(&signed, &current, now)?;
    let after = reader.read_original_registry(crate::authbus_ingress::now_ms()?)?;
    anyhow::ensure!(
        after.receipt() == current.receipt()
            && after.witness_digest() == current.witness_digest()
            && after.trust_digest() == current.trust_digest(),
        "original Current changed while the independent Selector signed"
    );
    verifier.verify(&signed, &after, crate::authbus_ingress::now_ms()?)?;
    let data = super::super::data::SelectionData::from_original_selection(&signed)?;
    plan.resources
        .owners
        .independent_selection
        .write_original_once(&serde_json::to_vec(&data)?)?;
    Ok(OriginalSelectedArtifactData {
        selection: signed,
        manifest,
        registry: after.receipt(),
    })
}

fn open_original_data(path: &Path) -> anyhow::Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)?;
    let actual = file.metadata()?;
    let named = std::fs::symlink_metadata(path)?;
    anyhow::ensure!(
        actual.is_file()
            && actual.nlink() == 1
            && actual.uid() == 60001
            && actual.gid() == 60001
            && actual.mode() == 0o100600
            && named.is_file()
            && (named.dev(), named.ino()) == (actual.dev(), actual.ino()),
        "actual immutable Artifact data descriptor differs"
    );
    Ok(file)
}
