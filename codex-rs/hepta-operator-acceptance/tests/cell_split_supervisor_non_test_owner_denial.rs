#![cfg(unix)]
#![allow(
    clippy::expect_used,
    reason = "external native product-denial fixture must surface setup failures"
)]

// Normal external Cargo integration tests link the non-cfg(test) library.
// An arbitrary generic Supervisor trait implementation must not cause a
// retirement without the original shared Control B/C and CNS signed effect.
use std::os::unix::fs::PermissionsExt as _;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_operator_acceptance::CellSplitDurableEffectBackendV1;
use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorCommitV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorFenceBindingV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorFenceErrorV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorFenceOwnerV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorLiveFenceV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorPhaseV1;
use codex_hepta_operator_acceptance::CellSplitSupervisorRuntimePortV1;
use sha2::Digest as _;
use sha2::Sha256;

struct CallerSelectedSupervisor {
    callbacks: Arc<AtomicUsize>,
    retirements: Arc<AtomicUsize>,
}

impl CallerSelectedSupervisor {
    fn touched(&self) {
        self.callbacks.fetch_add(1, Ordering::SeqCst);
    }
}

impl CellSplitSupervisorRuntimePortV1 for CallerSelectedSupervisor {
    type Error = &'static str;

    fn verify_preconditions(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _intent: &CellSplitExecutionIntentV1,
        _binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), Self::Error> {
        self.touched();
        Ok(())
    }

    fn read_live(
        &mut self,
        _supervisor_id: &str,
        _domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorLiveFenceV1, Self::Error> {
        self.touched();
        Ok(CellSplitSupervisorLiveFenceV1 {
            supervisor_id: "supervisor.main".into(),
            domain_id: "scope.domain".into(),
            old_generation: 3,
            new_generation: 4,
            authority_epoch: 7,
            route_fence_digest: "55".repeat(32),
            handoff_plan_digest: "66".repeat(32),
            phase: CellSplitSupervisorPhaseV1::RoutePublished,
            old_writer_admission_closed: true,
            old_writer_result_fenced: true,
            new_writer_admission_open: true,
            unknown_effect_count: 0,
            current_revision: 8,
            challenge_nonce: challenge_nonce.to_owned(),
            // Caller-selected bytes are not an original Supervisor signature.
            signed_live_checkpoint_bytes: vec![0x53; 96],
        })
    }

    fn verify_live(&mut self, _live: &CellSplitSupervisorLiveFenceV1) -> Result<(), Self::Error> {
        self.touched();
        Ok(())
    }

    fn finalize_once(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _intent: &CellSplitExecutionIntentV1,
        _binding: &CellSplitSupervisorFenceBindingV1,
    ) -> Result<(), Self::Error> {
        self.touched();
        self.retirements.fetch_add(1, Ordering::SeqCst);
        // This arbitrary trait object would falsely report an actual
        // Supervisor finalization if the generic product owner called it.
        Ok(())
    }

    fn read_original_commit(
        &mut self,
        _idempotency_key: &str,
    ) -> Result<Option<CellSplitSupervisorCommitV1>, Self::Error> {
        self.touched();
        Ok(None)
    }

    fn verify_original_commit(
        &mut self,
        _receipt: &CellSplitSupervisorCommitV1,
    ) -> Result<(), Self::Error> {
        self.touched();
        Ok(())
    }

    fn durable_revision(&mut self, _supervisor_id: &str) -> Result<u64, Self::Error> {
        self.touched();
        Ok(8)
    }
}

fn frozen_plan() -> CellSplitExecutionPlanV1 {
    CellSplitExecutionPlanV1 {
        split_id: "split.generic.supervisor".into(),
        scope_digest: "11".repeat(32),
        parent_generation: 3,
        child_generation: 4,
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
    }
}

fn frozen_binding() -> CellSplitSupervisorFenceBindingV1 {
    CellSplitSupervisorFenceBindingV1 {
        supervisor_id: "supervisor.main".into(),
        domain_id: "scope.domain".into(),
        authority_epoch: 7,
        handoff_plan_digest: "66".repeat(32),
        successor_route_digest: "88".repeat(32),
    }
}

fn frozen_intent(plan: &CellSplitExecutionPlanV1) -> CellSplitExecutionIntentV1 {
    let digest = plan.digest().expect("valid frozen Supervisor split plan");
    let predecessor = "77".repeat(32);
    let key = format!(
        "{:x}",
        Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                digest,
                CellSplitExecutionStepV1::SupervisorGenerationFence.index(),
                predecessor,
            )
            .as_bytes()
        )
    );
    CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest: digest,
        step: CellSplitExecutionStepV1::SupervisorGenerationFence,
        owner_id: "supervisor-owner".into(),
        idempotency_key: key,
        previous_receipt_digest: predecessor,
    }
}

#[test]
fn compiled_generic_supervisor_owner_denies_execute_and_cold_replay_before_callbacks() {
    let temp_root = std::env::temp_dir()
        .canonicalize()
        .expect("canonical Unix temp root");
    let dir = tempfile::Builder::new()
        .tempdir_in(temp_root)
        .expect("private external Supervisor root");
    std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private Supervisor original owner");

    let plan = frozen_plan();
    let binding = frozen_binding();
    let intent = frozen_intent(&plan);
    let callbacks = Arc::new(AtomicUsize::new(0));
    let retirements = Arc::new(AtomicUsize::new(0));
    let make_port = || CallerSelectedSupervisor {
        callbacks: Arc::clone(&callbacks),
        retirements: Arc::clone(&retirements),
    };

    let mut owner = CellSplitSupervisorFenceOwnerV1::open(
        dir.path(),
        plan.clone(),
        binding.clone(),
        make_port(),
    )
    .expect("frozen Supervisor owner without original effect custody");
    let original_frozen = std::fs::read(
        dir.path().join("cell-split-supervisor-frozen.json"),
    )
    .expect("actual immutable local plan");

    assert!(matches!(
        owner.authorize_execute(&intent),
        Err(CellSplitSupervisorFenceErrorV1::OriginalControlUnverified)
    ));
    for _ in 0..2 {
        assert!(matches!(
            owner.commit_once(&intent),
            Err(CellSplitSupervisorFenceErrorV1::OriginalControlUnverified)
        ));
    }
    assert_eq!(
        callbacks.load(Ordering::SeqCst),
        0,
        "compiled product may not invoke caller-selected Supervisor callbacks"
    );
    assert_eq!(retirements.load(Ordering::SeqCst), 0);
    assert_eq!(
        std::fs::read(dir.path().join("cell-split-supervisor-frozen.json"))
            .expect("unchanged frozen plan"),
        original_frozen
    );
    drop(owner);

    let mut reopened = CellSplitSupervisorFenceOwnerV1::open(
        dir.path(),
        plan,
        binding,
        make_port(),
    )
    .expect("reopen original Supervisor frozen plan");
    assert!(matches!(
        reopened.commit_once(&intent),
        Err(CellSplitSupervisorFenceErrorV1::OriginalControlUnverified)
    ));
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    assert_eq!(retirements.load(Ordering::SeqCst), 0);
    assert_eq!(
        std::fs::read(dir.path().join("cell-split-supervisor-frozen.json"))
            .expect("unchanged frozen plan"),
        original_frozen
    );
}
