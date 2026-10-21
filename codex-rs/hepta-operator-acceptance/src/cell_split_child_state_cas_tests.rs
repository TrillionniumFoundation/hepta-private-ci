use std::fs;
use std::os::unix::net::UnixListener;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;

use codex_hepta_neuron::CellStateSplitPlanV1 as NeuronSplitPlan;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::canonical_partition_digest_v1;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_types::CellBundleBindingV1;
use codex_hepta_types::CellBundleInheritanceV1;
use codex_hepta_types::CellBundleModeV1;
use codex_hepta_types::CellCachePolicyV1;
use codex_hepta_types::CellChildPortBindingV1;
use codex_hepta_types::CellChildV1;
use codex_hepta_types::CellInFlightPolicyV1;
use codex_hepta_types::CellParentDispositionV1;
use codex_hepta_types::CellParentRetirementPlanV1;
use codex_hepta_types::CellPortCompatibilityV1;
use codex_hepta_types::CellResourceDeltaV1;
use codex_hepta_types::CellRouteModeV1;
use codex_hepta_types::CellSplitEvaluationBindingV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::CellStateSplitPlanV1 as SemanticStatePlan;
use codex_hepta_types::CellStateTransformKindV1;
use codex_hepta_types::CellStateTransformV1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use super::*;
use crate::CellSplitEffectServiceV1;
use crate::CellSplitExecutionPortV1;
use crate::CellSplitUnixEffectPortV1;

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
        kind,
        source_schema_digest: digest("source-schema"),
        target_schema_digest: digest("target-schema"),
        mapping_digest: mapping,
    }
}

fn contract() -> CellSplitV1 {
    let children = vec!["a", "b"]
        .into_iter()
        .enumerate()
        .map(|(_index, suffix)| CellChildV1 {
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
        })
        .collect::<Vec<_>>();
    let bundles = children
        .iter()
        .enumerate()
        .map(|(index, child)| CellBundleBindingV1 {
            child_cell_id: child.child_cell_id.clone(),
            base_digest: digest("base"),
            organ_adapter_digest: digest("organ-adapter"),
            cell_adapter_digest: digest(&format!("cell-adapter-{index}")),
            head_digest: digest(&format!("head-{index}")),
            compatibility_digest: digest(&format!("compat-{index}")),
        })
        .collect();
    let ports = children
        .iter()
        .enumerate()
        .map(|(index, child)| CellChildPortBindingV1 {
            child_cell_id: child.child_cell_id.clone(),
            input_port_digest: digest(&format!("input-{index}")),
            output_port_digest: digest(&format!("output-{index}")),
            termination_port_digest: digest(&format!("terminal-{index}")),
            compatibility_digest: digest(&format!("port-compat-{index}")),
        })
        .collect();
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
                canonical_partition_digest_v1(b"temporal", &partitions),
            ),
            eligibility: transform(
                CellStateTransformKindV1::Partition,
                canonical_partition_digest_v1(b"activation", &partitions),
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
    sparse_tick(&configuration, &input, None)
        .expect("parent state")
        .0
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
    )
    .expect("typed projection plan");
    let migration = CellStateMigrationV1::begin(
        id("split.integration"),
        &contract,
        anchor,
        &checkpoint,
        &plan,
    )
    .expect("verified migration from parent");
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
    let key = sha256(
        format!(
            "hepta.learning.cell-split.execution-owner.v1\0{plan_digest}\0{}\0{predecessor}",
            CellSplitExecutionStepV1::ChildStateMigration.index(),
        )
        .as_bytes(),
    );
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
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
    ) -> Result<JournalAnchor, Self::Error> {
        Ok(*self.live.lock().expect("anchor"))
    }
    fn verify_committed_artifact(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        previous: &str,
    ) -> Result<(), Self::Error> {
        let pinned = self.exact_cas_receipt.lock().expect("pinned CAS receipt");
        if self.cas_good.load(Ordering::Acquire) && previous == pinned.as_str() {
            Ok(())
        } else {
            Err("CAS predecessor no longer committed")
        }
    }
    fn verify_final_use(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
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
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).expect("private root");
    root
}

fn owner(
    root: &std::path::Path,
    migration: CellStateMigrationV1,
    auth: ObservedAuthority,
) -> CellSplitChildStateCasOwnerV1<ObservedAuthority> {
    CellSplitChildStateCasOwnerV1::open(root, execution_plan(), migration, auth)
        .expect("durable owner")
}

