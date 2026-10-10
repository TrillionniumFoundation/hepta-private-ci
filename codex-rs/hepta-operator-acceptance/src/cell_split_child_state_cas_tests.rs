use std::fs;
use std::os::unix::net::UnixListener;
use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

use codex_hepta_neuron::{
    CellStateSplitPlanV1 as NeuronSplitPlan, SparseConfig, SparseTick,
    canonical_partition_digest_v1, sparse_tick,
};
use codex_hepta_types::{
    CellBundleBindingV1, CellBundleInheritanceV1, CellBundleModeV1,
    CellCachePolicyV1, CellChildPortBindingV1, CellChildV1,
    CellInFlightPolicyV1, CellParentDispositionV1, CellParentRetirementPlanV1,
    CellPortCompatibilityV1, CellResourceDeltaV1, CellRouteModeV1,
    CellSplitEvaluationBindingV1, CellSplitV1,
    CellStateSplitPlanV1 as SemanticStatePlan, CellStateTransformKindV1,
    CellStateTransformV1, Generation, StableId,
};
use ed25519_dalek::SigningKey;

use super::*;
use crate::{
    CellSplitEffectServiceV1, CellSplitExecutionPortV1, CellSplitUnixEffectPortV1,
};

const Q: i64 = 1 << 24;
fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture ID")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn g(value: u64) -> Generation {
    Generation::new(value).expect("fixture generation")
}
fn transform(kind: CellStateTransformKindV1, mapping: Digest32) -> CellStateTransformV1 {
    CellStateTransformV1 {
        kind, source_schema_digest: digest("source-schema"),
        target_schema_digest: digest("target-schema"), mapping_digest: mapping,
    }
}

fn contract() -> CellSplitV1 {
    let children = vec!["a", "b"].into_iter().enumerate().map(|(_index, suffix)| {
        CellChildV1 {
            child_cell_id: id(&format!("cell.{suffix}")),
            child_generation: g(8),
            child_scope_digest: digest(&format!("scope-{suffix}")),
            lineage_digest: digest(&format!("lineage-{suffix}")),
            child_definition_digest: digest(&format!("definition-{suffix}")),
            child_bundle_digest: digest(&format!("bundle-{suffix}")),
            dataset_partition_digest: digest(&format!("dataset-{suffix}")),
            task_objective_digest: digest(&format!("task-{suffix}")),
            route_predicate_digest: digest(&format!("predicate-{suffix}")),
            fallback_route_digest: digest(&format!("fallback-{suffix}")),
            route_mode: CellRouteModeV1::Exclusive,
        }
    }).collect::<Vec<_>>();
    let bundles = children.iter().enumerate().map(|(index, child)| CellBundleBindingV1 {
        child_cell_id: child.child_cell_id.clone(),
        base_digest: digest("base"),
        organ_adapter_digest: digest("organ-adapter"),
        cell_adapter_digest: digest(&format!("cell-adapter-{index}")),
        head_digest: digest(&format!("head-{index}")),
        compatibility_digest: digest(&format!("compat-{index}")),
    }).collect();
    let ports = children.iter().enumerate().map(|(index, child)| CellChildPortBindingV1 {
        child_cell_id: child.child_cell_id.clone(),
        input_port_digest: digest(&format!("input-{index}")),
        output_port_digest: digest(&format!("output-{index}")),
        termination_port_digest: digest(&format!("terminal-{index}")),
        compatibility_digest: digest(&format!("port-compat-{index}")),
    }).collect();
    let partitions = vec![vec![0, 2], vec![1, 3]];
    let value = CellSplitV1 {
        split_id: id("split.integration"),
        proposer_id: id("proposer"),
        evaluator_id: id("evaluator"),
        parent_cell_id: id("cell.parent"),
        organ_id: id("organ.decision"),
        parent_scope_digest: digest("parent-scope"),
        predecessor_generation: g(7),
        successor_generation: g(8),
        parent_definition_digest: digest("parent-definition"),
        parent_bundle_digest: digest("parent-bundle"),
        children,
        inheritance: CellBundleInheritanceV1 {
            base_mode: CellBundleModeV1::SharedImmutable,
            organ_adapter_mode: CellBundleModeV1::SharedImmutable,
            cell_adapter_mode: CellBundleModeV1::CloneMutable,
            head_mode: CellBundleModeV1::CloneMutable,
            compatibility_digest: digest("global-bundle-compat"),
            children: bundles,
        },
        state: SemanticStatePlan {
            recurrent: transform(
                CellStateTransformKindV1::Partition,
                canonical_partition_digest_v1(b"temporal", &partitions)
            ),
            eligibility: transform(
                CellStateTransformKindV1::Partition,
                canonical_partition_digest_v1(b"activation", &partitions)
            ),
            optimizer: transform(CellStateTransformKindV1::Reset, Digest32::ZERO),
            cache_policy: CellCachePolicyV1::Revalidate,
            in_flight_policy: CellInFlightPolicyV1::Drain,
            state_evidence_digest: digest("state-evidence"),
        },
        ports: CellPortCompatibilityV1 {
            parent_input_port_digest: digest("parent-input"),
            parent_output_port_digest: digest("parent-output"),
            circuit_route_digest: digest("cns-route"),
            abi_digest: digest("abi"),
            children: ports,
        },
        resources: CellResourceDeltaV1 {
            inference_latency_micros: 100,
            training_steps: 200,
            communication_bytes: 300,
            migration_bytes: 400,
            evaluation_steps: 500,
            resident_bytes: 600,
            checkpoint_bytes: 700,
        },
        retirement: CellParentRetirementPlanV1 {
            disposition: CellParentDispositionV1::Retire,
            drain_watermark_digest: digest("drain"),
            tombstone_digest: digest("tombstone"),
            deletion_lineage_digest: digest("deletion-lineage"),
            rollback_digest: digest("rollback"),
        },
        evaluation: CellSplitEvaluationBindingV1 {
            no_change_baseline_id: id("baseline"),
            evaluation_id: id("evaluation"),
            evaluator_id: id("evaluator"),
            evaluation_receipt_digest: digest("eval-receipt"),
            retention_receipt_digest: digest("retention"),
            negative_transfer_receipt_digest: digest("negative-transfer"),
            cost_receipt_digest: digest("cost"),
        },
        rollback_predecessor_digest: digest("predecessor"),
        evidence_digest: digest("split-evidence"),
    };
    value.validate().expect("valid typed split contract");
    value
}

