//! Versioned HPTC topology candidate for current product admission.
//!
//! V2 is a new commitment, not a reinterpretation of historical V1 candidates.
//! Constructing or validating it grants no selection/effect authority. Product
//! admission requires independently issued witnesses bound to its V2 digest.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use crate::CanonicalFieldV1;
use crate::CanonicalValueV1;
use crate::Digest32;
use crate::Generation;
use crate::StableId;
use crate::canonical_digest_v1;

pub const MAX_RUNTIME_TOPOLOGY_DELTAS_V2: usize = 256;

const RUNTIME_TOPOLOGY_CANDIDATE_TYPE_ID_V2: &str = "platform.types:runtime-topology-candidate-v2";
const RUNTIME_TOPOLOGY_DELTA_TYPE_ID_V2: &str = "platform.types:runtime-topology-delta-v2";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum RuntimeTopologyOperationV2 {
    Add,
    Replace,
    Retire,
    Rewire,
    Split,
    Merge,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct RuntimeTopologyDeltaV2 {
    pub module_id: StableId,
    pub operation: RuntimeTopologyOperationV2,
    pub related_module_ids: Vec<StableId>,
    pub predecessor_digest: Digest32,
    pub candidate_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTopologyCandidateV2 {
    pub proposal_digest: Digest32,
    pub candidate_id: StableId,
    pub candidate_digest: Digest32,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub selected_topology_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub changed: bool,
    pub deltas: Vec<RuntimeTopologyDeltaV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeTopologyContractErrorV2 {
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

impl std::fmt::Display for RuntimeTopologyContractErrorV2 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RuntimeTopologyContractErrorV2 {}

impl RuntimeTopologyDeltaV2 {
    fn semantic_digest(&self) -> Result<Digest32, RuntimeTopologyContractErrorV2> {
        validate_related_module_ids(self)?;
        let type_id = topology_type_id(RUNTIME_TOPOLOGY_DELTA_TYPE_ID_V2)?;
        let related_module_ids = self
            .related_module_ids
            .iter()
            .map(CanonicalValueV1::StableId)
            .collect::<Vec<_>>();
        let fields = [
            CanonicalFieldV1 {
                name: "candidate_digest",
                value: CanonicalValueV1::Digest(self.candidate_digest),
            },
            CanonicalFieldV1 {
                name: "evidence_digest",
                value: CanonicalValueV1::Digest(self.evidence_digest),
            },
            CanonicalFieldV1 {
                name: "module_id",
                value: CanonicalValueV1::StableId(&self.module_id),
            },
            CanonicalFieldV1 {
                name: "operation",
                value: CanonicalValueV1::Text(operation_id(self.operation)),
            },
            CanonicalFieldV1 {
                name: "predecessor_digest",
                value: CanonicalValueV1::Digest(self.predecessor_digest),
            },
            CanonicalFieldV1 {
                name: "related_module_ids",
                value: CanonicalValueV1::Array(&related_module_ids),
            },
        ];
        canonical_digest_v1(&type_id, 2, &fields)
            .map_err(|_| RuntimeTopologyContractErrorV2::InvalidDelta(self.module_id.clone()))
    }
}

impl RuntimeTopologyCandidateV2 {
    /// Maximum delta count and maximum related-module count for each delta.
    /// Validated owners also use this bound for retained collection capacity.
    pub const MAX_DELTAS_V2: usize = MAX_RUNTIME_TOPOLOGY_DELTAS_V2;

    pub fn validate(&self) -> Result<(), RuntimeTopologyContractErrorV2> {
        for (name, digest) in [
            ("proposal", self.proposal_digest),
            ("candidate", self.candidate_digest),
            ("selected topology", self.selected_topology_digest),
            ("evaluation", self.evaluation_digest),
            ("rollback predecessor", self.rollback_predecessor_digest),
        ] {
            if digest.is_zero() {
                return Err(RuntimeTopologyContractErrorV2::EmptyDigest(name));
            }
        }
        if self.baseline_generation.next() != Ok(self.candidate_generation) {
            return Err(RuntimeTopologyContractErrorV2::GenerationNotExactSuccessor);
        }
        if self.rollback_predecessor_digest != self.selected_topology_digest {
            return Err(RuntimeTopologyContractErrorV2::RollbackPredecessorMismatch);
        }
        if self.changed == self.deltas.is_empty() {
            return Err(RuntimeTopologyContractErrorV2::CandidateShape);
        }
        if self.deltas.len() > MAX_RUNTIME_TOPOLOGY_DELTAS_V2 {
            return Err(RuntimeTopologyContractErrorV2::DeltaCount);
        }
        validate_delta_order(&self.deltas)?;

        let mut by_module = BTreeMap::new();
        for delta in &self.deltas {
            validate_related_module_ids(delta)?;
            if by_module.insert(delta.module_id.clone(), delta).is_some() {
                return Err(RuntimeTopologyContractErrorV2::DuplicateModule(
                    delta.module_id.clone(),
                ));
            }
            if delta.evidence_digest.is_zero() {
                return Err(RuntimeTopologyContractErrorV2::InvalidDelta(
                    delta.module_id.clone(),
                ));
            }
            let shape_ok = match delta.operation {
                RuntimeTopologyOperationV2::Add => {
                    delta.related_module_ids.is_empty()
                        && delta.predecessor_digest.is_zero()
                        && !delta.candidate_digest.is_zero()
                }
                RuntimeTopologyOperationV2::Retire => {
                    delta.related_module_ids.is_empty()
                        && !delta.predecessor_digest.is_zero()
                        && delta.candidate_digest.is_zero()
                }
                RuntimeTopologyOperationV2::Replace | RuntimeTopologyOperationV2::Rewire => {
                    delta.related_module_ids.is_empty()
                        && !delta.predecessor_digest.is_zero()
                        && !delta.candidate_digest.is_zero()
                        && delta.predecessor_digest != delta.candidate_digest
                }
                RuntimeTopologyOperationV2::Split | RuntimeTopologyOperationV2::Merge => {
                    !delta.related_module_ids.is_empty()
                        && !delta.predecessor_digest.is_zero()
                        && !delta.candidate_digest.is_zero()
                        && delta.predecessor_digest != delta.candidate_digest
                }
            };
            if !shape_ok {
                return Err(RuntimeTopologyContractErrorV2::InvalidDelta(
                    delta.module_id.clone(),
                ));
            }
        }

        // V2 binds structural fan-out/fan-in without adding another wire format:
        // every split participant must have its own Add delta and every merge
        // participant its own Retire delta. This gives each implementation an
        // exact content digest instead of hiding participants behind one digest.
        for delta in &self.deltas {
            match delta.operation {
                RuntimeTopologyOperationV2::Split => {
                    for related in &delta.related_module_ids {
                        if !matches!(
                            by_module.get(related).map(|value| value.operation),
                            Some(RuntimeTopologyOperationV2::Add)
                        ) {
                            return Err(
                                RuntimeTopologyContractErrorV2::SplitParticipantMissingAdd(
                                    related.clone(),
                                ),
                            );
                        }
                    }
                }
                RuntimeTopologyOperationV2::Merge => {
                    for related in &delta.related_module_ids {
                        if !matches!(
                            by_module.get(related).map(|value| value.operation),
                            Some(RuntimeTopologyOperationV2::Retire)
                        ) {
                            return Err(
                                RuntimeTopologyContractErrorV2::MergeParticipantMissingRetire(
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
        // selected digest while substituting a different proposal, generation,
        // evaluation, rollback predecessor, implementation or delta.
        if self.candidate_digest != self.content_digest()? {
            return Err(RuntimeTopologyContractErrorV2::CandidateDigestMismatch);
        }
        Ok(())
    }

    /// Recompute the exact HPTC V1 semantic commitment at the runtime boundary.
    /// `candidate_digest` is the derived result and is intentionally excluded;
    /// every other candidate field and every delta field is committed. Delta
    /// and related-module vectors represent sets and must be in strictly
    /// increasing `StableId` order. This is integrity verification, not
    /// selection authority.
    pub fn content_digest(&self) -> Result<Digest32, RuntimeTopologyContractErrorV2> {
        if self.deltas.len() > MAX_RUNTIME_TOPOLOGY_DELTAS_V2 {
            return Err(RuntimeTopologyContractErrorV2::DeltaCount);
        }
        validate_delta_order(&self.deltas)?;
        let delta_digests = self
            .deltas
            .iter()
            .map(RuntimeTopologyDeltaV2::semantic_digest)
            .collect::<Result<Vec<_>, _>>()?;
        let deltas = delta_digests
            .iter()
            .copied()
            .map(CanonicalValueV1::Digest)
            .collect::<Vec<_>>();
        let type_id = topology_type_id(RUNTIME_TOPOLOGY_CANDIDATE_TYPE_ID_V2)?;
        let fields = [
            CanonicalFieldV1 {
                name: "baseline_generation",
                value: CanonicalValueV1::U64(self.baseline_generation.get()),
            },
            CanonicalFieldV1 {
                name: "candidate_generation",
                value: CanonicalValueV1::U64(self.candidate_generation.get()),
            },
            CanonicalFieldV1 {
                name: "candidate_id",
                value: CanonicalValueV1::StableId(&self.candidate_id),
            },
            CanonicalFieldV1 {
                name: "changed",
                value: CanonicalValueV1::Bool(self.changed),
            },
            CanonicalFieldV1 {
                name: "deltas",
                value: CanonicalValueV1::Array(&deltas),
            },
            CanonicalFieldV1 {
                name: "evaluation_digest",
                value: CanonicalValueV1::Digest(self.evaluation_digest),
            },
            CanonicalFieldV1 {
                name: "proposal_digest",
                value: CanonicalValueV1::Digest(self.proposal_digest),
            },
            CanonicalFieldV1 {
                name: "rollback_predecessor_digest",
                value: CanonicalValueV1::Digest(self.rollback_predecessor_digest),
            },
            CanonicalFieldV1 {
                name: "selected_topology_digest",
                value: CanonicalValueV1::Digest(self.selected_topology_digest),
            },
        ];
        canonical_digest_v1(&type_id, 2, &fields)
            .map_err(|_| RuntimeTopologyContractErrorV2::CandidateShape)
    }
}

fn topology_type_id(value: &str) -> Result<StableId, RuntimeTopologyContractErrorV2> {
    StableId::new(value).map_err(|_| RuntimeTopologyContractErrorV2::CandidateShape)
}

const fn operation_id(operation: RuntimeTopologyOperationV2) -> &'static str {
    match operation {
        RuntimeTopologyOperationV2::Add => "add",
        RuntimeTopologyOperationV2::Replace => "replace",
        RuntimeTopologyOperationV2::Retire => "retire",
        RuntimeTopologyOperationV2::Rewire => "rewire",
        RuntimeTopologyOperationV2::Split => "split",
        RuntimeTopologyOperationV2::Merge => "merge",
    }
}

fn validate_delta_order(
    deltas: &[RuntimeTopologyDeltaV2],
) -> Result<(), RuntimeTopologyContractErrorV2> {
    let mut seen = BTreeSet::new();
    let mut previous: Option<&StableId> = None;
    for delta in deltas {
        if !seen.insert(delta.module_id.clone()) {
            return Err(RuntimeTopologyContractErrorV2::DuplicateModule(
                delta.module_id.clone(),
            ));
        }
        if let Some(previous) = previous
            && previous > &delta.module_id
        {
            return Err(RuntimeTopologyContractErrorV2::InvalidDelta(
                delta.module_id.clone(),
            ));
        }
        previous = Some(&delta.module_id);
    }
    Ok(())
}

fn validate_related_module_ids(
    delta: &RuntimeTopologyDeltaV2,
) -> Result<(), RuntimeTopologyContractErrorV2> {
    if delta.related_module_ids.len() > MAX_RUNTIME_TOPOLOGY_DELTAS_V2 {
        return Err(RuntimeTopologyContractErrorV2::DeltaCount);
    }
    let mut seen = BTreeSet::new();
    let mut previous: Option<&StableId> = None;
    for related in &delta.related_module_ids {
        if related == &delta.module_id || !seen.insert(related.clone()) {
            return Err(RuntimeTopologyContractErrorV2::DuplicateRelatedModule(
                delta.module_id.clone(),
            ));
        }
        if let Some(previous) = previous
            && previous > related
        {
            return Err(RuntimeTopologyContractErrorV2::DuplicateRelatedModule(
                delta.module_id.clone(),
            ));
        }
        previous = Some(related);
    }
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

    fn add_delta(module_id: &str, candidate: &str, evidence: &str) -> RuntimeTopologyDeltaV2 {
        RuntimeTopologyDeltaV2 {
            module_id: id(module_id),
            operation: RuntimeTopologyOperationV2::Add,
            related_module_ids: Vec::new(),
            predecessor_digest: Digest32::ZERO,
            candidate_digest: digest(candidate),
            evidence_digest: digest(evidence),
        }
    }

    fn candidate(deltas: Vec<RuntimeTopologyDeltaV2>) -> RuntimeTopologyCandidateV2 {
        let mut value = RuntimeTopologyCandidateV2 {
            proposal_digest: digest("proposal"),
            candidate_id: id("candidate"),
            candidate_digest: digest("candidate-placeholder"),
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

    fn assert_digest_changes(
        baseline: &RuntimeTopologyCandidateV2,
        mutate: impl FnOnce(&mut RuntimeTopologyCandidateV2),
    ) {
        let expected = baseline.content_digest().expect("baseline digest");
        let mut changed = baseline.clone();
        mutate(&mut changed);
        assert_ne!(changed.content_digest().expect("changed digest"), expected);
    }

    #[test]
    fn split_requires_individually_bound_add_participants() {
        let split = RuntimeTopologyDeltaV2 {
            module_id: id("memory.root"),
            operation: RuntimeTopologyOperationV2::Split,
            related_module_ids: vec![id("memory.zfast")],
            predecessor_digest: digest("old"),
            candidate_digest: digest("new-root"),
            evidence_digest: digest("evidence"),
        };
        assert!(matches!(
            candidate(vec![split.clone()]).validate(),
            Err(RuntimeTopologyContractErrorV2::SplitParticipantMissingAdd(
                _
            ))
        ));
        let added = add_delta("memory.zfast", "fast", "fast-evidence");
        candidate(vec![split, added])
            .validate()
            .expect("bound split");
    }

    #[test]
    fn digest_binds_every_candidate_semantic_field() {
        let baseline = candidate(vec![add_delta("module", "implementation", "evidence")]);
        assert_digest_changes(&baseline, |value| {
            value.proposal_digest = digest("proposal-2")
        });
        assert_digest_changes(&baseline, |value| value.candidate_id = id("candidate-2"));
        assert_digest_changes(&baseline, |value| {
            value.baseline_generation = Generation::new(6).expect("generation");
        });
        assert_digest_changes(&baseline, |value| {
            value.candidate_generation = Generation::new(9).expect("generation");
        });
        assert_digest_changes(&baseline, |value| {
            value.selected_topology_digest = digest("topology-8");
        });
        assert_digest_changes(&baseline, |value| {
            value.evaluation_digest = digest("evaluation-2");
        });
        assert_digest_changes(&baseline, |value| {
            value.rollback_predecessor_digest = digest("topology-6");
        });
        assert_digest_changes(&baseline, |value| value.changed = false);
        assert_digest_changes(&baseline, |value| {
            value.deltas[0].module_id = id("module-2");
        });
        assert_digest_changes(&baseline, |value| {
            value.deltas[0].operation = RuntimeTopologyOperationV2::Replace;
        });
        assert_digest_changes(&baseline, |value| {
            value.deltas[0].predecessor_digest = digest("predecessor");
        });
        assert_digest_changes(&baseline, |value| {
            value.deltas[0].candidate_digest = digest("implementation-2");
        });
        assert_digest_changes(&baseline, |value| {
            value.deltas[0].evidence_digest = digest("evidence-2");
        });

        let mut changed = baseline.clone();
        changed.candidate_digest = digest("derived-field-is-not-an-input");
        assert_eq!(
            changed.content_digest().expect("digest"),
            baseline.content_digest().expect("baseline digest")
        );
        assert_eq!(
            changed.validate(),
            Err(RuntimeTopologyContractErrorV2::CandidateDigestMismatch)
        );
    }

    #[test]
    fn digest_binds_related_module_ids() {
        let split = RuntimeTopologyDeltaV2 {
            module_id: id("a.root"),
            operation: RuntimeTopologyOperationV2::Split,
            related_module_ids: vec![id("b.child")],
            predecessor_digest: digest("old"),
            candidate_digest: digest("new-root"),
            evidence_digest: digest("evidence"),
        };
        let baseline = candidate(vec![
            split,
            add_delta("b.child", "child", "child-evidence"),
            add_delta("c.child", "child-2", "child-evidence-2"),
        ]);
        assert_digest_changes(&baseline, |value| {
            value.deltas[0].related_module_ids.push(id("c.child"));
        });
    }

    #[test]
    fn selected_digest_cannot_hide_substituted_candidate_content() {
        let original = candidate(vec![add_delta(
            "module",
            "reviewed-implementation",
            "reviewed-evidence",
        )]);
        original.validate().expect("original");
        let mut changed = original.clone();
        changed.proposal_digest = digest("other-proposal");
        assert_eq!(
            changed.validate(),
            Err(RuntimeTopologyContractErrorV2::CandidateDigestMismatch)
        );
        changed = original.clone();
        changed.evaluation_digest = digest("other-evaluation");
        assert_eq!(
            changed.validate(),
            Err(RuntimeTopologyContractErrorV2::CandidateDigestMismatch)
        );
        changed = original;
        changed.deltas[0].candidate_digest = digest("substituted-implementation");
        assert_eq!(
            changed.validate(),
            Err(RuntimeTopologyContractErrorV2::CandidateDigestMismatch)
        );
    }

    #[test]
    fn delta_and_related_ids_have_canonical_set_order() {
        let sorted = candidate(vec![
            add_delta("a.module", "a", "a-evidence"),
            add_delta("b.module", "b", "b-evidence"),
        ]);
        sorted.validate().expect("canonical order");

        let mut reversed = sorted;
        reversed.deltas.reverse();
        assert!(matches!(
            reversed.content_digest(),
            Err(RuntimeTopologyContractErrorV2::InvalidDelta(_))
        ));

        let split = RuntimeTopologyDeltaV2 {
            module_id: id("a.root"),
            operation: RuntimeTopologyOperationV2::Split,
            related_module_ids: vec![id("c.child"), id("b.child")],
            predecessor_digest: digest("old"),
            candidate_digest: digest("new-root"),
            evidence_digest: digest("evidence"),
        };
        let unordered_related = RuntimeTopologyCandidateV2 {
            deltas: vec![
                split,
                add_delta("b.child", "b", "b-evidence"),
                add_delta("c.child", "c", "c-evidence"),
            ],
            ..candidate(Vec::new())
        };
        assert!(matches!(
            unordered_related.content_digest(),
            Err(RuntimeTopologyContractErrorV2::DuplicateRelatedModule(_))
        ));
    }

    #[test]
    fn related_module_bounds_are_checked_before_digest_allocation() {
        let mut value = candidate(Vec::new());
        value.changed = true;
        value.deltas.push(RuntimeTopologyDeltaV2 {
            module_id: id("module"),
            operation: RuntimeTopologyOperationV2::Split,
            related_module_ids: vec![id("child"); MAX_RUNTIME_TOPOLOGY_DELTAS_V2 + 1],
            predecessor_digest: digest("old"),
            candidate_digest: digest("new"),
            evidence_digest: digest("evidence"),
        });
        assert_eq!(
            value.validate(),
            Err(RuntimeTopologyContractErrorV2::DeltaCount)
        );
        assert_eq!(
            value.content_digest(),
            Err(RuntimeTopologyContractErrorV2::DeltaCount)
        );
    }
}
