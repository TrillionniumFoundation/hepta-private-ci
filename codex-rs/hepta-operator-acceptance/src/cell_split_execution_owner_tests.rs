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
use super::verify_cell_split_execution_transcript_signatures_v1;
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
    tamper_frozen_during_preflight: Option<std::path::PathBuf>,
    tamper_during_live_readback: Rc<RefCell<Option<std::path::PathBuf>>>,
    revoke_previous_during_preflight: bool,
    revoke_selection_during_preflight: Option<Rc<RefCell<bool>>>,
    revoke_selection_on_readback: Option<(Rc<RefCell<bool>>, usize)>,
}

impl FixturePort {
    fn new(observed: Rc<RefCell<Observed>>) -> Self {
        Self {
            observed,
            drop_ack: false,
            reject_signature: false,
            tamper_frozen_during_preflight: None,
            tamper_during_live_readback: Rc::new(RefCell::new(None)),
            revoke_previous_during_preflight: false,
            revoke_selection_during_preflight: None,
            revoke_selection_on_readback: None,
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

    fn preflight_uncommitted(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        if self
            .observed
            .borrow()
            .commits
            .contains_key(&intent.idempotency_key)
        {
            return Err("effect already exists");
        }
        if let Some(path) = &self.tamper_frozen_during_preflight {
            fs::write(path, b"{}").map_err(|_| "fixture could not alter frozen trust")?;
        }
        if self.revoke_previous_during_preflight {
            self.observed.borrow_mut().commits.clear();
        }
        if let Some(selected) = &self.revoke_selection_during_preflight {
            *selected.borrow_mut() = false;
        }
        Ok(())
    }

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
        let count = {
            let mut observed = self.observed.borrow_mut();
            observed.verifications += 1;
            observed.verifications
        };
        if let Some((selected, at)) = &self.revoke_selection_on_readback
            && count == *at
        {
            *selected.borrow_mut() = false;
        }
        if let Some(path) = self.tamper_during_live_readback.borrow_mut().take() {
            fs::write(path, b"{}").map_err(|_| "fixture could not tamper local readback frame")?;
        }
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

// The production durable owner deliberately rejects group/other-readable roots.
// TempDir defaults are platform/runner-dependent, so fixtures must explicitly
// construct the same private directory that the production owner requires.
fn private_tempdir() -> tempfile::TempDir {
    let root = tempfile::tempdir().expect("root");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
            .expect("private fixture directory");
    }
    root
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
fn frozen_split_plan_rejects_noncanonical_split_and_owner_ids() {
    assert!(plan().digest().is_ok());
    for invalid_id in ["../other", "parent/child", "line\nspoof", "nul\0id"] {
        let mut invalid_split = plan();
        invalid_split.split_id = invalid_id.into();
        assert!(
            invalid_split.digest().is_err(),
            "invalid split ID: {invalid_id:?}"
        );

        let mut invalid_owner = plan();
        invalid_owner.owner_ids[2] = invalid_id.into();
        assert!(
            invalid_owner.digest().is_err(),
            "invalid owner ID: {invalid_id:?}"
        );
    }
}

#[test]
fn cns_predecessor_bridge_rejects_wrong_signer_receipt_and_plan() {
    let frozen = plan();
    let digest = frozen.digest().expect("frozen plan");
    let intent = super::make_intent(
        &frozen,
        &digest,
        super::CellSplitExecutionStepV1::CnsRouteCutover,
        &"ab".repeat(32),
    );
    let original = FixturePort::receipt(&intent);
    let key = signing_key(2).verifying_key();
    super::verify_cell_split_cns_step_receipt_v1(&frozen, &original, &key)
        .expect("signed CNS owner predecessor");
    assert_eq!(
        super::cell_split_execution_receipt_digest_v1(&original).expect("outer digest"),
        original.receipt_digest
    );
    assert_ne!(
        original.output_digest, original.receipt_digest,
        "the original CNS payload and signed coordinator receipt differ"
    );

    assert!(
        super::verify_cell_split_cns_step_receipt_v1(
            &frozen,
            &original,
            &signing_key(0).verifying_key(),
        )
        .is_err()
    );
    let mut changed = original.clone();
    changed.receipt_digest = "cd".repeat(32);
    assert!(super::verify_cell_split_cns_step_receipt_v1(&frozen, &changed, &key).is_err());
    changed = original.clone();
    changed.owner_receipt_bytes[0] ^= 1;
    assert!(super::verify_cell_split_cns_step_receipt_v1(&frozen, &changed, &key).is_err());
    changed = original.clone();
    changed.intent.owner_id = frozen.owner_ids[3].clone();
    assert!(super::verify_cell_split_cns_step_receipt_v1(&frozen, &changed, &key).is_err());
}

#[test]
fn transcript_only_reopen_cannot_dispatch_an_uncommitted_effect() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("initialize private frozen owner");
        assert_eq!(owner.completed_steps(), 0);
    }
    let mut reader = CellSplitExecutionOwnerV1::open_existing(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("reopen for read-only transcript");
    assert!(matches!(
        reader.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(
            "read-only CellSplit owner cannot advance"
        ))
    ));
    let transcript = reader
        .verified_transcript()
        .expect("read-only evidence inspection");
    assert!(transcript.is_none());
    assert_eq!(reader.completed_steps(), 0);
    assert_eq!(state.borrow().executions, 0);
    assert!(!root.path().join("cell-split-00-prepared.json").exists());
    assert!(!root.path().join("cell-split-00-committed.json").exists());
}

#[test]
fn existing_unprepared_effect_must_not_be_adopted_or_dispatched() {
    let root = private_tempdir();
    let frozen = plan();
    let plan_digest = frozen.digest().expect("frozen plan");
    let intent = super::make_intent(
        &frozen,
        &plan_digest,
        super::CellSplitExecutionStepV1::ArtifactCas,
        &plan_digest,
    );
    let state = Rc::new(RefCell::new(Observed::default()));
    state.borrow_mut().commits.insert(
        intent.idempotency_key.clone(),
        FixturePort::receipt(&intent),
    );
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        frozen.clone(),
        trust_for(&frozen),
        FixturePort::new(state.clone()),
    )
    .expect("frozen plan before effects");

    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::External(_))
    ));
    assert_eq!(owner.completed_steps(), 0);
    assert_eq!(state.borrow().executions, 0);
    assert!(!root.path().join("cell-split-00-prepared.json").exists());
    assert!(!root.path().join("cell-split-00-committed.json").exists());
}