fn parent_checkpoint() -> codex_hepta_neuron::SparseCheckpoint {
    let configuration = SparseConfig {
        model_digest: digest("model"),
        normalization_digest: digest("normalization"),
        generation: g(7),
        width: 4,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 4,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    let input = SparseTick {
        scope_digest: digest("parent-scope"),
        objective_digest: digest("objective"),
        ndu_digest: digest("ndu"),
        body_digest: digest("body"),
        input_digest: digest("input"),
        sequence: 1,
        monotonic_micros: 100,
        drive_q24: vec![Q, Q / 2, Q / 4, 0],
        prediction_q24: vec![0; 4],
    };
    sparse_tick(&configuration, &input, None).expect("parent state").0
}

fn prepared() -> (CellStateMigrationV1, JournalAnchor) {
    let contract = contract();
    let checkpoint = parent_checkpoint();
    let anchor = JournalAnchor {
        sequence: checkpoint.sequence(),
        checkpoint_digest: checkpoint.digest(),
    };
    let plan = NeuronSplitPlan::from_contract(
        &contract,
        vec![vec![0, 2], vec![1, 3]],
        vec![vec![0, 2], vec![1, 3]],
    ).expect("typed projection plan");
    let migration = CellStateMigrationV1::begin(
        id("split.integration"), &contract, anchor, &checkpoint, &plan,
    ).expect("verified migration from parent");
    (migration, anchor)
}

fn execution_plan() -> CellSplitExecutionPlanV1 {
    CellSplitExecutionPlanV1 {
        split_id: "split.integration".into(),
        scope_digest: digest("parent-scope").to_string(),
        parent_generation: 7,
        child_generation: 8,
        parent_artifact_digest: sha256(b"real parent artifact"),
        child_artifact_digest: sha256(b"real child artifact"),
        ndu_snapshot_digest: "33".repeat(32),
        route_fence_digest: "44".repeat(32),
        owner_ids: [
            "artifact-cas-owner".into(),
            "migration-owner".into(),
            "cns-owner".into(),
            "supervisor-owner".into(),
        ],
    }
}

fn operation(plan: &CellSplitExecutionPlanV1) -> CellSplitExecutionIntentV1 {
    let plan_digest = sha256(&canonical_json(plan).expect("plan"));
    let predecessor = "55".repeat(32);
    let key = sha256(format!(
        "hepta.learning.cell-split.execution-owner.v1\0{plan_digest}\0{}\0{predecessor}",
        CellSplitExecutionStepV1::ChildStateMigration.index(),
    ).as_bytes());
    CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest,
        step: CellSplitExecutionStepV1::ChildStateMigration,
        owner_id: "migration-owner".into(),
        idempotency_key: key,
        previous_receipt_digest: predecessor,
    }
}

