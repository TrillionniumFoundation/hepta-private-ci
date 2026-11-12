//! Real file/CAS/provider boundary checks over explicit synthetic test cohorts.
//! Test keys are inherited from the mechanism fixture, never deployment custody.

use super::*;
use crate::FinalHoldoutCasAnchorV1;
use crate::FinalHoldoutCasRecordV1;
use crate::FinalHoldoutCasStoreError;
use crate::LockedFileFinalHoldoutCasStoreV1;
use crate::LockedFileProductEvaluationExecutionStoreV1;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Files {
    root: PathBuf,
}
impl Files {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-physical-holdout-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed),
        ));
        fs::create_dir(&root).expect("exclusive test directory");
        Self { root }
    }
    fn create(&self, name: &str) -> File {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(self.root.join(name))
            .expect("exclusive original file")
    }
    fn open(&self, name: &str) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join(name))
            .expect("original file")
    }
    fn bytes(&self) -> [Vec<u8>; 2] {
        ["holdout", "executions"]
            .map(|name| fs::read(self.root.join(name)).expect("original physical bytes"))
    }
    fn replace_holdout(&self, bytes: &[u8]) {
        let mut file = self.open("holdout");
        assert_eq!(
            file.metadata().expect("original length").len(),
            bytes.len() as u64
        );
        file.seek(SeekFrom::Start(0)).expect("adversarial position");
        file.write_all(bytes)
            .expect("adversarial same-length write");
        file.sync_all().expect("adversarial sync");
    }
}
impl Drop for Files {
    fn drop(&mut self) {
        let _ = fs::remove_file(self.root.join("holdout"));
        let _ = fs::remove_file(self.root.join("executions"));
        let _ = fs::remove_dir(&self.root);
    }
}

#[derive(Clone, Copy)]
enum CasAck {
    Normal,
    BeforeWrite,
    AfterWrite,
}
struct OriginalCas {
    original: LockedFileFinalHoldoutCasStoreV1,
    lost: CasAck,
}
impl FinalHoldoutCasStoreV1 for OriginalCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        self.original.load(binding)
    }
    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        // Only the real final-holdout consumption is faulted, after execution
        // claimed Pending. Original fence initialization always uses real CAS.
        let lost = if next.journal.records.is_empty() {
            CasAck::Normal
        } else {
            std::mem::replace(&mut self.lost, CasAck::Normal)
        };
        if matches!(lost, CasAck::BeforeWrite) {
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        self.original.compare_and_swap(binding, expected, next)?;
        if matches!(lost, CasAck::AfterWrite) {
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        Ok(())
    }
}

struct FileHarness {
    runner: Option<ProductEvaluationRunnerV1<OriginalCas>>,
    executions: Option<LockedFileProductEvaluationExecutionStoreV1>,
    fixture: Fixture,
    frozen: ProductFrozenEvaluationPlanV1,
    context: ProductQualificationContextV1,
    verifier: LearningEvidenceVerifierV1,
    attestor: Attestor,
    minimum: FinalHoldoutCasAnchorV1,
    now: u64,
    files: Files,
}
impl FileHarness {
    fn new(lost: CasAck) -> Self {
        let Harness {
            fixture,
            frozen,
            context,
            verifier,
            attestor,
            now,
            ..
        } = Harness::new();
        let files = Files::new();
        let original = LockedFileFinalHoldoutCasStoreV1::create(
            files.create("holdout"),
            digest("holdout-binding"),
        )
        .expect("real locked holdout store");
        let owner = FencedFinalHoldoutOwnerV1::initialize(
            OriginalCas { original, lost },
            digest("holdout-binding"),
            HoldoutWriterFenceV1 {
                owner_id: id("evaluation-owner"),
                generation: 1,
                lease_digest: digest("lease-1"),
            },
        )
        .expect("real original fence initialization");
        let minimum = owner.anchor();
        let executions = LockedFileProductEvaluationExecutionStoreV1::create(
            files.create("executions"),
            digest("physical-executions"),
        )
        .expect("real original execution file");
        Self {
            runner: Some(ProductEvaluationRunnerV1::new(owner)),
            executions: Some(executions),
            fixture,
            frozen,
            context,
            verifier,
            attestor,
            minimum,
            now,
            files,
        }
    }
    fn run(&mut self) -> Result<ProductTemporalEvaluationReceiptV1, Error> {
        let clock = || Ok(self.now);
        self.runner
            .as_mut()
            .expect("original runner")
            .evaluate_or_readback_temporal_comparison(
                &ProductEvaluationExecutionRequestV1 {
                    plan: &self.frozen,
                    candidate_plan: &self.fixture.candidate_plan,
                    baseline_plan: &self.fixture.baseline_plan,
                    evaluator: &self.context.evaluator,
                    verifier: &self.verifier,
                    clock: &clock,
                },
                &mut self.fixture.provider,
                self.executions.as_mut().expect("original executions"),
                &mut self.attestor,
            )
    }
    fn readback(&mut self) -> Result<ProductTemporalEvaluationReceiptV1, Error> {
        let clock = || Ok(self.now);
        self.runner
            .as_mut()
            .expect("original runner")
            .readback_temporal_comparison(
                &ProductEvaluationExecutionRequestV1 {
                    plan: &self.frozen,
                    candidate_plan: &self.fixture.candidate_plan,
                    baseline_plan: &self.fixture.baseline_plan,
                    evaluator: &self.context.evaluator,
                    verifier: &self.verifier,
                    clock: &clock,
                },
                self.executions.as_mut().expect("original executions"),
            )
    }
    fn reopen_original(&mut self) {
        let runner = self.runner.take().expect("original runner");
        let fence = runner.holdout.fence().clone();
        drop(runner);
        let mut executions = self.executions.take().expect("original executions");
        let minimum = executions
            .read_current_anchor()
            .expect("physical original execution floor");
        drop(executions);
        let original = LockedFileFinalHoldoutCasStoreV1::recover(
            self.files.open("holdout"),
            digest("holdout-binding"),
            Some(self.minimum),
        )
        .expect("original minimum prefix, no repair");
        let owner = FencedFinalHoldoutOwnerV1::recover(
            OriginalCas {
                original,
                lost: CasAck::Normal,
            },
            digest("holdout-binding"),
            fence,
        )
        .expect("same original holdout fence");
        self.runner = Some(ProductEvaluationRunnerV1::new(owner));
        self.executions = Some(
            LockedFileProductEvaluationExecutionStoreV1::recover(
                self.files.open("executions"),
                digest("physical-executions"),
                minimum,
            )
            .expect("original physical execution history"),
        );
    }
}