#[test]
fn advances_only_in_exact_dependency_order_and_recovers_verified_chain() {
    let root = private_tempdir();
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
fn transcript_only_reopen_must_not_reconcile_lost_ack_into_a_commit() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut port = FixturePort::new(state.clone());
        port.drop_ack = true;
        let mut writer = CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port)
            .expect("open effect owner");
        assert!(matches!(
            writer.advance(),
            Err(CellSplitExecutionErrorV1::External(_))
        ));
        assert_eq!(state.borrow().executions, 1);
    }
    {
        let mut reader = CellSplitExecutionOwnerV1::open_existing(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("read-only open of unresolved intent");
        assert!(matches!(
            reader.advance(),
            Err(CellSplitExecutionErrorV1::Invalid(
                "read-only CellSplit owner cannot advance"
            ))
        ));
        assert_eq!(reader.completed_steps(), 0);
        assert_eq!(state.borrow().executions, 1);
        assert!(!root.path().join("cell-split-00-committed.json").exists());
    }
    // Only a separately opened mutable execution owner may reconcile this
    // exact previously executed effect, without dispatching it a second time.
    let mut writer = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("execution recovery");
    assert!(writer.advance().expect("reconcile original").is_some());
    assert_eq!(writer.completed_steps(), 1);
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn lost_ack_reconciles_original_effect_without_duplicate_execution() {
    let root = private_tempdir();
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
    let root = private_tempdir();
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
    let root = private_tempdir();
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

#[test]
fn external_predecessor_revocation_fences_every_successor_and_completed_replay() {
    for completed in 1..=4 {
        let root = private_tempdir();
        let state = Rc::new(RefCell::new(Observed::default()));
        let mut owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("open");
        for _ in 0..completed {
            owner.advance().expect("committed effect");
        }
        state.borrow_mut().commits.clear();
        assert!(matches!(
            owner.advance(),
            Err(CellSplitExecutionErrorV1::External(_))
        ));
        assert_eq!(state.borrow().executions, completed);
        assert_eq!(owner.completed_steps(), completed);
    }
}

#[test]
fn post_open_future_frame_fences_first_effect_and_read_only_export() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("open");

    // This frame arrived after open, without the earlier durable intent
    // required for a valid prefix. It must not be ignored on a live owner.
    crate::durable::write_private_new(&root.path().join("cell-split-02-prepared.json"), b"{}")
        .expect("inject private future frame");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(
            "unexpected successor frame; reopen required"
        ))
    ));
    assert!(owner.verified_transcript().is_err());
    assert_eq!(state.borrow().executions, 0);
    assert!(!root.path().join("cell-split-00-prepared.json").exists());
}

#[test]
fn post_open_future_frame_fences_successor_after_valid_commit() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("open");
    owner.advance().expect("first committed effect");
    crate::durable::write_private_new(&root.path().join("cell-split-03-committed.json"), b"{}")
        .expect("inject future frame");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(
            "unexpected successor frame; reopen required"
        ))
    ));
    assert_eq!(state.borrow().executions, 1);
    assert!(!root.path().join("cell-split-01-prepared.json").exists());
}

#[test]
fn post_open_ledger_tampering_cannot_dispatch_a_successor() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("open");
    owner.advance().expect("first committed effect");
    let path = root.path().join("cell-split-00-committed.json");
    let mut receipt: CellSplitExecutionReceiptV1 =
        serde_json::from_slice(&fs::read(&path).expect("read")).expect("decode");
    receipt.owner_sequence += 1;
    fs::write(&path, canonical_json(&receipt).expect("encode")).expect("tamper");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(_))
    ));
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn read_only_transcript_rejects_post_open_pending_intent_tampering() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut port = FixturePort::new(state.clone());
    port.drop_ack = true;
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");
    assert!(owner.advance().is_err());
    let prepared = root.path().join("cell-split-00-prepared.json");
    fs::write(&prepared, b"{}").expect("tamper pending");
    assert!(matches!(
        owner.verified_transcript(),
        Err(CellSplitExecutionErrorV1::Invalid(_))
    ));
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn post_open_frozen_plan_tampering_fences_first_effect() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("open");
    fs::write(root.path().join("cell-split-frozen-plan.json"), b"{}").expect("tamper plan");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(_))
    ));
    assert_eq!(state.borrow().executions, 0);
}

#[test]
fn completed_history_must_be_verified_against_current_original_owners() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("open");

    assert!(!owner.verified_complete().expect("incomplete history"));
    assert_eq!(state.borrow().verifications, 0);
    for _ in 0..4 {
        owner.advance().expect("committed original effect");
    }
    assert!(owner.is_complete(), "historical cursor is complete");
    let before = state.borrow().verifications;
    assert!(owner.verified_complete().expect("four live originals"));
    assert_eq!(state.borrow().verifications - before, 4);

    state.borrow_mut().commits.clear();
    assert!(owner.is_complete(), "historical cursor stays complete");
    assert!(matches!(
        owner.verified_complete(),
        Err(CellSplitExecutionErrorV1::External(_))
    ));
    assert_eq!(state.borrow().executions, 4, "no effect replay");
}