#[cfg(unix)]
#[test]
fn missing_original_migration_writer_lock_never_creates_second_writer() {
    let root = private_root();
    let (migration, anchor) = prepared();
    let authority = ObservedAuthority::new(anchor);
    let _original = owner(root.path(), migration.clone(), authority.clone());
    let lock = root.path().join(crate::durable::SIDECAR_LOCK_FILE);
    fs::remove_file(&lock).expect("unlink original writer lock");
    assert!(matches!(
        CellSplitChildStateCasOwnerV1::open(root.path(), execution_plan(), migration, authority,),
        Err(CellSplitChildStateCasErrorV1::Durable(_))
    ));
    assert!(!lock.exists(), "must not mint a replacement writer lock");
    assert!(root.path().join(FROZEN).exists());
}

#[test]
fn missing_frozen_migration_manifest_never_reinitializes_an_existing_owner() {
    for committed in [false, true] {
        for lose_input in [false, true] {
            let root = private_root();
            let (migration, anchor) = prepared();
            let authority = ObservedAuthority::new(anchor);
            let request = operation(&execution_plan());
            let mut original = owner(root.path(), migration.clone(), authority.clone());
            if committed {
                original
                    .commit_once(&request)
                    .expect("persist original child batch");
                assert!(original.read_committed(&request).unwrap().is_some());
            }
            drop(original);

            let missing = root.path().join(if lose_input {
                "migration-frozen-input.json"
            } else {
                "migration-frozen-plan.json"
            });
            fs::remove_file(&missing).expect("simulate manifest loss");
            assert!(matches!(
                CellSplitChildStateCasOwnerV1::open(
                    root.path(),
                    execution_plan(),
                    migration.clone(),
                    authority.clone(),
                ),
                Err(CellSplitChildStateCasErrorV1::Ambiguous)
            ));
            assert!(!missing.exists(), "lost manifest must not be regenerated");
        }
    }
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
        assert_eq!(
            batch
                .current_sequence_for_intent(&intent)
                .expect("pre-commit revision"),
            migration.parent_anchor().sequence
        );
        batch.commit_once(&intent).expect("real typed child CAS");
        let committed = batch
            .read_committed(&intent)
            .expect("readback")
            .expect("marker");
        assert!(
            batch
                .verify_current(&intent, &committed)
                .expect("live readback")
        );
        assert_eq!(
            committed.owner_sequence,
            migration.parent_anchor().sequence + 1
        );
        assert_eq!(
            batch
                .current_sequence_for_intent(&intent)
                .expect("post-commit revision"),
            committed.owner_sequence
        );
        for (index, child) in migration.children().iter().enumerate() {
            let path = batch.child_path(
                index,
                &intent,
                CellStateMigrationV1::child_payload_digest(child),
            );
            assert_eq!(
                fs::read(path).expect("Q24 payload"),
                encode_cell_state_v1(child)
            );
        }
        assert!(owner_try_reopen(root.path(), migration.clone(), auth.clone()).is_err());
    }
    let mut reopened = owner(root.path(), migration.clone(), auth.clone());
    let signed = reopened
        .read_committed(&intent)
        .unwrap()
        .expect("reopened marker");
    assert!(reopened.verify_current(&intent, &signed).unwrap());
    assert_eq!(
        reopened
            .current_sequence_for_intent(&intent)
            .expect("recovered revision"),
        signed.owner_sequence
    );
    assert!(matches!(
        reopened.commit_once(&intent),
        Err(CellSplitChildStateCasErrorV1::Ambiguous)
    ));
    let path = reopened.child_path(
        0,
        &intent,
        CellStateMigrationV1::child_payload_digest(&migration.children()[0]),
    );
    fs::write(path, b"tampered child Q24").expect("external corruption");
    assert!(reopened.read_committed(&intent).is_err());
    assert!(reopened.verify_current(&intent, &signed).is_err());
}

#[test]
fn streaming_child_hash_checks_real_bytes_and_rejects_oversize_before_read() {
    let root = private_root();
    let path = root.path().join("streamed-child-hash-probe");
    let bytes = b"bounded child bytes";
    fs::write(&path, bytes).expect("probe");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private probe");
    }
    let (observed_digest, observed_size) =
        crate::durable::secure_hash_bounded(&path, bytes.len() as u64)
            .expect("streamed actual bytes");
    assert_eq!(observed_digest, sha256(bytes));
    assert_eq!(observed_size, bytes.len() as u64);
    assert!(crate::durable::secure_hash_bounded(&path, bytes.len() as u64 - 1).is_err());
    #[cfg(unix)]
    {
        let alias = root.path().join("untrusted-child-symlink");
        std::os::unix::fs::symlink(&path, &alias).expect("symlink fixture");
        assert!(crate::durable::secure_hash_bounded(&alias, bytes.len() as u64).is_err());
    }
}

