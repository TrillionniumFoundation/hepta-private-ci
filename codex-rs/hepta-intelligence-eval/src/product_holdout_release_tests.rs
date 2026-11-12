//! Original file-backed consumption and the actual runner/provider boundary.
//! Estimator rows remain the existing unit fixture, not production admission.

use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::LockedFileFinalHoldoutCasStoreV1;
use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct OriginalCase {
    path: PathBuf,
    fixture: Fixture,
    frozen: ProductFrozenEvaluationPlanV1,
    runner: ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
}

impl OriginalCase {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-original-holdout-release-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)
            .unwrap_or_else(|error| panic!("create original holdout fixture: {error}"));
        let fixture = fixture();
        let frozen = freeze_product_evaluation_plan_v1(
            fixture.cross_fold.clone(),
            fixture.roles.clone(),
            fixture.sources.clone(),
            &fixture.candidate_plan,
            &fixture.baseline_plan,
        )
        .unwrap_or_else(|error| panic!("freeze actual test plan: {error}"));
        let namespace = digest("original-release-namespace");
        let store = LockedFileFinalHoldoutCasStoreV1::create(file, namespace)
            .unwrap_or_else(|error| panic!("create original locked store: {error}"));
        let mut owner = FencedFinalHoldoutOwnerV1::initialize(
            store,
            namespace,
            HoldoutWriterFenceV1 {
                owner_id: id("original-release-owner"),
                generation: 1,
                lease_digest: digest("original-release-lease"),
            },
        )
        .unwrap_or_else(|error| panic!("initialize actual owner: {error}"));
        assert_eq!(
            owner.read_consumption(&frozen.frozen_plan),
            Ok((namespace, None))
        );
        Self {
            path,
            fixture,
            frozen,
            runner: ProductEvaluationRunnerV1::new(owner),
        }
    }

    fn provider(&mut self, mode: ReleaseMode) -> OriginalProvider {
        OriginalProvider {
            path: self.path.clone(),
            plan: self.frozen.frozen_plan.clone(),
            inputs: self.fixture.provider.inputs.take(),
            mode,
            calls: 0,
            callbacks: 0,
            observed: None,
            original_bytes: None,
        }
    }

    fn run(
        &mut self,
        provider: &mut OriginalProvider,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        self.runner.evaluate_temporal_comparison(
            &self.frozen,
            &self.fixture.candidate_plan,
            &self.fixture.baseline_plan,
            provider,
        )
    }
}

impl Drop for OriginalCase {
    fn drop(&mut self) {
        // The actual file owner still holds its handle until this scope ends.
        let _ = fs::remove_file(&self.path);
    }
}

#[derive(Clone, Copy)]
enum ReleaseMode {
    Accept,
    CorruptInside,
    CorruptWithoutBorrow,
    Indeterminate,
}

struct OriginalProvider {
    path: PathBuf,
    plan: CrossFoldPlanReceiptV1,
    inputs: Option<TemporalComparisonInputsV1>,
    mode: ReleaseMode,
    calls: usize,
    callbacks: usize,
    observed: Option<(
        Digest32,
        CrossFoldPlanReceiptV1,
        FinalHoldoutJournalReceiptV1,
    )>,
    original_bytes: Option<Vec<u8>>,
}

fn overwrite(path: &Path, bytes: &[u8]) {
    let mut file = OpenOptions::new()
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("open original inode for physical fault: {error}"));
    file.write_all(bytes)
        .and_then(|()| file.set_len(bytes.len() as u64))
        .and_then(|()| file.sync_all())
        .unwrap_or_else(|error| panic!("persist actual fault or restoration: {error}"));
}

impl OriginalProvider {
    fn corrupt(&mut self) {
        let original = fs::read(&self.path)
            .unwrap_or_else(|error| panic!("read original bytes before fault: {error}"));
        let mut corrupted = original.clone();
        corrupted[0] ^= 1;
        assert_eq!(corrupted.len(), original.len());
        overwrite(&self.path, &corrupted);
        self.original_bytes = Some(original);
    }

    fn restore(&self) {
        let original = self
            .original_bytes
            .as_ref()
            .unwrap_or_else(|| panic!("the first corrupting call did not execute"));
        overwrite(&self.path, original);
        assert_eq!(
            fs::read(&self.path).unwrap_or_else(|error| panic!("read restoration: {error}")),
            *original
        );
    }
}

