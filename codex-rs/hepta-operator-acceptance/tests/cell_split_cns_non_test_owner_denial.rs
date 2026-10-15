#![cfg(unix)]
#![allow(
    clippy::expect_used,
    reason = "the exact external native denial regression needs fail-fast fixture errors"
)]

// External integration tests link the ordinary non-cfg(test) library.
// A caller-selected generic CNS port must never authorize a new effect
// without the original durable same-Control Begin/effect/Commit protocol.
use std::os::unix::fs::PermissionsExt as _;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_operator_acceptance::CellSplitCnsCutoverErrorV1;
use codex_hepta_operator_acceptance::CellSplitCnsCutoverOwnerV1;
use codex_hepta_operator_acceptance::CellSplitCnsLiveRouteV1;
use codex_hepta_operator_acceptance::CellSplitCnsRouteBindingV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimeCommitV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimePortV1;
use codex_hepta_operator_acceptance::CellSplitDurableEffectBackendV1;
use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
use sha2::Digest as _;
use sha2::Sha256;

struct CallerSelectedCns {
    callbacks: Arc<AtomicUsize>,
    publishes: Arc<AtomicUsize>,
}

impl CallerSelectedCns {
    fn touched(&self) {
        self.callbacks.fetch_add(1, Ordering::SeqCst);
    }
}

impl CellSplitCnsRuntimePortV1 for CallerSelectedCns {
    type Error = &'static str;

    fn verify_preconditions(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.touched();
        Ok(())
    }

    fn inspect_live(
        &mut self,
        _cns_id: &str,
        _scope_digest: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitCnsLiveRouteV1, Self::Error> {
        self.touched();
        Ok(CellSplitCnsLiveRouteV1 {
            cns_id: "cns.main".into(),
            scope_digest: "11".repeat(32),
            generation: 3,
            artifact_digest: "22".repeat(32),
            route_digest: "66".repeat(32),
            route_fence_digest: "99".repeat(32),
            authority_epoch: 7,
            old_writer_fenced: true,
            unknown_effect_count: 0,
            challenge_nonce: challenge_nonce.to_owned(),
            // The caller can claim any bytes; they are NOT an independent
            // signed CNS runtime attestation or a production Final-use grant.
            live_runtime_proof_bytes: vec![0x42; 96],
        })
    }

    fn verify_live(&mut self, _live: &CellSplitCnsLiveRouteV1) -> Result<(), Self::Error> {
        self.touched();
        Ok(())
    }

    fn publish_once(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _binding: &CellSplitCnsRouteBindingV1,
        _intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.touched();
        self.publishes.fetch_add(1, Ordering::SeqCst);
        // A generic trait implementation can falsely claim success;
        // the compiled product owner must refuse before this callback.
        Ok(())
    }

    fn read_original_commit(
        &mut self,
        _idempotency_key: &str,
    ) -> Result<Option<CellSplitCnsRuntimeCommitV1>, Self::Error> {
        self.touched();
        Ok(None)
    }

    fn verify_original_commit(
        &mut self,
        _receipt: &CellSplitCnsRuntimeCommitV1,
    ) -> Result<(), Self::Error> {
        self.touched();
        Ok(())
    }

    fn committed_sequence(&mut self, _cns_id: &str) -> Result<u64, Self::Error> {
        self.touched();
        Ok(1)
    }
}

fn frozen_plan() -> CellSplitExecutionPlanV1 {
    CellSplitExecutionPlanV1 {
        split_id: "split.generic.cns".into(),
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

fn frozen_binding() -> CellSplitCnsRouteBindingV1 {
    CellSplitCnsRouteBindingV1 {
        cns_id: "cns.main".into(),
        predecessor_route_digest: "66".repeat(32),
        successor_route_digest: "88".repeat(32),
        authority_epoch: 7,
    }
}

fn frozen_intent(plan: &CellSplitExecutionPlanV1) -> CellSplitExecutionIntentV1 {
    let digest = plan.digest().expect("validly bound original CNS plan");
    let previous = "77".repeat(32);
    let key = format!(
        "{:x}",
        Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                digest,
                CellSplitExecutionStepV1::CnsRouteCutover.index(),
                previous,
            )
            .as_bytes()
        )
    );
    CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest: digest,
        step: CellSplitExecutionStepV1::CnsRouteCutover,
        owner_id: "cns-owner".into(),
        idempotency_key: key,
        previous_receipt_digest: previous,
    }
}

#[test]
fn compiled_generic_cns_effect_owner_denies_execute_and_cold_replay_before_port_callbacks() {
    let temp_root = std::env::temp_dir()
        .canonicalize()
        .expect("canonical Unix temp root");
    let dir = tempfile::Builder::new()
        .tempdir_in(temp_root)
        .expect("isolated original CNS owner root");
    std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private CNS owner root");

    let plan = frozen_plan();
    let binding = frozen_binding();
    let intent = frozen_intent(&plan);
    let callbacks = Arc::new(AtomicUsize::new(0));
    let publishes = Arc::new(AtomicUsize::new(0));
    let make_port = || CallerSelectedCns {
        callbacks: Arc::clone(&callbacks),
        publishes: Arc::clone(&publishes),
    };

    let mut owner = CellSplitCnsCutoverOwnerV1::open(
        dir.path(),
        plan.clone(),
        binding.clone(),
        make_port(),
    )
    .expect("untrusted but correctly shaped CNS owner fixture");
    // Bootstrap is read-only and may inspect a caller-supplied route; only
    // AFTER that point does this test assert the Execute boundary is sealed.
    let before_calls = callbacks.load(Ordering::SeqCst);
    let frozen_file = dir.path().join("cell-split-cns-frozen.json");
    let original_frozen = std::fs::read(&frozen_file).expect("original frozen binding");

    assert!(matches!(
        owner.authorize_execute(&intent),
        Err(CellSplitCnsCutoverErrorV1::OriginalControlUnverified)
    ));
    for _ in 0..2 {
        assert!(matches!(
            owner.commit_once(&intent),
            Err(CellSplitCnsCutoverErrorV1::OriginalControlUnverified)
        ));
    }
    assert_eq!(
        callbacks.load(Ordering::SeqCst),
        before_calls,
        "product admission and Execute must never invoke an untrusted port"
    );
    assert_eq!(
        publishes.load(Ordering::SeqCst),
        0,
        "product execution must never enter the caller-selected CNS writer"
    );
    assert_eq!(
        std::fs::read(&frozen_file).expect("unchanged original plan"),
        original_frozen
    );
    drop(owner);

    // An unacknowledged/denied attempt must not become a new effect after
    // reopening the same frozen sidecar under a caller-chosen runtime port.
    let mut reopened = CellSplitCnsCutoverOwnerV1::open(
        dir.path(),
        plan,
        binding,
        make_port(),
    )
    .expect("original frozen owner can reopen without authorizing effects");
    let before_replay = callbacks.load(Ordering::SeqCst);
    assert!(matches!(
        reopened.commit_once(&intent),
        Err(CellSplitCnsCutoverErrorV1::OriginalControlUnverified)
    ));
    assert_eq!(callbacks.load(Ordering::SeqCst), before_replay);
    assert_eq!(publishes.load(Ordering::SeqCst), 0);
    assert_eq!(
        std::fs::read(&frozen_file).expect("unchanged original plan"),
        original_frozen
    );
}
