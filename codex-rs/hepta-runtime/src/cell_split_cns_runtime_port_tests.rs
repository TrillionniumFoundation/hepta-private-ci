use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt as _;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimePortV1;
use codex_hepta_paths::HeptaStateRoot;
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
        Ok(None)
    }

    fn current_durable_sequence(&mut self, _cns_id: &str) -> Result<u64, Self::Error> {
        Ok(1)
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
        },
    )
    .expect("CNS runtime bridge");
    (runtime, plan, binding, intent, port)
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
fn valid_signed_live_route_cannot_bypass_missing_same_owner_control_prepare() {
    let key = SigningKey::from_bytes(&[52; 32]);
    let (runtime, plan, binding, intent, mut port) = fixture(false, false, key.clone(), key);
    let before = runtime.topology_snapshot().expect("actual predecessor");
    let signed = port
        .inspect_live(&binding.cns_id, &plan.scope_digest, &"ab".repeat(32))
        .expect("genuine signed current route");
    port.verify_live(&signed).expect("valid original signature");
    port.verify_preconditions(&plan, &intent)
        .expect("positive independent preflight");
    let denied = port
        .publish_once(&plan, &binding, &intent)
        .expect_err("Control did not durably prepare same-owner cutover");
    assert!(denied.contains("no shared durable Control/Neuron cutover transaction"));
    assert_eq!(
        runtime
            .topology_snapshot()
            .expect("unchanged serving route"),
        before,
        "a signed live readback cannot replace a Control transaction"
    );
    assert!(
        port.read_original_commit(&intent.idempotency_key)
            .expect("read original durable commit")
            .is_none(),
        "denied physical cutover cannot mint a positive commit receipt"
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
