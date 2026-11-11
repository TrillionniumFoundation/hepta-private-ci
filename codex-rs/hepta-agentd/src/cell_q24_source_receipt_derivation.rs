//! Canonical observations derived from original owners, never caller receipts.

use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWitnessFrontier;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::freeze_dataset_from_ledger;

use super::*;

#[derive(Eq, PartialEq)]
pub(super) struct OriginalSource {
    // Compared across one operation, but never substituted into an old receipt.
    current: LedgerWitnessFrontier,
    episode: Digest32,
    evidence: Digest32,
    completion: Digest32,
    dataset: Digest32,
    revocation_cut: Digest32,
    rows: u32,
    bytes: u64,
}

pub(super) fn read<SW: AnchorWitnessStore>(
    config: &OriginalCellQ24SourceSigningConfigV1,
    material: &OriginalCellQ24DatasetV1,
    original_material: &[u8],
    ledger: &LedgerWriter,
    source: &CircuitTaskSourceReadbackV1<SW>,
    identity: &AgentdIdentity,
) -> Result<OriginalSource, Error> {
    let before = super::super::current_ledger(ledger, identity, &material.profile)?;
    let request = &config.predecessor.snapshot().request;
    if recovery::original_material_bytes(material)? != original_material
        || material.profile.principal_id != request.principal_id
        || material.profile.agent_id.as_str() != request.agent_id.as_str()
        || material.profile.cell_id != request.cell_id
        || material.profile.objective_digest != request.envelope.objective_digest
        || material.profile.selected_bundle
            != request
                .selected_bundle
                .digest()
                .map_err(|_| Error::Binding("original selected bundle"))?
        || material.profile.evidence_trust_digest != config.verifier.trust_digest()
    {
        return Err(Error::Binding("complete original material and request"));
    }
    material.require_request_source(&request.source_run_id, request.completed_task_receipt)?;
    OriginalCellQ24DatasetV1::revalidate(material, ledger, source, identity)?;

    // Reproduce the exact signed freeze from the actual ledger's original prefix.
    // Neither an independently self-consistent receipt nor an appended tail is
    // a substitute for those complete original records and the original plan.
    let prefix = recovery::original_prefix(ledger, material.dataset.snapshot.ledger_head_digest)?;
    let plan = DatasetFreezePlanV2 {
        snapshot_id: material.dataset.snapshot.snapshot_id.clone(),
        objective_digest: material.dataset.snapshot.objective_digest,
        inclusion_policy_digest: material.dataset.inclusion_policy_digest,
    };
    let payload = dataset_freeze_signing_payload_v2(&prefix, &plan)?;
    if payload != material.freeze_payload {
        return Err(Error::Binding("original complete freeze payload"));
    }
    let at = now()?;
    let verified = ledger.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &material.evidence,
        &payload,
        at,
    )?;
    if freeze_dataset_from_ledger(&prefix, plan, verified.principal().clone(), at)?
        != material.dataset
    {
        return Err(Error::Binding("original complete Dataset receipt"));
    }
    let records = LedgerWriter::read_dataset_records(ledger, &material.dataset, at)?;
    if records
        .iter()
        .any(|record| !prefix.records().contains(*record))
    {
        return Err(Error::Binding(
            "selected record outside original signed prefix",
        ));
    }
    let mut decisions = records.iter().filter_map(|record| match &record.event {
        LedgerEvent::AuthenticatedDecisionV2(decision)
            if decision.record_id == request.source_run_id =>
        {
            Some((*record, decision))
        }
        _ => None,
    });
    let (decision_record, decision) = decisions
        .next()
        .ok_or(Error::Binding("missing original triggering Decision"))?;
    if decisions.next().is_some() {
        return Err(Error::Binding("multiple original triggering Decisions"));
    }
    let mut outcomes = records.iter().filter_map(|record| match &record.event {
        LedgerEvent::AuthenticatedOutcomeV2(outcome)
            if outcome.episode_id == decision.episode_id =>
        {
            Some((*record, outcome))
        }
        _ => None,
    });
    let (outcome_record, outcome) = outcomes
        .next()
        .ok_or(Error::Binding("missing original triggering Outcome"))?;
    if outcomes.next().is_some() {
        return Err(Error::Binding("multiple original triggering Outcomes"));
    }
    // Experience is the original Outcome Observer. A separately enrolled
    // Dataset Observer is allowed only through its actual Experience owner.
    if config.predecessor.stage() == LearningIterationStageV1::Experience
        && (outcome.observer_id != config.signer.principal.principal_id
            || outcome.observer_controller_id != config.signer.controller_id
            || outcome.observer_credential_chain_digest
                != config.signer.principal.credential_chain_digest
            || outcome.observer_signing_key_digest != config.signer.principal.signing_key_digest
            || outcome.observer_scope_digest != config.signer.principal.scope_digest
            || outcome.observer_authority_epoch != config.signer.principal.authority_epoch)
    {
        return Err(Error::Binding(
            "original terminal Outcome Observer identity",
        ));
    }
    let published = source
        .read_run_publication(identity, &request.source_run_id)
        .map_err(OriginalCellQ24DatasetErrorV1::from)?;
    if !material.publications.contains(&published)
        || published.history_digest().as_str().parse::<Digest32>().ok()
            != Some(request.completed_task_receipt)
        || outcome.support_digest != published.publication_digest()
        || outcome.terminality
            != codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality::Terminal
    {
        return Err(Error::Binding(
            "original A publication and terminal Observer Outcome",
        ));
    }
    let mut episode = b"hepta.agentd.original-q24-episode.v1\0".to_vec();
    episode.extend_from_slice(ledger.binding_digest().as_array());
    super::super::push_text(&mut episode, decision.episode_id.as_str());
    episode.extend_from_slice(decision_record.event_digest.as_array());
    episode.extend_from_slice(outcome_record.event_digest.as_array());
    let evidence = Digest32::of_parts(&[
        b"hepta.agentd.original-q24-source-observation.v1\0",
        Digest32::of_bytes(original_material).as_array(),
        decision_record.chain_digest.as_array(),
        outcome_record.chain_digest.as_array(),
        published.publication_digest().as_array(),
        request.completed_task_receipt.as_array(),
    ]);
    OriginalCellQ24DatasetV1::revalidate(material, ledger, source, identity)?;
    if super::super::current_ledger(ledger, identity, &material.profile)? != before {
        return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
    }
    Ok(OriginalSource {
        current: before,
        episode: Digest32::of_bytes(&episode),
        evidence,
        completion: request.completed_task_receipt,
        dataset: material.dataset.snapshot.dataset_digest,
        revocation_cut: material.dataset.revocation_cut_digest,
        rows: material.batch.rows(),
        bytes: material.batch.encoded().len() as u64,
    })
}

