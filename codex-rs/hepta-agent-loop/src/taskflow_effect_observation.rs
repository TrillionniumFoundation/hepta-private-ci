//! Read the existing native cursor to gate a prebound effect. No cursor write,
//! context preparation, owner claim or authority grant occurs here.

use super::*;

pub(crate) async fn observe_bound_effect_turn(
    store: &AutomationStore,
    fence: &TaskFlowFence,
    binding: &TurnBinding,
) -> Result<(Frame, TaskFlowRun)> {
    let cursor = store
        .taskflow_cursor(binding.run_id.as_str(), binding.turn_id.as_str(), fence)
        .await
        .map_err(store_error)?
        .ok_or(Error::Contract("original native effect cursor absent"))?;
    let saved: Snapshot = serde_json::from_str(&cursor.payload)
        .map_err(|_| Error::Contract("original native effect cursor encoding"))?;
    if saved.initial.binding != *binding
        || cursor.run_id != binding.run_id.as_str()
        || cursor.turn_key != binding.turn_id.as_str()
    {
        return Err(Error::Contract("original native effect cursor binding"));
    }
    let frame = saved.replay_retained()?;
    let run = store
        .taskflow_run(binding.run_id.as_str())
        .await
        .map_err(store_error)?
        .ok_or(Error::Contract("original native effect run absent"))?;
    if cursor.revision
        != frame
            .revision
            .checked_add(1)
            .ok_or(Error::Contract("native effect revision overflow"))?
        || cursor.run_revision > run.revision
        || run.owner_agent_id != fence.owner_agent_id
        || run.owner_id.as_deref() != Some(fence.owner_id.as_str())
        || run.owner_epoch != Some(fence.owner_epoch)
        || run.generation != Some(fence.generation)
        || run.fencing_token.as_deref() != Some(fence.fencing_token.as_str())
    {
        return Err(Error::Contract("original native effect owner changed"));
    }
    Ok((frame, run))
}