#[test]
fn same_length_tampered_child_cas_is_not_a_recoverable_batch() {
    let root = private_root();
    let (migration, anchor) = prepared();
    let auth = ObservedAuthority::new(anchor);
    let intent = operation(&execution_plan());
    let mut batch = owner(root.path(), migration.clone(), auth);
    batch.commit_once(&intent).expect("original durable children");
    let committed = batch.read_committed(&intent).expect("original readback");
    assert!(committed.is_some());
    let child = &migration.children()[0];
    let path = batch.child_path(
        0,
        &intent,
        CellStateMigrationV1::child_payload_digest(child),
    );
    let mut payload = fs::read(&path).expect("original child bytes");
    assert!(!payload.is_empty());
    payload[0] ^= 1;
    fs::write(&path, &payload).expect("same-size corruption");
    assert_eq!(fs::metadata(&path).expect("metadata").len(), payload.len() as u64);
    assert!(batch.read_committed(&intent).is_err());
    assert!(batch.current_sequence_for_intent(&intent).is_err());
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
        0,
        &intent,
        CellStateMigrationV1::child_payload_digest(child),
    );
    fs::write(&path, b"partial first child").expect("simulate power loss");
    assert!(matches!(
        batch.commit_once(&intent),
        Err(CellSplitChildStateCasErrorV1::Ambiguous)
    ));
    assert!(batch.read_committed(&intent).unwrap().is_none());
    assert_eq!(
        batch
            .current_sequence_for_intent(&intent)
            .expect("partial child is not a committed batch"),
        batch.migration.parent_anchor().sequence
    );
    drop(batch);
    let mut recovered = owner(root.path(), migration, auth);
    assert!(matches!(
        recovered.commit_once(&intent),
        Err(CellSplitChildStateCasErrorV1::Ambiguous)
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
    auth.final_use_good.store(false, Ordering::Release);
    assert!(batch.verify_current(&intent, &receipt).is_err());
    auth.final_use_good.store(true, Ordering::Release);
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
            &server_root,
            plan.clone(),
            migration.clone(),
            auth.clone(),
        )
        .expect("real state CAS backend");
        let signer = SigningKey::from_bytes(&[2; 32]);
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ChildStateMigration,
            plan.owner_ids[1].clone(),
            sha256(&canonical_json(&plan).expect("plan")),
            signer.clone(),
            backend,
        )
        .expect("signed service");
        for _ in 0..3 {
            let (mut stream, _) = listener.accept().expect("RPC");
            service
                .serve_connection(&mut stream)
                .expect("serving actual state");
        }
        drop(service);
        let reopened =
            CellSplitChildStateCasOwnerV1::open(&server_root, plan.clone(), migration, auth)
                .expect("disk reopen");
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ChildStateMigration,
            plan.owner_ids[1].clone(),
            sha256(&canonical_json(&plan).expect("plan")),
            signer,
            reopened,
        )
        .expect("reopened service");
        let (mut stream, _) = listener.accept().expect("restart RPC");
        service
            .serve_connection(&mut stream)
            .expect("recovered readback");
    });
    let keys = [1_u8, 2, 3, 4].map(|n| SigningKey::from_bytes(&[n; 32]).verifying_key());
    let mut client = CellSplitUnixEffectPortV1::new(
        [
            root.path().join("cas.sock"),
            socket,
            root.path().join("cns.sock"),
            root.path().join("supervisor.sock"),
        ],
        keys,
        Duration::from_secs(3),
    )
    .expect("RPC client");
    let signed = client.execute(&request).expect("real backend");
    client
        .verify_committed(&request, &signed)
        .expect("fresh readback");
    assert_eq!(
        client.reconcile(&request).expect("readback"),
        Some(signed.clone())
    );
    assert_eq!(
        client.reconcile(&request).expect("reopened readback"),
        Some(signed)
    );
    server.join().expect("server completed");
}