#[test]
fn current_selector_revocation_during_preflight_never_prepares_a_new_intent() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let selected = Rc::new(RefCell::new(true));
    let mut port = FixturePort::new(state.clone());
    port.revoke_selection_during_preflight = Some(selected.clone());
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");

    let mut admission_reads = 0_usize;
    let result = owner.advance_with_admission(|| {
        admission_reads += 1;
        if *selected.borrow() {
            Ok(())
        } else {
            Err("independent Selector revoked after original-owner preflight".to_string())
        }
    });

    assert!(matches!(
        result,
        Err(CellSplitExecutionErrorV1::External(message))
            if message.contains("Selector revoked")
    ));
    assert_eq!(admission_reads, 1, "post-preflight admission was exercised");
    assert_eq!(owner.completed_steps(), 0);
    assert!(!root.path().join("cell-split-00-prepared.json").exists());
    assert_eq!(state.borrow().executions, 0, "no original owner effect");
}

#[test]
fn selector_revoked_during_last_owner_readback_never_prepares_successor() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let selected = Rc::new(RefCell::new(true));
    let mut port = FixturePort::new(state.clone());
    // The first effect's original receipt is now checked again after
    // admission. During successor preflight, revoke at its *second*
    // predecessor readback rather than during the first independent check.
    port.revoke_selection_on_readback = Some((selected.clone(), 4));
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");
    owner.advance().expect("first effect");

    let mut admission_reads = 0;
    let result = owner.advance_with_admission(|| {
        admission_reads += 1;
        if *selected.borrow() {
            Ok(())
        } else {
            Err("Selector revoked during original-owner readback".to_string())
        }
    });
    assert!(matches!(
        result,
        Err(CellSplitExecutionErrorV1::External(message))
            if message.contains("Selector revoked")
    ));
    assert_eq!(
        admission_reads, 2,
        "Selector checked again after live readback"
    );
    assert_eq!(
        state.borrow().executions,
        1,
        "no successor effect may execute"
    );
    assert_eq!(owner.completed_steps(), 1);
    assert!(!root.path().join("cell-split-01-prepared.json").exists());
}

#[test]
fn trust_drift_during_preflight_never_persists_prepared_intent() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut port = FixturePort::new(state.clone());
    port.tamper_frozen_during_preflight =
        Some(root.path().join("cell-split-owner-trust-pins.json"));
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");

    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid("owner trust pins drift"))
    ));
    assert!(!root.path().join("cell-split-00-prepared.json").exists());
    assert_eq!(state.borrow().executions, 0);
}

#[test]
fn external_revocation_during_preflight_never_prepares_next_step() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut port = FixturePort::new(state.clone());
    port.revoke_previous_during_preflight = true;
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");

    owner.advance().expect("first committed effect");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::External(_))
    ));
    assert!(!root.path().join("cell-split-01-prepared.json").exists());
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn persisted_owner_keys_cannot_drift_after_a_committed_effect() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("owner");
        owner.advance().expect("original CAS effect");
    }
    let mut keys = [0, 1, 2, 3].map(|index| signing_key(index).verifying_key());
    keys[1] = SigningKey::from_bytes(&[91; 32]).verifying_key();
    let replacement = CellSplitOwnerTrustV1::new(&plan(), keys).expect("distinct new key");
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            replacement,
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "persisted effect owner keys changed"
        ))
    ));
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn rewritten_trust_pins_fence_live_dispatch_and_transcript() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("owner");
    fs::write(root.path().join("cell-split-owner-trust-pins.json"), b"{}").expect("rewrite pins");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid("owner trust pins drift"))
    ));
    assert!(matches!(
        owner.verified_transcript(),
        Err(CellSplitExecutionErrorV1::Invalid("owner trust pins drift"))
    ));
    assert_eq!(state.borrow().executions, 0);
}

#[test]
fn missing_frozen_plan_after_initialization_is_not_recreated() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("initial owner");
        assert_eq!(owner.completed_steps(), 0);
    }
    let frozen = root.path().join("cell-split-frozen-plan.json");
    fs::remove_file(&frozen).expect("remove frozen plan");
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "frozen plan lost after initialization"
        ))
    ));
    assert!(!frozen.exists());
    assert_eq!(state.borrow().executions, 0);
}

#[test]
fn missing_frozen_plan_after_lost_ack_fences_reconciliation() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut port = FixturePort::new(state.clone());
        port.drop_ack = true;
        let mut owner =
            CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("owner");
        assert!(owner.advance().is_err());
    }
    let frozen = root.path().join("cell-split-frozen-plan.json");
    fs::remove_file(&frozen).expect("remove frozen plan");
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "frozen plan lost after initialization"
        ))
    ));
    assert!(!frozen.exists());
    // The original external effect may already be durable: never retry it.
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn missing_frozen_plan_after_committed_effect_fences_recovery() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("initial owner");
        owner.advance().expect("first commit").expect("receipt");
    }
    let frozen = root.path().join("cell-split-frozen-plan.json");
    fs::remove_file(&frozen).expect("remove frozen plan");
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "frozen plan lost after initialization"
        ))
    ));
    assert!(!frozen.exists());
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn both_frozen_owner_frames_cannot_be_reset_before_first_effect() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("initialize frozen owner");
        assert_eq!(owner.completed_steps(), 0);
    }
    let frozen = root.path().join("cell-split-frozen-plan.json");
    let pins = root.path().join("cell-split-owner-trust-pins.json");
    let lock = root.path().join(crate::durable::SIDECAR_LOCK_FILE);
    assert!(lock.exists());
    fs::remove_file(&frozen).expect("remove frozen plan");
    fs::remove_file(&pins).expect("remove frozen pins");

    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "initialized split owner lost frozen identity"
        ))
    ));
    assert!(!frozen.exists());
    assert!(!pins.exists());
    assert_eq!(state.borrow().executions, 0);
}

