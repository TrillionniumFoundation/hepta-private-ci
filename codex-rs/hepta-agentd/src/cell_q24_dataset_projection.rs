//! Pure, canonical Dataset projection shared by the recipient and Root.
//! These data parameters provide no source, signer or training authority.
//! Only the actual owner may attach its private capability after independent
//! currentness, signature and physical-observation checks have all completed.

use std::collections::BTreeMap;

use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_types::ProbabilityQ32;

use super::*;

pub(crate) fn project_original_q24_dataset_v1(
    frozen: &LedgerSnapshot,
    receipt: &DatasetSnapshotReceiptV3,
    projection: &CellQ24DatasetProjectionV1,
    records: &[LedgerRecord],
    original_tasks: &[(CircuitTaskSourcePublicationV1, CellDecisionReceiptV1)],
    observed_at: u64,
) -> Result<CellQ24TrainingBatchV1, Error> {
    let profile = projection.inclusion_policy_digest()?;
    if !(1..=256).contains(&original_tasks.len())
        || frozen.records().len() > 4096
        || receipt.snapshot.source_record_digests.len() > 512
        || receipt.inclusion_policy_digest != profile
        || receipt.snapshot.pending_outcomes != 0
        || receipt.snapshot.censored_outcomes != 0
    {
        return Err(Error::Binding("bounded complete Dataset and projection"));
    }
    // Rebuild the exact active sequence from the complete original snapshot.
    // A peer's selected records or reordered digest vector cannot select rows.
    if LedgerSnapshot::read_dataset_records(frozen, receipt, observed_at)? != records {
        return Err(Error::Binding("exact frozen Dataset records in sequence"));
    }
    let mut decisions = Vec::new();
    let mut outcomes = BTreeMap::new();
    for record in records {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => decisions.push((record, value)),
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                if outcomes
                    .insert(&value.episode_id, (record, value))
                    .is_some()
                {
                    return Err(Error::Binding("ambiguous outcome per decision"));
                }
            }
            _ => return Err(Error::Binding("unsupported Dataset event")),
        }
    }
    if decisions.len() != original_tasks.len() || outcomes.len() != decisions.len() {
        return Err(Error::Binding("one source and outcome per decision"));
    }
    let mut tasks = BTreeMap::new();
    for (publication, decision) in original_tasks {
        if tasks
            .insert(&publication.input().scope.run_id, (publication, decision))
            .is_some()
        {
            return Err(Error::Binding("duplicate original task"));
        }
    }
    let mut samples = Vec::with_capacity(decisions.len());
    let mut transcript = profile.as_array().to_vec();
    for (record, decision) in decisions {
        let (publication, original) = tasks
            .remove(&decision.record_id)
            .ok_or(Error::Binding("original decision run"))?;
        let (outcome_record, outcome) = outcomes
            .remove(&decision.episode_id)
            .ok_or(Error::Binding("original Terminal outcome"))?;
        // The ledger canonicalizes candidate IDs; the source output still
        // binds the original policy order and its exact one-hot weights.
        let mut original_candidates = original
            .policy
            .iter()
            .map(|entry| entry.candidate_id.clone())
            .collect::<Vec<_>>();
        original_candidates.sort();
        if decision.run_snapshot_digest != cell_q24_dataset_run_snapshot_digest_v1(publication)
            || decision.objective_digest != publication.input().objective_digest
            || decision.objective_digest != receipt.snapshot.objective_digest
            || decision.policy_digest != Digest32::of_bytes(publication.output())
            || decision.support_digest != publication.publication_digest()
            || outcome.support_digest != publication.publication_digest()
            || publication.bundle_digest() != projection.baseline_bundle
            || decision.selected_candidate_id != original.selected_candidate
            || decision.selected_propensity != ProbabilityQ32::ONE
            || original.policy.iter().any(|p| {
                p.probability_ppm
                    != if p.candidate_id == original.selected_candidate {
                        1_000_000
                    } else {
                        0
                    }
            })
            || !original
                .policy
                .iter()
                .any(|p| p.candidate_id == original.selected_candidate && p.allowed)
            || decision.candidate_ids != original_candidates
            || outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
            || outcome.correction_predecessor.is_some()
            || outcome.unit_profile_digest != projection.unit_profile_digest
            || outcome_record.sequence <= record.sequence
        {
            return Err(Error::Binding(
                "exact task, model, decision, unit and outcome",
            ));
        }
        let raw = outcome.value.ok_or(Error::Binding("missing target"))?.raw();
        if !(-(8_i64 << 32)..=(8_i64 << 32)).contains(&raw) {
            return Err(Error::Binding("target range before conversion"));
        }
        let input = codec::input(
            &publication.input().observation,
            usize::from(projection.input_width),
        )
        .map_err(|_| Error::Binding("original HQ24I001 input"))?;
        samples.push(CellQ24TrainingSampleV1 {
            input,
            target: raw / 256,
        });
        for digest in [
            record.event_digest,
            outcome_record.event_digest,
            publication.publication_digest(),
        ] {
            transcript.extend_from_slice(digest.as_array());
        }
    }
    let mut batch = CellQ24TrainingBatchV1::new(receipt.snapshot.dataset_digest, samples)
        .map_err(|_| Error::Binding("bounded native samples"))?;
    batch.encoded[..8].copy_from_slice(b"HQ24T002");
    batch.encoded.extend_from_slice(profile.as_array());
    batch
        .encoded
        .extend_from_slice(Digest32::of_bytes(&transcript).as_array());
    batch.digest = Digest32::of_bytes(&batch.encoded);
    // new() sets source=None. This private pure kernel deliberately never
    // attaches OriginalDataset, even though its canonical format is HQ24T002.
    Ok(batch)
}
