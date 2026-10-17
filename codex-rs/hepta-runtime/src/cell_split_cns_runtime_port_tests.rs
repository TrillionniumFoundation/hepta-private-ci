use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt as _;
use std::str::FromStr as _;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_control_plane::NduPublicationOwnerV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimePortV1;
use codex_hepta_paths::HeptaStateRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::NduSnapshotRefV1;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use sha2::Sha256;

use crate::RuntimeStateAdapter;
use crate::RuntimeStateStatus;

use super::*;

#[derive(Debug)]
struct ReadOnlyState;

impl RuntimeStateAdapter for ReadOnlyState {
    fn status(&self) -> RuntimeStateStatus {
        RuntimeStateStatus {
            adapter: "cns-port-fixture",
            schema_version: 5,
            outcome_generation: 1,
            preference_generation: 1,
            runtime_snapshot_version: 1,
            runtime_snapshot_generation: 1,
            integrity_binding_present: true,
            integrity_verification: "test-only",
            open_mode: "read-only-test",
        }
    }
}

/// Test-only witness. Unlike the production protocol it has no mutation
/// authority, and it must NEVER return an admitted successor or positive
/// original commit.
struct DenyingWitness {
    _authority_root: tempfile::TempDir,
    signer: SigningKey,
    stale_nonce: bool,
    deny_authority: bool,
    signed_history: Option<CellSplitCnsRuntimeCommitV1>,
    durable_sequence: u64,
}

impl CellSplitCnsKernelWitnessV1 for DenyingWitness {
    type Error = &'static str;

    fn verify_preconditions(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        if self.deny_authority {
            Err("independent NDU/Selector denied")
        } else {
            Ok(())
        }
    }

    fn signed_current_route(
        &mut self,
        runtime: &RuntimeTopologySnapshotV1,
        nonce: &str,
    ) -> Result<CellSplitCnsLiveRouteV1, Self::Error> {
        let observed_nonce = if self.stale_nonce {
            "00".repeat(32)
        } else {
            nonce.to_owned()
        };
        let mut observation = CellSplitCnsLiveRouteV1 {
            cns_id: runtime.cns_id().to_string(),
            scope_digest: "11".repeat(32),
            generation: runtime.generation().get(),
            artifact_digest: "22".repeat(32),
            route_digest: runtime.hierarchy_digest().to_string(),
            route_fence_digest: "55".repeat(32),
            authority_epoch: 7,
            old_writer_fenced: true,
            unknown_effect_count: 0,
            challenge_nonce: observed_nonce,
            live_runtime_proof_bytes: Vec::new(),
        };
        observation.live_runtime_proof_bytes = self
            .signer
            .sign(
                &cell_split_cns_live_route_signing_bytes_v1(&observation).expect("canonical route"),
            )
            .to_bytes()
            .to_vec();
        Ok(observation)
    }

    fn take_admitted_successor(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _binding: &CellSplitCnsRouteBindingV1,
        _intent: &CellSplitExecutionIntentV1,
    ) -> Result<(SignedFinalUseGrant, RuntimeTopologyApplyRequestV1), Self::Error> {
        Err("no signed final-use grant and admitted runtime candidate")
    }

    fn persist_actual_runtime_receipt(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _binding: &CellSplitCnsRouteBindingV1,
        _intent: &CellSplitExecutionIntentV1,
        _actual: &RuntimeTopologyApplyReceiptV1,
    ) -> Result<(), Self::Error> {
        Err("never persist a synthetic runtime receipt")
    }

    fn read_original_commit(
        &mut self,
        _key: &str,
    ) -> Result<Option<CellSplitCnsRuntimeCommitV1>, Self::Error> {
        Ok(self.signed_history.clone())
    }

    fn current_durable_sequence(&mut self, _cns_id: &str) -> Result<u64, Self::Error> {
        Ok(self.durable_sequence)
    }
}