impl FinalHoldoutProviderV1 for OriginalProvider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(self.plan.final_holdout_digest)
    }

    fn release_after_original_consumption(
        &mut self,
        consumed: OriginalFinalHoldoutConsumptionV1<'_>,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.calls += 1;
        if matches!(self.mode, ReleaseMode::CorruptWithoutBorrow) {
            drop(consumed);
            self.corrupt();
            return self.inputs.take().ok_or(ProductProviderErrorV1::Rejected);
        }
        consumed.with_current_consumption(|namespace, plan, receipt| {
            self.callbacks += 1;
            assert_eq!(namespace, digest("original-release-namespace"));
            assert_eq!(plan, &self.plan);
            assert_eq!(receipt.disposition, HoldoutUseDispositionV1::Recorded);
            self.observed = Some((namespace, plan.clone(), receipt.clone()));
            match self.mode {
                ReleaseMode::Accept => {}
                ReleaseMode::CorruptInside => self.corrupt(),
                ReleaseMode::Indeterminate => return Err(ProductProviderErrorV1::Indeterminate),
                ReleaseMode::CorruptWithoutBorrow => panic!("already handled without borrow"),
            }
            self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
        })
    }
}

#[test]
fn original_holdout_release_requires_actual_borrow_and_refuses_receipt_replay() {
    let mut case = OriginalCase::new();
    let mut provider = case.provider(ReleaseMode::Accept);
    let executed = case
        .run(&mut provider)
        .unwrap_or_else(|error| panic!("actual original release: {error}"));
    assert_eq!((provider.calls, provider.callbacks), (1, 1));
    assert_eq!(
        provider.observed,
        Some((
            digest("original-release-namespace"),
            case.frozen.frozen_plan.clone(),
            executed.holdout.clone()
        ))
    );
    assert_eq!(
        provider.release_after_consumption(&executed.holdout).err(),
        Some(ProductProviderErrorV1::Rejected)
    );
    assert_eq!(
        case.run(&mut provider).err(),
        Some(ProductEvaluationError::Binding(
            "final holdout already consumed"
        ))
    );
    assert_eq!((provider.calls, provider.callbacks), (1, 1));
}

#[test]
fn original_holdout_release_corruption_then_restore_never_reaches_fit() {
    let mut case = OriginalCase::new();
    let mut provider = case.provider(ReleaseMode::CorruptInside);
    assert_eq!(
        case.run(&mut provider).err(),
        Some(ProductEvaluationError::Holdout(FencedHoldoutError::Store(
            crate::FinalHoldoutCasStoreError::Indeterminate
        )))
    );
    assert_eq!((provider.calls, provider.callbacks), (1, 1));
    assert!(
        provider.observed.is_some(),
        "the successful original physical read preceded corruption"
    );
    provider.restore();
    assert_eq!(
        case.run(&mut provider).err(),
        Some(ProductEvaluationError::Holdout(
            FencedHoldoutError::Indeterminate
        ))
    );
    assert_eq!((provider.calls, provider.callbacks), (1, 1));
}

#[test]
fn original_holdout_release_postcheck_survives_provider_ignoring_borrow() {
    let mut case = OriginalCase::new();
    let mut provider = case.provider(ReleaseMode::CorruptWithoutBorrow);
    assert_eq!(
        case.run(&mut provider).err(),
        Some(ProductEvaluationError::Holdout(FencedHoldoutError::Store(
            crate::FinalHoldoutCasStoreError::Indeterminate
        )))
    );
    assert_eq!((provider.calls, provider.callbacks), (1, 0));
    provider.restore();
    assert_eq!(
        case.run(&mut provider).err(),
        Some(ProductEvaluationError::Holdout(
            FencedHoldoutError::Indeterminate
        ))
    );
    assert_eq!((provider.calls, provider.callbacks), (1, 0));
}

#[test]
fn original_holdout_release_indeterminate_response_cannot_release_again() {
    let mut case = OriginalCase::new();
    let mut provider = case.provider(ReleaseMode::Indeterminate);
    assert_eq!(
        case.run(&mut provider).err(),
        Some(ProductEvaluationError::Provider(
            ProductProviderErrorV1::Indeterminate
        ))
    );
    assert_eq!((provider.calls, provider.callbacks), (1, 1));
    assert_eq!(
        case.run(&mut provider).err(),
        Some(ProductEvaluationError::Binding(
            "final holdout already consumed"
        ))
    );
    assert_eq!((provider.calls, provider.callbacks), (1, 1));
}
