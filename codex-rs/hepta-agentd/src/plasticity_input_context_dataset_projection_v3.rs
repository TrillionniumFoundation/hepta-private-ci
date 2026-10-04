//! Verify the explicit dataset purpose without opening an owner or writer.
use super::*;
use codex_hepta_agent_components::learning_ledger::ReviewEvidenceWireV1;

pub(super) fn project(
    input: &ParameterInputContextDatasetV3<'_>,
    verifier: &LearningEvidenceVerifierV1,
    round: &crate::AgentdSelfIterationRoundV1,
    now: u64,
) -> Result<
    (
        DatasetSnapshotReceiptV3,
        Digest32,
        Option<dataset_window::DatasetWindowDescriptorV3>,
    ),
    AgentdError,
> {
    let decode = |e| AgentdError::Invalid(format!("whole context dataset: {e}"));
    let (dataset, head, predecessor, window) = match input {
        ParameterInputContextDatasetV3::OriginalV2(facts) => {
            let dataset = facts.dataset.native().map_err(decode)?;
            if dataset.snapshot.ledger_head_digest.to_string() != facts.ledger_head_digest
                || dataset.snapshot.eligible_frontier > facts.ledger_record_count
            {
                return invalid("original dataset observation differs");
            }
            crate::plasticity_runtime::parameter_dataset::parameter_dataset_window::bounded_hex(
                &facts.freeze_payload_hex,
                crate::MAX_CONTROL_FRAME_BYTES as usize / 2,
            )?;
            (
                dataset,
                &facts.installed_artifact_head,
                &facts.proposal_registry_predecessor,
                None,
            )
        }
        ParameterInputContextDatasetV3::WindowV3 {
            facts,
            plan,
            window,
            evaluator,
        } => {
            facts.validate_at(round, now)?;
            let original_plan = facts.plan.native().map_err(decode)?;
            let original = facts.window.native().map_err(decode)?;
            let payload = crate::plasticity_runtime::parameter_dataset::parameter_dataset_window::bounded_hex(
                &facts.freeze_payload_hex, 4096 * 32 + 4096)?;
            let authenticated = verifier
                .verify(LearningEvidenceRoleV1::Evaluator, evaluator, &payload, now)
                .map_err(|e| AgentdError::Invalid(format!("dataset Window signature: {e}")))?;
            let actual = &window.receipt;
            let initial = &original.receipt;
            // Producer identity/times and dataset digest come from actual E,
            // rather than attaching a signature to the unsigned port receipt.
            if *plan != &original_plan
                || window.window_policy_digest != original.window_policy_digest
                || authenticated.principal() != &actual.producer
                || (
                    &actual.snapshot.snapshot_id,
                    actual.snapshot.ledger_head_digest,
                    actual.snapshot.objective_digest,
                    actual.snapshot.eligible_frontier,
                    actual.snapshot.outcome_watermark,
                    &actual.snapshot.source_record_digests,
                    actual.snapshot.pending_outcomes,
                    actual.snapshot.censored_outcomes,
                    actual.correction_cut_digest,
                    actual.revocation_cut_digest,
                    actual.inclusion_policy_digest,
                ) != (
                    &initial.snapshot.snapshot_id,
                    initial.snapshot.ledger_head_digest,
                    initial.snapshot.objective_digest,
                    initial.snapshot.eligible_frontier,
                    initial.snapshot.outcome_watermark,
                    &initial.snapshot.source_record_digests,
                    initial.snapshot.pending_outcomes,
                    initial.snapshot.censored_outcomes,
                    initial.correction_cut_digest,
                    initial.revocation_cut_digest,
                    initial.inclusion_policy_digest,
                )
            {
                return invalid("independent E Window changed the complete frozen selection");
            }
            (actual.clone(), &facts.installed_artifact_head, &facts.proposal_registry_predecessor,
                Some(dataset_window::DatasetWindowDescriptorV3 {
                    plan: codex_hepta_agent_components::learning_ledger::DatasetWindowFreezePlanWireV3::from_native(plan),
                    window: codex_hepta_agent_components::learning_ledger::DatasetWindowSnapshotWireV3::from_native(window),
                    evaluator: ReviewEvidenceWireV1::from_native(evaluator),
                }))
        }
    };
    let head = digest(head, "held installed artifact head")?;
    let _predecessor = Digest32::from_str(predecessor)
        .map_err(|_| AgentdError::Invalid("held proposal predecessor".into()))?;
    Ok((dataset, head, window))
}
