//! Private, bounded transfer of already observed original Material.
//! Only the pinned Material client reconstructs this sealed value. Canonical
//! receipt, freeze signature, provenance and the pre-frozen Q24 rule are all
//! checked again; a digest supplied by a reply is never enough.

use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::DatasetSnapshotV2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::OriginalCellQ24DatasetV1;
use crate::CellQ24TrainingBatchV1;
use crate::CellQ24TrainingSampleV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24MaterialSourceErrorV1 as Error;
use crate::OriginalCellQ24TrainingSourceConfigV1;

/// Private protocol representation. It has no authority, constructor or
/// public decode-to-capability API. One row and at most three original
/// Decision/Outcome/Credit record digests are the supported source profile.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OriginalCellQ24MaterialWireV1 {
    ledger_binding: String,
    trust_distribution: String,
    source_publication: String,
    batch: String,
    snapshot_id: String,
    ledger_head: String,
    objective: String,
    eligible_frontier: u64,
    outcome_watermark: u64,
    source_records: Vec<String>,
    pending_outcomes: u32,
    censored_outcomes: u32,
    dataset_digest: String,
    correction_cut: String,
    revocation_cut: String,
    inclusion_policy: String,
}

impl OriginalCellQ24DatasetV1 {
    /// Project only this sealed result of actual Source/Ledger CURRENT reads.
    /// No caller-supplied label, scope, signer or observation is accepted.
    pub(crate) fn original_material_wire(&self) -> OriginalCellQ24MaterialWireV1 {
        let snapshot = &self.receipt.snapshot;
        OriginalCellQ24MaterialWireV1 {
            ledger_binding: self.ledger_binding.to_string(),
            trust_distribution: self.trust_distribution.to_string(),
            source_publication: self.source_publication.to_string(),
            batch: STANDARD_NO_PAD.encode(self.batch.encoded()),
            snapshot_id: snapshot.snapshot_id.to_string(),
            ledger_head: snapshot.ledger_head_digest.to_string(),
            objective: snapshot.objective_digest.to_string(),
            eligible_frontier: snapshot.eligible_frontier,
            outcome_watermark: snapshot.outcome_watermark,
            source_records: snapshot
                .source_record_digests
                .iter()
                .map(ToString::to_string)
                .collect(),
            pending_outcomes: snapshot.pending_outcomes,
            censored_outcomes: snapshot.censored_outcomes,
            dataset_digest: snapshot.dataset_digest.to_string(),
            correction_cut: self.receipt.correction_cut_digest.to_string(),
            revocation_cut: self.receipt.revocation_cut_digest.to_string(),
            inclusion_policy: self.receipt.inclusion_policy_digest.to_string(),
        }
    }