#[test]
fn frozen_plan_cannot_reseed_missing_owner_keys_before_any_effect() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("frozen owner");
        assert_eq!(owner.completed_steps(), 0);
    }

    let pins = root.path().join("cell-split-owner-trust-pins.json");
    fs::remove_file(&pins).expect("remove original signer pins");

    // Reusing the original keys does not justify recreating a deleted,
    // previously frozen trust frontier.
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "frozen plan lost owner trust pins"
        ))
    ));

    // In particular, no caller can rotate an original owner key by deleting
    // the local pins while preserving the frozen plan.
    let mut keys = [0, 1, 2, 3].map(|index| signing_key(index).verifying_key());
    keys[2] = SigningKey::from_bytes(&[97; 32]).verifying_key();
    let replacement = CellSplitOwnerTrustV1::new(&plan(), keys).expect("distinct signers");
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            replacement,
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "frozen plan lost owner trust pins"
        ))
    ));
    assert!(!pins.exists());
    assert_eq!(state.borrow().executions, 0);
}

#[test]
fn missing_trust_pins_reject_recovery_after_effect_history() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("owner");
        owner.advance().expect("first commit");
    }
    fs::remove_file(root.path().join("cell-split-owner-trust-pins.json")).expect("remove pins");
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "effect history lost trust pins"
        ))
    ));
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn receipt_whitespace_rewrite_fails_before_successor_and_recovery() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("owner");
    owner.advance().expect("first committed effect");
    let path = root.path().join("cell-split-00-committed.json");
    let mut bytes = fs::read(&path).expect("original receipt");
    bytes.push(b'\n');
    fs::write(&path, bytes).expect("noncanonical rewrite");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(
            "noncanonical committed receipt bytes"
        ))
    ));
    assert_eq!(state.borrow().executions, 1);
    drop(owner);
    assert!(
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), FixturePort::new(state))
            .is_err()
    );
}

#[cfg(unix)]
#[test]
fn missing_trust_pins_cannot_be_hidden_by_dangling_prepared_symlink() {
    use std::os::unix::fs::symlink;

    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("owner");
        assert_eq!(owner.completed_steps(), 0);
    }
    fs::remove_file(root.path().join("cell-split-owner-trust-pins.json")).expect("remove pins");
    symlink(
        root.path().join("missing-intent"),
        root.path().join("cell-split-00-prepared.json"),
    )
    .expect("inject dangling prepared frame");
    assert!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .is_err()
    );
    assert_eq!(state.borrow().executions, 0);
}

#[test]
fn post_open_pending_intent_tampering_cannot_reconcile_or_dispatch() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut port = FixturePort::new(state.clone());
    port.drop_ack = true;
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");
    assert!(owner.advance().is_err());
    fs::write(root.path().join("cell-split-00-prepared.json"), b"{}").expect("tamper pending");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(_))
    ));
    assert_eq!(state.borrow().executions, 1);
}

#[cfg(unix)]
#[test]
fn dangling_later_frame_is_not_treated_as_absent_during_recovery() {
    use std::os::unix::fs::symlink;

    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    symlink(
        root.path().join("absent-target"),
        root.path().join("cell-split-02-prepared.json"),
    )
    .expect("inject dangling successor");
    assert!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .is_err()
    );
    assert_eq!(state.borrow().executions, 0);
}

#[cfg(unix)]
#[test]
fn pending_step_recovery_rejects_dangling_successor_frame() {
    use std::os::unix::fs::symlink;

    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    {
        let mut port = FixturePort::new(state.clone());
        port.drop_ack = true;
        let mut owner =
            CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("open");
        assert!(owner.advance().is_err());
    }
    symlink(
        root.path().join("absent-target"),
        root.path().join("cell-split-03-committed.json"),
    )
    .expect("inject dangling successor");
    assert!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .is_err()
    );
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn recovery_rejects_local_identity_and_history_drift_during_live_readbacks() {
    for (filename, expected_error) in [
        (
            "cell-split-frozen-plan.json",
            "frozen identity changed during owner recovery",
        ),
        (
            "cell-split-owner-trust-pins.json",
            "frozen identity changed during owner recovery",
        ),
        (
            "cell-split-00-committed.json",
            "local history changed during owner recovery",
        ),
    ] {
        let root = private_tempdir();
        let state = Rc::new(RefCell::new(Observed::default()));
        {
            let mut owner = CellSplitExecutionOwnerV1::open(
                root.path(),
                plan(),
                trust(),
                FixturePort::new(state.clone()),
            )
            .expect("initialize owner");
            for _ in 0..4 {
                owner.advance().expect("original effect");
            }
        }
        let port = FixturePort::new(state.clone());
        *port.tamper_during_live_readback.borrow_mut() = Some(root.path().join(filename));
        assert!(
            matches!(
                CellSplitExecutionOwnerV1::open_existing(root.path(), plan(), trust(), port),
                Err(CellSplitExecutionErrorV1::Invalid(reason)) if reason == expected_error
            ),
            "recovery accepted changed {filename}"
        );
        assert_eq!(state.borrow().executions, 4, "no replay on recovery");
    }
}

