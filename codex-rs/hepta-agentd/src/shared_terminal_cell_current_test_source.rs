//! Signed unit-fixture views; this does not qualify a protected installed owner.
#![cfg(test)]
use codex_hepta_agent_components::learning_artifacts::*;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

pub(super) fn current_fixture(
    registry: Arc<Mutex<ArtifactRegistry>>,
) -> crate::CurrentArtifactRegistrySourceV1 {
    crate::CurrentArtifactRegistrySourceV1::fixture(move |now| {
        let registry = registry.lock().map_err(|error| error.to_string())?;
        let directory = tempfile::tempdir().map_err(|error| error.to_string())?;
        let path = directory.path().join("current-registry");
        let scope = Digest32::of_bytes(b"shared-terminal-current-fixture");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&path).map_err(|error| error.to_string())?,
            &registry,
            scope,
        )
        .map_err(|error| error.to_string())?;
        let key = SigningKey::from_bytes(&[73; 32]);
        let public = key.verifying_key().to_bytes();
        let signer_id =
            StableId::new("shared-terminal-current-signer").map_err(|error| error.to_string())?;
        let registry_id =
            StableId::new("shared-terminal-current-registry").map_err(|error| error.to_string())?;
        let expires_at = now.checked_add(60_000).ok_or("fixture time overflow")?;
        let signer = TrustedArtifactSignerV1 {
            signer_id: signer_id.clone(),
            verifying_key: public,
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: now.saturating_sub(1_000),
            expires_at,
            revoked_at: None,
        };
        let verifier = ArtifactOwnerVerifierV1::new(ArtifactOwnerTrustV1 {
            registry_id: registry_id.clone(),
            withdrawal_scope_digest: scope,
            minimum_registry_generation: Generation::new(1).map_err(|error| error.to_string())?,
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        })
        .map_err(|error| error.to_string())?;
        let generation =
            Generation::new(u64::try_from(receipt.records).map_err(|error| error.to_string())?)
                .map_err(|error| error.to_string())?;
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: scope,
            binding: receipt.binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: registry_id.clone(),
                generation,
                head_digest: receipt.head_digest,
                predecessor_head_digest: Digest32::ZERO,
                authority_epoch: 1,
                signer_id,
                signing_key_digest: Digest32::of_bytes(&public),
                issued_at: now,
                expires_at,
            },
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        verifier
            .verify_current_registry_view(
                File::open(path).map_err(|error| error.to_string())?,
                receipt,
                &signed,
                &RegistryHeadRequirementV1 {
                    registry_id,
                    minimum_generation: generation,
                    expected_predecessor_head_digest: Digest32::ZERO,
                    minimum_authority_epoch: 1,
                    now,
                },
            )
            .map_err(|error| error.to_string())
    })
}
