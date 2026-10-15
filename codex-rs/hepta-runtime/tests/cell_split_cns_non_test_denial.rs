#![cfg(all(unix, feature = "cell-split-cns-port"))]
#![allow(
    clippy::expect_used,
    reason = "fail-fast external native security regression must identify invalid setup"
)]

// External Cargo integration links the ordinary non-cfg(test) HeptaRuntime
// library. Supplying a caller-selected witness and a syntactically valid
// pinned plan must never turn an optional Control handle into B/effect/C.
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt as _;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_operator_acceptance::CellSplitCnsLiveRouteV1;
use codex_hepta_operator_acceptance::CellSplitCnsRouteBindingV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimeCommitV1;
use codex_hepta_operator_acceptance::CellSplitCnsRuntimePortV1;
use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
use codex_hepta_paths::HeptaStateRoot;
use codex_hepta_runtime::CellSplitCnsKernelRuntimePortV1;
use codex_hepta_runtime::CellSplitCnsKernelWitnessV1;
use codex_hepta_runtime::HeptaRuntime;
use codex_hepta_runtime::RuntimeStateAdapter;
use codex_hepta_runtime::RuntimeStateStatus;
use codex_hepta_runtime::RuntimeTopologyApplyReceiptV1;
use codex_hepta_runtime::RuntimeTopologyApplyRequestV1;
use codex_hepta_runtime::RuntimeTopologySnapshotV1;
use ed25519_dalek::SigningKey;
use sha2::Digest as _;
use sha2::Sha256;

#[derive(Debug)]
struct ReadOnlyHost;

impl RuntimeStateAdapter for ReadOnlyHost {
    fn status(&self) -> RuntimeStateStatus {
        RuntimeStateStatus {
            adapter: "cns-original-control-non-test-denial",
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

struct CallerControlledWitness {
    calls: Arc<AtomicUsize>,
}

impl CallerControlledWitness {
    fn touched(&self) {
        self.calls.fetch_add(1, Ordering::SeqCst);
    }
}

impl CellSplitCnsKernelWitnessV1 for CallerControlledWitness {
    type Error = &'static str;

    fn verify_preconditions(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        self.touched();
        Ok(())
    }

    fn signed_current_route(
        &mut self,
        _runtime: &RuntimeTopologySnapshotV1,
        _nonce: &str,
    ) -> Result<CellSplitCnsLiveRouteV1, Self::Error> {
        self.touched();
        Err("no original signed runtime")
    }

    fn take_admitted_successor(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _binding: &CellSplitCnsRouteBindingV1,
        _intent: &CellSplitExecutionIntentV1,
    ) -> Result<(SignedFinalUseGrant, RuntimeTopologyApplyRequestV1), Self::Error> {
        self.touched();
        Err("no original final-use")
    }

    fn persist_actual_runtime_receipt(
        &mut self,
        _plan: &CellSplitExecutionPlanV1,
        _binding: &CellSplitCnsRouteBindingV1,
        _intent: &CellSplitExecutionIntentV1,
        _actual: &RuntimeTopologyApplyReceiptV1,
    ) -> Result<(), Self::Error> {
        self.touched();
        Err("no original durable CNS writer")
    }

    fn read_original_commit(
        &mut self,
        _idempotency_key: &str,
    ) -> Result<Option<CellSplitCnsRuntimeCommitV1>, Self::Error> {
        self.touched();
        Ok(None)
    }

    fn current_durable_sequence(&mut self, _cns_id: &str) -> Result<u64, Self::Error> {
        self.touched();
        Ok(1)
    }
}

#[test]
fn compiled_product_cns_port_denies_before_preflight_or_physical_effect() {
    let private = tempfile::tempdir().expect("private native runtime root");
    std::fs::set_permissions(private.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private owner directory");
    let root = HeptaStateRoot::parse(private.path().join("runtime")).expect("original runtime path");
    let runtime = HeptaRuntime::from_adapter(root, Arc::new(ReadOnlyHost));
    let predecessor = runtime.topology_snapshot().expect("serving predecessor");

    let plan = CellSplitExecutionPlanV1 {
        split_id: "split.cns.live".into(),
        scope_digest: "11".repeat(32),
        parent_generation: predecessor.generation().get(),
        child_generation: predecessor.generation().get() + 1,
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
        cns_id: predecessor.cns_id().to_string(),
        predecessor_route_digest: predecessor.hierarchy_digest().to_string(),
        successor_route_digest: "aa".repeat(32),
        authority_epoch: 7,
    };
    let frozen = plan.digest().expect("frozen validated split");
    let previous = "77".repeat(32);
    let key = format!(
        "{:x}",
        Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                frozen,
                CellSplitExecutionStepV1::CnsRouteCutover.index(),
                previous,
            )
            .as_bytes()
        )
    );
    let intent = CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest: frozen,
        step: CellSplitExecutionStepV1::CnsRouteCutover,
        owner_id: "cns-owner".into(),
        idempotency_key: key,
        previous_receipt_digest: previous,
    };
    let authority = Arc::new(
        FinalUseAuthority::open_state_dir(
            private.path(),
            "caller-selected-local-authority".into(),
            SigningKey::from_bytes(&[55; 32])
                .verifying_key()
                .to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("test-local verifier cannot grant original CNS authority"),
    );
    let calls = Arc::new(AtomicUsize::new(0));
    let mut port = CellSplitCnsKernelRuntimePortV1::new(
        runtime.clone(),
        authority,
        plan.clone(),
        binding.clone(),
        intent.clone(),
        SigningKey::from_bytes(&[42; 32]).verifying_key(),
        CallerControlledWitness {
            calls: Arc::clone(&calls),
        },
    )
    .expect("validly shaped but untrusted original-owner construction");

    assert_eq!(
        port.publish_once(&plan, &binding, &intent),
        Err(
            "CNS mutation denied: original same-owner Control B/effect/C is not production-composed"
                .into()
        ),
        "non-test CNS must refuse before any claimed signer/witness callback"
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0, "no injected owner callback");
    assert_eq!(
        runtime.topology_snapshot().expect("unchanged serving CNS"),
        predecessor,
        "no physical topology replacement or generation increment"
    );
}