/// Fixture only: deployment must query the actual immutable CAS receipt,
/// signed NDU/Selector authority and parent journal witness, not these flags.
#[derive(Clone)]
struct ObservedAuthority {
    live: Arc<Mutex<JournalAnchor>>,
    cas_good: Arc<AtomicBool>,
    exact_cas_receipt: Arc<Mutex<String>>,
    final_use_good: Arc<AtomicBool>,
}

impl ObservedAuthority {
    fn new(anchor: JournalAnchor) -> Self {
        Self {
            live: Arc::new(Mutex::new(anchor)),
            cas_good: Arc::new(AtomicBool::new(true)),
            exact_cas_receipt: Arc::new(Mutex::new("55".repeat(32))),
            final_use_good: Arc::new(AtomicBool::new(true)),
        }
    }
}
impl CellSplitMigrationAuthorityPortV1 for ObservedAuthority {
    type Error = &'static str;
    fn current_parent_anchor(
        &mut self, _plan: &CellSplitExecutionPlanV1,
    ) -> Result<JournalAnchor, Self::Error> {
        Ok(*self.live.lock().expect("anchor"))
    }
    fn verify_committed_artifact(
        &mut self, _plan: &CellSplitExecutionPlanV1, previous: &str,
    ) -> Result<(), Self::Error> {
        if self.cas_good.load(Ordering::Acquire)
            && previous == *self.exact_cas_receipt.lock().expect("pinned CAS receipt")
        {
            Ok(())
        } else {
            Err("CAS predecessor no longer committed")
        }
    }
    fn verify_final_use(
        &mut self, _plan: &CellSplitExecutionPlanV1,
        _intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        if self.final_use_good.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err("final use revoked")
        }
    }
}

fn private_root() -> tempfile::TempDir {
    let root = tempfile::tempdir().expect("root");
    use std::os::unix::fs::PermissionsExt as _;
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
        .expect("private root");
    root
}

fn owner(
    root: &std::path::Path, migration: CellStateMigrationV1,
    auth: ObservedAuthority,
) -> CellSplitChildStateCasOwnerV1<ObservedAuthority> {
    CellSplitChildStateCasOwnerV1::open(
        root, execution_plan(), migration, auth,
    ).expect("durable owner")
}

#[test]
fn real_q24_children_commit_atomically_and_reopen_from_original_bytes() {
    let root = private_root();
    let (migration, anchor) = prepared();
    let auth = ObservedAuthority::new(anchor);
    let intent = operation(&execution_plan());
    {
        let mut batch = owner(root.path(), migration.clone(), auth.clone());
        assert!(batch.read_committed(&intent).expect("empty").is_none());
        batch.commit_once(&intent).expect("real typed child CAS");
        let committed = batch.read_committed(&intent).expect("readback").expect("marker");
        assert!(batch.verify_current(&intent, &committed).expect("live readback"));
        for (index, child) in migration.children().iter().enumerate() {
            let path = batch.child_path(
                index, &intent, CellStateMigrationV1::child_payload_digest(child),
            );
            assert_eq!(fs::read(path).expect("Q24 payload"), encode_cell_state_v1(child));
        }
        assert!(owner_try_reopen(root.path(), migration.clone(), auth.clone()).is_err());
    }
    let mut reopened = owner(root.path(), migration.clone(), auth.clone());
    let signed = reopened.read_committed(&intent).unwrap().expect("reopened marker");
    assert!(reopened.verify_current(&intent, &signed).unwrap());
    reopened.commit_once(&intent).expect("verified duplicate is idempotent");
    let path = reopened.child_path(
        0, &intent, CellStateMigrationV1::child_payload_digest(&migration.children()[0]),
    );
    fs::write(path, b"tampered child Q24").expect("external corruption");
    assert!(reopened.verify_current(&intent, &signed).is_err());
}

fn owner_try_reopen(
    root: &std::path::Path,
    migration: CellStateMigrationV1,
    auth: ObservedAuthority,
) -> Result<CellSplitChildStateCasOwnerV1<ObservedAuthority>, CellSplitChildStateCasErrorV1> {
    CellSplitChildStateCasOwnerV1::open(root, execution_plan(), migration, auth)
}