pub(super) fn receipt(
    config: &OriginalCellQ24SourceSigningConfigV1,
    original: &OriginalSource,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    let cut = config.predecessor.snapshot();
    let (domain, observation): (&[u8], _) = match config.predecessor.stage() {
        LearningIterationStageV1::Experience => (
            b"hepta.agentd.original-q24-experience-evidence.v1\0",
            LearningIterationObservationV1::Experience {
                episode_digest: original.episode,
                completed_task_receipt: original.completion,
            },
        ),
        LearningIterationStageV1::Dataset => (
            b"hepta.agentd.original-q24-dataset-evidence.v1\0",
            LearningIterationObservationV1::Dataset {
                snapshot_digest: original.dataset,
                episode_digest: original.episode,
                // Historical Ledger revocation cut, as in the original Q24
                // ingress contract. Current source withdrawal was read above;
                // this field is not a global current source-owner frontier.
                withdrawal_frontier: original.revocation_cut,
                rows: original.rows,
                bytes: original.bytes,
            },
        ),
        LearningIterationStageV1::Training
        | LearningIterationStageV1::Evaluation
        | LearningIterationStageV1::Proposal
        | LearningIterationStageV1::Selection
        | LearningIterationStageV1::NextUse => {
            return Err(Error::Binding("original source receipt stage"));
        }
    };
    let receipt = LearningIterationReceiptV1 {
        operation_id: cut.request.operation_id.clone(),
        predecessor: cut.head_digest,
        actor_id: cut.owners.owner(config.predecessor.stage()).clone(),
        evidence_digest: Digest32::of_parts(&[domain, original.evidence.as_array()]),
        observed_unix_seconds,
        observation,
    };
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(cut.clone())?;
    coordinator.record(receipt.clone(), observed_unix_seconds)?;
    config.scope.validate_snapshot(coordinator.snapshot())?;
    Ok(receipt)
}