/// Two physical durable operations, two independent signed RPC owners, one
/// coordinator ledger. CNS and Supervisor deliberately have no service:
/// neither can be inferred from the earlier Artifact + migration commits.
#[test]
fn coordinator_executes_real_artifact_and_child_migration_then_fences_cns() {
    use crate::CellSplitArtifactCasOwnerV1;
    use crate::CellSplitCasFinalUsePortV1;
    use crate::CellSplitExecutionOwnerV1;
    use crate::CellSplitOwnerTrustV1;
    use std::io::ErrorKind;
    use std::os::unix::fs::PermissionsExt as _;

    #[derive(Clone)]
    struct CasFinalUse(Arc<AtomicBool>);
    impl CellSplitCasFinalUsePortV1 for CasFinalUse {
        type Error = &'static str;
        fn verify_current_authority(
            &mut self,
            plan: &CellSplitExecutionPlanV1,
            intent: &CellSplitExecutionIntentV1,
        ) -> Result<(), Self::Error> {
            if self.0.load(Ordering::Acquire) && plan.owner_ids[0] == intent.owner_id {
                Ok(())
            } else {
                Err("CAS owner final use denied")
            }
        }
    }

    let root = private_root();
    let cas_root = root.path().join("artifact-cas");
    let state_root = root.path().join("state-batch");
    let ledger = root.path().join("split-ledger");
    for dir in [&cas_root, &state_root, &ledger] {
        fs::create_dir(dir).expect("independent private owner root");
        fs::set_permissions(dir, fs::Permissions::from_mode(0o700))
            .expect("private owner permissions");
    }
    let parent = root.path().join("parent-artifact");
    let child = root.path().join("child-artifact");
    fs::write(&parent, b"real parent artifact").expect("parent bytes");
    fs::write(&child, b"real child artifact").expect("child bytes");
    for path in [&parent, &child] {
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))
            .expect("private input artifact");
    }

    let plan = execution_plan();
    let (migration, anchor) = prepared();
    let migration_auth = ObservedAuthority::new(anchor);
    let stop = Arc::new(AtomicBool::new(false));
    let cas_socket = root.path().join("cas.sock");
    let migration_socket = root.path().join("migration.sock");
    let cas_listener = UnixListener::bind(&cas_socket).expect("CAS socket");
    let state_listener = UnixListener::bind(&migration_socket).expect("migration socket");
    cas_listener.set_nonblocking(true).expect("CAS listener");
    state_listener
        .set_nonblocking(true)
        .expect("state listener");
    let plan_digest = sha256(&canonical_json(&plan).expect("frozen plan"));

    let cas_stop = stop.clone();
    let cas_plan = plan.clone();
    let cas_plan_digest = plan_digest.clone();
    let cas_root_copy = cas_root.clone();
    let cas_thread = thread::spawn(move || {
        let backend = CellSplitArtifactCasOwnerV1::open(
            &cas_root_copy,
            &parent,
            &child,
            cas_plan.clone(),
            CasFinalUse(Arc::new(AtomicBool::new(true))),
        )
        .expect("actual Artifact CAS");
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ArtifactCas,
            cas_plan.owner_ids[0].clone(),
            cas_plan_digest,
            SigningKey::from_bytes(&[1; 32]),
            backend,
        )
        .expect("CAS signer");
        while !cas_stop.load(Ordering::Acquire) {
            match cas_listener.accept() {
                Ok((mut stream, _)) => {
                    let _ = service.serve_connection(&mut stream);
                }
                Err(e) if e.kind() == ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(1));
                }
                Err(e) => panic!("CAS endpoint failure: {e}"),
            }
        }
    });
    let state_stop = stop.clone();
    let state_plan = plan.clone();
    let state_migration = migration.clone();
    let state_auth = migration_auth.clone();
    let state_root_copy = state_root.clone();
    let state_thread = thread::spawn(move || {
        let backend = CellSplitChildStateCasOwnerV1::open(
            &state_root_copy,
            state_plan.clone(),
            state_migration,
            state_auth,
        )
        .expect("typed migration owner");
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::ChildStateMigration,
            state_plan.owner_ids[1].clone(),
            sha256(&canonical_json(&state_plan).expect("frozen state plan")),
            SigningKey::from_bytes(&[2; 32]),
            backend,
        )
        .expect("independent migration signer");
        while !state_stop.load(Ordering::Acquire) {
            match state_listener.accept() {
                Ok((mut stream, _)) => {
                    let _ = service.serve_connection(&mut stream);
                }
                Err(e) if e.kind() == ErrorKind::WouldBlock => {
                    thread::sleep(Duration::from_millis(1));
                }
                Err(e) => panic!("migration endpoint failure: {e}"),
            }
        }
    });
    let keys = [1_u8, 2, 3, 4].map(|n| SigningKey::from_bytes(&[n; 32]).verifying_key());
    let endpoints = [
        cas_socket,
        migration_socket,
        root.path().join("missing-cns.sock"),
        root.path().join("missing-supervisor.sock"),
    ];
    let trust = CellSplitOwnerTrustV1::new(&plan, keys.clone())
        .expect("four distinct pinned owner identities");
    let migration_receipt;
    {
        let client =
            CellSplitUnixEffectPortV1::new(endpoints.clone(), keys.clone(), Duration::from_secs(3))
                .expect("four owner connections");
        let mut coordinator =
            CellSplitExecutionOwnerV1::open(&ledger, plan.clone(), trust.clone(), client)
                .expect("frozen coordinator");
        let artifact = coordinator.advance().expect("real CAS").expect("step zero");
        assert_eq!(artifact.intent.step, CellSplitExecutionStepV1::ArtifactCas);
        assert_eq!(coordinator.completed_steps(), 1);
        *migration_auth
            .exact_cas_receipt
            .lock()
            .expect("CAS witness") = artifact.receipt_digest.clone();
        let state = coordinator
            .advance()
            .expect("durable child migration")
            .expect("step one");
        assert_eq!(
            state.intent.step,
            CellSplitExecutionStepV1::ChildStateMigration
        );
        migration_receipt = state.clone();
        assert_eq!(
            state.intent.previous_receipt_digest,
            artifact.receipt_digest
        );
        assert_eq!(coordinator.completed_steps(), 2);
        assert!(
            coordinator.advance().is_err(),
            "no CNS owner, no route cutover"
        );
        assert!(!coordinator.is_complete());
    }
    assert!(
        cas_root
            .join(format!("sha256-{}", plan.child_artifact_digest))
            .exists(),
        "actual immutable artifact was published"
    );
    for (index, state) in migration.children().iter().enumerate() {
        let path = state_root.join(format!(
            "child-{}-{index:02}-{}.q24",
            migration_receipt.intent.idempotency_key,
            CellStateMigrationV1::child_payload_digest(state),
        ));
        assert_eq!(
            fs::read(path).expect("physically committed state"),
            encode_cell_state_v1(state)
        );
    }
    {
        let client =
            CellSplitUnixEffectPortV1::new(endpoints.clone(), keys.clone(), Duration::from_secs(3))
                .expect("reopened transport");
        let mut coordinator =
            CellSplitExecutionOwnerV1::open(&ledger, plan.clone(), trust.clone(), client)
                .expect("read two real current owner receipts");
        assert_eq!(coordinator.completed_steps(), 2);
        assert!(coordinator.advance().is_err(), "missing CNS is ambiguous");
    }
    let corrupt = state_root.join(format!(
        "child-{}-{:02}-{}.q24",
        migration_receipt.intent.idempotency_key,
        0,
        CellStateMigrationV1::child_payload_digest(&migration.children()[0]),
    ));
    fs::write(corrupt, b"tampered after committed batch").expect("external corruption");
    let client = CellSplitUnixEffectPortV1::new(endpoints, keys, Duration::from_secs(3))
        .expect("readback client");
    assert!(
        CellSplitExecutionOwnerV1::open(&ledger, plan, trust, client).is_err(),
        "a stale migration readback must fail closed"
    );
    stop.store(true, Ordering::Release);
    cas_thread.join().expect("CAS server");
    state_thread.join().expect("migration server");
}

#[test]
fn frozen_projected_input_tamper_is_denied_without_publishing_children() {
    let root = private_root();
    let (migration, anchor) = prepared();
    let auth = ObservedAuthority::new(anchor);
    let request = operation(&execution_plan());
    let mut batch = owner(root.path(), migration.clone(), auth.clone());
    let path = root.path().join("migration-frozen-input.json");
    let original = fs::read(&path).expect("frozen original projection");
    assert!(!original.is_empty());
    fs::write(&path, b"alternate state substituted").expect("out-of-band change");
    assert!(batch.authorize_execute(&request).is_err());
    assert!(batch.read_committed(&request).is_err());
    assert!(!batch.commit_path(&request).exists());
    drop(batch);
    assert!(owner_try_reopen(root.path(), migration, auth).is_err());
}
