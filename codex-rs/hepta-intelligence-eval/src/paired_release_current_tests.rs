//! Current-owner regressions for the paired profile and legacy readback.
use super::PairedDataV1;
use super::PairedEvaluationError;
use super::PairedFinalHoldoutProviderV1;
use super::ProductProviderErrorV1;
use super::holdout_release::OriginalPairedFinalHoldoutConsumptionV1;
use super::holdout_release::release_original_frozen_paired_holdout;
use super::tests::sign;
use super::tests::trust;
use crate::FencedFinalHoldoutOwnerV1;
use crate::FencedHoldoutError;
use crate::FinalHoldoutCasRecordV1;
use crate::FinalHoldoutCasStoreError;
use crate::FinalHoldoutCasStoreV1;
use crate::FrozenPairedPlanV1;
use crate::PairedHoldoutJournalReceiptV1;
use crate::paired_data::tests::fixture;
use crate::paired_observation_signing_payload_v1;
use crate::paired_owner_tests::MemoryCas;
use crate::paired_owner_tests::d;
use crate::paired_owner_tests::fence;
use crate::paired_owner_tests::ope;
use crate::paired_owner_tests::paired;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::rc::Rc;

#[derive(Clone, Default)]
struct ObservedCas {
    inner: MemoryCas,
    uncertain_read: Rc<Cell<bool>>,
    writes: Rc<Cell<usize>>,
}

impl FinalHoldoutCasStoreV1 for ObservedCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        if self.uncertain_read.get() {
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        self.inner.load(binding)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        self.writes.set(self.writes.get() + 1);
        self.inner.compare_and_swap(binding, expected, next)
    }
}

#[test]
fn mixed_journal_preserves_original_legacy_readback_without_a_write() {
    let store = MemoryCas::default();
    let mut owner =
        FencedFinalHoldoutOwnerV1::initialize(store.clone(), d("binding"), fence(/*generation*/ 1))
            .expect("owner");
    let legacy = ope("legacy-read", d("legacy-source"));
    let recorded = owner.consume(&legacy).expect("legacy recorded");
    let paired_plan = paired("paired-read");
    owner.consume_paired(&paired_plan).expect("paired recorded");
    let before = store.state.borrow().clone();
    assert_eq!(
        owner.read_consumption(&legacy),
        Ok((d("binding"), Some(recorded))),
    );
    assert_eq!(*store.state.borrow(), before);
    let cross_profile = ope("paired-read", d("another-source"));
    assert_eq!(
        owner.read_consumption(&cross_profile),
        Err(FencedHoldoutError::Binding),
    );
    assert_eq!(*store.state.borrow(), before);
}

#[test]
fn prior_legacy_read_uncertainty_blocks_paired_consumption_without_cas() {
    let store = ObservedCas::default();
    let mut owner =
        FencedFinalHoldoutOwnerV1::initialize(store.clone(), d("binding"), fence(/*generation*/ 1))
            .expect("owner");
    let legacy = ope("legacy-read", d("legacy-source"));
    owner.consume(&legacy).expect("legacy recorded");
    let before = store.inner.state.borrow().clone();
    let writes = store.writes.get();
    store.uncertain_read.set(/*value*/ true);
    assert_eq!(
        owner.read_consumption(&legacy),
        Err(FencedHoldoutError::Store(
            FinalHoldoutCasStoreError::Indeterminate
        )),
    );
    store.uncertain_read.set(/*value*/ false);
    assert_eq!(
        owner.consume_paired(&paired("paired-read")),
        Err(FencedHoldoutError::Indeterminate),
    );
    assert!(owner.is_poisoned());
    assert_eq!(*store.inner.state.borrow(), before);
    assert_eq!(store.writes.get(), writes);
}

#[derive(Clone, Copy)]
enum CallbackOutcome {
    Accepted,
    Rejected,
}
#[derive(Clone, Copy)]
enum BorrowUse {
    Observed,
    Ignored,
}

struct TakeoverProvider {
    store: MemoryCas,
    plan: FrozenPairedPlanV1,
    data: PairedDataV1,
    evidence: SignedLearningEvidenceV1,
    releases: usize,
    outcome: CallbackOutcome,
    borrow_use: BorrowUse,
}

impl TakeoverProvider {
    fn new(store: MemoryCas, outcome: CallbackOutcome, borrow_use: BorrowUse) -> Self {
        let (plan, data) = fixture();
        let verifier = trust(/*shared_controller*/ false);
        let evidence = sign(
            &verifier,
            /*index*/ 1,
            &paired_observation_signing_payload_v1(&plan).expect("observer payload"),
        );
        Self {
            store,
            plan,
            data,
            evidence,
            releases: 0,
            outcome,
            borrow_use,
        }
    }

