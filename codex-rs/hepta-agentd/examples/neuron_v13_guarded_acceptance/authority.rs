//! Isolated local qualification authority, using the actual root CAS backend.
//! Public fixture signing keys never certify production adoption or custody.

use std::collections::BTreeSet;
use std::path::Path;
use std::sync::Arc;

use anyhow::Result;
use codex_hepta_agentd::AgentdGenerationUpdateAuthoritiesV1;
use codex_hepta_contracts::*;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::artifacts::ArtifactFiles;

pub(super) struct Authority {
    pub root: Arc<RootAuthorityDirectory>,
    pub artifacts: ArtifactFiles,
    pub final_use: Arc<FinalUseAuthority>,
    pub clock: Arc<SystemAuthorityClock>,
    key: SigningKey,
}

impl Authority {
    pub fn new(
        root: Arc<RootAuthorityDirectory>,
        output: &Path,
        manifest: &CellBackendManifestV2,
        dataset: Digest32,
    ) -> Result<Self> {
        let clock = Arc::new(SystemAuthorityClock);
        let now = clock.now_unix_ms()?;
        let artifacts = ArtifactFiles::new(&output.join("artifacts"), manifest, dataset, now)?;
        let key = SigningKey::from_bytes(&[63; 32]);
        let head = FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let signer = "qualification-v13-final-use".to_owned();
        let frontier = Arc::new(HostAuthorityFrontierStore::initialize(
            root.clone(),
            signer.clone(),
            FinalUseFrontier::for_initial_head(&head)?,
        )?);
        let path = output.join("final-use");
        super::directory(&path)?;
        let final_use = Arc::new(FinalUseAuthority::open_state_dir_with_trust(
            &path,
            signer,
            key.verifying_key().to_bytes(),
            head,
            clock.clone(),
            frontier,
        )?);
        Ok(Self {
            root,
            artifacts,
            final_use,
            clock,
            key,
        })
    }

    pub fn authorities(&self) -> Result<AgentdGenerationUpdateAuthoritiesV1> {
        Ok(AgentdGenerationUpdateAuthoritiesV1::new(
            self.artifacts.owner.clone(),
            self.final_use.clone(),
            self.clock.clone(),
        )?)
    }

    pub fn sign(&self, binding: &FinalUseBinding) -> Result<SignedFinalUseGrant> {
        let now = self.clock.now_unix_ms()?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "qualification-v13-final-use".into(),
            authority_epoch: 1,
            grant_id: format!(
                "qualification-{}",
                Digest32::from_array(binding.request_sha256)
            ),
            nonce: Digest32::of_parts(&[
                b"hepta.v13.qualification-nonce.v1\0",
                &serde_json::to_vec(binding)?,
            ])
            .into_array(),
            binding: binding.clone(),
            not_before_unix_ms: now,
            expires_at_unix_ms: now + 300_000,
        };
        let signature = self.key.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }
}