#[cfg(unix)]
#[test]
fn original_writer_lock_must_not_be_recreated_around_frozen_or_committed_state() {
    for completed in [0, 1] {
        let root = private_tempdir();
        let state = Rc::new(RefCell::new(Observed::default()));
        let mut original = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("original writer");
        for _ in 0..completed {
            original
                .advance()
                .expect("durable effect")
                .expect("receipt");
        }
        let frozen = root.path().join("cell-split-frozen-plan.json");
        let pins = root.path().join("cell-split-owner-trust-pins.json");
        let frozen_bytes = fs::read(&frozen).expect("frozen plan");
        let pins_bytes = fs::read(&pins).expect("frozen trust");
        let lock = root.path().join(crate::durable::SIDECAR_LOCK_FILE);

        // The old process still holds its original lock inode after unlink.
        // Reopening must not silently mint a second writer lock inode.
        fs::remove_file(&lock).expect("unlink original lock");
        assert!(matches!(
            CellSplitExecutionOwnerV1::open(
                root.path(),
                plan(),
                trust(),
                FixturePort::new(state.clone()),
            ),
            Err(CellSplitExecutionErrorV1::Invalid(
                "initialized split owner lost original writer lock"
            ))
        ));
        assert!(!lock.exists(), "denied reopen must not recreate the lock");
        assert_eq!(fs::read(&frozen).expect("plan preserved"), frozen_bytes);
        assert_eq!(fs::read(&pins).expect("pins preserved"), pins_bytes);
        assert_eq!(state.borrow().executions, completed);

        // The detached original lock no longer protects this namespace.
        assert!(matches!(
            original.advance(),
            Err(CellSplitExecutionErrorV1::Durable(_))
        ));
        assert_eq!(state.borrow().executions, completed);
    }
}

#[cfg(unix)]
#[test]
fn replacing_lock_inode_fences_live_execution_and_verified_transcripts() {
    for completed in [0, 4] {
        let root = private_tempdir();
        let state = Rc::new(RefCell::new(Observed::default()));
        let mut owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("single writer owner");
        for _ in 0..completed {
            owner.advance().expect("current effect");
        }

        // The original process still holds an OS lock on the old inode.
        // A second process can obtain the replacement path's lock unless
        // the original owner rechecks the actual directory identity.
        fs::remove_file(root.path().join(crate::durable::SIDECAR_LOCK_FILE))
            .expect("unlink original lock inode");
        let _replacement =
            crate::durable::lock_sidecar(root.path()).expect("second lock on a different inode");

        assert!(matches!(
            owner.advance(),
            Err(CellSplitExecutionErrorV1::Durable(_))
        ));
        assert!(matches!(
            owner.verified_transcript(),
            Err(CellSplitExecutionErrorV1::Durable(_))
        ));
        assert_eq!(state.borrow().executions, completed);
        if completed == 0 {
            assert!(!root.path().join("cell-split-00-prepared.json").exists());
        }
    }
}

#[test]
fn effect_completion_does_not_acknowledge_replaced_local_trust_frames() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let port = FixturePort::new(state.clone());
    let tamper = port.tamper_during_live_readback.clone();
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("owner");
    // The real external commit occurs before its signed live-readback
    // callback. A local trust change at that exact point must leave the
    // prepared intent unreconciled rather than reporting a completed step.
    *tamper.borrow_mut() = Some(root.path().join("cell-split-owner-trust-pins.json"));
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid("owner trust pins drift"))
    ));
    assert_eq!(state.borrow().executions, 1);
    assert_eq!(owner.completed_steps(), 0);
    assert!(root.path().join("cell-split-00-prepared.json").exists());
    assert!(!root.path().join("cell-split-00-committed.json").exists());
    assert!(owner.advance().is_err(), "cannot retry an ambiguous effect");
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn transcript_rejects_local_evidence_replacement_during_live_owner_verification() {
    // Every signed remote receipt remains current. Tampering only with the
    // local frozen plan, pinned owner keys or an earlier committed frame
    // *during* the remote read must nevertheless prevent a positive result.
    for (filename, expected_error) in [
        (
            "cell-split-frozen-plan.json",
            "frozen identity changed during live owner readback",
        ),
        (
            "cell-split-owner-trust-pins.json",
            "frozen identity changed during live owner readback",
        ),
        (
            "cell-split-00-committed.json",
            "committed frame changed during live owner readback",
        ),
    ] {
        let root = private_tempdir();
        let state = Rc::new(RefCell::new(Observed::default()));
        let port = FixturePort::new(state.clone());
        let tamper = port.tamper_during_live_readback.clone();
        let mut owner =
            CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("owner");
        for _ in 0..4 {
            owner.advance().expect("committed original effect");
        }
        *tamper.borrow_mut() = Some(root.path().join(filename));
        assert!(
            matches!(
                owner.verified_transcript(),
                Err(CellSplitExecutionErrorV1::Invalid(reason)) if reason == expected_error
            ),
            "unexpected transcript outcome for {filename}"
        );
        assert_eq!(state.borrow().executions, 4);
    }
}

#[test]
fn transcript_rejects_unknown_frame_injected_during_live_owner_readback() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let port = FixturePort::new(state.clone());
    let tamper = port.tamper_during_live_readback.clone();
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("owner");
    for _ in 0..4 {
        owner.advance().expect("original effect").expect("receipt");
    }
    // The original frames and all four remotely signed receipts stay valid.
    // A fifth frame appears only after the initial namespace scan.
    *tamper.borrow_mut() = Some(root.path().join("cell-split-04-committed.json"));
    assert!(matches!(
        owner.verified_transcript(),
        Err(CellSplitExecutionErrorV1::Invalid(
            "unknown cell split durable frame"
        ))
    ));
    assert_eq!(state.borrow().executions, 4);
}

