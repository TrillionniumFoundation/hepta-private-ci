//! New hosted input must not cross an unfinished original logical turn.
//! This reads the existing history; it owns no queue, permit, or held flag.

use codex_history::{RolloutItem, RolloutLine};
use codex_protocol::error::{CodexErr, Result as CodexResult};
use codex_protocol::protocol::EventMsg;
use codex_thread_store::PersistContext;
use tokio::io::BufReader;

use crate::hosted_turn::invalid;
use crate::session::session::Session;

/// The caller holds Core's idle active-turn lock through this read and the
/// subsequent original reservation. This helper never acquires that lock.
/// Deferred first histories are materialized through the original owner;
/// missing files and failed reads cannot be mistaken for an empty safe tail.
pub(crate) async fn allows_new_turn(session: &Session) -> CodexResult<bool> {
    let live = session.live_thread_for_persistence("verify hosted new-turn admission")
        .map_err(|error| invalid(&error.to_string()))?;
    live.persist(PersistContext::TurnStart).await.map_err(|error| invalid(&error.to_string()))?;
    live.flush().await.map_err(|error| invalid(&error.to_string()))?;
    let path = live.local_rollout_path().await.map_err(|error| invalid(&error.to_string()))?
        .ok_or_else(|| invalid("hosted admission requires its original local history owner"))?;
    let mut reader = BufReader::new(tokio::fs::File::open(path).await.map_err(CodexErr::from)?);
    let mut tail = AdmissionTail::default();
    while let Some(bytes) = super::read_bounded_line(&mut reader).await? {
        if bytes.iter().all(u8::is_ascii_whitespace) { continue; }
        let line: RolloutLine = serde_json::from_slice(&bytes)
            .map_err(|error| invalid(&format!("original hosted admission history is malformed: {error}")))?;
        tail.observe(&line.item)?;
    }
    Ok(tail.open.is_none())
}

#[derive(Default)]
struct AdmissionTail { open: Option<String> }

impl AdmissionTail {
    fn observe(&mut self, item: &RolloutItem) -> CodexResult<()> {
        match item {
            RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => {
                if self.open.as_ref().is_some_and(|original| original != &event.turn_id) {
                    return Err(invalid("new hosted turn crossed an unfinished original history"));
                }
                // Repeated starts of this same logical turn remain open. The
                // separate recovery reader validates their typed succession;
                // this lifecycle observation cannot authorize recovery.
                self.open = Some(event.turn_id.clone());
            }
            RolloutItem::EventMsg(EventMsg::TurnComplete(event)) => {
                if self.open.as_deref().is_some_and(|original| original != event.turn_id) {
                    return Err(invalid("hosted admission history has an unmatched completion"));
                }
                self.open = None;
            }
            RolloutItem::EventMsg(EventMsg::TurnAborted(event)) => {
                if self.open.is_some() && self.open.as_deref() != event.turn_id.as_deref() {
                    return Err(invalid("hosted admission history has an unmatched cancellation"));
                }
                // Core can cancel a reserved task before it records its first
                // TurnStarted. That terminal cannot hide any earlier open turn.
                self.open = None;
            }
            _ => {}
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "hosted_turn_admission_tests.rs"]
mod tests;
