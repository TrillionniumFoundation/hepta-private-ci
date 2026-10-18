//! Immutable publications below the original admitted custody root.
use super::cycle_transfer::CalibrationCycleScopeWireV2;
use super::cycle_transfer::FixedCalibrationPublicationV2;
use super::files::Access;
use super::files::ReviewResult;
use super::files::create_private;
use super::files::read_root;
use super::files::root_directory;
use super::generator_wire::encode_hex;
use super::independent_trust::IndependentTrust;
use super::observations::PinnedModel;
use super::transfer::FixedCalibrationCutV1;
use super::transfer::FixedCalibrationPublicationV1;
use super::transfer::ReviewDatasetWireV1;
use super::transfer::ReviewEvidenceWireV1;
use super::transfer::ReviewTrustWireV1;
use crate::CalibrationCycleScopeV2;
use crate::DatasetSnapshotReceiptV3;
use crate::LearningEvidenceRoleV1;
use crate::LedgerSnapshot;
use crate::ProductionDecisionV2;
use crate::SignedLearningEvidenceV1;
use crate::decision_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
pub(super) struct PublicationTarget {
    path: PathBuf,
    directory: File,
    gid: u32,
}
fn current_path<'a>(admitted: &'a Path, current: Option<&'a Path>) -> ReviewResult<&'a Path> {
    if let Some(path) = current {
        if path == admitted || !path.starts_with(admitted) {
            return Err("new cycle publication must be below original admitted directory".into());
        }
        Ok(path)
    } else {
        Ok(admitted)
    }
}
impl PublicationTarget {
    pub(super) fn open(
        trust: &IndependentTrust,
        current: Option<&Path>,
    ) -> ReviewResult<Option<Self>> {
        let Some(reviewer) = &trust.config.independent_reviewer else {
            if current.is_some() {
                return Err("cycle publication has no original admitted reviewer".into());
            }
            return Ok(None);
        };
        let path = current_path(&reviewer.publication_directory, current)?;
        let directory = root_directory(path)?;
        if current.is_some()
            && (directory.metadata()?.gid() != reviewer.gid
                || directory.metadata()?.mode() & 0o2050 != 0o2050)
        {
            return Err("new publication needs preprovisioned protected SGID reviewer read/search directory".into());
        }
        Ok(Some(Self {
            path: path.to_owned(),
            directory,
            gid: reviewer.gid,
        }))
    }
}
pub(super) struct PublicationContext<'a> {
    pub trust: &'a IndependentTrust,
    pub target: &'a PublicationTarget,
    pub binding: Digest32,
    pub audit: Digest32,
    pub candidate: &'a PinnedModel,
    pub baseline: &'a PinnedModel,
    pub snapshot: &'a LedgerSnapshot,
    pub dataset: &'a DatasetSnapshotReceiptV3,
    pub freeze: &'a SignedLearningEvidenceV1,
    pub generator_fact: &'a ProductionDecisionV2,
    pub generator: &'a SignedLearningEvidenceV1,
    pub ledger_bytes: Vec<u8>,
    pub signing_time: u64,
    pub cycle: Option<CalibrationCycleScopeV2>,
}
pub(super) fn publish(value: PublicationContext<'_>) -> ReviewResult<()> {
    let cut = FixedCalibrationCutV1 {
        schema: "hepta.signed-calibration-cut.v1".into(),
        observer_program_digest: value.trust.evaluator_program.to_string(),
        ledger_binding_digest: value.binding.to_string(),
        ledger_file_digest: Digest32::of_bytes(&value.ledger_bytes).to_string(),
        acknowledged_sequence: value
            .snapshot
            .records()
            .last()
            .ok_or("empty calibration ledger")?
            .sequence
            .get(),
        acknowledged_head: value.snapshot.head_digest.to_string(),
        candidate_manifest_digest: value.candidate.manifest.to_string(),
        baseline_manifest_digest: value.baseline.manifest.to_string(),
        candidate_weights_digest: value.candidate.weights.to_string(),
        baseline_weights_digest: value.baseline.weights.to_string(),
        audit_digest: value.audit.to_string(),
        dataset: ReviewDatasetWireV1::from_native(value.dataset),
        generator_payload_hex: encode_hex(&decision_signing_payload_v2(value.generator_fact)?),
        generator_evidence: ReviewEvidenceWireV1::from_native(value.generator),
        freeze_evidence: ReviewEvidenceWireV1::from_native(value.freeze),
    };
    let payload = if let Some(cycle) = &value.cycle {
        crate::calibration_cycle_cut_signing_payload_v2(&cut.binding()?, cycle)
    } else {
        cut.signing_payload()?
    };
    let observer = value.trust.sign(
        LearningEvidenceRoleV1::Observer,
        StableId::new(format!("calibration.cut.{}", value.audit))?,
        &payload,
        value.signing_time,
        super::generator_wire::now_ms()?,
    )?;
    let observer_evidence = ReviewEvidenceWireV1::from_native(&observer);
    let trust = ReviewTrustWireV1::from_native(&value.trust.root, &value.trust.distribution);
    let publication = if let Some(cycle) = &value.cycle {
        serde_json::to_vec(&FixedCalibrationPublicationV2 {
            schema: "hepta.signed-calibration-cycle-publication.v2".into(),
            cut,
            cycle: CalibrationCycleScopeWireV2::from_native(cycle),
            observer_evidence,
            trust,
        })?
    } else {
        serde_json::to_vec(&FixedCalibrationPublicationV1 {
            cut,
            observer_evidence,
            trust,
        })?
    };
    for (name, bytes) in [
        ("ledger-readonly.bin", value.ledger_bytes),
        ("signed-calibration-cut.json", publication),
    ] {
        let path = value.target.path.join(name);
        if path.exists() {
            if read_root(&path, 8 * 1024 * 1024, Access::Immutable)? != bytes {
                return Err("existing signed calibration publication changed".into());
            }
        } else {
            let file = create_private(&path, &bytes)?;
            if file.metadata()?.gid() != value.target.gid {
                std::os::unix::fs::chown(&path, Some(0), Some(value.target.gid))?;
            }
            file.set_permissions(std::fs::Permissions::from_mode(0o640))?;
            file.sync_all()?;
            value.target.directory.sync_all()?;
        }
    }
    Ok(())
}
pub(super) fn native_scope(
    trust: &IndependentTrust,
    source: Digest32,
    executions: &[super::observations::CalibrationExecution],
    candidate: &PinnedModel,
    baseline: &PinnedModel,
) -> ReviewResult<Option<CalibrationCycleScopeV2>> {
    trust
        .cycle
        .as_ref()
        .map(|approval| {
            let mut sources = b"hepta.calibration.original-ordered-tasks.v2".to_vec();
            sources.extend_from_slice(source.as_array());
            let mut snapshots = Vec::with_capacity(executions.len());
            for item in executions {
                let input: Digest32 = item.candidate.input_digest.parse()?;
                sources.extend_from_slice(item.source_digest.as_array());
                sources.extend_from_slice(input.as_array());
                snapshots.push([candidate.manifest, baseline.manifest].map(|model| {
                    Digest32::of_bytes(
                        &[
                            item.source_digest.as_array().as_slice(),
                            input.as_array(),
                            model.as_array(),
                        ]
                        .concat(),
                    )
                }));
            }
            Ok(CalibrationCycleScopeV2 {
                first_sequence: approval
                    .previous_sequence
                    .checked_add(1)
                    .ok_or("cycle first sequence overflow")?,
                previous_acknowledged_head: approval.previous_head,
                original_task_sources_digest: Digest32::of_bytes(&sources),
                run_snapshot_digests: snapshots,
                current_program_approval_digest: approval.digest,
            })
        })
        .transpose()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cycle_publication_preserves_legacy_and_only_allows_descendant() {
        let admitted = Path::new("/protected/original");
        assert_eq!(current_path(admitted, None).unwrap(), admitted);
        assert!(current_path(admitted, Some(admitted)).is_err());
        assert!(current_path(admitted, Some(Path::new("/protected/other"))).is_err());
        assert!(
            current_path(
                admitted,
                Some(Path::new("/protected/original-pseudo/cycle"))
            )
            .is_err()
        );
        assert_eq!(
            current_path(admitted, Some(Path::new("/protected/original/cycle"))).unwrap(),
            Path::new("/protected/original/cycle")
        );
    }
}
