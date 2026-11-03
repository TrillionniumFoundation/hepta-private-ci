//! Bounded route discovery through the original live writer's history.
//! The discovered correlation is not a grant; the host must verify its original
//! checkpoint and may only observe old effects when Core reserves recovery.

use codex_history::{RolloutLine, TurnRecoveryRequestBinding};
use codex_protocol::error::{CodexErr, Result as CodexResult};
use tokio::io::{AsyncBufReadExt, BufReader};

use crate::hosted_turn::invalid;
use crate::session::session::Session;

#[path = "hosted_turn_admission.rs"]
mod admission;
pub(crate) use admission::allows_new_turn;

#[path = "hosted_turn_history_scan.rs"]
mod scan;

pub(crate) struct HostedRecoveryHistory {
    pub(crate) original: TurnRecoveryRequestBinding,
    pub(crate) latest_generation: u64,
    pub(crate) preparation_interrupted: bool,
}

pub(crate) async fn load(session: &Session, turn_id: &str) -> CodexResult<HostedRecoveryHistory> {
    let live = session.live_thread_for_persistence("find original hosted recovery")
        .map_err(|error| invalid(&error.to_string()))?;
    live.flush().await.map_err(|error| invalid(&error.to_string()))?;
    let path = live.local_rollout_path().await.map_err(|error| invalid(&error.to_string()))?
        .ok_or_else(|| invalid("hosted recovery requires the original local rollout owner"))?;
    let file = tokio::fs::File::open(path).await.map_err(CodexErr::from)?;
    let mut reader = BufReader::new(file);
    let mut history = scan::HostedHistoryScan::new(turn_id);
    while let Some(bytes) = read_bounded_line(&mut reader).await? {
        if bytes.iter().all(u8::is_ascii_whitespace) { continue; }
        let record: RolloutLine = serde_json::from_slice(&bytes)
            .map_err(|error| invalid(&format!("original hosted history is malformed: {error}")))?;
        history.observe(record.item)?;
    }
    history.finish()
}

pub(crate) async fn read_bounded_line(reader: &mut BufReader<tokio::fs::File>) -> CodexResult<Option<Vec<u8>>> {
    const MAX_LINE_BYTES: usize = 16 * 1024 * 1024;
    let mut line = Vec::new();
    loop {
        let available = reader.fill_buf().await.map_err(CodexErr::from)?;
        if available.is_empty() {
            return if line.is_empty() { Ok(None) } else { Err(invalid("original hosted history has a partial final line")) };
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let take = newline.map_or(available.len(), |index| index + 1);
        if line.len().saturating_add(take) > MAX_LINE_BYTES {
            return Err(invalid("original hosted history line exceeds its bound"));
        }
        line.extend_from_slice(&available[..take]);
        reader.consume(take);
        if newline.is_some() { return Ok(Some(line)); }
    }
}
