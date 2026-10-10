use super::*;
use ed25519_dalek::{Signer, SigningKey};
use tempfile::TempDir;

const PARENT: u64 = 7;
const SPLIT: &str = "split.target.42";

fn owner_key() -> SigningKey {
    SigningKey::from_bytes(&[7; 32])
}
fn observer_key() -> SigningKey {
    SigningKey::from_bytes(&[9; 32])
}

fn trust() -> BTreeMap<CellSplitEffectStepV1, CellSplitOperationTrustV1> {
    CellSplitEffectStepV1::ORDER
        .into_iter()
        .map(|step| {
            (
                step,
                CellSplitOperationTrustV1 {
                    signer_id: format!("native-owner-{step:?}"),
                    owner_key: owner_key().verifying_key(),
                    observer_id: "independent-observer".to_owned(),
                    observer_key: observer_key().verifying_key(),
                },
            )
        })
        .collect()
}

fn root() -> TempDir {
    let dir = tempfile::tempdir().expect("temp root");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700))
            .expect("private directory");
    }
    dir
}

fn receipt(
    step: CellSplitEffectStepV1,
    operation_id: &str,
    predecessor: &str,
) -> CellSplitNativeOperationReceiptV1 {
    let native = serde_json::to_vec(&serde_json::json!({
        "schema": step.native_schema(),
        "operationId": operation_id,
        "commitWitness": sha256(b"durable-native-commit-witness"),
        "nativeOwnerObserved": {
            "parentGeneration": PARENT,
            "successorGeneration": PARENT + 1,
            "commitSequence": 13,
            "durablyReopened": true
        }
    }))
    .expect("native materialized receipt");
    let native_digest = sha256(&native);
    let readback = serde_json::to_vec(&serde_json::json!({
        "operationId": operation_id,
        "receiptSha256": native_digest,
        "committed": true,
        "storageReopened": true,
        "observerReadback": "independently-pinned-owner-state"
    }))
    .expect("native readback");
    let mut value = CellSplitNativeOperationReceiptV1 {
        step,
        split_id: SPLIT.to_owned(),
        operation_id: operation_id.to_owned(),
        parent_generation: PARENT,
        child_generation: PARENT + 1,
        predecessor_ledger_head: predecessor.to_owned(),
        native_receipt_schema: step.native_schema().to_owned(),
        native_receipt_base64: BASE64.encode(native),
        native_readback_base64: BASE64.encode(readback),
        native_receipt_sha256: native_digest,
        signer_id: format!("native-owner-{step:?}"),
        observer_id: "independent-observer".to_owned(),
        owner_signature_base64: String::new(),
        observer_signature_base64: String::new(),
    };
    let bytes = value.signing_bytes().expect("signing bytes");
    value.owner_signature_base64 = BASE64.encode(owner_key().sign(&bytes).to_bytes());
    value.observer_signature_base64 = BASE64.encode(observer_key().sign(&bytes).to_bytes());
    value
}

/// Test-only port: no production qualification is derived from these keys.
struct FixturePort {
    executions: usize,
    reconciles: usize,
    effect_committed_but_callback_lost: bool,
    tamper_observer_signature: bool,
    persisted: Option<CellSplitNativeOperationReceiptV1>,
}

impl FixturePort {
    fn new() -> Self {
        Self {
            executions: 0,
            reconciles: 0,
            effect_committed_but_callback_lost: false,
            tamper_observer_signature: false,
            persisted: None,
        }
    }
}

impl CellSplitNativeEffectPortV1 for FixturePort {
    type Error = &'static str;

    fn execute(
        &mut self,
        step: CellSplitEffectStepV1,
        operation_id: &str,
        predecessor_head: &str,
    ) -> Result<CellSplitNativeOperationReceiptV1, Self::Error> {
        self.executions += 1;
        let mut result = receipt(step, operation_id, predecessor_head);
        if self.tamper_observer_signature {
            result.observer_signature_base64 = BASE64.encode([0u8; 64]);
        }
        self.persisted = Some(result.clone());
        if self.effect_committed_but_callback_lost {
            Err("simulated lost effect response after effect")
        } else {
            Ok(result)
        }
    }

    fn reconcile(
        &mut self,
        step: CellSplitEffectStepV1,
        operation_id: &str,
        predecessor_head: &str,
    ) -> Result<Option<CellSplitNativeOperationReceiptV1>, Self::Error> {
        self.reconciles += 1;
        Ok(self.persisted.clone().filter(|value| {
            value.step == step
                && value.operation_id == operation_id
                && value.predecessor_ledger_head == predecessor_head
        }))
    }
}