#[test]
fn new_effect_is_not_acknowledged_if_unknown_frame_arrives_during_readback() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let port = FixturePort::new(state.clone());
    let tamper = port.tamper_during_live_readback.clone();
    let mut owner =
        CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port).expect("owner");
    *tamper.borrow_mut() = Some(root.path().join("cell-split-04-committed.json"));
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(
            "unknown cell split durable frame"
        ))
    ));
    // The real external effect may already exist, so no retry is permitted.
    assert_eq!(state.borrow().executions, 1);
    assert_eq!(owner.completed_steps(), 0);
    assert!(root.path().join("cell-split-00-prepared.json").exists());
    assert!(!root.path().join("cell-split-00-committed.json").exists());
    assert!(owner.advance().is_err());
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn full_transcript_uses_only_four_current_owner_receipts() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let expected_digest;
    {
        let mut owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("owner");
        assert!(owner.verified_transcript().expect("incomplete").is_none());
        for index in 0..4 {
            owner.advance().expect("original effect").expect("receipt");
            if index < 3 {
                assert!(owner.verified_transcript().expect("partial").is_none());
            }
        }
        let before_readbacks = state.borrow().verifications;
        let proof = owner
            .verified_transcript()
            .expect("four owner reads")
            .expect("complete transcript");
        // Export must revalidate all four original effects against their
        // current owner, but not perform the same remote readback twice.
        assert_eq!(state.borrow().verifications - before_readbacks, 4);
        assert_eq!(proof.receipts.len(), 4);
        assert_eq!(proof.plan, plan());
        assert_eq!(
            proof.receipts[0].intent.previous_receipt_digest,
            proof.receipts[0].intent.plan_digest
        );
        for index in 1..4 {
            assert_eq!(
                proof.receipts[index].intent.previous_receipt_digest,
                proof.receipts[index - 1].receipt_digest,
            );
        }
        expected_digest = proof.transcript_digest;
    }
    let mut recovered = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("recovered");
    let before_recovery_readbacks = state.borrow().verifications;
    assert_eq!(
        recovered
            .verified_transcript()
            .expect("fresh owner rechecks")
            .expect("four original effects")
            .transcript_digest,
        expected_digest,
    );
    assert_eq!(state.borrow().verifications - before_recovery_readbacks, 4);
    let last = recovered.verified_transcript().unwrap().unwrap().receipts[3]
        .intent
        .idempotency_key
        .clone();
    assert!(state.borrow_mut().commits.remove(&last).is_some());
    assert!(matches!(
        recovered.verified_transcript(),
        Err(CellSplitExecutionErrorV1::External(_)),
    ));
}

#[test]
fn independent_transcript_signature_verifier_rejects_mutations_without_live_effects() {
    let root = private_tempdir();
    let observed = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(observed.clone()),
    )
    .expect("owner");
    for _ in 0..4 {
        owner.advance().expect("step").expect("receipt");
    }
    let original = owner
        .verified_transcript()
        .expect("live original-owner verification")
        .expect("four-step transcript");
    let reads = observed.borrow().verifications;
    verify_cell_split_execution_transcript_signatures_v1(&original, &trust())
        .expect("independent signature and predecessor-chain verification");
    assert_eq!(observed.borrow().verifications, reads);
    assert_eq!(observed.borrow().executions, 4);

    let mut swapped = original.clone();
    swapped.receipts.swap(0, 1);
    assert!(verify_cell_split_execution_transcript_signatures_v1(&swapped, &trust()).is_err());

    let mut modified = original.clone();
    modified.receipts[0].owner_receipt_bytes.push(0);
    assert!(verify_cell_split_execution_transcript_signatures_v1(&modified, &trust()).is_err());

    let mut missing = original.clone();
    missing.receipts.pop();
    assert!(verify_cell_split_execution_transcript_signatures_v1(&missing, &trust()).is_err());

    let mut forged = original.clone();
    forged.receipts[3].owner_signature_bytes[0] ^= 0x80;
    assert!(verify_cell_split_execution_transcript_signatures_v1(&forged, &trust()).is_err());

    let mut wrong_digest = original.clone();
    wrong_digest.transcript_digest = "11".repeat(32);
    assert!(verify_cell_split_execution_transcript_signatures_v1(&wrong_digest, &trust()).is_err());

    let mut different_plan = plan();
    different_plan.scope_digest = "aa".repeat(32);
    assert!(
        verify_cell_split_execution_transcript_signatures_v1(
            &original,
            &trust_for(&different_plan),
        )
        .is_err()
    );
    // An offline digest/signature check cannot mint or exercise effect authority.
    assert_eq!(observed.borrow().verifications, reads);
    assert_eq!(observed.borrow().executions, 4);
}

#[test]
fn weak_effect_owner_public_key_fails_before_any_coordinator_io() {
    let mut keys = [0, 1, 2, 3].map(|index| signing_key(index).verifying_key());
    let mut identity_bytes = [0_u8; 32];
    identity_bytes[0] = 1;
    let weak = ed25519_dalek::VerifyingKey::from_bytes(&identity_bytes)
        .expect("valid compressed identity point");
    assert!(weak.is_weak());
    keys[2] = weak;
    assert!(matches!(
        CellSplitOwnerTrustV1::new(&plan(), keys),
        Err(CellSplitExecutionErrorV1::Invalid(
            "effect owner has a weak signing key"
        )),
    ));
}

#[test]
fn invalid_frozen_plans_cannot_derive_a_trusted_effect_digest() {
    let original = plan();
    assert_eq!(
        original.digest().expect("validated plan"),
        sha256(&canonical_json(&original).expect("canonical plan"))
    );

    let mut invalid = original.clone();
    invalid.owner_ids[1] = invalid.owner_ids[0].clone();
    assert!(invalid.digest().is_err());

    invalid = original.clone();
    invalid.scope_digest = "00".repeat(32);
    assert!(invalid.digest().is_err());

    invalid = original.clone();
    invalid.child_generation = invalid.parent_generation;
    assert!(invalid.digest().is_err());

    invalid = original;
    invalid.split_id.clear();
    assert!(invalid.digest().is_err());
}

