//! Process-local reopening of the original research CURRENT and guarded journal.
//! No admission, nonce claim, ACK append, grant renewal, or model call occurs.

use super::*;
use crate::learning_iteration_checkpoint::os_process_recovery::RecoveryContext;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;
use std::sync::Arc;

pub(crate) fn reopen_generation(context: &RecoveryContext) -> anyhow::Result<()> {
    let current_file = Arc::new(FileCas::<CurrentHead>::reopen(
        &context.root.join("current.json"),
        current_id(&context.old_config)?,
    )?);
    let current = Arc::new(NeuronGenerationCurrentOwnerV1 {
        store: CurrentStore::from_test_store(&context.old_config.initial.scope, current_file)?,
    });
    let prepared = current.recover_operation(
        &context.operation_id,
        Digest32::from_array(context.intent_digest),
    )?;
    anyhow::ensure!(
        matches!(
            current.read_operation(&prepared)?,
            super::super::types::NeuronGenerationUpdateReadbackV1::Published(_)
        ),
        "original CURRENT is not published"
    );
    let open = |name: &str| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(context.root.join(name))
    };
    let binding = CellGenerationOwnerBindingV1::new(&context.target_config, RECORDS)?;
    let witness = FileAnchorWitnessStore::open(
        open("target-witness")?,
        JournalScope {
            scope_digest: Digest32::from_array(binding.digest()?),
            objective_digest: Digest32::from_array(context.target_config.task_digest),
        },
        Generation::new(context.target_config.initial.generation)?,
        /*max_records*/ 256,
    )?;
    let journal = CellGenerationJournalV2::open_guarded(
        open("target-journal")?,
        witness,
        context.target_config.clone(),
        RECORDS,
        current,
    )?;
    journal.require_current()?;
    assert_eq!(
        journal.lookup(&context.request)?,
        Some(context.receipt.clone())
    );
    assert_eq!(
        journal.receipt_for_intent(&context.request.intent()?)?,
        Some(context.receipt.clone())
    );
    anyhow::ensure!(
        journal.is_drained()?
            && journal.observe_generation()?.is_terminal()
            && journal.pending_request()?.is_none()
            && journal.pending_output()?.is_none(),
        "original next task is not completed and acknowledged"
    );
    Ok(())
}

pub(crate) fn reopen_checkpoint(
    root: &std::path::Path,
    update_rule: Digest32,
    initial: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
) -> anyhow::Result<crate::LearningIterationCheckpointOwnerV1> {
    let owner_id = format!("research-checkpoint:{}", initial.request.operation_id);
    let store = Arc::new(FileCas::reopen(
        &root.join("learning-checkpoint"),
        owner_id.clone(),
    )?);
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        update_rule,
    )?;
    Ok(
        crate::LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(
            store,
            owner_id,
            initial.request.clone(),
            initial.owners.clone(),
            scope,
        )?,
    )
}