#[test]
fn all_native_stages_are_fenced_and_durably_reopened_in_order() {
    let directory = root();
    let mut owner = CellSplitExecutionLedgerOwnerV1::open(directory.path(), SPLIT, PARENT, trust())
        .expect("create owner");
    let mut port = FixturePort::new();
    for (i, step) in CellSplitEffectStepV1::ORDER.into_iter().enumerate() {
        let operation_id = format!("native-effect-{i}");
        let signed = owner
            .execute_next(&operation_id, &mut port)
            .expect("execute next");
        assert_eq!(signed.step, step);
        assert_eq!(owner.completed_steps(), i + 1);
        assert!(owner.pending().is_none());
    }
    assert!(owner.complete());
    assert!(matches!(
        owner.execute_next("another-effect", &mut port),
        Err(CellSplitExecutionErrorV1::Complete)
    ));
    drop(owner);
    let reopened = CellSplitExecutionLedgerOwnerV1::open(directory.path(), SPLIT, PARENT, trust())
        .expect("verify durable replay");
    assert_eq!(reopened.completed_steps(), 5);
    assert!(reopened.complete());
    assert_eq!(port.executions, 5);
    assert_eq!(port.reconciles, 0);
}

#[test]
fn lost_response_does_not_replay_mutation_after_restart() {
    let directory = root();
    let mut owner = CellSplitExecutionLedgerOwnerV1::open(directory.path(), SPLIT, PARENT, trust())
        .expect("create");
    let mut port = FixturePort::new();
    port.effect_committed_but_callback_lost = true;
    assert!(matches!(
        owner.execute_next("once-only-cas-1", &mut port),
        Err(CellSplitExecutionErrorV1::External(_))
    ));
    assert!(owner.pending().is_some());
    assert_eq!(port.executions, 1);
    drop(owner);

    let mut owner = CellSplitExecutionLedgerOwnerV1::open(directory.path(), SPLIT, PARENT, trust())
        .expect("reopen uncertain");
    assert!(matches!(
        owner.execute_next("once-only-cas-1", &mut port),
        Err(CellSplitExecutionErrorV1::UncertainEffect)
    ));
    assert_eq!(port.executions, 1);
    let reconciled = owner
        .reconcile_pending(&mut port)
        .expect("read-only reconciliation");
    assert_eq!(reconciled.operation_id, "once-only-cas-1");
    assert_eq!(owner.completed_steps(), 1);
    assert_eq!(port.executions, 1);
    assert_eq!(port.reconciles, 1);
    port.effect_committed_but_callback_lost = false;
    owner
        .execute_next("migration-2", &mut port)
        .expect("next step");
    assert_eq!(owner.completed_steps(), 2);
}

#[test]
fn missing_reconciliation_keeps_fence_closed() {
    let directory = root();
    let mut owner = CellSplitExecutionLedgerOwnerV1::open(directory.path(), SPLIT, PARENT, trust())
        .expect("create");
    let mut port = FixturePort::new();
    port.effect_committed_but_callback_lost = true;
    let _ = owner.execute_next("uncertain-1", &mut port);
    port.persisted = None;
    assert!(matches!(
        owner.reconcile_pending(&mut port),
        Err(CellSplitExecutionErrorV1::UncertainEffect)
    ));
    assert_eq!(owner.completed_steps(), 0);
    assert_eq!(port.executions, 1);
}

#[test]
fn invalid_independent_observer_signature_is_never_durable_completion() {
    let directory = root();
    let mut owner = CellSplitExecutionLedgerOwnerV1::open(directory.path(), SPLIT, PARENT, trust())
        .expect("create");
    let mut port = FixturePort::new();
    port.tamper_observer_signature = true;
    assert!(matches!(
        owner.execute_next("cas-tampered", &mut port),
        Err(CellSplitExecutionErrorV1::NativeReceipt)
    ));
    assert!(owner.pending().is_some());
    assert_eq!(owner.completed_steps(), 0);
    assert!(matches!(
        owner.reconcile_pending(&mut port),
        Err(CellSplitExecutionErrorV1::NativeReceipt)
    ));
}

#[test]
fn corrupted_durable_snapshot_cannot_be_reopened() {
    let directory = root();
    let owner = CellSplitExecutionLedgerOwnerV1::open(directory.path(), SPLIT, PARENT, trust())
        .expect("create");
    drop(owner);
    let path = directory.path().join(LEDGER_FILE);
    let bytes = std::fs::read(&path).expect("ledger file");
    let mut ledger: LedgerV1 = serde_json::from_slice(&bytes).expect("ledger");
    ledger.head = sha256(b"rewound-ledger");
    std::fs::write(&path, canonical_json(&ledger).expect("canonical"))
        .expect("corrupt fixture on disk");
    assert!(matches!(
        CellSplitExecutionLedgerOwnerV1::open(directory.path(), SPLIT, PARENT, trust()),
        Err(CellSplitExecutionErrorV1::Transition)
    ));
}
