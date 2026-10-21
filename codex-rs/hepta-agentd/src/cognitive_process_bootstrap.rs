//! Opt-in ordinary-process installation from complete, host-pinned evidence.
//! Paths and trust come from an independently selected descriptor digest. Native
//! owners replay journals and authenticate all evidence again; no opaque token
//! or caller-provided receipt can be deserialized into admission authority.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::EvaluatedCognitiveBootstrapV1;
use crate::cognitive_process_evaluation::*;
use crate::cognitive_process_evidence::*;
use crate::cognitive_process_materials::*;
use crate::cognitive_process_product::*;
use crate::cognitive_process_wire::*;

const SCHEMA: &str = "hepta.agentd.cognitive-bootstrap.v2";
const MAX_DESCRIPTOR_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CognitiveProcessDescriptorV1 {
    schema: String,
    profile: String,
    agent_id: String,
    spawn_generation: u64,
    snapshot_path: PathBuf,
    payload_path: PathBuf,
    selected: PinnedCandidateSpecRaw,
    model_pin: TabularPayloadPinV1Raw,
    source_manifest: LearningArtifactManifestV2Raw,
    current: crate::cognitive_process_current::CognitiveCurrentOwnerDescriptorV1,
    policy: SelfEvolutionSelectionPolicyV1Raw,
    selection_request: SelfEvolutionSelectionRequestV1Raw,
    frozen_plan: CrossFoldPlanV1Raw,
    product: ProductReplayDescriptorV1,
    product_candidate_binding_evidence: SignedLearningEvidenceV1Raw,
    metric_roles: Vec<MetricRoleContractV2Raw>,
    evaluation_evidence: SignedEvaluationEvidenceV1Raw,
    longitudinal_time: LongitudinalTimeEvidenceV1Raw,
    dataset_receipt: DatasetSnapshotReceiptV3Raw,
    ledger: LedgerDescriptorV1,
    holdout: FencedHoldoutDescriptorV1,
    trust: LearningEvidenceTrustV1Raw,
    selector_evidence: SignedLearningEvidenceV1Raw,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LedgerDescriptorV1 {
    path: PathBuf,
    binding: Digest,
    max_records: usize,
    anchor_sequence: u64,
    anchor_chain_digest: Digest,
}

/// Reconstruct complete installation input for the ordinary Agentd config.
/// The host must independently authorize the descriptor digest. Absence is an
/// explicit opt-out; any configured input failure is terminal, with no fallback.
pub fn load_cognitive_process_bootstrap_v1(
    path: &Path,
    expected_descriptor_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<EvaluatedCognitiveBootstrapV1, AgentdError> {
    if !cfg!(any(target_os = "linux", target_os = "macos")) {
        return Err(invalid(
            "cognitive product bootstrap requires the Linux/macOS observation profile",
        ));
    }
    let mut bytes = Vec::new();
    let file = open_bounded_regular(path, MAX_DESCRIPTOR_BYTES, FileAccess::Read)?;
    file.take(MAX_DESCRIPTOR_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_DESCRIPTOR_BYTES
        || expected_descriptor_digest.is_zero()
        || Digest32::of_bytes(&bytes) != expected_descriptor_digest
    {
        return Err(invalid(
            "cognitive bootstrap descriptor digest/size mismatch",
        ));
    }
    let descriptor: CognitiveProcessDescriptorV1 = serde_json::from_slice(&bytes)?;
    if descriptor.schema != SCHEMA || descriptor.profile != "published_product_qualification_v1" {
        return Err(invalid("unsupported cognitive bootstrap schema/profile"));
    }
    if descriptor.agent_id != identity.agent_id.as_str()
        || descriptor.spawn_generation != identity.spawn_generation
    {
        return Err(AgentdError::GenerationFenced(
            "cognitive bootstrap identity/generation mismatch".to_owned(),
        ));
    }
    // Trust, history anchors and mutable owners must remain outside the body
    // whose learned behavior they constrain. Immutable digest-pinned snapshot
    // and payload copies may be installed in the body's own cache.
    for material in [
        path,
        &descriptor.ledger.path,
        &descriptor.holdout.path,
        &descriptor.current.root,
        &descriptor.product.released_inputs.path,
        &descriptor.product.holdout_material.path,
        &descriptor.product.qualification_evidence.path,
    ] {
        for owned in [&identity.home_root, &identity.run_root, &identity.workspace] {
            if material.starts_with(owned) {
                return Err(invalid(
                    "cognitive trust/history owner must be outside Agentd-owned paths",
                ));
            }
        }
    }
    if descriptor.ledger.anchor_sequence == 0 || descriptor.holdout.anchor.record_count == 0 {
        return Err(invalid(
            "cognitive bootstrap requires independent nonempty journal anchors",
        ));
    }
    let snapshot =
        open_bounded_regular(&descriptor.snapshot_path, 8 * 1024 * 1024, FileAccess::Read)?;
    let payload =
        open_bounded_regular(&descriptor.payload_path, 64 * 1024 * 1024, FileAccess::Read)?;
    let ledger_file = open_bounded_regular(
        &descriptor.ledger.path,
        8 * 1024 * 1024,
        FileAccess::Recover,
    )?;
    let holdout_file = open_bounded_regular(
        &descriptor.holdout.path,
        16 * 1024 * 1024,
        FileAccess::Recover,
    )?;
    reject_aliases(&[&snapshot, &payload, &ledger_file, &holdout_file])?;
    let ledger = DurableLedger::recover(
        ledger_file,
        descriptor.ledger.binding.into(),
        descriptor.ledger.max_records,
        LedgerRecovery::Acknowledged(LedgerAnchor {
            sequence: descriptor.ledger.anchor_sequence,
            chain_digest: descriptor.ledger.anchor_chain_digest.into(),
        }),
    )
    .map_err(|error| invalid(&format!("cognitive ledger recovery: {error}")))?;
    let ledger_snapshot = ledger
        .snapshot()
        .map_err(|error| invalid(&format!("cognitive ledger snapshot: {error}")))?;
    let metric_roles: Vec<_> = descriptor
        .metric_roles
        .into_iter()
        .map(Into::into)
        .collect();
    let verifier = LearningEvidenceVerifierV1::new(descriptor.trust.into())
        .map_err(|error| invalid(&format!("cognitive trust: {error}")))?;
    let evaluation_evidence = descriptor.evaluation_evidence.into();
    let longitudinal_time = descriptor.longitudinal_time.into();
    let policy: codex_hepta_intelligence_eval::SelfEvolutionSelectionPolicyV1 =
        descriptor.policy.into();
    let evaluation_now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| invalid(&error.to_string()))?
            .as_micros(),
    )
    .map_err(|error| invalid(&error.to_string()))?;
    let (evaluation_bundle, product_qualification) = replay_product_qualification_v1(
        descriptor.product,
        descriptor.holdout,
        holdout_file,
        descriptor.frozen_plan.into(),
        metric_roles.clone(),
        &evaluation_evidence,
        &longitudinal_time,
        policy.minimum_future_window_micros,
        &verifier,
        evaluation_now,
    )?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| invalid(&error.to_string()))?
        .as_secs();
    let current = crate::cognitive_process_current::load_current_cognitive_owner_v1(
        descriptor.current,
        &identity.home_root,
        now,
    )?;
    Ok(EvaluatedCognitiveBootstrapV1 {
        snapshot,
        payload,
        selected: descriptor.selected.into(),
        model_pin: descriptor.model_pin.into(),
        source_manifest: descriptor.source_manifest.into(),
        current,
        policy,
        selection_request: descriptor.selection_request.into(),
        evaluation_bundle,
        metric_roles,
        evaluation_evidence,
        longitudinal_time,
        product_qualification,
        product_candidate_binding_evidence: descriptor.product_candidate_binding_evidence.into(),
        dataset_receipt: descriptor.dataset_receipt.into(),
        ledger_snapshot,
        verifier,
        selector_evidence: descriptor.selector_evidence.into(),
    })
}

