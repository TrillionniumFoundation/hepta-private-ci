//! Shared signed-selection, CURRENT, withdrawal and generation checks.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactPublicationReceiptV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::VerifiedArtifactSelectionV1;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_learning_artifacts::load_selected_candidate;
use codex_hepta_learning_artifacts::validate_artifact_publication_v3;
use codex_hepta_types::Digest32;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;


/// Typed immutable payload contract at the shared artifact authority boundary.
/// Implementations must bind all profile-specific bytes and owner dependencies.
pub(crate) trait MemoryReleaseBundle: Sized {
    fn decode(bytes: &[u8], expected: Digest32) -> Result<Self, String>;
    fn validate_manifest(&self, manifest: &LearningArtifactManifestV2) -> Result<(), String>;
    fn generation(&self) -> ContractGenerationV1;
    fn bundle_digest(&self) -> ContractDigestV1;
    fn scope(&self) -> &ContractIdV1;
}

pub(super) struct InstalledBundle<B> {
    candidate: RevalidatingCandidate,
    bundle: Arc<B>,
    admission: WithdrawalBoundArtifactAdmissionV3,
    selected_current: RegistrySnapshotReceipt,
    installed_at: u64,
    selection_expires_at: u64,
    owner_trust_digest: Digest32,
    selector_trust_digest: Digest32,
    available: bool,
}

/// A configured product consumer of the real artifact service. Its in-memory
/// cache is never an independent active-version authority: restart requires a
/// freshly verified selection against that service's durable signed CURRENT.
pub(crate) struct MemoryReleaseSlot<B> {
    service: Arc<Mutex<LearningArtifactOwnerService>>,
    pub(super) selection_verifier: ArtifactSelectionVerifierV1,
    pub(super) selected: Mutex<Option<InstalledBundle<B>>>,
}

impl<B: MemoryReleaseBundle> MemoryReleaseSlot<B> {
    pub fn new(
        service: Arc<Mutex<LearningArtifactOwnerService>>,
        selection_verifier: ArtifactSelectionVerifierV1,
    ) -> Self {
        Self {
            service,
            selection_verifier,
            selected: Mutex::new(None),
        }
    }

    /// Publish exact typed bytes through the existing owner transaction. An
    /// owner snapshot is historical evidence; the runtime reacquires its live
    /// cut before and after every read. Publishing does not select a reader.
    pub fn publish(
        &self,
        mut request: LearningArtifactPublishRequestV1,
        validate_owner: impl FnOnce(&B) -> Result<(), String>,
    ) -> Result<ArtifactPublicationReceiptV1, String> {
        let now = now()?;
        let manifest = &request.admission.validated_manifest.manifest;
        let bundle = B::decode(&request.payload, manifest.bytes_digest)?;
        validate_owner(&bundle)?;
        bundle.validate_manifest(manifest)?;
        let mut service = self
            .service
            .lock()
            .map_err(|_| "memory artifact owner lock poisoned".to_string())?;
        validate_admission(&service, &request.admission, now)?;
        request.now = now;
        service.publish(request).map_err(|error| error.to_string())
    }

    pub fn install_selected(
        &self,
        snapshot: File,
        payload: File,
        selection: VerifiedArtifactSelectionV1,
        admission: WithdrawalBoundArtifactAdmissionV3,
    ) -> Result<(), String> {
        let now = now()?;
        if !selection.valid_at(now)
            || selection.authority().grants_any()
            || selection.trust_digest() != self.selection_verifier.trust_digest()
            || selection.current_owner_trust_digest()
                != self.selection_verifier.owner_trust_digest()
        {
            return Err("memory artifact selection expired or grants effects".to_string());
        }
        let selection_expires_at = selection.expires_at();
        let selector_trust_digest = selection.trust_digest();
        let owner_trust_digest = selection.current_owner_trust_digest();
        let mut candidate = load_selected_candidate(snapshot, payload, selection)
            .map_err(|error| error.to_string())?;
        validate_pin(&candidate.spec().manifest, &admission)?;
        let service = self
            .service
            .lock()
            .map_err(|_| "memory artifact owner lock poisoned".to_string())?;
        validate_admission(&service, &admission, now)?;
        let current = service
            .current_registry_view(now)
            .map_err(|error| error.to_string())?;
        let selected_current = current.receipt();
        if selected_current != candidate.spec().registry_receipt
            || current.trust_digest() != owner_trust_digest
        {
            return Err("memory artifact selection is not at current registry head".to_string());
        }
        let manifest = &admission.validated_manifest.manifest;
        let bundle = candidate
            .with_current(current, |bytes| {
                let decoded = B::decode(bytes, manifest.bytes_digest)?;
                decoded.validate_manifest(manifest)?;
                Ok::<_, String>(decoded)
            })
            .map_err(|error| error.to_string())??;
        let mut selected = self
            .selected
            .lock()
            .map_err(|_| "memory selection lock poisoned".to_string())?;
        if let Some(old) = selected.as_ref() {
            let same_version = bundle.generation() == old.bundle.generation()
                && bundle.bundle_digest() == old.bundle.bundle_digest()
                && candidate.spec().manifest == old.candidate.spec().manifest;
            let valid_successor = old.bundle.generation().get().checked_add(1)
                == Some(bundle.generation().get())
                && manifest.predecessor_ids
                    == vec![old.candidate.spec().manifest.artifact_id.clone()];
            if bundle.scope() != old.bundle.scope() || (!same_version && !valid_successor) {
                return Err("memory artifact generation rollback, fork or scope change".to_string());
            }
        }
        *selected = Some(InstalledBundle {
            candidate,
            bundle: Arc::new(bundle),
            admission,
            selected_current,
            installed_at: now,
            selection_expires_at,
            owner_trust_digest,
            selector_trust_digest,
            available: true,
        });
        Ok(())
    }

