use super::*;
use crate::CellSplitCheckpointV1;
use crate::CellSplitChildMigrationV1;
use crate::CellSplitChildSpecV1;
use crate::CellSplitMigrationOwnerV1;
use crate::CellSplitParentStateV1;
use crate::CellSplitPlanV1;
use codex_hepta_learning_artifacts::CasArtifactRefV1;
use codex_hepta_learning_artifacts::CellArtifactManifestV1;
use codex_hepta_learning_artifacts::CellBundlePredecessorV1;
use codex_hepta_learning_artifacts::CellComponentModeV1;
use codex_hepta_learning_artifacts::CellComponentRefV1;
use codex_hepta_learning_artifacts::CellIdentityV1;
use codex_hepta_learning_artifacts::CellParameterBundleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::collections::BTreeMap;

#[derive(Debug)]
struct FixtureChild {
    id: String,
}

impl CellSplitChildMigrationV1 for FixtureChild {
    fn child_id(&self) -> &str {
        &self.id
    }

    fn migrate(
        &mut self,
        input: &crate::CellSplitChildInputV1<'_>,
    ) -> Result<crate::CellSplitChildStateV1, crate::CellSplitMigrationError> {
        Ok(crate::CellSplitChildStateV1 {
            child_id: self.id.clone(),
            candidate_weights: input.spec.candidate_weights,
            selected_weights: input.parent.selected_weights,
            recurrent_state: input.parent.recurrent_state.clone(),
            eligibility_state: input.parent.eligibility_state.clone(),
            optimizer_state: input.parent.optimizer_state.clone(),
            cache: input.parent.cache.clone(),
            cache_generation: input.candidate_generation,
            message_fence: input.parent.message_fence(),
        })
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn parent() -> CellSplitParentStateV1 {
    CellSplitParentStateV1 {
        checkpoint: CellSplitCheckpointV1 {
            generation: 7,
            digest: digest("checkpoint"),
            committed: true,
        },
        selected_weights: digest("selected"),
        recurrent_state: b"r".to_vec(),
        eligibility_state: b"e".to_vec(),
        optimizer_state: b"o".to_vec(),
        cache: b"c".to_vec(),
        cache_generation: 7,
        in_flight: Vec::new(),
    }
}

fn plan() -> CellSplitPlanV1 {
    CellSplitPlanV1 {
        parent_generation: 7,
        candidate_generation: 8,
        predecessor_writer_fence: 7,
        successor_writer_fence: 8,
        selected_weights: digest("selected"),
        migration_digest: digest("migration"),
        rollback_digest: digest("rollback"),
        children: ["child-a", "child-b"]
            .into_iter()
            .map(|child_id| CellSplitChildSpecV1 {
                child_id: child_id.to_owned(),
                candidate_weights: digest(child_id),
                transform_digest: digest("transform"),
            })
            .collect(),
    }
}

fn children() -> Vec<Box<dyn CellSplitChildMigrationV1>> {
    ["child-a", "child-b"]
        .into_iter()
        .map(|id| {
            Box::new(FixtureChild { id: id.to_owned() }) as Box<dyn CellSplitChildMigrationV1>
        })
        .collect()
}

fn artifact(label: &str) -> CasArtifactRefV1 {
    CasArtifactRefV1 {
        artifact_id: id(&format!("artifact:{label}")),
        content_digest: digest(&format!("content:{label}")),
        manifest_digest: digest(&format!("manifest:{label}")),
        compatibility_digest: digest(&format!("compatibility:{label}")),
        encoded_size_bytes: 32,
    }
}

fn owner(child_id: &str) -> CellParameterBundleOwnerV1 {
    let scope = digest(&format!("scope:{child_id}"));
    CellParameterBundleOwnerV1::new(scope).expect("owner")
}

fn bundle(
    child_id: &str,
    generation: u64,
    parent: Option<&CellParameterBundleV1>,
) -> CellParameterBundleV1 {
    let base = artifact(&format!("base:{child_id}"));
    let adapter_artifact = artifact(&format!("adapter:{child_id}:{generation}"));
    let head_artifact = artifact(&format!("head:{child_id}:{generation}"));
    let adapter = CellComponentRefV1 {
        component_id: id(&format!("component:adapter:{child_id}:{generation}")),
        mode: CellComponentModeV1::Reinitialized,
        artifact: adapter_artifact.clone(),
        source_artifact_digest: None,
        compatibility_digest: digest("adapter-compatible"),
    };
    let head = CellComponentRefV1 {
        component_id: id(&format!("component:head:{child_id}:{generation}")),
        mode: CellComponentModeV1::Reinitialized,
        artifact: head_artifact.clone(),
        source_artifact_digest: None,
        compatibility_digest: digest("head-compatible"),
    };
    let scope = digest(&format!("scope:{child_id}"));
    let mut bundle = CellParameterBundleV1 {
        bundle_id: id(&format!("bundle:{child_id}:{generation}")),
        identity: CellIdentityV1 {
            cell_id: id(&format!("cell:{child_id}")),
            child_id: id(child_id),
            generation: Generation::new(generation).expect("generation"),
            scope_digest: scope,
            lineage_digest: Digest32::ZERO,
        },
        parent_predecessor: parent.map(|value| CellBundlePredecessorV1 {
            bundle_id: value.bundle_id.clone(),
            bundle_digest: value.bundle_digest,
            generation: value.identity.generation,
            lineage_digest: value.identity.lineage_digest,
        }),
        shared_base: base.clone(),
        adapter,
        head,
        state_schema_digest: digest("state-schema"),
        optimizer_lineage_digest: digest("optimizer"),
        artifact_manifest: CellArtifactManifestV1::from_entries(
            id(&format!("manifest:{child_id}:{generation}")),
            vec![base, adapter_artifact, head_artifact],
        )
        .expect("manifest"),
        rollback_target: None,
        bundle_digest: Digest32::ZERO,
    };
    bundle.seal().expect("bundle");
    bundle
}

fn owners_and_candidates() -> (
    BTreeMap<String, CellParameterBundleOwnerV1>,
    Vec<CellParameterBundleV1>,
) {
    let mut owners = BTreeMap::new();
    let mut candidates = Vec::new();
    for child_id in ["child-a", "child-b"] {
        let genesis = bundle(child_id, 1, None);
        let mut owner = owner(child_id);
        owner
            .append(Digest32::ZERO, genesis.clone())
            .expect("genesis");
        let candidate = bundle(child_id, 2, Some(&genesis));
        owners.insert(child_id.to_owned(), owner);
        candidates.push(candidate);
    }
    (owners, candidates)
}

#[test]
fn all_child_bundles_commit_atomically_and_rollback_restores_each_cas_head() {
    let migration =
        CellSplitMigrationOwnerV1::new_in_memory(plan(), digest("handoff"), parent(), children())
            .expect("migration");
    let (owners, candidates) = owners_and_candidates();
    let mut owner = CellSplitParameterBundleSetMigrationOwnerV1::new(migration, owners, candidates)
        .expect("bundle bridge");
    let snapshot = owner
        .snapshot(Generation::new(7).expect("generation"))
        .expect("snapshot");
    owner
        .migrate(
            &snapshot,
            Generation::new(7).expect("generation"),
            Generation::new(8).expect("generation"),
        )
        .expect("migrate");
    assert!(
        owner
            .owners()
            .values()
            .all(|value| value.records().len() == 2)
    );
    owner
        .rollback(
            &snapshot,
            Generation::new(7).expect("generation"),
            Generation::new(8).expect("generation"),
        )
        .expect("rollback");
    assert!(
        owner
            .owners()
            .values()
            .all(|value| value.records().len() == 1)
    );
}

#[test]
fn receipt_mismatch_fails_closed_before_any_sibling_owner_changes() {
    let migration =
        CellSplitMigrationOwnerV1::new_in_memory(plan(), digest("handoff"), parent(), children())
            .expect("migration");
    let (owners, mut candidates) = owners_and_candidates();
    candidates[1].parent_predecessor = Some(CellBundlePredecessorV1 {
        bundle_id: id("bundle:stale"),
        bundle_digest: digest("stale"),
        generation: Generation::new(1).expect("generation"),
        lineage_digest: digest("stale-lineage"),
    });
    candidates[1].identity.lineage_digest = Digest32::ZERO;
    candidates[1].seal().expect("candidate remains well shaped");
    let mut owner = CellSplitParameterBundleSetMigrationOwnerV1::new(migration, owners, candidates)
        .expect("bundle bridge");
    let snapshot = owner
        .snapshot(Generation::new(7).expect("generation"))
        .expect("snapshot");
    assert!(
        owner
            .migrate(
                &snapshot,
                Generation::new(7).expect("generation"),
                Generation::new(8).expect("generation"),
            )
            .is_err()
    );
    assert!(
        owner
            .owners()
            .values()
            .all(|value| value.records().len() == 1)
    );
    owner
        .rollback(
            &snapshot,
            Generation::new(7).expect("generation"),
            Generation::new(8).expect("generation"),
        )
        .expect("rollback");
}