    fn take_over_and_release(
        &mut self,
    ) -> Result<(PairedDataV1, SignedLearningEvidenceV1), ProductProviderErrorV1> {
        self.releases += 1;
        let replacement = FencedFinalHoldoutOwnerV1::recover(
            self.store.clone(),
            d("binding"),
            fence(/*generation*/ 2),
        )
        .expect("take over original authoritative store");
        drop(replacement);
        match self.outcome {
            CallbackOutcome::Accepted => Ok((self.data.clone(), self.evidence.clone())),
            CallbackOutcome::Rejected => Err(ProductProviderErrorV1::Rejected),
        }
    }
}

impl PairedFinalHoldoutProviderV1 for TakeoverProvider {
    fn identities(&mut self) -> Result<(Digest32, Digest32), ProductProviderErrorV1> {
        Ok((
            self.plan.spec().holdout_digest,
            self.plan.spec().outcome_bundle_digest,
        ))
    }

    fn release_after_consumption(
        &mut self,
        receipt: &PairedHoldoutJournalReceiptV1,
    ) -> Result<(PairedDataV1, SignedLearningEvidenceV1), ProductProviderErrorV1> {
        receipt
            .validate(&self.plan)
            .map_err(|_| ProductProviderErrorV1::Rejected)?;
        self.take_over_and_release()
    }

    fn release_after_original_consumption(
        &mut self,
        consumed: OriginalPairedFinalHoldoutConsumptionV1<'_>,
    ) -> Result<(PairedDataV1, SignedLearningEvidenceV1), ProductProviderErrorV1> {
        match self.borrow_use {
            BorrowUse::Observed => consumed
                .with_current_consumption(|_, _, receipt| self.release_after_consumption(receipt)),
            BorrowUse::Ignored => self.take_over_and_release(),
        }
    }
}

#[test]
fn paired_release_refuses_a_stale_original_owner_before_provider_callback() {
    let store = MemoryCas::default();
    let mut owner =
        FencedFinalHoldoutOwnerV1::initialize(store.clone(), d("binding"), fence(/*generation*/ 1))
            .expect("owner");
    let mut provider = TakeoverProvider::new(
        store.clone(),
        CallbackOutcome::Accepted,
        BorrowUse::Observed,
    );
    let plan = provider.plan.clone();
    let receipt = owner.consume_paired(&plan).expect("paired recorded");
    let replacement =
        FencedFinalHoldoutOwnerV1::recover(store.clone(), d("binding"), fence(/*generation*/ 2))
            .expect("replacement");
    let before = store.state.borrow().clone();
    assert_eq!(
        release_original_frozen_paired_holdout(&mut owner, &plan, &receipt, &mut provider),
        Err(PairedEvaluationError::Holdout(
            FencedHoldoutError::StaleFence
        )),
    );
    assert_eq!(provider.releases, 0);
    assert!(owner.is_poisoned());
    assert_eq!(*store.state.borrow(), before);
    drop(replacement);
}

#[test]
fn paired_release_rechecks_the_original_owner_after_success_and_error() {
    for outcome in [CallbackOutcome::Accepted, CallbackOutcome::Rejected] {
        let store = MemoryCas::default();
        let mut owner = FencedFinalHoldoutOwnerV1::initialize(
            store.clone(),
            d("binding"),
            fence(/*generation*/ 1),
        )
        .expect("owner");
        let mut provider = TakeoverProvider::new(store.clone(), outcome, BorrowUse::Observed);
        let plan = provider.plan.clone();
        let receipt = owner.consume_paired(&plan).expect("paired recorded");
        assert_eq!(
            release_original_frozen_paired_holdout(&mut owner, &plan, &receipt, &mut provider),
            Err(PairedEvaluationError::Holdout(FencedHoldoutError::Poisoned)),
        );
        assert_eq!(provider.releases, 1);
        assert_eq!(
            store.state.borrow().as_ref().expect("record").fence,
            fence(/*generation*/ 2)
        );
        assert!(owner.is_poisoned());
        assert_eq!(
            owner.consume_paired(&plan),
            Err(FencedHoldoutError::Poisoned)
        );
    }
}

#[test]
fn paired_release_checks_the_owner_even_when_provider_ignores_its_borrow() {
    let store = MemoryCas::default();
    let mut owner =
        FencedFinalHoldoutOwnerV1::initialize(store.clone(), d("binding"), fence(/*generation*/ 1))
            .expect("owner");
    let mut provider =
        TakeoverProvider::new(store.clone(), CallbackOutcome::Accepted, BorrowUse::Ignored);
    let plan = provider.plan.clone();
    let receipt = owner.consume_paired(&plan).expect("paired recorded");
    assert_eq!(
        release_original_frozen_paired_holdout(&mut owner, &plan, &receipt, &mut provider),
        Err(PairedEvaluationError::Holdout(
            FencedHoldoutError::StaleFence
        )),
    );
    assert_eq!(provider.releases, 1);
    assert!(owner.is_poisoned());
    assert_eq!(
        store.state.borrow().as_ref().expect("record").fence,
        fence(/*generation*/ 2)
    );
}
