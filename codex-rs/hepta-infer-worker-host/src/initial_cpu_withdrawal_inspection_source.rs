//! Original witnessed source ACK inspection. No writer/recovery/seed is opened.
use super::super::*;
use super::Request;
use super::source::ArchiveUse;
use super::source::authenticated_archive;
use super::source::directory;
use codex_hepta_agent_components::learning_ledger as ledger;
use std::os::unix::fs::MetadataExt;

pub(super) struct SourceInspection {
    pub ack: Value,
    pub notice: DatasetWithdrawalNoticeV1,
}

pub(super) fn read(
    request: &Request,
    evidence: &ledger::SignedLearningEvidenceV1,
    expected_source: Digest32,
    expected_event: Digest32,
) -> HostResult<SourceInspection> {
    let original = authenticated_archive(request, ArchiveUse::AcknowledgedHistory)?;
    directory(&request.ledger_directory)?;
    directory(&request.witness_directory)?;
    let witness = request.witness_directory.join("acknowledged-frontier.bin");
    let causal = request.ledger_directory.join("causal-ledger.bin");
    for path in [&witness, &causal] {
        if ledger::open_root_review_input(path)?.metadata()?.mode() & 0o077 != 0 {
            return Err("original source/witness must remain private".into());
        }
    }
    let before = read_root_review_input(&witness, 1024 * 1024)?;
    let frontier = ledger::inspect_ledger_witness_frontier(
        ledger::open_root_review_input(&witness)?,
        original.binding,
        8192,
    )?;
    let actual = ledger::inspect_ledger(
        ledger::open_root_review_input(&causal)?,
        original.binding,
        4096,
        frontier.anchor,
    )?;
    if read_root_review_input(&witness, 1024 * 1024)? != before
        || actual.records().get(..original.archived.records().len())
            != Some(original.archived.records())
    {
        return Err("original independent witness/calibration prefix changed".into());
    }
    let source = actual
        .records()
        .iter()
        .find(|record| record.event.record_id().as_str() == request.source_record_id)
        .ok_or("original unlearning source disappeared")?;
    if !original
        .dataset
        .snapshot
        .source_record_digests
        .contains(&source.event_digest)
        || expected_source != source.event_digest
    {
        return Err("original source is not in the actual calibrated dataset".into());
    }
    let native = ledger::UnlearningLineageRequestV1 {
        record_id: id(&request.record_id)?,
        lineage_id: id(&request.lineage_id)?,
        source_record_id: id(&request.source_record_id)?,
        dataset_snapshot_id: original.dataset.snapshot.snapshot_id.clone(),
        dataset_digest: original.dataset.snapshot.dataset_digest,
        artifact_id: id(&request.artifact_id)?,
        reason_digest: digest(&request.reason_digest)?,
    };
    let verified = original.trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::UnlearningAuthority,
        evidence,
        &ledger::unlearning_signing_payload_v1(&native),
        evidence.issued_at,
    )?;
    let principal = verified.principal();
    let record = actual
        .records()
        .iter()
        .find(|record| record.event.record_id() == &native.record_id)
        .ok_or("original source append has no independently acknowledged record")?;
    let ledger::LedgerEvent::UnlearningLineageV1(event) = &record.event else {
        return Err("original source ACK is not an unlearning record".into());
    };
    let mut authentication = evidence.signing_bytes();
    authentication.extend_from_slice(&evidence.signature);
    let expected = ledger::UnlearningLineageEventV1 {
        record_id: native.record_id,
        lineage_id: native.lineage_id,
        source_record_id: native.source_record_id,
        source_event_digest: source.event_digest,
        dataset_snapshot_id: native.dataset_snapshot_id,
        dataset_digest: native.dataset_digest,
        artifact_id: native.artifact_id,
        authority_id: principal.principal_id.clone(),
        reason_digest: native.reason_digest,
        authentication_digest: Digest32::of_bytes(&authentication),
    };
    if event != &expected
        || record.predecessor_chain_digest != digest(&request.expected_ledger_head)?
        || record.event_digest != expected_event
    {
        return Err("original source ACK/evidence/canonical event was substituted".into());
    }
    request.calibration_archive.read(8 * 1024 * 1024)?;
    Ok(SourceInspection {
        ack: serde_json::json!({"lineage_id":event.lineage_id.as_str(),"source_record_id":event.source_record_id.as_str(),
            "source_event_digest":event.source_event_digest.to_string(),"dataset_snapshot_id":event.dataset_snapshot_id.as_str(),
            "dataset_digest":event.dataset_digest.to_string(),"artifact_id":event.artifact_id.as_str(),
            "sequence":record.sequence.get(),"event_digest":record.event_digest.to_string(),"chain_digest":record.chain_digest.to_string()}),
        notice: DatasetWithdrawalNoticeV1 {
            notice_id: event.lineage_id.clone(),
            dataset_digest: event.dataset_digest,
            source_tombstone_digest: record.event_digest,
            authority_id: principal.principal_id.clone(),
            credential_chain_digest: principal.credential_chain_digest,
            signing_key_digest: principal.signing_key_digest,
            authority_epoch: principal.authority_epoch,
            issued_at: evidence.issued_at,
        },
    })
}
