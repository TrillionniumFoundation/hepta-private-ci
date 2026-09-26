use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::SubjectClass;
use crate::UpdateGeneration;

const MAX_HIERARCHY_NODES: usize = 4096;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct HierarchyNodeV1 {
    pub subject_id: StableId,
    pub parent_subject_id: Option<StableId>,
    pub subject_class: SubjectClass,
}

/// Immutable hierarchy evidence selected by the product owner. The digest is
/// computed from the hierarchy id, revision and complete canonical node set.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HierarchySnapshotV1 {
    pub hierarchy_id: StableId,
    pub revision: u64,
    pub nodes: Vec<HierarchyNodeV1>,
    pub snapshot_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HierarchyValidationErrorV1 {
    InvalidSnapshot(&'static str),
    DuplicateSubject(String),
    MissingParent(String),
    InvalidParentClass(String),
    SnapshotDigestMismatch,
    ExpectedSnapshotMismatch,
    RevisionMismatch,
    UpdateNotInSnapshot(String),
    UpdateRelationMismatch(String),
    ConflictingStagedArtifact {
        generation: u64,
        subject: String,
    },
    AncestorConflict {
        generation: u64,
        ancestor: String,
        descendant: String,
    },
}

impl fmt::Display for HierarchyValidationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for HierarchyValidationErrorV1 {}

impl HierarchySnapshotV1 {
    pub fn try_new(
        hierarchy_id: StableId,
        revision: u64,
        mut nodes: Vec<HierarchyNodeV1>,
    ) -> Result<Self, HierarchyValidationErrorV1> {
        nodes.sort();
        validate_nodes(revision, &nodes)?;
        let snapshot_digest = hierarchy_snapshot_digest(&hierarchy_id, revision, &nodes);
        Ok(Self {
            hierarchy_id,
            revision,
            nodes,
            snapshot_digest,
        })
    }

    pub fn validate(&self) -> Result<(), HierarchyValidationErrorV1> {
        let mut nodes = self.nodes.clone();
        nodes.sort();
        if nodes != self.nodes {
            return Err(HierarchyValidationErrorV1::InvalidSnapshot(
                "nodes are not canonically ordered",
            ));
        }
        validate_nodes(self.revision, &nodes)?;
        if hierarchy_snapshot_digest(&self.hierarchy_id, self.revision, &nodes)
            != self.snapshot_digest
        {
            return Err(HierarchyValidationErrorV1::SnapshotDigestMismatch);
        }
        Ok(())
    }
}

#[must_use]
pub fn hierarchy_snapshot_digest(
    hierarchy_id: &StableId,
    revision: u64,
    nodes: &[HierarchyNodeV1],
) -> Digest32 {
    let mut canonical = nodes.to_vec();
    canonical.sort();
    let mut bytes = b"hepta.ndu.hierarchy-snapshot.v1\0".to_vec();
    push_id(&mut bytes, hierarchy_id);
    bytes.extend_from_slice(&revision.to_be_bytes());
    bytes.extend_from_slice(&u32::try_from(canonical.len()).unwrap_or(u32::MAX).to_be_bytes());
    for node in canonical {
        push_id(&mut bytes, &node.subject_id);
        bytes.push(node.subject_class.tag());
        match node.parent_subject_id {
            Some(parent) => {
                bytes.push(1);
                push_id(&mut bytes, &parent);
            }
            None => bytes.push(0),
        }
    }
    Digest32::of_bytes(&bytes)
}

/// Validate updates against one exact hierarchy revision. Unlike the legacy
/// batch-local helper, this proves every parent edge against the complete
/// snapshot and rejects any ancestor/descendant pair in the same generation.
pub fn validate_staged_updates_against_snapshot(
    snapshot: &HierarchySnapshotV1,
    expected_revision: u64,
    expected_snapshot_digest: Digest32,
    updates: &[UpdateGeneration],
) -> Result<(), HierarchyValidationErrorV1> {
    snapshot.validate()?;
    if expected_revision == 0 || snapshot.revision != expected_revision {
        return Err(HierarchyValidationErrorV1::RevisionMismatch);
    }
    if expected_snapshot_digest.is_zero() || snapshot.snapshot_digest != expected_snapshot_digest {
        return Err(HierarchyValidationErrorV1::ExpectedSnapshotMismatch);
    }

    let nodes: BTreeMap<&StableId, &HierarchyNodeV1> = snapshot
        .nodes
        .iter()
        .map(|node| (&node.subject_id, node))
        .collect();
    let mut staged: BTreeMap<(u64, StableId), &UpdateGeneration> = BTreeMap::new();
    for update in updates {
        let node = nodes.get(&update.subject_id).copied().ok_or_else(|| {
            HierarchyValidationErrorV1::UpdateNotInSnapshot(update.subject_id.to_string())
        })?;
        if node.subject_class != update.subject_class
            || node.parent_subject_id != update.parent_subject_id
        {
            return Err(HierarchyValidationErrorV1::UpdateRelationMismatch(
                update.subject_id.to_string(),
            ));
        }
        let key = (update.generation.get(), update.subject_id.clone());
        if let Some(existing) = staged.get(&key) {
            if existing.artifact_id != update.artifact_id
                || existing.parent_subject_id != update.parent_subject_id
                || existing.subject_class != update.subject_class
            {
                return Err(HierarchyValidationErrorV1::ConflictingStagedArtifact {
                    generation: update.generation.get(),
                    subject: update.subject_id.to_string(),
                });
            }
            continue;
        }
        staged.insert(key, update);
    }

    let unique: Vec<&UpdateGeneration> = staged.values().copied().collect();
    for (index, left) in unique.iter().enumerate() {
        for right in unique.iter().skip(index + 1) {
            if left.generation != right.generation {
                continue;
            }
            if is_ancestor(&left.subject_id, &right.subject_id, &nodes) {
                return Err(HierarchyValidationErrorV1::AncestorConflict {
                    generation: left.generation.get(),
                    ancestor: left.subject_id.to_string(),
                    descendant: right.subject_id.to_string(),
                });
            }
            if is_ancestor(&right.subject_id, &left.subject_id, &nodes) {
                return Err(HierarchyValidationErrorV1::AncestorConflict {
                    generation: left.generation.get(),
                    ancestor: right.subject_id.to_string(),
                    descendant: left.subject_id.to_string(),
                });
            }
        }
    }
    Ok(())
}

fn validate_nodes(
    revision: u64,
    nodes: &[HierarchyNodeV1],
) -> Result<(), HierarchyValidationErrorV1> {
    if revision == 0 {
        return Err(HierarchyValidationErrorV1::InvalidSnapshot(
            "revision must be non-zero",
        ));
    }
    if nodes.is_empty() || nodes.len() > MAX_HIERARCHY_NODES {
        return Err(HierarchyValidationErrorV1::InvalidSnapshot(
            "node count outside bounded envelope",
        ));
    }
    let mut by_id = BTreeMap::new();
    for node in nodes {
        if by_id.insert(&node.subject_id, node).is_some() {
            return Err(HierarchyValidationErrorV1::DuplicateSubject(
                node.subject_id.to_string(),
            ));
        }
    }
    let roots = nodes
        .iter()
        .filter(|node| node.subject_class == SubjectClass::System)
        .count();
    if roots != 1 {
        return Err(HierarchyValidationErrorV1::InvalidSnapshot(
            "exactly one system root is required",
        ));
    }
    for node in nodes {
        match node.subject_class {
            SubjectClass::System => {
                if node.parent_subject_id.is_some() {
                    return Err(HierarchyValidationErrorV1::InvalidParentClass(
                        node.subject_id.to_string(),
                    ));
                }
            }
            SubjectClass::Domain | SubjectClass::Agent | SubjectClass::Episode => {
                let parent_id = node.parent_subject_id.as_ref().ok_or_else(|| {
                    HierarchyValidationErrorV1::MissingParent(node.subject_id.to_string())
                })?;
                if parent_id == &node.subject_id {
                    return Err(HierarchyValidationErrorV1::InvalidParentClass(
                        node.subject_id.to_string(),
                    ));
                }
                let parent = by_id.get(parent_id).copied().ok_or_else(|| {
                    HierarchyValidationErrorV1::MissingParent(node.subject_id.to_string())
                })?;
                let valid = matches!(
                    (parent.subject_class, node.subject_class),
                    (SubjectClass::System, SubjectClass::Domain)
                        | (SubjectClass::Domain, SubjectClass::Agent)
                        | (SubjectClass::Agent, SubjectClass::Episode)
                );
                if !valid {
                    return Err(HierarchyValidationErrorV1::InvalidParentClass(
                        node.subject_id.to_string(),
                    ));
                }
            }
        }
    }
    Ok(())
}

fn is_ancestor(
    ancestor: &StableId,
    descendant: &StableId,
    nodes: &BTreeMap<&StableId, &HierarchyNodeV1>,
) -> bool {
    let mut cursor = nodes
        .get(descendant)
        .and_then(|node| node.parent_subject_id.as_ref());
    for _ in 0..nodes.len() {
        let Some(subject) = cursor else {
            return false;
        };
        if subject == ancestor {
            return true;
        }
        cursor = nodes
            .get(subject)
            .and_then(|node| node.parent_subject_id.as_ref());
    }
    false
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Generation;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn snapshot() -> HierarchySnapshotV1 {
        HierarchySnapshotV1::try_new(
            id("hierarchy-a"),
            7,
            vec![
                HierarchyNodeV1 {
                    subject_id: id("episode-a"),
                    parent_subject_id: Some(id("agent-a")),
                    subject_class: SubjectClass::Episode,
                },
                HierarchyNodeV1 {
                    subject_id: id("system"),
                    parent_subject_id: None,
                    subject_class: SubjectClass::System,
                },
                HierarchyNodeV1 {
                    subject_id: id("agent-a"),
                    parent_subject_id: Some(id("domain-a")),
                    subject_class: SubjectClass::Agent,
                },
                HierarchyNodeV1 {
                    subject_id: id("domain-a"),
                    parent_subject_id: Some(id("system")),
                    subject_class: SubjectClass::Domain,
                },
                HierarchyNodeV1 {
                    subject_id: id("domain-b"),
                    parent_subject_id: Some(id("system")),
                    subject_class: SubjectClass::Domain,
                },
            ],
        )
        .expect("snapshot")
    }

    fn update(
        subject: &str,
        parent: Option<&str>,
        class: SubjectClass,
        artifact: &str,
    ) -> UpdateGeneration {
        UpdateGeneration {
            generation: Generation::new(9).expect("generation"),
            subject_id: id(subject),
            parent_subject_id: parent.map(id),
            subject_class: class,
            artifact_id: id(artifact),
        }
    }

    #[test]
    fn snapshot_rejects_non_immediate_and_missing_parent_edges() {
        assert!(matches!(
            HierarchySnapshotV1::try_new(
                id("bad"),
                1,
                vec![
                    HierarchyNodeV1 {
                        subject_id: id("system"),
                        parent_subject_id: None,
                        subject_class: SubjectClass::System,
                    },
                    HierarchyNodeV1 {
                        subject_id: id("agent"),
                        parent_subject_id: Some(id("system")),
                        subject_class: SubjectClass::Agent,
                    },
                ],
            ),
            Err(HierarchyValidationErrorV1::InvalidParentClass(_))
        ));
    }

    #[test]
    fn snapshot_binding_rejects_any_ancestor_descendant_same_generation() {
        let snapshot = snapshot();
        let updates = vec![
            update("domain-a", Some("system"), SubjectClass::Domain, "a"),
            update(
                "episode-a",
                Some("agent-a"),
                SubjectClass::Episode,
                "b",
            ),
        ];
        assert!(matches!(
            validate_staged_updates_against_snapshot(
                &snapshot,
                snapshot.revision,
                snapshot.snapshot_digest,
                &updates,
            ),
            Err(HierarchyValidationErrorV1::AncestorConflict { .. })
        ));
    }

    #[test]
    fn unrelated_branches_can_advance_in_the_same_generation() {
        let snapshot = snapshot();
        let updates = vec![
            update("agent-a", Some("domain-a"), SubjectClass::Agent, "a"),
            update("domain-b", Some("system"), SubjectClass::Domain, "b"),
        ];
        validate_staged_updates_against_snapshot(
            &snapshot,
            snapshot.revision,
            snapshot.snapshot_digest,
            &updates,
        )
        .expect("unrelated branches");
    }

    #[test]
    fn update_must_match_the_authenticated_snapshot_revision_and_edge() {
        let snapshot = snapshot();
        let mismatch = update("agent-a", Some("domain-b"), SubjectClass::Agent, "a");
        assert!(matches!(
            validate_staged_updates_against_snapshot(
                &snapshot,
                snapshot.revision,
                snapshot.snapshot_digest,
                &[mismatch],
            ),
            Err(HierarchyValidationErrorV1::UpdateRelationMismatch(_))
        ));
        assert!(matches!(
            validate_staged_updates_against_snapshot(
                &snapshot,
                snapshot.revision + 1,
                snapshot.snapshot_digest,
                &[],
            ),
            Err(HierarchyValidationErrorV1::RevisionMismatch)
        ));
    }
}