#[test]
fn holdout_current_lost_cas_ack_preserves_pending_without_provider_replay() {
    for lost in [CasAck::BeforeWrite, CasAck::AfterWrite] {
        let mut test = FileHarness::new(lost);
        let before = test.files.bytes();
        assert_eq!(
            test.run(),
            Err(Error::Evaluation(ProductEvaluationError::Holdout(
                crate::FencedHoldoutError::Indeterminate,
            )))
        );
        let after = test.files.bytes();
        if matches!(lost, CasAck::BeforeWrite) {
            assert_eq!(after[0], before[0], "failed ACK may precede the real write");
        } else {
            assert_ne!(
                after[0], before[0],
                "failed ACK may follow the durable write"
            );
        }
        assert_ne!(
            after[1], before[1],
            "the original execution already claimed Pending"
        );
        assert_eq!(
            (test.fixture.provider.release_count, test.attestor.calls),
            (0, 0)
        );
        assert_eq!(
            test.run(),
            Err(Error::Evaluation(ProductEvaluationError::Holdout(
                crate::FencedHoldoutError::Poisoned,
            )))
        );
        assert_eq!(test.files.bytes(), after);
        test.reopen_original();
        assert_eq!(test.readback(), Err(Error::Pending));
        assert_eq!(test.run(), Err(Error::Pending));
        assert_eq!(
            (test.fixture.provider.release_count, test.attestor.calls),
            (0, 0)
        );
        assert_eq!(
            test.files.bytes(),
            after,
            "recovery never reconsumes or repairs Pending"
        );
    }
}

#[test]
fn holdout_current_completed_execution_readback_requires_physical_original() {
    let mut test = FileHarness::new(CasAck::Normal);
    let completed = test.run().expect("actual original execution");
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
    assert_eq!(test.readback().expect("original completed read"), completed);
    let original = test.files.bytes();
    let mut changed = original[0].clone();
    let payload_byte = changed.len() - 33;
    changed[payload_byte] ^= 1;
    test.files.replace_holdout(&changed);
    let physical_error = Err(Error::Evaluation(ProductEvaluationError::Holdout(
        crate::FencedHoldoutError::Indeterminate,
    )));
    assert_eq!(test.readback(), physical_error);
    assert!(
        test.runner
            .as_ref()
            .expect("original runner")
            .holdout
            .is_poisoned()
    );
    test.files.replace_holdout(&original[0]);
    assert_eq!(
        test.readback(),
        Err(Error::Evaluation(ProductEvaluationError::Holdout(
            crate::FencedHoldoutError::Poisoned,
        ))),
        "restoring bytes cannot unfence this owner"
    );
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
    assert_eq!(test.files.bytes(), original);
    test.reopen_original();
    assert_eq!(
        test.readback().expect("exact original cold read"),
        completed
    );
    assert_eq!(test.run().expect("existing completion only"), completed);
    assert_eq!(
        (test.fixture.provider.release_count, test.attestor.calls),
        (1, 1)
    );
    assert_eq!(
        test.files.bytes(),
        original,
        "no release, resigning or fresh execution"
    );
}
