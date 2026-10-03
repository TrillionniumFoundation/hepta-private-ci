//! Project the original whole registration from independently published
//! manifest Sources and the existing authenticated CURRENT owner.
use super::*;
use crate::ParameterRoleSourceV3;

pub fn project_registered_artifact_manifest_configuration_v3(
    path: &Path,
    pin: Digest32,
    manifests: &[(ParameterRoleSourceV3, Digest32); 3],
    material: &NeuronGenerationMaterialV2,
    subject: &StableId,
    now: u64,
) -> HostResult<Vec<u8>> {
    let source = Source { path: path.to_owned(), digest: pin.to_string() };
    let bytes = source.read(64 * 1024)?;
    let mut registration: Registration = serde_json::from_slice(&bytes)?;
    let owner = registration.owner.open(now)?;
    let view = owner.current_registry_view(now)?;
    let head = owner.protected_current_head(now)?;
    let acknowledgement = owner.current_publication_acknowledgement(now)?;
    if acknowledgement.registry_receipt != Some(view.receipt()) {
        return Err("complete original manifest projection CURRENT/ACK differs".into());
    }
    let mut original_sources = Vec::new();
    for (index, (slot, (manifest_source, admission_digest))) in
        registration.manifests.iter_mut().zip(manifests).enumerate()
    {
        let source = Source {
            path: manifest_source.path.clone(), digest: manifest_source.digest.clone(),
        };
        let full = source.read(128 * 1024)?;
        let admission = read_artifact_admission_by_digest(
            codex_hepta_learning_ledger::open_root_review_input(&source.path)?,
            *admission_digest,
        )?;
        if index == 0 {
            // The model alone has a model predecessor. Calibration and OOD
            // retain their original independently measured policy lineage.
            let model = &admission.validated_manifest.manifest;
            match model.predecessor_ids.as_slice() {
                [] if material.runtime.generation.get() == 1 => {
                    registration.predecessor_id = None;
                    registration.predecessor_manifest_digest = None;
                }
                [id] if material.runtime.generation.get() > 1 => {
                    let actual = view.registered_manifest(id)
                        .ok_or("actual original model predecessor absent")?;
                    if actual.kind != ArtifactKind::Model
                        || actual.generation.next()? != material.runtime.generation
                    {
                        return Err("actual original model predecessor generation differs".into());
                    }
                    registration.predecessor_id = Some(id.to_string());
                    registration.predecessor_manifest_digest = Some(actual.support_digest.to_string());
                }
                _ => return Err("complete original model predecessor frontier".into()),
            }
        }
        *slot = ManifestSource { source, admission_digest: admission_digest.to_string() };
        original_sources.push(full);
    }
    registration.publication_operation_id = acknowledgement.operation_id.to_string();
    let facts = inspect_current_material(&registration, material, subject, now)?;
    if facts.acknowledgement() != &acknowledgement
        || facts.current_head() != &head
        || facts.current_view().receipt() != view.receipt()
        || owner.protected_current_head(now)? != head
        || source.read(64 * 1024)? != bytes
    {
        return Err("whole original manifest projection changed".into());
    }
    for (manifest, original) in registration.manifests.iter().zip(original_sources) {
        if manifest.source.read(128 * 1024)? != original {
            return Err("complete original manifest Source changed during projection".into());
        }
    }
    facts.revalidate_current(now)?;
    let mut whole: serde_json::Value = serde_json::from_slice(&bytes)?;
    whole["manifests"] = serde_json::Value::Array(manifests.iter().map(|(source, admission)| {
        serde_json::json!({"source": source, "admission_digest": admission.to_string()})
    }).collect());
    whole["predecessor_id"] = serde_json::to_value(&registration.predecessor_id)?;
    whole["predecessor_manifest_digest"] = serde_json::to_value(&registration.predecessor_manifest_digest)?;
    whole["publication_operation_id"] = registration.publication_operation_id.into();
    let projected = serde_json::to_vec(&whole)?;
    if projected.len() > 64 * 1024 {
        return Err("whole original manifest configuration bound".into());
    }
    Ok(projected)
}

/// Read original legacy manifest Sources through their same authenticated
/// Artifact owner. Root must publish independent immutable whole-byte Sources
/// before using the ordinary registration inspector.
pub fn read_registered_artifact_manifest_sources_v3(
    path: &Path,
    pin: Digest32,
    now: u64,
) -> HostResult<[(Vec<u8>, Digest32); 3]> {
    let source = Source { path: path.to_owned(), digest: pin.to_string() };
    let original = source.read(64 * 1024)?;
    let registration: Registration = serde_json::from_slice(&original)?;
    let owner = registration.owner.open(now)?;
    let mut outputs = Vec::new();
    for manifest in &registration.manifests {
        let admission = manifest.admission_digest.parse()?;
        let bytes = match manifest.source.read(128 * 1024) {
            Ok(bytes) => bytes,
            Err(_) => owner.read_current_manifest_admission_source(&manifest.source.path,
                manifest.source.digest.parse()?, admission, now)?,
        };
        outputs.push((bytes, admission));
    }
    if source.read(64 * 1024)? != original {
        return Err("whole original registration changed during legacy source read".into());
    }
    Ok(outputs.try_into().map_err(|_| "three complete original manifest Sources")?)
}
