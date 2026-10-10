use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fs;
use std::rc::Rc;

use super::CellSplitExecutionErrorV1;
use super::CellSplitExecutionIntentV1;
use super::CellSplitExecutionOwnerV1;
use super::CellSplitExecutionPlanV1;
use super::CellSplitExecutionPortV1;
use super::CellSplitExecutionReceiptV1;
use super::CellSplitOwnerTrustV1;
use super::cell_split_execution_signing_payload_v1;
use super::receipt_digest;
use crate::durable::canonical_json;
use crate::durable::sha256;

#[derive(Default)]
struct Observed {
    commits: BTreeMap<String, CellSplitExecutionReceiptV1>,
    executions: usize,
    verifications: usize,
}

#[derive(Clone)]
struct FixturePort {
    observed: Rc<RefCell<Observed>>,
    drop_ack: bool,
    reject_signature: bool,
}

impl FixturePort {
    fn new(observed: Rc<RefCell<Observed>>) -> Self {
        Self {
            observed,
            drop_ack: false,
            reject_signature: false,
        }
    }

    fn receipt(intent: &CellSplitExecutionIntentV1) -> CellSplitExecutionReceiptV1 {
        let receipt_bytes = canonical_json(intent).expect("fixture receipt bytes");
        let mut receipt = CellSplitExecutionReceiptV1 {
            intent: intent.clone(),
            owner_sequence: intent.step.index() as u64 + 1,
            output_digest: sha256(&receipt_bytes),
            owner_receipt_bytes: receipt_bytes,
            owner_signature_bytes: Vec::new(),
            receipt_digest: String::new(),
        };
        receipt.owner_signature_bytes = signing_key(intent.step.index())
            .sign(&cell_split_execution_signing_payload_v1(&receipt).expect("payload"))
            .to_bytes()
            .to_vec();
        receipt.receipt_digest = receipt_digest(&receipt).expect("fixture receipt digest");
        receipt
    }
}

impl CellSplitExecutionPortV1 for FixturePort {
    type Error = &'static str;

    fn execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<CellSplitExecutionReceiptV1, Self::Error> {
        let receipt = Self::receipt(intent);
        let mut state = self.observed.borrow_mut();
        state.executions += 1;
        state
            .commits
            .insert(intent.idempotency_key.clone(), receipt.clone());
        if self.drop_ack {
            return Err("ack lost after durable effect");
        }
        Ok(receipt)
    }

    fn reconcile(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, Self::Error> {
        Ok(self
            .observed
            .borrow()
            .commits
            .get(&intent.idempotency_key)
            .cloned())
    }

    fn verify_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        receipt: &CellSplitExecutionReceiptV1,
    ) -> Result<(), Self::Error> {
        self.observed.borrow_mut().verifications += 1;
        if self.reject_signature || receipt.owner_signature_bytes.len() != 64 {
            return Err("signature rejected");
        }
        if self.observed.borrow().commits.get(&intent.idempotency_key) != Some(receipt) {
            return Err("not present in external durable owner");
        }
        Ok(())
    }
}

fn signing_key(index: usize) -> SigningKey {
    SigningKey::from_bytes(&[u8::try_from(index).expect("bounded index") + 1; 32])
}

fn trust_for(plan: &CellSplitExecutionPlanV1) -> CellSplitOwnerTrustV1 {
    CellSplitOwnerTrustV1::new(
        plan,
        [0, 1, 2, 3].map(|index| signing_key(index).verifying_key()),
    )
    .expect("trusted independent fixture owners")
}

fn trust() -> CellSplitOwnerTrustV1 {
    trust_for(&plan())
}

fn plan() -> CellSplitExecutionPlanV1 {
    CellSplitExecutionPlanV1 {
        split_id: "split-42".into(),
        scope_digest: "11".repeat(32),
        parent_generation: 3,
        child_generation: 4,
        parent_artifact_digest: "22".repeat(32),
        child_artifact_digest: "33".repeat(32),
        ndu_snapshot_digest: "44".repeat(32),
        route_fence_digest: "55".repeat(32),
        owner_ids: [
            "artifact-cas-owner".into(),
            "state-migration-owner".into(),
            "cns-owner".into(),
            "supervisor-owner".into(),
        ],
    }
}

#[test]
fn advances_only_in_exact_dependency_order_and_recovers_verified_chain() {
    let root = tempfile::tempdir().expect("root");
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let port = FixturePort::new(state.clone());
        let mut owner = CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port)
            .expect("initial open");
        assert!(
            CellSplitExecutionOwnerV1::open(
                root.path(),
                plan(),
                trust(),
                FixturePort::new(state.clone())
            )
            .is_err()
        );
        let mut observed_steps = Vec::new();
        for _ in 0..4 {
            let receipt = owner.advance().expect("external effect").expect("step");
            observed_steps.push(receipt.intent.step.index());
        }
        assert_eq!(observed_steps, vec![0, 1, 2, 3]);
        assert!(owner.is_complete());
        assert!(owner.advance().expect("done").is_none());
    }
    let mut reopened = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("reopen and authenticate four external receipts");
    assert_eq!(reopened.completed_steps(), 4);
    assert!(reopened.advance().expect("no re-execution").is_none());
    assert_eq!(state.borrow().executions, 4);
    assert!(state.borrow().verifications >= 8);
}

#[test]
fn lost_ack_reconciles_original_effect_without_duplicate_execution() {
    let root = tempfile::tempdir().expect("root");
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut port = FixturePort::new(state.clone());
        port.drop_ack = true;
        let mut owner =
            CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");
        assert!(matches!(
            owner.advance(),
            Err(CellSplitExecutionErrorV1::External(_))
        ));
        assert_eq!(owner.completed_steps(), 0);
        assert_eq!(state.borrow().executions, 1);
    }
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("reopen");
    assert_eq!(
        owner
            .advance()
            .expect("read after ack loss")
            .expect("commit")
            .intent
            .step
            .index(),
        0
    );
    assert_eq!(state.borrow().executions, 1);
    assert_eq!(owner.completed_steps(), 1);
}

#[test]
fn unknown_effect_must_fail_closed_and_frozen_plan_cannot_drift() {
    let root = tempfile::tempdir().expect("root");
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut port = FixturePort::new(state.clone());
        port.drop_ack = true;
        let mut owner =
            CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");
        assert!(owner.advance().is_err());
    }
    state.borrow_mut().commits.clear();
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("reopen");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Ambiguous)
    ));
    assert_eq!(state.borrow().executions, 1);
    drop(owner);
    let mut changed = plan();
    changed.child_artifact_digest = "aa".repeat(32);
    assert!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            changed.clone(),
            trust_for(&changed),
            FixturePort::new(state)
        )
        .is_err()
    );
}

#[test]
fn tamper_and_invalid_signature_prevent_committed_replay() {
    let root = tempfile::tempdir().expect("root");
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("open");
        owner.advance().expect("first commit");
    }
    let mut denied = FixturePort::new(state.clone());
    denied.reject_signature = true;
    assert!(CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), denied).is_err());
    let path = root.path().join("cell-split-00-committed.json");
    let mut receipt: CellSplitExecutionReceiptV1 =
        serde_json::from_slice(&fs::read(&path).expect("read")).expect("decode");
    receipt.output_digest = "ff".repeat(32);
    fs::write(&path, canonical_json(&receipt).expect("encode")).expect("tamper");
    assert!(
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), FixturePort::new(state))
            .is_err()
    );
}