    /// The only product caller is the admitted original-peer client, after an
    /// actual reply on its already connected, pidfd-pinned purpose channel.
    /// All source metadata is re-bound to both complete original signatures.
    /// Time is internal; nothing here enrolls, re-signs, claims or trains.
    pub(crate) fn from_original_material_peer(
        wire: OriginalCellQ24MaterialWireV1,
        config: &OriginalCellQ24TrainingSourceConfigV1,
        baseline: Arc<LoadedCellQ24ModelV1>,
        experience: &SignedLearningEvidenceV1,
        dataset: &SignedLearningEvidenceV1,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        require_original_material_signatures(config, experience, dataset, started_at)?;
        let initial = LearningIterationCoordinatorV1::new(
            config.dataset.request.clone(),
            config.dataset.owners.clone(),
        )?;
        let policy = config.rule.inclusion_policy_digest(initial.snapshot())?;
        if wire.snapshot_id != config.freeze_plan.snapshot_id.as_str()
            || digest(&wire.objective)? != config.freeze_plan.objective_digest
            || config.freeze_plan.objective_digest
                != config.dataset.request.envelope.objective_digest
            || digest(&wire.inclusion_policy)? != policy
            || config.freeze_plan.inclusion_policy_digest != policy
            || !(2..=3).contains(&wire.source_records.len())
            || wire.pending_outcomes != 0
            || wire.censored_outcomes != 0
            || baseline.components() != &config.dataset.request.selected_bundle.components
        {
            return Err(Error::Binding("fixed original Material profile"));
        }
        let ledger_binding = digest(&wire.ledger_binding)?;
        let trust_distribution = digest(&wire.trust_distribution)?;
        let source_publication = digest(&wire.source_publication)?;
        let ledger_head = digest(&wire.ledger_head)?;
        let correction_cut = digest(&wire.correction_cut)?;
        let revocation_cut = digest(&wire.revocation_cut)?;
        let source_records = wire
            .source_records
            .iter()
            .map(|value| digest(value))
            .collect::<Result<Vec<_>, _>>()?;
        // This is the exact existing dataset_freeze_signing_payload_v2 byte
        // encoding, recomputed from the received canonical receipt fields.
        // The live original Ledger remains responsible for source-set truth.
        let freeze_payload = freeze_payload(
            config,
            ledger_head,
            wire.eligible_frontier,
            wire.outcome_watermark,
            correction_cut,
            revocation_cut,
            &source_records,
        );
        let producer = config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &config.freeze_evidence,
            &freeze_payload,
            started_at,
        )?;
        let receipt = DatasetSnapshotReceiptV3 {
            snapshot: DatasetSnapshotV2 {
                snapshot_id: config.freeze_plan.snapshot_id.clone(),
                ledger_head_digest: ledger_head,
                objective_digest: config.freeze_plan.objective_digest,
                eligible_frontier: wire.eligible_frontier,
                outcome_watermark: wire.outcome_watermark,
                source_record_digests: source_records,
                pending_outcomes: wire.pending_outcomes,
                censored_outcomes: wire.censored_outcomes,
                dataset_digest: digest(&wire.dataset_digest)?,
                authority: AuthorityPosture::DENY_ALL,
            },
            producer: producer.principal().clone(),
            correction_cut_digest: correction_cut,
            revocation_cut_digest: revocation_cut,
            inclusion_policy_digest: policy,
        };
        verify_dataset_snapshot_receipt_v3(&receipt, started_at)?;
        let batch = decode_batch(
            &wire.batch,
            receipt.snapshot.dataset_digest,
            baseline.input_width(),
        )?;
        if batch.rows() > config.dataset.request.budget.maximum_dataset_rows
            || batch.encoded().len() as u64 > config.dataset.request.budget.maximum_dataset_bytes
        {
            return Err(Error::Binding("original Material batch budget"));
        }
        let LearningIterationObservationV1::Experience {
            episode_digest,
            completed_task_receipt,
        } = &config.dataset.receipts[0].observation
        else {
            return Err(Error::Binding("original Experience observation"));
        };
        if *completed_task_receipt != config.dataset.request.completed_task_receipt {
            return Err(Error::Binding("original ordinary-task receipt"));
        }
        let mut signed_freeze = config.freeze_evidence.signing_bytes();
        signed_freeze.extend_from_slice(&config.freeze_evidence.signature);
        let provenance_digest = Digest32::of_parts(&[
            b"hepta.cell.q24.original-dataset-provenance.v1\0",
            initial.snapshot().head_digest.as_array(),
            ledger_binding.as_array(),
            trust_distribution.as_array(),
            source_publication.as_array(),
            receipt.snapshot.ledger_head_digest.as_array(),
            receipt.snapshot.dataset_digest.as_array(),
            receipt.correction_cut_digest.as_array(),
            receipt.revocation_cut_digest.as_array(),
            episode_digest.as_array(),
            batch.digest().as_array(),
            policy.as_array(),
            Digest32::of_bytes(&signed_freeze).as_array(),
        ]);
        let material = Self {
            initial_head: initial.snapshot().head_digest,
            completed_task_receipt: *completed_task_receipt,
            episode_digest: *episode_digest,
            provenance_digest,
            head: config.rule.head,
            receipt,
            batch,
            ledger_binding,
            trust_distribution,
            source_publication,
        };
        if config.dataset.receipts[0].observation != material.experience_observation()
            || config.dataset.receipts[1].observation != material.dataset_observation()
            || config.dataset.receipts[0].evidence_digest != material.provenance_digest()
            || config.dataset.receipts[1].evidence_digest != material.provenance_digest()
        {
            return Err(Error::Binding(
                "original signatures bind recomputed material",
            ));
        }
        // training_plan recomputes batch -> optimizer -> row update rule and
        // compares the resulting constraint to the already held frozen scope.
        // A response cannot install a new scope or choose another optimizer.
        let _ = material.training_plan(
            config.dataset.clone(),
            config.scope.clone(),
            baseline,
            config.optimizer,
        )?;
        let fresh_now = now()?;
        if fresh_now < started_at {
            return Err(Error::Binding("Material decode clock moved backwards"));
        }
        require_original_material_signatures(config, experience, dataset, fresh_now)?;
        config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &config.freeze_evidence,
            &freeze_payload,
            fresh_now,
        )?;
        verify_dataset_snapshot_receipt_v3(material.receipt(), fresh_now)?;
        Ok(material)
    }

    /// Reverify the same already materialized freeze after the native lane's
    /// final physical owner I/O. This reconstructs the existing signed payload;
    /// it grants no new Dataset, new window, or source CURRENT observation.
    pub(crate) fn require_original_freeze_current(
        &self,
        config: &OriginalCellQ24TrainingSourceConfigV1,
        at: u64,
    ) -> Result<(), Error> {
        let receipt = self.receipt();
        let snapshot = &receipt.snapshot;
        if snapshot.snapshot_id != config.freeze_plan.snapshot_id
            || snapshot.objective_digest != config.freeze_plan.objective_digest
            || receipt.inclusion_policy_digest != config.freeze_plan.inclusion_policy_digest
        {
            return Err(Error::Binding("same original source freeze plan"));
        }
        let payload = freeze_payload(
            config,
            snapshot.ledger_head_digest,
            snapshot.eligible_frontier,
            snapshot.outcome_watermark,
            receipt.correction_cut_digest,
            receipt.revocation_cut_digest,
            &snapshot.source_record_digests,
        );
        let verified = config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &config.freeze_evidence,
            &payload,
            at,
        )?;
        if verified.principal() != &receipt.producer {
            return Err(Error::Binding("same original source freeze producer"));
        }
        verify_dataset_snapshot_receipt_v3(receipt, at)?;
        Ok(())
    }
}

