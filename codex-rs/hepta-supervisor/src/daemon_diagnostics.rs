//! Bounded administrator observations from the existing process owner. These
//! strings never enter a control fence, durable receipt or public UI projection.
use crate::AgentSupervisorSnapshot;

const MAX_ENTRIES_PER_KIND: usize = 8;
const MAX_ENTRY_BYTES: usize = 512;

pub(super) fn entries(snapshot: &AgentSupervisorSnapshot) -> Vec<String> {
    let events = snapshot
        .events
        .iter()
        .rev()
        .take(MAX_ENTRIES_PER_KIND)
        .map(|event| {
            bounded(format!(
                "generation={} event={:?}",
                event.generation, event.kind
            ))
        });
    let logs = snapshot
        .logs
        .iter()
        .rev()
        .take(MAX_ENTRIES_PER_KIND)
        .map(|log| {
            bounded(format!(
                "{:?}: {}",
                log.stream,
                String::from_utf8_lossy(&log.bytes)
            ))
        });
    events.chain(logs).collect()
}

fn bounded(mut text: String) -> String {
    if text.len() > MAX_ENTRY_BYTES {
        let mut end = MAX_ENTRY_BYTES;
        while !text.is_char_boundary(end) {
            end -= 1;
        }
        text.truncate(end);
    }
    text
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn diagnostics_truncates_utf8_and_binary_expansion_within_wire_bounds()
    -> Result<(), Box<dyn std::error::Error>> {
        let text = bounded(format!("stderr: {}", "错".repeat(1024)));
        assert!(text.len() <= MAX_ENTRY_BYTES);
        assert!(text.starts_with("stderr:"));
        let binary = vec![0xff; 8192];
        let expanded = bounded(String::from_utf8_lossy(&binary).into_owned());
        assert!(expanded.len() <= MAX_ENTRY_BYTES);
        let worst = vec!["\0".repeat(MAX_ENTRY_BYTES); 16];
        let encoded = serde_json::to_vec(&worst)?;
        assert!(
            encoded.len() as u64 + 1024
                < crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES
        );
        Ok(())
    }
}
