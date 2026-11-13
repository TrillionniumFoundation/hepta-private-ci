//! Read only the exact original Source configuration while it is current.
//! These data describe expected input and never create a Source publication.

use super::*;
use crate::circuit_task::root_bootstrap_codec::{Reader, Writer};

impl<W: AnchorWitnessStore + Send> DurableCircuitTaskSourceV1<W> {
    pub(crate) fn original_root_handoff_source(&self) -> Result<(Digest32, Vec<u8>), Error> {
        let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
        owner.require_current()?;
        if owner.sources.len() != 1 { return Err(Error::InvalidBinding); }
        let source = owner.sources.values().next().ok_or(Error::InvalidBinding)?;
        let bytes = encode(&owner.fence, source)?;
        let binding = owner.binding;
        owner.require_current()?;
        Ok((binding, bytes))
    }
}

fn encode(fence: &TaskFlowFence, source: &CircuitTaskSourceInputV1) -> Result<Vec<u8>, Error> {
    let mut out = Writer::new(b"HCRTSRC1");
    out.json(fence)?;
    let id = StableId::new("circuit-source").map_err(|_| Error::InvalidBinding)?;
    out.bytes(&codec::encode_input(&source.input(id))?)?;
    out.u64(source.lease_duration_ms)?;
    Ok(out.finish())
}

pub(crate) fn decode(bytes: &[u8]) -> Result<(TaskFlowFence, CircuitTaskSourceInputV1), Error> {
    let mut reader = Reader::new(bytes, b"HCRTSRC1")?;
    let fence = reader.json()?;
    let input = codec::decode_configuration_input(reader.bytes()?)?;
    let source = CircuitTaskSourceInputV1 { scope: input.scope, source_frontier: input.source_frontier,
        objective_digest: input.objective_digest, ndu_snapshot_digest: input.ndu_snapshot_digest,
        monotonic_micros: input.monotonic_micros, deadline_micros: input.deadline_micros,
        observation: input.observation, candidates: input.candidates, lease_duration_ms: reader.u64()? };
    reader.end()?;
    if encode(&fence, &source)? != bytes { return Err(Error::InvalidBinding); }
    Ok((fence, source))
}
