//! Deterministic bounded expansion of a candidate-local engram subgraph.

use std::collections::BTreeSet;

use crate::generation_bound::CandidateUnionV1;
use crate::hnmf::EngramSnapshotV1;
use crate::hnmf::HnmfRecallErrorV1;
use crate::hnmf::MAX_RECURRENT_STEPS;

/// Expand the exact candidate identities through the supplied immutable engram
/// projection for at most `maximum_hops`. Both incoming and outgoing neighbors
/// are included because either can contribute recurrent support. The source
/// projection remains externally owned; this function only derives a bounded,
/// canonical local view.
pub fn expand_candidate_engram(
    union: &CandidateUnionV1,
    source: &EngramSnapshotV1,
    maximum_hops: u8,
) -> Result<EngramSnapshotV1, HnmfRecallErrorV1> {
    union.validate().map_err(HnmfRecallErrorV1::Recall)?;
    source.validate()?;
    if maximum_hops > MAX_RECURRENT_STEPS {
        return Err(HnmfRecallErrorV1::InvalidRecurrentSteps);
    }
    if source.generation_vector_digest != union.generation_vector_digest {
        return Err(HnmfRecallErrorV1::GenerationVectorMismatch);
    }

    let available = source
        .nodes
        .iter()
        .map(|node| node.record_id.clone())
        .collect::<BTreeSet<_>>();
    let mut selected = BTreeSet::new();
    let mut frontier = BTreeSet::new();
    for entry in &union.entries {
        if !available.contains(&entry.record.record_id) {
            return Err(HnmfRecallErrorV1::MissingCandidateNode);
        }
        selected.insert(entry.record.record_id.clone());
        frontier.insert(entry.record.record_id.clone());
    }

    for _ in 0..maximum_hops {
        if frontier.is_empty() {
            break;
        }
        let mut next = BTreeSet::new();
        for synapse in &source.synapses {
            if frontier.contains(&synapse.from_record_id)
                && !selected.contains(&synapse.to_record_id)
            {
                next.insert(synapse.to_record_id.clone());
            }
            if frontier.contains(&synapse.to_record_id)
                && !selected.contains(&synapse.from_record_id)
            {
                next.insert(synapse.from_record_id.clone());
            }
        }
        for id in &next {
            selected.insert(id.clone());
        }
        frontier = next;
    }

    let mut nodes = source
        .nodes
        .iter()
        .filter(|node| selected.contains(&node.record_id))
        .cloned()
        .collect::<Vec<_>>();
    nodes.sort_by(|left, right| left.record_id.cmp(&right.record_id));

    let mut synapses = source
        .synapses
        .iter()
        .filter(|synapse| {
            selected.contains(&synapse.from_record_id)
                && selected.contains(&synapse.to_record_id)
        })
        .cloned()
        .collect::<Vec<_>>();
    synapses.sort_by(|left, right| {
        left.from_record_id
            .cmp(&right.from_record_id)
            .then_with(|| left.to_record_id.cmp(&right.to_record_id))
            .then_with(|| left.inhibitory.cmp(&right.inhibitory))
    });

    let result = EngramSnapshotV1 {
        generation_vector_digest: source.generation_vector_digest,
        nodes,
        synapses,
    };
    result.validate()?;
    Ok(result)
}