#[test]
fn abandoned_partial_child_and_stale_authority_never_publish_a_batch_marker() {
    let root = private_root();
    let (migration, anchor) = prepared();
    let auth = ObservedAuthority::new(anchor);
    let intent = operation(&execution_plan());
    let mut batch = owner(root.path(), migration.clone(), auth.clone());
    auth.final_use_good.store(false, Ordering::Release);
    assert!(batch.commit_once(&intent).is_err());
    assert!(batch.read_committed(&intent).unwrap().is_none());
    auth.final_use_good.store(true, Ordering::Release);
    let child = &migration.children()[0];
    let path = batch.child_path(
        0, &intent, CellStateMigrationV1::child_payload_digest(child),
    );
    fs::write(&path, b"partial first child").expect("simulate power loss");
    assert!(matches!(batch.commit_once(&intent), Err(CellSplitChildStateCasErrorV1::Ambiguous)));
    assert!(batch.read_committed(&intent).unwrap().is_none());
    drop(batch);
    let mut recovered = owner(root.path(), migration, auth);
    assert!(matches!(
        recovered.commit_once(&intent), Err(CellSplitChildStateCasErrorV1::Ambiguous)
    ));
    assert!(recovered.read_committed(&intent).unwrap().is_none());
}

#[test]
fn independent_cas_or_parent_anchor_revocation_fences_existing_batch() {
    let root = private_root();
    let (migration, anchor) = prepared();
    let auth = ObservedAuthority::new(anchor);
    let intent = operation(&execution_plan());
    let mut batch = owner(root.path(), migration, auth.clone());
    batch.commit_once(&intent).expect("committed");
    let receipt = batch.read_committed(&intent).unwrap().expect("committed");
    auth.cas_good.store(false, Ordering::Release);
    assert!(batch.verify_current(&intent, &receipt).is_err());
    auth.cas_good.store(true, Ordering::Release);
    *auth.live.lock().expect("anchor") = JournalAnchor {
        sequence: anchor.sequence + 1,
        checkpoint_digest: digest("different parent checkpoint"),
    };
    assert!(batch.verify_current(&intent, &receipt).is_err());
}

#[test]
fn signed_migration_rpc_requires_reopening_real_child_bytes() {
    let root = private_root();
    let socket = root.path().join("migration.sock");
    let listener = UnixListener::bind(&socket).expect("service socket");
    let (migration, anchor) = prepared();
    let auth = ObservedAuthority::new(anchor);
    let request = operation(&execution_plan());
    let plan = execution_plan();
    let server_root = root.path().to_path_buf();
    let server = thread::spawn(move || {
        let backend = CellSplitChildStateCasOwnerV1::open(
            &server_root, plan.clone(), migration.clone(), auth.clone(),
        ).expect("real state CAS backend");
        let signer = SigningKey::from_bytes(&[2; 32]);
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ChildStateMigration,
            plan.owner_ids[1].clone(),
            sha256(&canonical_json(&plan).expect("plan")),
            signer.clone(), backend,
        ).expect("signed service");
        for _ in 0..3 {
            let (mut stream, _) = listener.accept().expect("RPC");
            service.serve_connection(&mut stream).expect("serving actual state");
        }
        drop(service);
        let reopened = CellSplitChildStateCasOwnerV1::open(
            &server_root, plan.clone(), migration, auth,
        ).expect("disk reopen");
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ChildStateMigration,
            plan.owner_ids[1].clone(),
            sha256(&canonical_json(&plan).expect("plan")),
            signer, reopened,
        ).expect("reopened service");
        let (mut stream, _) = listener.accept().expect("restart RPC");
        service.serve_connection(&mut stream).expect("recovered readback");
    });
    let keys = [1_u8, 2, 3, 4]
        .map(|n| SigningKey::from_bytes(&[n; 32]).verifying_key());
    let mut client = CellSplitUnixEffectPortV1::new(
        [
            root.path().join("cas.sock"), socket,
            root.path().join("cns.sock"),
            root.path().join("supervisor.sock"),
        ],
        keys,
        Duration::from_secs(3),
    ).expect("RPC client");
    let signed = client.execute(&request).expect("real backend");
    client.verify_committed(&request, &signed).expect("fresh readback");
    assert_eq!(client.reconcile(&request).expect("readback"), Some(signed.clone()));
    assert_eq!(client.reconcile(&request).expect("reopened readback"), Some(signed));
    server.join().expect("server completed");
}