#[test]
fn unknown_step_frame_fences_owner_before_first_effect_and_after_open() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let foreign = root.path().join("cell-split-04-committed.json");
    fs::write(&foreign, b"{}").expect("unrecognized fifth-step frame");
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "unknown cell split durable frame"
        )),
    ));
    assert!(!root.path().join("cell-split-frozen-plan.json").exists());
    assert_eq!(state.borrow().executions, 0);
    fs::remove_file(&foreign).expect("clean injected frame");

    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("clean owner");
    owner.advance().expect("first effect").expect("receipt");
    let injected = root.path().join("cell-split-00-replayed.json");
    fs::write(&injected, b"{}").expect("unrecognized replay marker");
    assert!(matches!(
        owner.advance(),
        Err(CellSplitExecutionErrorV1::Invalid(
            "unknown cell split durable frame"
        )),
    ));
    assert!(matches!(
        owner.verified_transcript(),
        Err(CellSplitExecutionErrorV1::Invalid(
            "unknown cell split durable frame"
        )),
    ));
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn oversized_owner_directory_fails_before_writing_frozen_plan() {
    let root = private_tempdir();
    for index in 0..33 {
        fs::write(root.path().join(format!("unrelated-{index:02}")), b"data")
            .expect("adversarial directory entry");
    }
    let state = Rc::new(RefCell::new(Observed::default()));
    assert!(matches!(
        CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        ),
        Err(CellSplitExecutionErrorV1::Invalid(
            "split ledger namespace exceeds bounded entry limit"
        )),
    ));
    assert!(!root.path().join("cell-split-frozen-plan.json").exists());
    assert_eq!(state.borrow().executions, 0);
}

#[test]
fn post_effect_selection_revocation_keeps_all_stages_pending() {
    for completed_predecessors in 0..4 {
        let root = private_tempdir();
        let state = Rc::new(RefCell::new(Observed::default()));
        {
            let mut owner = CellSplitExecutionOwnerV1::open(
                root.path(),
                plan(),
                trust(),
                FixturePort::new(state.clone()),
            )
            .expect("single writer owner");
            for _ in 0..completed_predecessors {
                owner
                    .advance()
                    .expect("predecessor effect")
                    .expect("receipt");
            }
            let mut admission_reads = 0;
            let rejected = owner.advance_with_admission(|| {
                admission_reads += 1;
                if admission_reads < 3 {
                    Ok(())
                } else {
                    Err("selection withdrawn after external commit".into())
                }
            });
            assert!(matches!(
                rejected,
                Err(CellSplitExecutionErrorV1::External(reason))
                    if reason == "selection withdrawn after external commit"
            ));
            assert_eq!(
                admission_reads, 3,
                "recheck selection after the signed original-owner effect"
            );
            assert_eq!(owner.completed_steps(), completed_predecessors);
            assert_eq!(state.borrow().executions, completed_predecessors + 1);
            assert!(
                root.path()
                    .join(format!(
                        "cell-split-{completed_predecessors:02}-prepared.json"
                    ))
                    .exists(),
                "original intent must remain durable for recovery"
            );
            assert!(
                !root
                    .path()
                    .join(format!(
                        "cell-split-{completed_predecessors:02}-committed.json"
                    ))
                    .exists(),
                "revoked selection must not be acknowledged in the local ledger"
            );
        }

        let mut recovered = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("reopen original prepared intent");
        assert!(matches!(
            recovered.advance_with_admission(|| Err("selection still withdrawn".into())),
            Err(CellSplitExecutionErrorV1::External(reason))
                if reason == "selection still withdrawn"
        ));
        assert_eq!(recovered.completed_steps(), completed_predecessors);
        assert_eq!(
            state.borrow().executions,
            completed_predecessors + 1,
            "denied readback must never replay an external effect"
        );

        let original_receipt = recovered
            .advance_with_admission(|| Ok(()))
            .expect("read-only recovery with current selection")
            .expect("original commit receipt");
        assert_eq!(original_receipt.intent.step.index(), completed_predecessors);
        assert_eq!(recovered.completed_steps(), completed_predecessors + 1);
        assert_eq!(
            state.borrow().executions,
            completed_predecessors + 1,
            "recovery must not execute a second effect"
        );
    }
}

#[test]
fn tamper_during_post_effect_admission_cannot_seal_a_success_frame() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("single writer");
    let frozen = root.path().join("cell-split-frozen-plan.json");
    let mut admission_reads = 0;
    let result = owner.advance_with_admission(|| {
        admission_reads += 1;
        if admission_reads == 3 {
            fs::write(&frozen, b"{}").expect("adversarial plan replacement");
        }
        Ok(())
    });
    assert!(matches!(
        result,
        Err(CellSplitExecutionErrorV1::Invalid("frozen plan drift"))
    ));
    assert_eq!(admission_reads, 3);
    assert_eq!(owner.completed_steps(), 0);
    assert_eq!(state.borrow().executions, 1, "external commit was real");
    assert!(root.path().join("cell-split-00-prepared.json").exists());
    assert!(!root.path().join("cell-split-00-committed.json").exists());
    assert!(owner.advance().is_err(), "corrupted ledger stays denied");
    assert_eq!(state.borrow().executions, 1, "never duplicate effect");
}

