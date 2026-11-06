//! Authenticated CURRENT and independent selection for a generation update.
//!
//! The selected Model payload is canonical CellBackendManifestV2 JSON. Its
//! compatibility digest is the complete V2 manifest digest. Loading and this
//! sealed observation grant no activation authority: Control must separately
//! consume the exact independently signed FinalUse operation.

use std::fs::File;

use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::load_selected_candidate;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AgentdError;

const MAX_GENERATION_MANIFEST_BYTES: u64 = 64 * 1024;

/// Independently opened immutable registry snapshot and selected payload.
pub struct AgentdGenerationSelectionFilesV1 {
    pub registry_snapshot: File,
    pub payload: File,
}

/// Frozen identity of a verified CURRENT and selection observation.
/// The fields remain private; there is no deserialization/admission shortcut.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdGenerationSelectionObservationV1 {
    selection: Digest32,
    registry_head: Digest32,
    current_witness: Digest32,
    current_trust: Digest32,
    selector_trust: Digest32,
    withdrawal_scope: Digest32,
    withdrawal_head: Digest32,
    payload: Digest32,
    manifest: [u8; 32],
}

impl AgentdGenerationSelectionObservationV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.agentd.generation-selection.v1\0",
            self.selection.as_array(),
            self.registry_head.as_array(),
            self.current_witness.as_array(),
            self.current_trust.as_array(),
            self.selector_trust.as_array(),
            self.withdrawal_scope.as_array(),
            self.withdrawal_head.as_array(),
            self.payload.as_array(),
            &self.manifest,
        ])
    }

    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection
    }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Retains actual verified payload bytes and independently signed selection.
/// A newer CURRENT or withdrawal cut requires a new selection, never a relabel.
pub struct AgentdSelectedGenerationV1 {
    manifest: CellBackendManifestV2,
    candidate: RevalidatingCandidate,
    signed: SignedArtifactSelectionV1,
    verifier: ArtifactSelectionVerifierV1,
    observation: AgentdGenerationSelectionObservationV1,
    observed_at: u64,
}

impl AgentdSelectedGenerationV1 {
    pub fn load(
        owner: &LearningArtifactOwnerService,
        verifier: ArtifactSelectionVerifierV1,
        signed: SignedArtifactSelectionV1,
        files: AgentdGenerationSelectionFilesV1,
        now: u64,
    ) -> Result<Self, AgentdError> {
        if owner.recovery_required().is_some()
            || signed.artifact_kind != ArtifactKind::Model
            || signed.encoded_size_bytes == 0
            || signed.encoded_size_bytes > MAX_GENERATION_MANIFEST_BYTES
        {
            return Err(invalid("generation selection is not a bounded ready Model"));
        }
        let metadata = files.payload.metadata()?;
        if !metadata.is_file() || metadata.len() != signed.encoded_size_bytes {
            return Err(invalid("generation payload file differs from selection"));
        }
        let current = owner.current_registry_view(now).map_err(invalid)?;
        let verified = verifier.verify(&signed, &current, now).map_err(invalid)?;
        let selection = verified.selection_digest();
        let mut candidate = load_selected_candidate(
            files.registry_snapshot,
            files.payload,
            verified,
        )
        .map_err(invalid)?;
        let manifest = candidate
            .with_current(current, |bytes| {
                let manifest: CellBackendManifestV2 =
                    serde_json::from_slice(bytes).map_err(invalid)?;
                let canonical = serde_json::to_vec(&manifest).map_err(invalid)?;
                if canonical != bytes {
                    return Err(invalid("generation manifest payload is not canonical"));
                }
                manifest.digest().map_err(invalid)?;
                Ok(manifest)
            })
            .map_err(invalid)??;
        let manifest_digest = manifest.digest().map_err(invalid)?;
        if signed.compatibility_digest.as_array() != &manifest_digest {
            return Err(invalid("selection does not bind the complete generation manifest"));
        }
        let withdrawal = owner.withdrawal_registry();
        let withdrawal_scope = withdrawal
            .scope_digest()
            .ok_or_else(|| invalid("missing authenticated withdrawal scope"))?;
        if withdrawal_scope != signed.withdrawal_scope_digest {
            return Err(invalid("generation selection withdrawal scope differs"));
        }
        let observation = AgentdGenerationSelectionObservationV1 {
            selection,
            registry_head: signed.registry_head_digest,
            current_witness: signed.current_witness_digest,
            current_trust: signed.current_trust_digest,
            selector_trust: verifier.trust_digest(),
            withdrawal_scope,
            withdrawal_head: withdrawal.head_digest(),
            payload: signed.content_digest,
            manifest: manifest_digest,
        };
        Ok(Self {
            manifest,
            candidate,
            signed,
            verifier,
            observation,
            observed_at: now,
        })
    }

    #[must_use]
    pub fn manifest(&self) -> &CellBackendManifestV2 {
        &self.manifest
    }

    #[must_use]
    pub fn observation(&self) -> &AgentdGenerationSelectionObservationV1 {
        &self.observation
    }

    /// Re-read real CURRENT and re-verify the selection at the host boundary.
    /// The coordinator holds the concrete artifact owner exclusively across
    /// this check and Control publication; this is not a remote freshness RPC.
    pub(crate) fn revalidate(
        &mut self,
        owner: &LearningArtifactOwnerService,
        now: u64,
    ) -> Result<(), AgentdError> {
        if now < self.observed_at || owner.recovery_required().is_some() {
            return Err(invalid("generation selection owner or clock is unavailable"));
        }
        let withdrawal = owner.withdrawal_registry();
        if withdrawal.scope_digest() != Some(self.observation.withdrawal_scope)
            || withdrawal.head_digest() != self.observation.withdrawal_head
        {
            return Err(invalid("generation selection withdrawal cut changed"));
        }
        let current = owner.current_registry_view(now).map_err(invalid)?;
        let verified = self.verifier.verify(&self.signed, &current, now).map_err(invalid)?;
        if verified.selection_digest() != self.observation.selection {
            return Err(invalid("generation selection identity changed"));
        }
        self.candidate.with_current(current, |_| ()).map_err(invalid)?;
        self.observed_at = now;
        Ok(())
    }
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

