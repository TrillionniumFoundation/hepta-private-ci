//! No-effect service qualification; this does not construct a production writer.

use super::qualification::exchange;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointStatus;
use std::os::unix::net::UnixStream;

pub(super) fn qualify(stream: &mut UnixStream) -> Result<(), Box<dyn std::error::Error>> {
    let request = |sequence: u64, command: &str, expected: serde_json::Value| serde_json::json!({"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1","request_id":format!("{:016x}{sequence:016x}",1),"command":command,"expected":expected,"proposal":null});
    let read: CognitiveCheckpointResponse = serde_json::from_value(exchange(
        stream,
        &request(1, "read_head", serde_json::Value::Null),
        32 * 1024,
    ))?;
    assert_eq!(read.status, CognitiveCheckpointStatus::Ack);
    let current = read.head.as_ref().ok_or("missing actual Current head")?;
    assert_eq!(current.phase, CognitiveCheckpointPhase::Current);
    assert_eq!(current.counter, 0);
    let original_cut = current.last_current.clone();
    let begin = request(2, "begin_writes", serde_json::to_value(read.token)?);
    let dirty: CognitiveCheckpointResponse =
        serde_json::from_value(exchange(stream, &begin, 32 * 1024))?;
    assert_eq!(dirty.status, CognitiveCheckpointStatus::Ack);
    assert_eq!(
        dirty.head.as_ref().ok_or("missing Dirty")?.phase,
        CognitiveCheckpointPhase::Dirty
    );
    let duplicate: CognitiveCheckpointResponse =
        serde_json::from_value(exchange(stream, &begin, 32 * 1024))?;
    assert_eq!(duplicate, dirty);
    // A fresh request cannot reuse the previous full-head token.
    let stale: CognitiveCheckpointResponse = serde_json::from_value(exchange(
        stream,
        &request(3, "fence_publisher", begin["expected"].clone()),
        32 * 1024,
    ))?;
    assert_eq!(stale.status, CognitiveCheckpointStatus::Refused);
    let fenced: CognitiveCheckpointResponse = serde_json::from_value(exchange(
        stream,
        &request(4, "fence_publisher", serde_json::to_value(dirty.token)?),
        32 * 1024,
    ))?;
    assert_eq!(fenced.status, CognitiveCheckpointStatus::Ack);
    let head = fenced.head.as_ref().ok_or("missing Fenced")?;
    assert_eq!(head.phase, CognitiveCheckpointPhase::Fenced);
    assert_eq!(head.counter, 2);
    assert_eq!(head.last_current, original_cut);
    let refused: CognitiveCheckpointResponse = serde_json::from_value(exchange(
        stream,
        &request(5, "begin_writes", serde_json::to_value(fenced.token)?),
        32 * 1024,
    ))?;
    assert_eq!(refused.status, CognitiveCheckpointStatus::Refused);
    println!(
        "{}",
        serde_json::json!({"qualification":"root_checkpoint_original_fresh_cut_wire","uid":60001,"commands":["read_head","begin_writes","fence_publisher"],"idempotent_ack":true,"stale_cas_refused":true,"terminal_fenced":true,"production_ready":false,"production_writer_mutation":false})
    );
    Ok(())
}