#[derive(Clone, Copy)]
pub(super) enum FileAccess {
    Read,
    Recover,
}

pub(super) fn open_bounded_regular(
    path: &Path,
    maximum: u64,
    access: FileAccess,
) -> Result<File, AgentdError> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(invalid(
            "cognitive material path must be absolute and canonical",
        ));
    }
    let before = std::fs::symlink_metadata(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.nlink() != 1 {
            return Err(invalid(
                "cognitive material must not have hard-link aliases",
            ));
        }
    }
    if !before.is_file()
        || before.file_type().is_symlink()
        || before.len() == 0
        || before.len() > maximum
    {
        return Err(invalid("cognitive material must be a bounded regular file"));
    }
    let mut options = OpenOptions::new();
    options
        .read(true)
        .write(matches!(access, FileAccess::Recover));
    // Reject a last-component symlink replacement atomically and avoid blocking
    // on a FIFO substituted between metadata and open. Parent/file identity is
    // checked again before any content is read.
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(0x20000 | 0x800); // O_NOFOLLOW | O_NONBLOCK
    }
    #[cfg(target_os = "macos")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(0x100 | 0x4); // O_NOFOLLOW | O_NONBLOCK
    }
    let file = options.open(path)?;
    let opened = file.metadata()?;
    let after = std::fs::symlink_metadata(path)?;
    if !opened.is_file()
        || opened.len() == 0
        || opened.len() > maximum
        || after.file_type().is_symlink()
        || path.canonicalize()? != path
    {
        return Err(invalid("cognitive material changed while opening"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let identity = |meta: &std::fs::Metadata| (meta.dev(), meta.ino());
        if identity(&before) != identity(&opened)
            || identity(&opened) != identity(&after)
            || opened.nlink() != 1
            || after.nlink() != 1
        {
            return Err(invalid("cognitive material identity changed while opening"));
        }
    }
    Ok(file)
}

fn reject_aliases(files: &[&File]) -> Result<(), AgentdError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let mut identities = std::collections::BTreeSet::new();
        for file in files {
            let metadata = file.metadata()?;
            if !identities.insert((metadata.dev(), metadata.ino())) {
                return Err(invalid("cognitive inputs alias the same file"));
            }
        }
    }
    #[cfg(not(unix))]
    let _ = files;
    Ok(())
}

pub(super) fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(message.to_owned())
}

#[cfg(test)]
#[path = "cognitive_process_bootstrap_tests.rs"]
mod tests;