    pub fn load_current(&self) -> Result<Arc<B>, String> {
        let service = self
            .service
            .lock()
            .map_err(|_| "memory artifact owner lock poisoned".to_string())?;
        let mut selected = self
            .selected
            .lock()
            .map_err(|_| "memory selection lock poisoned".to_string())?;
        let state = selected
            .as_mut()
            .ok_or_else(|| "memory parameters have no verified selection".to_string())?;
        revalidate_state(&service, &self.selection_verifier, state, now()?)?;
        Ok(Arc::clone(&state.bundle))
    }

    pub fn revalidate(&self, bundle: &B) -> Result<(), String> {
        let service = self
            .service
            .lock()
            .map_err(|_| "memory artifact owner lock poisoned".to_string())?;
        let mut selected = self
            .selected
            .lock()
            .map_err(|_| "memory selection lock poisoned".to_string())?;
        let state = selected
            .as_mut()
            .ok_or_else(|| "memory parameters have no verified selection".to_string())?;
        if !std::ptr::eq(bundle, state.bundle.as_ref()) {
            return Err("memory reader retained a superseded selection".to_string());
        }
        revalidate_state(&service, &self.selection_verifier, state, now()?)
    }
}

pub(super) fn revalidate_state<B: MemoryReleaseBundle>(
    service: &LearningArtifactOwnerService,
    verifier: &ArtifactSelectionVerifierV1,
    state: &mut InstalledBundle<B>,
    now: u64,
) -> Result<(), String> {
    if !state.available {
        return Err("memory selection failed freshness; explicit reload required".to_string());
    }
    // Mark unavailable before every fallible check. No stale fallback may
    // revive this reader after a failed CURRENT/withdrawal refresh.
    state.available = false;
    if now < state.installed_at || now > state.selection_expires_at {
        return Err("memory selection validity window elapsed".to_string());
    }
    validate_admission(service, &state.admission, now)?;
    let current = service
        .current_registry_view(now)
        .map_err(|error| error.to_string())?;
    if current.receipt() != state.selected_current
        || current.trust_digest() != state.owner_trust_digest
        || current.trust_digest() != verifier.owner_trust_digest()
        || state.selector_trust_digest != verifier.trust_digest()
    {
        return Err("memory registry changed; a new verified selection is required".to_string());
    }
    state
        .candidate
        .with_current(current, |_| ())
        .map_err(|error| error.to_string())?;
    state.available = true;
    Ok(())
}

fn validate_admission(
    service: &LearningArtifactOwnerService,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    now: u64,
) -> Result<(), String> {
    let withdrawals = service.withdrawal_registry();
    validate_artifact_publication_v3(admission, withdrawals, now)
        .map_err(|error| error.to_string())?;
    // Admission receipts contain public fields. Recompute eligibility against
    // the actual owner frontier, not just their self-consistent digest.
    let checked = withdrawals
        .admit_manifest(admission.validated_manifest.manifest.clone(), now)
        .map_err(|error| error.to_string())?;
    if checked != admission.validated_manifest
        || checked
            .manifest
            .lineage_digests
            .iter()
            .any(|source| withdrawals.is_withdrawn(*source))
    {
        return Err(
            "memory artifact training lineage is withdrawn or admission differs".to_string(),
        );
    }
    Ok(())
}

fn validate_pin(
    pin: &ArtifactManifest,
    admission: &WithdrawalBoundArtifactAdmissionV3,
) -> Result<(), String> {
    let manifest = &admission.validated_manifest.manifest;
    let expected = ArtifactManifest {
        artifact_id: manifest.artifact_id.clone(),
        kind: manifest.kind,
        generation: manifest.generation,
        predecessor_id: manifest.predecessor_ids.first().cloned(),
        content_digest: manifest.bytes_digest,
        objective_digest: manifest.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: manifest.producer_id.clone(),
        compatibility_digest: manifest.compatibility_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
    };
    if *pin != expected {
        return Err(
            "memory signed selection differs from complete parameter admission".to_string(),
        );
    }
    Ok(())
}

pub(super) fn now() -> Result<u64, String> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|error| error.to_string())
}