fn require_original_material_signatures(
    config: &OriginalCellQ24TrainingSourceConfigV1,
    experience: &SignedLearningEvidenceV1,
    dataset: &SignedLearningEvidenceV1,
    at: u64,
) -> Result<(), Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.dataset.clone())?;
    config.scope.validate_snapshot(&config.dataset)?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
        || config.dataset.receipts.len() != 2
        || config.dataset.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.dataset.request.envelope.objective_digest != config.verifier.objective_digest()
        || experience != &config.experience_evidence
        || dataset != &config.dataset_evidence
        || at < config.freeze_evidence.issued_at
        || at >= config.freeze_evidence.expires_at
    {
        return Err(Error::Binding(
            "fixed original Material signatures and scope",
        ));
    }
    for (receipt, evidence) in config.dataset.receipts.iter().zip([experience, dataset]) {
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let verified =
            config
                .verifier
                .verify(LearningEvidenceRoleV1::Observer, evidence, &payload, at)?;
        if verified.principal().principal_id != receipt.actor_id
            || receipt.observed_unix_seconds != evidence.issued_at
            || receipt.observed_unix_seconds > at
        {
            return Err(Error::Binding("original Material signer and window"));
        }
    }
    Ok(())
}

fn decode_batch(
    text: &str,
    dataset: Digest32,
    expected_width: usize,
) -> Result<CellQ24TrainingBatchV1, Error> {
    if text.is_empty() || text.len() > 1_024 {
        return Err(Error::Binding("bounded canonical original batch"));
    }
    let bytes = STANDARD_NO_PAD
        .decode(text)
        .map_err(|_| Error::Binding("batch base64"))?;
    if STANDARD_NO_PAD.encode(&bytes) != text || bytes.len() < 44 || &bytes[..8] != b"HQ24T001" {
        return Err(Error::Binding("canonical HQ24T001 batch"));
    }
    if &bytes[8..40] != dataset.as_array() {
        return Err(Error::Binding("original batch Dataset digest"));
    }
    let width = usize::from(u16::from_le_bytes([bytes[40], bytes[41]]));
    let rows = u16::from_le_bytes([bytes[42], bytes[43]]);
    if width != expected_width || !(1..=64).contains(&width) || rows != 1 {
        return Err(Error::Binding("one original row and loaded input width"));
    }
    let length = 44_usize
        .checked_add(
            width
                .checked_add(1)
                .and_then(|n| n.checked_mul(8))
                .ok_or(Error::Binding("batch length overflow"))?,
        )
        .ok_or(Error::Binding("batch length overflow"))?;
    if bytes.len() != length {
        return Err(Error::Binding("exact original batch length"));
    }
    let values = bytes[44..]
        .chunks_exact(8)
        .map(|chunk| {
            let raw: [u8; 8] = chunk
                .try_into()
                .map_err(|_| Error::Binding("batch integer"))?;
            Ok(i64::from_le_bytes(raw))
        })
        .collect::<Result<Vec<_>, Error>>()?;
    let batch = CellQ24TrainingBatchV1::new(
        dataset,
        vec![CellQ24TrainingSampleV1 {
            input: values[..width].to_vec(),
            target: values[width],
        }],
    )?;
    if batch.encoded() != bytes.as_slice() {
        return Err(Error::Binding("reencoded canonical original batch"));
    }
    Ok(batch)
}

fn freeze_payload(
    config: &OriginalCellQ24TrainingSourceConfigV1,
    ledger_head: Digest32,
    eligible_frontier: u64,
    outcome_watermark: u64,
    correction_cut: Digest32,
    revocation_cut: Digest32,
    records: &[Digest32],
) -> Vec<u8> {
    let mut bytes = b"hepta.learning-ledger.dataset-freeze-plan.v2".to_vec();
    let id = config.freeze_plan.snapshot_id.as_str().as_bytes();
    bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(config.freeze_plan.objective_digest.as_array());
    bytes.extend_from_slice(config.freeze_plan.inclusion_policy_digest.as_array());
    bytes.extend_from_slice(ledger_head.as_array());
    bytes.extend_from_slice(&eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(correction_cut.as_array());
    bytes.extend_from_slice(revocation_cut.as_array());
    bytes.extend_from_slice(&(records.len() as u64).to_be_bytes());
    for digest in records {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

fn digest(text: &str) -> Result<Digest32, Error> {
    let value: Digest32 = text
        .parse()
        .map_err(|_| Error::Binding("material digest"))?;
    if value.is_zero() || value.to_string() != text {
        return Err(Error::Binding("canonical nonzero material digest"));
    }
    Ok(value)
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("Material clock before Unix epoch"))
}