fn fixture(
    stale_nonce: bool,
    deny_authority: bool,
    trusted_key: SigningKey,
    actual_key: SigningKey,
) -> (
    HeptaRuntime,
    CellSplitExecutionPlanV1,
    CellSplitCnsRouteBindingV1,
    CellSplitExecutionIntentV1,
    CellSplitCnsKernelRuntimePortV1<DenyingWitness>,
) {
    let root = HeptaStateRoot::parse(std::env::temp_dir().join("hepta-cell-split-live-cns-port"))
        .expect("runtime state root");
    let runtime = HeptaRuntime::from_adapter(root, Arc::new(ReadOnlyState));
    let current = runtime.topology_snapshot().expect("actual current CNS");
    let plan = CellSplitExecutionPlanV1 {
        split_id: "split.cns.live".into(),
        scope_digest: "11".repeat(32),
        parent_generation: current.generation().get(),
        child_generation: current.generation().get() + 1,
        parent_artifact_digest: "22".repeat(32),
        child_artifact_digest: "33".repeat(32),
        ndu_snapshot_digest: "44".repeat(32),
        route_fence_digest: "55".repeat(32),
        owner_ids: [
            "cas-owner".into(),
            "migration-owner".into(),
            "cns-owner".into(),
            "supervisor-owner".into(),
        ],
    };
    let binding = CellSplitCnsRouteBindingV1 {
        cns_id: current.cns_id().to_string(),
        predecessor_route_digest: current.hierarchy_digest().to_string(),
        successor_route_digest: "aa".repeat(32),
        authority_epoch: 7,
    };
    let predecessor = "77".repeat(32);
    let plan_digest = plan.digest().expect("frozen plan");
    let idempotency_key = format!(
        "{:x}",
        Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                plan_digest,
                CellSplitExecutionStepV1::CnsRouteCutover.index(),
                predecessor,
            )
            .as_bytes()
        ),
    );
    let intent = CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest,
        step: CellSplitExecutionStepV1::CnsRouteCutover,
        owner_id: "cns-owner".into(),
        idempotency_key,
        previous_receipt_digest: predecessor,
    };
    let private = tempfile::tempdir().expect("private final-use state");
    std::fs::set_permissions(private.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private authority directory");
    let pinned_authority = Arc::new(
        FinalUseAuthority::open_state_dir(
            private.path(),
            "cns-port-independent-test-issuer".to_owned(),
            SigningKey::from_bytes(&[55; 32]).verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("independent fixed verifier"),
    );
    let port = CellSplitCnsKernelRuntimePortV1::new(
        runtime.clone(),
        pinned_authority,
        plan.clone(),
        binding.clone(),
        intent.clone(),
        trusted_key.verifying_key(),
        DenyingWitness {
            _authority_root: private,
            signer: actual_key,
            stale_nonce,
            deny_authority,
            signed_history: None,
            durable_sequence: 1,
        },
    )
    .expect("CNS runtime bridge");
    (runtime, plan, binding, intent, port)
}

#[derive(Clone, Copy)]
enum IndependentControlWitnessFault {
    None,
    ReplayedChallenge,
    WrongStoredSequence,
    WrongScope,
    WrongPlan,
    CorruptedSignature,
}

/// This mock signs a privately retained test snapshot. Crucially its runtime
/// port receives ONLY split/scope/challenge, never the local WAL contents.
struct IndependentControlWitnessFixture {
    stored: NduPublicationLocalFrontierV1,
    signer: SigningKey,
    plan_digest: String,
    observer_id: String,
    fault: IndependentControlWitnessFault,
}

impl CellSplitIndependentControlObserverV1 for IndependentControlWitnessFixture {
    type Error = &'static str;

    fn read_signed_highwater(
        &mut self,
        split_id: &str,
        _scope_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSignedControlHighwaterV1, Self::Error> {
        let s = &self.stored.snapshot;
        let mut proof = CellSplitSignedControlHighwaterV1 {
            schema: CELL_SPLIT_SIGNED_CONTROL_HIGHWATER_SCHEMA_V1.into(),
            observer_id: self.observer_id.clone(),
            plan_digest: self.plan_digest.clone(),
            split_id: split_id.into(),
            scope_id: s.scope_id.to_string(),
            ndu_owner_id: s.owner_id.to_string(),
            ndu_snapshot_digest: s.snapshot_digest.to_string(),
            generation: s.generation.get(),
            route_fence: s.route_fence,
            revocation_epoch: s.revocation_epoch,
            sequence: self.stored.sequence,
            wal_head: self.stored.head.to_string(),
            checkpoint_digest: self.stored.checkpoint.to_string(),
            wal_bytes: self.stored.wal_bytes,
            wal_device: self.stored.wal_device,
            wal_inode: self.stored.wal_inode,
            marker_device: self.stored.marker_device,
            marker_inode: self.stored.marker_inode,
            original_cns_receipt_binding: self
                .stored
                .original_cns_receipt_binding
                .map(|digest| digest.to_string()),
            challenge_nonce: challenge_nonce.to_owned(),
            observer_signature_bytes: Vec::new(),
        };
        match self.fault {
            IndependentControlWitnessFault::None
            | IndependentControlWitnessFault::CorruptedSignature => {}
            IndependentControlWitnessFault::ReplayedChallenge => {
                proof.challenge_nonce = "00".repeat(32);
            }
            IndependentControlWitnessFault::WrongStoredSequence => {
                proof.sequence += 1;
            }
            IndependentControlWitnessFault::WrongScope => {
                proof.scope_id = "another-unrelated-scope".into();
            }
            IndependentControlWitnessFault::WrongPlan => {
                proof.plan_digest = "ee".repeat(32);
            }
        }
        proof.observer_signature_bytes = self
            .signer
            .sign(
                &cell_split_control_highwater_signing_bytes_v1(&proof)
                    .expect("canonical external Observer payload"),
            )
            .to_bytes()
            .to_vec();
        if matches!(
            self.fault,
            IndependentControlWitnessFault::CorruptedSignature
        ) {
            proof.observer_signature_bytes[0] ^= 1;
        }
        Ok(proof)
    }
}

fn independent_control_snapshot(plan: &CellSplitExecutionPlanV1) -> NduSnapshotRefV1 {
    NduSnapshotRefV1 {
        scope_id: StableId::new("observed-scope").expect("stable scope"),
        owner_id: StableId::new("original-control-owner").expect("stable owner"),
        generation: Generation::new(3).expect("generation"),
        route_fence: 7,
        revocation_epoch: 9,
        policy_digest: Digest32::of_bytes(b"control-observer-policy"),
        snapshot_digest: Digest32::from_str(&plan.ndu_snapshot_digest)
            .expect("frozen plan has canonical NDU digest"),
        projection_head_digest: Digest32::of_bytes(b"control-observer-projection"),
    }
}

#[test]
fn direct_original_cns_receipt_refuses_replay_after_durable_frontier_advance() {
    let signer = SigningKey::from_bytes(&[42; 32]);
    let (runtime, plan, binding, intent, mut port) =
        fixture(false, true, signer.clone(), signer.clone());
    let before = runtime.topology_snapshot().expect("original serving runtime");
    // A synthetic historically signed record exercises verification ONLY;
    // this fixture never runs a physical cutover or creates Control Commit.
    let mut historical = CellSplitCnsRuntimeCommitV1 {
        idempotency_key: intent.idempotency_key.clone(),
        cns_id: binding.cns_id.clone(),
        predecessor_route_digest: binding.predecessor_route_digest.clone(),
        successor_route_digest: binding.successor_route_digest.clone(),
        predecessor_generation: plan.parent_generation,
        successor_generation: plan.child_generation,
        authority_epoch: binding.authority_epoch,
        committed_sequence: 11,
        original_runtime_receipt_bytes: Vec::new(),
        original_runtime_signature_bytes: Vec::new(),
    };
    let bytes = CellSplitCnsRuntimeAttestationV1::for_commit(&plan, &historical)
        .canonical_bytes()
        .expect("canonical historical attestation");
    historical.original_runtime_signature_bytes = signer.sign(&bytes).to_bytes().to_vec();
    historical.original_runtime_receipt_bytes = bytes;
    port.witness.signed_history = Some(historical.clone());

    port.witness.durable_sequence = 12;
    assert!(
        port.verify_original_commit(&historical).is_err(),
        "a newer original CNS revision must fence even a valid old signature"
    );
    port.witness.durable_sequence = 11;
    assert!(
        port.verify_original_commit(&historical).is_ok(),
        "same original revision authenticates the historical record only"
    );
    assert_eq!(
        runtime.topology_snapshot().expect("unchanged serving host"),
        before
    );
}

#[test]
fn independent_control_observer_uses_fresh_signed_original_highwater_without_mutation() {
    let runtime_signer = SigningKey::from_bytes(&[42; 32]);
    let (_runtime, plan, _binding, _intent, mut port) =
        fixture(false, true, runtime_signer.clone(), runtime_signer.clone());
    let root = tempfile::tempdir().expect("private Control test directory");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private test Control root");
    let path = root.path().join("original-control.wal");
    let snapshot = independent_control_snapshot(&plan);
    let checkpoint = Digest32::of_bytes(b"initial-verified-model-checkpoint");
    let control = NduPublicationOwnerV1::open_production(&path, snapshot.clone(), checkpoint)
        .expect("actual original signed Control journal");
    let original_wal = std::fs::read(&path).expect("fsynced original WAL");
    let signed_owner = SigningKey::from_bytes(&[77; 32]);
    let observer_key = signed_owner.verifying_key();
    let mut observer = IndependentControlWitnessFixture {
        stored: control
            .read_original_local_frontier_v1()
            .expect("real original WAL replay"),
        signer: signed_owner,
        plan_digest: plan.digest().unwrap(),
        observer_id: "separate-control-observer".into(),
        fault: IndependentControlWitnessFault::None,
    };
    assert_eq!(
        port.verify_independent_control_highwater_v1(
            &control,
            &mut observer,
            &observer_key,
            "separate-control-observer",
        ),
        Ok(()),
        "matching independent signed high-water qualifies read-only evidence"
    );
    assert_eq!(std::fs::read(&path).unwrap(), original_wal);

    // Two independently fsynced Control frontiers may carry the SAME NDU
    // snapshot while model checkpoint CAS advances the original WAL.
    control
        .compare_and_publish_checkpoint(
            &snapshot,
            Digest32::of_bytes(b"fresh-read"),
            Digest32::of_bytes(b"verified-tick"),
            checkpoint,
            Digest32::of_bytes(b"new-checkpoint"),
        )
        .expect("real original journal commit");
    assert!(
        port.verify_independent_control_highwater_v1(
            &control,
            &mut observer,
            &observer_key,
            "separate-control-observer",
        )
        .is_err(),
        "an old signed high-water must not bless newer/rolled-back Control state"
    );
    assert!(
        control.current().is_ok(),
        "Observer denial cannot mutate Control"
    );
}

#[test]
fn independent_control_observer_rejects_replayed_nonce_wrong_scope_or_forged_signer() {
    let runtime_signer = SigningKey::from_bytes(&[42; 32]);
    let (_runtime, plan, _binding, _intent, mut port) =
        fixture(false, true, runtime_signer.clone(), runtime_signer.clone());
    let root = tempfile::tempdir().expect("private Control test directory");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private Control fixture");
    let path = root.path().join("observer-negative.wal");
    let control = NduPublicationOwnerV1::open_production(
        &path,
        independent_control_snapshot(&plan),
        Digest32::of_bytes(b"verified-checkpoint"),
    )
    .expect("original Control fixture");
    let observer_signer = SigningKey::from_bytes(&[77; 32]);
    let pin = observer_signer.verifying_key();
    let mut observer = IndependentControlWitnessFixture {
        stored: control.read_original_local_frontier_v1().unwrap(),
        signer: observer_signer,
        plan_digest: plan.digest().unwrap(),
        observer_id: "separate-control-observer".into(),
        fault: IndependentControlWitnessFault::None,
    };
    assert!(
        port.verify_independent_control_highwater_v1(
            &control,
            &mut observer,
            &runtime_signer.verifying_key(),
            "separate-control-observer"
        )
        .is_err(),
        "CNS signer must never double as independent Observer"
    );
    assert!(
        port.verify_independent_control_highwater_v1(
            &control,
            &mut observer,
            &SigningKey::from_bytes(&[99; 32]).verifying_key(),
            "separate-control-observer"
        )
        .is_err(),
        "untrusted signer must never qualify original Control WAL"
    );
    for fault in [
        IndependentControlWitnessFault::ReplayedChallenge,
        IndependentControlWitnessFault::WrongStoredSequence,
        IndependentControlWitnessFault::WrongScope,
        IndependentControlWitnessFault::WrongPlan,
        IndependentControlWitnessFault::CorruptedSignature,
    ] {
        observer.fault = fault;
        assert!(
            port.verify_independent_control_highwater_v1(
                &control,
                &mut observer,
                &pin,
                "separate-control-observer"
            )
            .is_err(),
            "signed but stale, replayed or malformed external high-water denied"
        );
    }
    assert!(control.current().is_ok());
}

/// An original CNS commit must be authenticated before any remote high-water
/// request. The test port has no signer and deliberately cannot produce a
/// positive proof, so this fixture cannot mint mutation or Observer authority.
struct JoinedControlObserverProbe {
    calls: usize,
}

impl CellSplitIndependentControlObserverV1 for JoinedControlObserverProbe {
    type Error = &'static str;

    fn read_signed_highwater(
        &mut self,
        _split_id: &str,
        _scope_id: &str,
        _challenge_nonce: &str,
    ) -> Result<CellSplitSignedControlHighwaterV1, Self::Error> {
        self.calls += 1;
        Err("untrusted Observer must never be queried before original CNS proof")
    }
}

#[test]
fn joined_cns_control_observer_denies_missing_original_commit_before_remote_rpc() {
    let runtime_signer = SigningKey::from_bytes(&[42; 32]);
    let (runtime, plan, _binding, _intent, mut port) =
        fixture(false, false, runtime_signer.clone(), runtime_signer);
    let root = tempfile::tempdir().expect("private original Control WAL root");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("Control root must stay private");
    let path = root.path().join("joined-original.wal");
    let control = NduPublicationOwnerV1::open_production(
        &path,
        independent_control_snapshot(&plan),
        Digest32::of_bytes(b"joined-original-checkpoint"),
    )
    .expect("real original Control WAL writer");
    let state_before = runtime.topology_snapshot().expect("original serving route");
    let original_bytes = std::fs::read(&path).expect("fsynced original Control history");
    let before = control.read_original_local_frontier_v1().unwrap();
    let mut observer = JoinedControlObserverProbe { calls: 0 };
    let pinned = SigningKey::from_bytes(&[77; 32]).verifying_key();
    let denial = port
        .verify_original_cns_control_independent_highwater_join_v1(
            &control,
            &mut observer,
            &pinned,
            "separate-control-observer",
        )
        .expect_err("original CNS runtime commit must exist before remote Observer");
    assert!(denial.contains("original durable effect receipt is missing"));
    assert_eq!(
        observer.calls, 0,
        "never query remote on missing original effect"
    );
    assert_eq!(std::fs::read(&path).unwrap(), original_bytes);
    assert_eq!(control.read_original_local_frontier_v1().unwrap(), before);
    assert_eq!(runtime.topology_snapshot().unwrap(), state_before);
}

#[test]
fn joined_cns_control_observer_denies_missing_original_wal_before_remote_rpc() {
    let runtime_signer = SigningKey::from_bytes(&[42; 32]);
    let (_runtime, plan, _binding, _intent, mut port) =
        fixture(false, false, runtime_signer.clone(), runtime_signer);
    let root = tempfile::tempdir().expect("private original Control root");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("Control root must stay private");
    let path = root.path().join("missing-original.wal");
    let control = NduPublicationOwnerV1::open_production(
        &path,
        independent_control_snapshot(&plan),
        Digest32::of_bytes(b"joined-missing-checkpoint"),
    )
    .expect("real fsynced Control root");
    assert!(control.read_original_local_frontier_v1().is_ok());
    std::fs::remove_file(&path).expect("simulate lost original WAL inode path");
    let mut observer = JoinedControlObserverProbe { calls: 0 };
    let pinned = SigningKey::from_bytes(&[77; 32]).verifying_key();
    let denial = port
        .verify_original_cns_control_independent_highwater_join_v1(
            &control,
            &mut observer,
            &pinned,
            "separate-control-observer",
        )
        .expect_err("a missing original WAL must deny before any remote claim");
    assert!(denial.contains("original Control WAL unavailable before join"));
    assert_eq!(observer.calls, 0);
    assert!(control.read_original_local_frontier_v1().is_err());
    assert!(
        !path.exists(),
        "read-only verification must not rebootstrap WAL"
    );
}

#[test]
fn signed_fresh_readback_is_checked_against_actual_runtime_host() {
    let key = SigningKey::from_bytes(&[42; 32]);
    let (runtime, plan, binding, intent, mut port) = fixture(false, true, key.clone(), key);
    let challenge = "bb".repeat(32);
    let original = runtime.topology_snapshot().expect("original CNS");
    let live = port
        .inspect_live(&binding.cns_id, &plan.scope_digest, &challenge)
        .expect("real host challenge");
    assert_eq!(live.route_digest, original.hierarchy_digest().to_string());
    port.verify_live(&live).expect("signed current runtime");
    let mut tampered = live.clone();
    tampered.artifact_digest = "ff".repeat(32);
    assert!(port.verify_live(&tampered).is_err());
    assert!(port.publish_once(&plan, &binding, &intent).is_err());
    assert_eq!(
        runtime
            .topology_snapshot()
            .expect("no authorized transition"),
        original,
    );
    assert!(
        port.read_original_commit(&intent.idempotency_key)
            .unwrap()
            .is_none()
    );
}

#[test]
fn stale_nonce_and_wrong_runtime_signer_fail_before_any_cutover() {
    let trusted = SigningKey::from_bytes(&[43; 32]);
    let (_, plan, binding, _, mut stale) = fixture(true, false, trusted.clone(), trusted.clone());
    assert!(
        stale
            .inspect_live(&binding.cns_id, &plan.scope_digest, &"cd".repeat(32))
            .is_err()
    );
    let (_, plan, binding, _, mut forged) =
        fixture(false, false, trusted, SigningKey::from_bytes(&[44; 32]));
    assert!(
        forged
            .inspect_live(&binding.cns_id, &plan.scope_digest, &"ab".repeat(32))
            .is_err()
    );
}

#[test]
fn preflight_pass_without_signed_successor_cannot_mutate_real_runtime() {
    let key = SigningKey::from_bytes(&[45; 32]);
    let (runtime, plan, binding, intent, mut port) = fixture(false, false, key.clone(), key);
    let before = runtime.topology_snapshot().expect("serving CNS");
    port.verify_preconditions(&plan, &intent)
        .expect("preflight allowed");
    assert!(
        port.publish_once(&plan, &binding, &intent).is_err(),
        "missing independently signed final-use grant must stop cutover",
    );
    assert_eq!(
        runtime
            .topology_snapshot()
            .expect("still serving predecessor"),
        before,
    );
    assert!(
        port.read_original_commit(&intent.idempotency_key)
            .unwrap()
            .is_none()
    );
}

#[test]
fn signed_live_route_and_positive_preflight_cannot_bypass_unbound_control_cutover_owner() {
    let key = SigningKey::from_bytes(&[52; 32]);
    let (runtime, plan, binding, intent, mut port) = fixture(false, false, key.clone(), key);
    let before = runtime
        .topology_snapshot()
        .expect("actual live predecessor");
    let route = port
        .inspect_live(&binding.cns_id, &plan.scope_digest, &"ab".repeat(32))
        .expect("signed route is independently observable");
    port.verify_live(&route).expect("valid signed read");
    port.verify_preconditions(&plan, &intent)
        .expect("separate preliminary admission");
    let denial = port
        .publish_once(&plan, &binding, &intent)
        .expect_err("no independent same-owner Control cutover transaction");
    assert!(
        denial.contains("no shared durable Control/Neuron cutover transaction"),
        "a good signature or preflight must not enable physical CNS dispatch"
    );
    assert_eq!(
        runtime.topology_snapshot().expect("serving state"),
        before,
        "no irreversible topology mutation may occur"
    );
    assert!(
        port.read_original_commit(&intent.idempotency_key)
            .expect("read-only original commit")
            .is_none()
    );
}

#[test]
#[allow(deprecated)]
fn signed_cns_and_control_commit_join_cannot_accept_opaque_wal_without_original_owner() {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::NduSnapshotRefV1;
    use codex_hepta_types::StableId;

    let signer = SigningKey::from_bytes(&[57; 32]);
    let (runtime, _plan, _binding, _intent, mut port) =
        fixture(false, false, signer.clone(), signer);
    let before = runtime.topology_snapshot().expect("serving predecessor");

    let root = tempfile::tempdir().expect("independent Control state");
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private Control directory");
    let frozen = NduSnapshotRefV1 {
        scope_id: StableId::new("scope-cns-control").expect("scope"),
        owner_id: StableId::new("ndu-owner").expect("owner"),
        generation: Generation::new(1).expect("generation"),
        route_fence: 1,
        revocation_epoch: 1,
        policy_digest: Digest32::of_bytes(b"policy"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        projection_head_digest: Digest32::of_bytes(b"projection"),
    };
    let path = root.path().join("control-ledger.wal");
    let control = NduPublicationOwnerV1::open_production(&path, frozen.clone(), Digest32::ZERO)
        .expect("durable Control owner");
    assert!(
        port.verify_original_cns_control_commit_v1(&control)
            .expect_err("no independently signed CNS receipt")
            .contains("original durable effect receipt is missing")
    );

    // The public Control interface must not accept a caller-controlled
    // callback that can manufacture unsigned CNS success. The legacy direct
    // route writer remains denied without a signed original-owner adapter.
    let mut next = frozen.clone();
    next.route_fence += 1;
    assert_eq!(
        control.publish_cutover(
            &frozen,
            Digest32::ZERO,
            next,
            Digest32::of_bytes(b"fixture-migrated"),
        ),
        Err(codex_hepta_control_plane::NduPublicationErrorV1::Unsupported)
    );
    assert_eq!(
        control
            .last_cns_original_receipt_binding()
            .expect("read-only Control frontier"),
        None
    );
    assert_eq!(
        control.verify_original_cns_receipt_binding(&[0x6f; 96]),
        Err(codex_hepta_control_plane::NduPublicationErrorV1::Stale)
    );
    assert!(
        port.verify_original_cns_control_commit_v1(&control)
            .expect_err("unsigned Control bytes cannot mint an original CNS effect")
            .contains("original durable effect receipt is missing")
    );
    assert_eq!(
        runtime
            .topology_snapshot()
            .expect("unchanged serving predecessor"),
        before
    );
}

#[test]
fn typed_cell_split_cutover_rejects_generic_non_split_mutations() {
    use codex_hepta_plasticity::TopologyCandidateKindV2;
    use codex_hepta_plasticity::TopologyCandidateV2;
    use codex_hepta_plasticity::TopologyChangeV2;
    use codex_hepta_plasticity::TopologyOperationV2;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    let evidence = Digest32::of_bytes(b"typed-cell-split-evidence");
    let split_change = TopologyChangeV2 {
        module_id: StableId::new("organ.cell.split").expect("organ"),
        operation: TopologyOperationV2::Split,
        predecessor_digest: Some(evidence),
        candidate_digest: Some(evidence),
        capability_typing_digest: evidence,
        compatibility_plan_digest: evidence,
        lesion_ablation_digest: evidence,
        resource_review_digest: evidence,
        security_review_digest: evidence,
        migration_digest: evidence,
        rollback_digest: evidence,
        writer_handoff_digest: evidence,
        evidence_digest: evidence,
    };
    let typed = TopologyCandidateV2 {
        candidate_id: StableId::new("candidate.split").expect("candidate"),
        kind: TopologyCandidateKindV2::Update,
        changes: vec![split_change.clone()],
    };
    assert!(is_typed_cell_split_candidate_v1(&typed));

    let mut replacement = typed.clone();
    replacement.changes[0].operation = TopologyOperationV2::Replace;
    assert!(!is_typed_cell_split_candidate_v1(&replacement));

    let mut rewire = typed.clone();
    rewire.changes[0].operation = TopologyOperationV2::Rewire;
    assert!(!is_typed_cell_split_candidate_v1(&rewire));

    let mut no_change = typed.clone();
    no_change.kind = TopologyCandidateKindV2::NoChange;
    assert!(!is_typed_cell_split_candidate_v1(&no_change));

    let mut multiple = typed;
    multiple.changes.push(split_change);
    assert!(!is_typed_cell_split_candidate_v1(&multiple));
}