#[test]
fn original_effect_withdrawn_during_final_admission_cannot_be_acknowledged() {
    let root = private_tempdir();
    let state = Rc::new(RefCell::new(Observed::default()));
    let mut owner = CellSplitExecutionOwnerV1::open(
        root.path(),
        plan(),
        trust(),
        FixturePort::new(state.clone()),
    )
    .expect("single writer");
    let mut admission_reads = 0;
    let original = state.clone();
    let result = owner.advance_with_admission(|| {
        admission_reads += 1;
        if admission_reads == 3 {
            original.borrow_mut().commits.clear();
        }
        Ok(())
    });
    assert!(matches!(
        result,
        Err(CellSplitExecutionErrorV1::External(_))
    ));
    assert_eq!(admission_reads, 3);
    assert_eq!(owner.completed_steps(), 0);
    assert_eq!(state.borrow().executions, 1, "one real owner effect");
    assert!(root.path().join("cell-split-00-prepared.json").exists());
    assert!(!root.path().join("cell-split-00-committed.json").exists());
    assert!(owner.advance().is_err(), "lost effect remains ambiguous");
    assert_eq!(state.borrow().executions, 1);
}

#[test]
fn final_owner_readback_cannot_acknowledge_late_local_ledger_tamper() {
    for filename in [
        "cell-split-frozen-plan.json",
        "cell-split-owner-trust-pins.json",
        "cell-split-00-prepared.json",
        "cell-split-00-committed.json",
        "cell-split-01-prepared.json",
    ] {
        let root = private_tempdir();
        let state = Rc::new(RefCell::new(Observed::default()));
        let port = FixturePort::new(state.clone());
        let tamper = port.tamper_during_live_readback.clone();
        let mut owner = CellSplitExecutionOwnerV1::open(root.path(), plan(), trust(), port)
            .expect("single writer");
        let altered = root.path().join(filename);
        let mut admission_reads = 0;
        let result = owner.advance_with_admission(|| {
            admission_reads += 1;
            if admission_reads == 3 {
                // The callback completes, then the last signed original
                // owner readback mutates local state before acknowledging.
                *tamper.borrow_mut() = Some(altered.clone());
            }
            Ok(())
        });
        assert!(
            matches!(
                result,
                Err(CellSplitExecutionErrorV1::Invalid(
                    "split ledger changed during final owner readback"
                ))
            ),
            "acknowledged local tampering in {filename}"
        );
        assert_eq!(admission_reads, 3, "final owner readback was reached");
        assert_eq!(owner.completed_steps(), 0);
        assert_eq!(state.borrow().executions, 1, "original effect is real");
        assert_eq!(
            root.path().join("cell-split-00-committed.json").exists(),
            filename == "cell-split-00-committed.json",
            "the coordinator must not write its success frame"
        );
        assert!(owner.advance().is_err(), "corrupted intent stays denied");
        assert_eq!(state.borrow().executions, 1, "no duplicate external effect");
    }
}

#[test]
fn selector_revoked_during_final_original_owner_readback_never_acknowledges_any_stage() {
    for completed_predecessors in 0..4 {
        let root = private_tempdir();
        let state = Rc::new(RefCell::new(Observed::default()));
        let selected = Rc::new(RefCell::new(true));
        let mut owner = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("single writer owner");
        for _ in 0..completed_predecessors {
            owner
                .advance()
                .expect("predecessor effect")
                .expect("signed predecessor receipt");
        }
        let prior_readbacks = state.borrow().verifications;
        // A fresh stage rereads each committed predecessor four times and
        // verifies the new original effect twice. Revoke only during its last
        // signed original-owner readback, after the third admission check.
        owner.port.revoke_selection_on_readback = Some((
            selected.clone(),
            prior_readbacks + completed_predecessors * 4 + 2,
        ));
        let mut admission_reads = 0;
        let rejected = owner.advance_with_admission(|| {
            admission_reads += 1;
            if *selected.borrow() {
                Ok(())
            } else {
                Err("independent selection withdrawn during final owner readback".into())
            }
        });
        assert!(matches!(
            rejected,
            Err(CellSplitExecutionErrorV1::External(reason))
                if reason == "independent selection withdrawn during final owner readback"
        ));
        assert_eq!(admission_reads, 4, "admission must follow the last readback");
        assert!(!*selected.borrow(), "original readback revoked selection");
        assert_eq!(owner.completed_steps(), completed_predecessors);
        assert_eq!(state.borrow().executions, completed_predecessors + 1);
        assert!(
            root.path()
                .join(format!("cell-split-{completed_predecessors:02}-prepared.json"))
                .exists()
        );
        assert!(
            !root
                .path()
                .join(format!("cell-split-{completed_predecessors:02}-committed.json"))
                .exists(),
            "a real effect is not yet an authorized coordinator acknowledgement"
        );

        drop(owner);
        let mut recovered = CellSplitExecutionOwnerV1::open(
            root.path(),
            plan(),
            trust(),
            FixturePort::new(state.clone()),
        )
        .expect("recover original pending intent");
        assert!(matches!(
            recovered.advance_with_admission(|| Err("selection remains withdrawn".into())),
            Err(CellSplitExecutionErrorV1::External(reason))
                if reason == "selection remains withdrawn"
        ));
        assert_eq!(state.borrow().executions, completed_predecessors + 1);
        *selected.borrow_mut() = true;
        let signed_readback = recovered
            .advance_with_admission(|| {
                if *selected.borrow() {
                    Ok(())
                } else {
                    Err("selection remains withdrawn".into())
                }
            })
            .expect("reconcile same original effect")
            .expect("signed original owner receipt");
        assert_eq!(signed_readback.intent.step.index(), completed_predecessors);
        assert_eq!(recovered.completed_steps(), completed_predecessors + 1);
        assert_eq!(
            state.borrow().executions,
            completed_predecessors + 1,
            "recovery must not re-execute an already committed external effect"
        );
    }
}
