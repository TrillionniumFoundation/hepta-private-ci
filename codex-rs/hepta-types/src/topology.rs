//! Authority-free topology-candidate contract shared by proposal and runtime lanes.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use crate::Digest32;
use crate::Generation;
use crate::StableId;

pub const MAX_RUNTIME_TOPOLOGY_DELTAS_V1: usize = 256;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum RuntimeTopologyOperationV1 {
    Add,
    Replace,
    Retire,
    Rewire,
    Split,
    Merge,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct RuntimeTopologyDeltaV1 {
    pub module_id: StableId,
    pub operation: RuntimeTopologyOperationV1,
    pub related_module_ids: Vec<StableId>,
    pub predecessor_digest: Digest32,
    pub candidate_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTopologyCandidateV1 {
    pub proposal_digest: Digest32,
    pub candidate_id: StableId,
    pub candidate_digest: Digest32,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub selected_topology_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub changed: bool,
    pub deltas: Vec<RuntimeTopologyDeltaV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeTopologyContractErrorV1 {
    EmptyDigest(&'static str),
    GenerationNotExactSuccessor,
    RollbackPredecessorMismatch,
    CandidateShape,
    DeltaCount,
    CandidateDigestMismatch,
    DuplicateModule(StableId),
    DuplicateRelatedModule(StableId),
    InvalidDelta(StableId),
    SplitParticipantMissingAdd(StableId),
    MergeParticipantMissingRetire(StableId),
}

impl std::fmt::Display for RuntimeTopologyContractErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RuntimeTopologyContractErrorV1 {}

impl RuntimeTopologyCandidateV1 {
    pub fn validate(&self) -> Result<(), RuntimeTopologyContractErrorV1> {
        for (name, digest) in [
            ("proposal", self.proposal_digest),
            ("candidate", self.candidate_digest),
            ("selected topology", self.selected_topology_digest),
            ("evaluation", self.evaluation_digest),
            ("rollback predecessor", self.rollback_predecessor_digest),
        ] {
            if digest.is_zero() {
                return Err(RuntimeTopologyContractErrorV1::EmptyDigest(name));
            }
        }
        if self.baseline_generation.next() != Ok(self.candidate_generation) {
            return Err(RuntimeTopologyContractErrorV1::GenerationNotExactSuccessor);
        }
        if self.rollback_predecessor_digest != self.selected_topology_digest {
            return Err(RuntimeTopologyContractErrorV1::RollbackPredecessorMismatch);
        }
        if self.changed == self.deltas.is_empty() {
            return Err(RuntimeTopologyContractErrorV1::CandidateShape);
        }
        if self.deltas.len() > MAX_RUNTIME_TOPOLOGY_DELTAS_V1 {
            return Err(RuntimeTopologyContractErrorV1::DeltaCount);
        }

        let mut by_module = BTreeMap::new();
        for delta in &self.deltas {
            if delta.related_module_ids.len() > MAX_RUNTIME_TOPOLOGY_DELTAS_V1 {
                return Err(RuntimeTopologyContractErrorV1::DeltaCount);
            }
            if by_module.insert(delta.module_id.clone(), delta).is_some() {
                return Err(RuntimeTopologyContractErrorV1::DuplicateModule(
                    delta.module_id.clone(),
                ));
            }
            if delta.evidence_digest.is_zero() {
                return Err(RuntimeTopologyContractErrorV1::InvalidDelta(
                    delta.module_id.clone(),
                ));
            }
            let related = delta
                .related_module_ids
                .iter()
                .cloned()
                .collect::<BTreeSet<_>>();
            if related.len() != delta.related_module_ids.len() || related.contains(&delta.module_id)
            {
                return Err(RuntimeTopologyContractErrorV1::DuplicateRelatedModule(
                    delta.module_id.clone(),
                ));
            }
            let shape_ok = match delta.operation {
                RuntimeTopologyOperationV1::Add => {
                    delta.related_module_ids.is_empty()
                        && delta.predecessor_digest.is_zero()
                        && !delta.candidate_digest.is_zero()
                }
                RuntimeTopologyOperationV1::Retire => {
                    delta.related_module_ids.is_empty()
                        && !delta.predecessor_digest.is_zero()
                        && delta.candidate_digest.is_zero()
                }
                RuntimeTopologyOperationV1::Replace | RuntimeTopologyOperationV1::Rewire => {
                    delta.related_module_ids.is_empty()
                        && !delta.predecessor_digest.is_zero()
                        && !delta.candidate_digest.is_zero()
                        && delta.predecessor_digest != delta.candidate_digest
                }
                RuntimeTopologyOperationV1::Split | RuntimeTopologyOperationV1::Merge => {
                    !delta.related_module_ids.is_empty()
                        && !delta.predecessor_digest.is_zero()
                        && !delta.candidate_digest.is_zero()
                        && delta.predecessor_digest != delta.candidate_digest
                }
            };
            if !shape_ok {
                return Err(RuntimeTopologyContractErrorV1::InvalidDelta(
                    delta.module_id.clone(),
                ));
            }
        }

        // V1 binds structural fan-out/fan-in without adding another wire format:
        // every split participant must have its own Add delta and every merge
        // participant its own Retire delta. This gives each implementation an
        // exact content digest instead of hiding participants behind one digest.
        for delta in &self.deltas {
            match delta.operation {
                RuntimeTopologyOperationV1::Split => {
                    for related in &delta.related_module_ids {
                        if !matches!(
                            by_module.get(related).map(|value| value.operation),
                            Some(RuntimeTopologyOperationV1::Add)
                        ) {
                            return Err(
                                RuntimeTopologyContractErrorV1::SplitParticipantMissingAdd(
                                    related.clone(),
                                ),
                            );
                        }
                    }
                }
                RuntimeTopologyOperationV1::Merge => {
                    for related in &delta.related_module_ids {
                        if !matches!(
                            by_module.get(related).map(|value| value.operation),
                            Some(RuntimeTopologyOperationV1::Retire)
                        ) {
                            return Err(
                                RuntimeTopologyContractErrorV1::MergeParticipantMissingRetire(
                                    related.clone(),
                                ),
                            );
                        }
                    }
                }
                _ => {}
            }
        }
        // This DTO has public fields: callers must not be able to keep a
        // selected digest while substituting a different implementation/delta.
        if self.candidate_digest != self.content_digest()? {
            return Err(RuntimeTopologyContractErrorV1::CandidateDigestMismatch);
        }
        Ok(())
    }

    /// Recompute the exact V3 proposal-candidate byte binding at the runtime
    /// boundary. This is integrity verification, not selection authority.
    pub fn content_digest(&self) -> Result<Digest32, RuntimeTopologyContractErrorV1> {
        if self.deltas.len() > MAX_RUNTIME_TOPOLOGY_DELTAS_V1 {
            return Err(RuntimeTopologyContractErrorV1::DeltaCount);
        }
        let mut bytes = b"hepta.plasticity.topology-candidate.v3".to_vec();
        push_text(&mut bytes, self.candidate_id.as_str())?;
        bytes.push(u8::from(self.changed));
        push_length(&mut bytes, self.deltas.len())?;
        for delta in &self.deltas {
            if delta.related_module_ids.len() > MAX_RUNTIME_TOPOLOGY_DELTAS_V1 {
                return Err(RuntimeTopologyContractErrorV1::DeltaCount);
            }
            push_text(&mut bytes, delta.module_id.as_str())?;
            bytes.push(match delta.operation {
                RuntimeTopologyOperationV1::Add => 0,
                RuntimeTopologyOperationV1::Replace => 1,
                RuntimeTopologyOperationV1::Retire => 2,
                RuntimeTopologyOperationV1::Rewire => 3,
                RuntimeTopologyOperationV1::Split => 4,
                RuntimeTopologyOperationV1::Merge => 5,
            });
            push_length(&mut bytes, delta.related_module_ids.len())?;
            for related in &delta.related_module_ids {
                push_text(&mut bytes, related.as_str())?;
            }
            bytes.extend_from_slice(delta.predecessor_digest.as_array());
            bytes.extend_from_slice(delta.candidate_digest.as_array());
            bytes.extend_from_slice(delta.evidence_digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

fn push_length(bytes: &mut Vec<u8>, value: usize) -> Result<(), RuntimeTopologyContractErrorV1> {
    let length = u32::try_from(value).map_err(|_| RuntimeTopologyContractErrorV1::DeltaCount)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    Ok(())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) -> Result<(), RuntimeTopologyContractErrorV1> {
    push_length(bytes, value.len())?;
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn candidate(deltas: Vec<RuntimeTopologyDeltaV1>) -> RuntimeTopologyCandidateV1 {
        let mut value = RuntimeTopologyCandidateV1 {
            proposal_digest: digest("proposal"),
            candidate_id: id("candidate"),
            candidate_digest: digest("candidate"),
            baseline_generation: Generation::new(7).expect("generation"),
            candidate_generation: Generation::new(8).expect("generation"),
            selected_topology_digest: digest("topology-7"),
            evaluation_digest: digest("evaluation"),
            rollback_predecessor_digest: digest("topology-7"),
            changed: !deltas.is_empty(),
            deltas,
        };
        value.candidate_digest = value.content_digest().expect("digest");
        value
    }

    #[test]
    fn split_requires_individually_bound_add_participants() {
        let split = RuntimeTopologyDeltaV1 {
            module_id: id("memory.retrieval"),
            operation: RuntimeTopologyOperationV1::Split,
            related_module_ids: vec![id("memory.fast")],
            predecessor_digest: digest("old"),
            candidate_digest: digest("new-root"),
            evidence_digest: digest("evidence"),
        };
        assert!(matches!(
            candidate(vec![split.clone()]).validate(),
            Err(RuntimeTopologyContractErrorV1::SplitParticipantMissingAdd(
                _
            ))
        ));
        let added = RuntimeTopologyDeltaV1 {
            module_id: id("memory.fast"),
            operation: RuntimeTopologyOperationV1::Add,
            related_module_ids: Vec::new(),
            predecessor_digest: Digest32::ZERO,
            candidate_digest: digest("fast"),
            evidence_digest: digest("fast-evidence"),
        };
        candidate(vec![split, added])
            .validate()
            .expect("bound split");
    }

    #[test]
    fn selected_digest_cannot_hide_substituted_delta_content() {
        let original = candidate(vec![RuntimeTopologyDeltaV1 {
            module_id: id("module"),
            operation: RuntimeTopologyOperationV1::Add,
            related_module_ids: Vec::new(),
            predecessor_digest: Digest32::ZERO,
            candidate_digest: digest("reviewed-implementation"),
            evidence_digest: digest("reviewed-evidence"),
        }]);
        original.validate().expect("original");
        let mut changed = original.clone();
        changed.deltas[0].candidate_digest = digest("substituted-implementation");
        assert_eq!(
            changed.validate(),
            Err(RuntimeTopologyContractErrorV1::CandidateDigestMismatch)
        );
        changed = original.clone();
        changed.deltas[0].evidence_digest = digest("other-evidence");
        assert_eq!(
            changed.validate(),
            Err(RuntimeTopologyContractErrorV1::CandidateDigestMismatch)
        );
        changed = original;
        changed.candidate_id = id("other-candidate");
        assert_eq!(
            changed.validate(),
            Err(RuntimeTopologyContractErrorV1::CandidateDigestMismatch)
        );
    }

    #[test]
    fn related_module_bounds_are_checked_before_digest_allocation() {
        let mut value = candidate(Vec::new());
        value.changed = true;
        value.deltas.push(RuntimeTopologyDeltaV1 {
            module_id: id("module"),
            operation: RuntimeTopologyOperationV1::Split,
            related_module_ids: vec![id("child"); MAX_RUNTIME_TOPOLOGY_DELTAS_V1 + 1],
            predecessor_digest: digest("old"),
            candidate_digest: digest("new"),
            evidence_digest: digest("evidence"),
        });
        assert_eq!(
            value.validate(),
            Err(RuntimeTopologyContractErrorV1::DeltaCount)
        );
        assert_eq!(
            value.content_digest(),
            Err(RuntimeTopologyContractErrorV1::DeltaCount)
        );
    }
}
