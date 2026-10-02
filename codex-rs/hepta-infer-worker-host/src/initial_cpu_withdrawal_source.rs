//! Reopen the actual calibrated ledger under its original exclusive witness.
//! The authenticated archive is only a prefix pin, never a replacement store.
use super::super::*;
use super::Request;
use codex_hepta_agent_components::learning_ledger as ledger;
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

pub(super) struct SourceOwner {
    pub writer: ledger::LedgerWriter,
    pub dataset: ledger::DatasetSnapshotReceiptV3,
}
pub(super) fn open(request: &Request) -> HostResult<SourceOwner> {
    let Archive {
        trust,
        binding,
        archived,
        dataset,
    } = authenticated_archive(request, ArchiveUse::CurrentWithdrawal)?;
    let ledger_directory = directory(&request.ledger_directory)?;
    let witness_directory = directory(&request.witness_directory)?;
    let witness = ledger::LedgerWitnessStore::recover(
        mutable(&request.witness_directory.join("acknowledged-frontier.bin"))?,
        binding,
    )?;
    let anchor = witness.frontier()?.anchor;
    let durable = ledger::DurableLedger::recover(
        mutable(&request.ledger_directory.join("causal-ledger.bin"))?,
        binding,
        4096,
        ledger::LedgerRecovery::Acknowledged(anchor),
    )?;
    let writer = ledger::LedgerWriter::from_durable(
        durable,
        witness,
        trust,
        &ledger_directory,
        &witness_directory,
    )?;
    let actual = writer.snapshot()?;
    if actual.records().get(..archived.records().len()) != Some(archived.records()) {
        return Err(
            "original writer no longer contains the authenticated calibration prefix".into(),
        );
    }
    // An archive replacement during recovery cannot change the bound dataset.
    request.calibration_archive.read(8 * 1024 * 1024)?;
    Ok(SourceOwner { writer, dataset })
}
pub(super) enum ArchiveUse {
    CurrentWithdrawal,
    AcknowledgedHistory,
}
pub(super) struct Archive {
    pub trust: ledger::ActivatedLearningTrustV1,
    pub binding: Digest32,
    pub archived: ledger::LedgerSnapshot,
    pub dataset: ledger::DatasetSnapshotReceiptV3,
}
/// Historical parsing supplies no writer/current capability. Only original
/// source/cut integrity is shared with the current admitted writer path.
pub(super) fn authenticated_archive(
    request: &Request,
    use_case: ArchiveUse,
) -> HostResult<Archive> {
    let publication: ledger::FixedCalibrationPublicationV1 =
        serde_json::from_slice(&request.calibration_publication.read(2 * 1024 * 1024)?)?;
    let cut = &publication.cut;
    if cut.schema != "hepta.signed-calibration-cut.v1" {
        return Err("withdrawal requires the original native calibration publication".into());
    }
    let (root, distribution) = publication.trust.native()?;
    // Revalidate the same retained distribution. No rotation or new trust is
    // issued here; the Root configuration is also bound into the original file.
    let trust_at = match use_case {
        ArchiveUse::CurrentWithdrawal => now_ms()?,
        ArchiveUse::AcknowledgedHistory => distribution
            .distribution
            .effective_at
            .max(distribution.issued_at),
    };
    let trust = ledger::activate_learning_trust(&root, distribution, None, trust_at)?;
    let binding = Digest32::of_bytes(
        &[
            b"hepta.fixed-custody-calibration-ledger.v1".as_slice(),
            digest(&request.calibration_trust_config.digest)?.as_array(),
            trust.verifier().objective_digest().as_array(),
        ]
        .concat(),
    );
    request.calibration_trust_config.read(16 * 1024)?;
    if binding != digest(&cut.ledger_binding_digest)?
        || request.calibration_archive.digest != cut.ledger_file_digest
    {
        return Err("withdrawal is not bound to the original calibrated ledger".into());
    }
    request.calibration_archive.read(8 * 1024 * 1024)?;
    let archived = ledger::inspect_ledger(
        ledger::open_root_review_input(&request.calibration_archive.path)?,
        binding,
        4096,
        ledger::LedgerAnchor {
            sequence: cut.acknowledged_sequence,
            chain_digest: digest(&cut.acknowledged_head)?,
        },
    )?;
    let dataset = cut.dataset.native()?;
    ledger::verify_dataset_snapshot_receipt_against_ledger_v3(
        &dataset,
        &archived,
        dataset.producer.authenticated_at,
    )?;
    let observer = publication.observer_evidence.native()?;
    trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Observer,
        &observer,
        &cut.signing_payload()?,
        observer.issued_at,
    )?;
    let generator = cut.generator_evidence.native()?;
    trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Generator,
        &generator,
        &ledger::decode_review_payload_hex(&cut.generator_payload_hex)?,
        generator.issued_at,
    )?;
    let freeze = cut.freeze_evidence.native()?;
    let verified = trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Evaluator,
        &freeze,
        &ledger::dataset_freeze_signing_payload_v2(
            &archived,
            &ledger::DatasetFreezePlanV2 {
                snapshot_id: dataset.snapshot.snapshot_id.clone(),
                objective_digest: dataset.snapshot.objective_digest,
                inclusion_policy_digest: dataset.inclusion_policy_digest,
            },
        )?,
        freeze.issued_at,
    )?;
    if verified.principal() != &dataset.producer {
        return Err("dataset was not frozen by its original evaluator".into());
    }
    Ok(Archive {
        trust,
        binding,
        archived,
        dataset,
    })
}
pub(super) fn directory(path: &Path) -> HostResult<File> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err("withdrawal path must be canonical".into());
    }
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err("withdrawal directory must stay in Root custody".into());
        }
    }
    Ok(File::open(path)?)
}
fn mutable(path: &Path) -> HostResult<File> {
    let before = ledger::open_root_review_input(path)?.metadata()?;
    if before.mode() & 0o077 != 0 {
        return Err("original calibrated writer file must remain private".into());
    }
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(
            rustix::fs::OFlags::NOFOLLOW.bits() as i32 | rustix::fs::OFlags::NONBLOCK.bits() as i32,
        )
        .open(path)?;
    let after = file.metadata()?;
    if before.dev() != after.dev()
        || before.ino() != after.ino()
        || !after.is_file()
        || after.uid() != 0
        || after.nlink() != 1
        || after.mode() & 0o077 != 0
    {
        return Err("original calibrated writer FD changed".into());
    }
    Ok(file)
}

#[cfg(test)]
#[path = "initial_cpu_withdrawal_source_tests.rs"]
mod tests;
