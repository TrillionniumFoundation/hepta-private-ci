//! Actual Cell journals and original publication owner; inputs remain synthetic.

use std::cell::Cell;
use std::rc::Rc;

use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellQualificationErrorV1;
use crate::OriginalCellQualificationSourceV1;
use crate::OriginalProductQualificationSourceV1;

fn publish<W: AnchorWitnessStore>(
    fixture: &mut OriginalQualificationFixture,
    owner: &mut OriginalProductQualificationOwnerV1<W>,
) -> Result<CellEvaluationQualificationV1, OriginalCellQualificationErrorV1> {
    fixture.runner.publish_original_qualification(
        owner,
        &mut fixture.executions,
        OriginalCellQualificationSourceV1 {
            plan: &fixture.cell_plan,
            journals: CellEvaluationJournalsV1 {
                candidate: &fixture.candidate,
                fixed_expert: &fixture.fixed,
            },
            product: OriginalProductQualificationSourceV1 {
                plan: &fixture.plan,
                candidate_plan: &fixture.candidate_plan,
                baseline_plan: &fixture.baseline_plan,
                evaluator: &fixture.context.evaluator,
                verifier: &fixture.verifier,
            },
        },
        &fixture.context,
        &fixture.evidence,
    )
}

fn readback<W: AnchorWitnessStore>(
    fixture: &mut OriginalQualificationFixture,
    owner: &mut OriginalProductQualificationOwnerV1<W>,
) -> Result<CellEvaluationQualificationV1, OriginalCellQualificationErrorV1> {
    fixture.runner.readback_original_qualification(
        owner,
        &mut fixture.executions,
        OriginalCellQualificationSourceV1 {
            plan: &fixture.cell_plan,
            journals: CellEvaluationJournalsV1 {
                candidate: &fixture.candidate,
                fixed_expert: &fixture.fixed,
            },
            product: OriginalProductQualificationSourceV1 {
                plan: &fixture.plan,
                candidate_plan: &fixture.candidate_plan,
                baseline_plan: &fixture.baseline_plan,
                evaluator: &fixture.trust.signers[1].principal,
                verifier: &fixture.verifier,
            },
        },
    )
}

#[test]
fn cell_publication_and_file_reopen_preserve_complete_original_qualification() {
    let fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let (mut fixture, source_before) = fixture.snapshot_source_bytes();
    initialize_publication(&path);
    let mut publication = recover_publication(&path);
    let first = checked(publish(&mut fixture, &mut publication));
    assert_eq!(first.comparison(), fixture.cell_plan.record());
    assert_eq!(
        first.product(),
        &checked(fixture.readback(&mut publication))
    );
    assert_eq!(first.authority(), AuthorityPosture::DENY_ALL);
    let (mut publication, saved) = snapshot_publication(publication, &path);
    assert_eq!(checked(publish(&mut fixture, &mut publication)), first);
    assert_eq!(checked(readback(&mut fixture, &mut publication)), first);
    drop(publication);
    fixture.evidence.generator_plan.signature.fill(0);
    fixture.evidence.evaluator_bundle.signature.fill(0);
    fixture.context.generator.principal_id = id("discarded-caller-context");
    let mut fixture = fixture.reopen_sources();
    let mut publication = checked(OriginalProductQualificationOwnerV1::recover(
        existing(&path.join("publication")),
        witness(existing(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    assert_eq!(checked(readback(&mut fixture, &mut publication)), first);
    drop(publication);
    assert_eq!(publication_bytes(&path), saved);
    let (fixture, source_after) = fixture.snapshot_source_bytes();
    assert_eq!(source_after, source_before);
    assert_eq!(fixture.provider_calls, (1, 1));
}

#[test]
fn missing_cell_publication_is_read_only_and_does_not_issue() {
    let fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let (mut fixture, source_before) = fixture.snapshot_source_bytes();
    let before = initialize_publication(&path);
    let mut publication = recover_publication(&path);
    assert!(matches!(
        readback(&mut fixture, &mut publication),
        Err(OriginalCellQualificationErrorV1::Publication(
            OriginalProductQualificationErrorV1::Owner(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing
            ))
        ))
    ));
    drop(publication);
    assert_eq!(publication_bytes(&path), before);
    let (_fixture, source_after) = fixture.snapshot_source_bytes();
    assert_eq!(source_after, source_before);
}

#[test]
fn complete_cell_product_plan_is_checked_before_publication_or_readback() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let before = initialize_publication(&path);
    let mut publication = recover_publication(&path);
    let original_digest = fixture.plan.frozen_plan.plan_digest;
    fixture.plan.frozen_plan.plan_id = id("changed-plan-retaining-original-digest");
    assert_eq!(fixture.plan.frozen_plan.plan_digest, original_digest);
    for result in [
        publish(&mut fixture, &mut publication),
        readback(&mut fixture, &mut publication),
    ] {
        assert!(matches!(
            result,
            Err(OriginalCellQualificationErrorV1::Cell(
                CellEvaluationErrorV1::Binding("original Cell qualification product plan")
            ))
        ));
    }
    drop(publication);
    assert_eq!(publication_bytes(&path), before);
}

#[test]
fn changed_candidate_or_fixed_cut_cannot_publish_or_reuse_cell_qualification() {
    for selected in ["candidate", "fixed"] {
        let mut fixture = OriginalQualificationFixture::new();
        let path = fixture.directory.path().to_path_buf();
        initialize_publication(&path);
        let mut publication = recover_publication(&path);
        checked(publish(&mut fixture, &mut publication));
        let (mut publication, before) = snapshot_publication(publication, &path);
        let journal = if selected == "candidate" {
            &mut fixture.candidate
        } else {
            &mut fixture.fixed
        };
        let snapshot = checked(journal.snapshot()).clone();
        checked(journal.resume());
        checked(journal.drain());
        assert_eq!(journal.snapshot(), Ok(&snapshot));
        for result in [
            publish(&mut fixture, &mut publication),
            readback(&mut fixture, &mut publication),
        ] {
            assert!(matches!(
                result,
                Err(OriginalCellQualificationErrorV1::Cell(
                    CellEvaluationErrorV1::Binding("Cell journal changed after registration")
                ))
            ));
        }
        drop(publication);
        assert_eq!(publication_bytes(&path), before);
    }
}

#[test]
fn invalid_original_signature_does_not_become_a_cell_qualification() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let before = initialize_publication(&path);
    let mut publication = recover_publication(&path);
    fixture.evidence.evaluator_bundle.signature[0] ^= 1;
    assert!(matches!(
        publish(&mut fixture, &mut publication),
        Err(OriginalCellQualificationErrorV1::Publication(_))
    ));
    drop(publication);
    assert_eq!(publication_bytes(&path), before);
}

struct RefuseClaimWitness(FileAnchorWitnessStore);
impl AnchorWitnessStore for RefuseClaimWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if next.sequence == 2 {
            return Err(WitnessStoreError::Indeterminate);
        }
        self.0.compare_and_swap(expected, next)
    }
}

#[test]
fn cell_bridge_preserves_uncertain_claim_and_original_pending_recovery() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let mut publication = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        RefuseClaimWitness(witness(file(&path.join("publication-witness")))),
        digest("publication-namespace"),
    ));
    assert!(matches!(
        publish(&mut fixture, &mut publication),
        Err(OriginalCellQualificationErrorV1::Publication(
            OriginalProductQualificationErrorV1::Owner(
                LearningOriginalOwnerErrorV1::CommitUncertain
            )
        ))
    ));
    drop(publication);
    let bytes = checked(fs::read(path.join("publication")));
    let mut publication = checked(OriginalProductQualificationOwnerV1::recover(
        existing(&path.join("publication")),
        witness(existing(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    for result in [
        readback(&mut fixture, &mut publication),
        publish(&mut fixture, &mut publication),
    ] {
        assert!(matches!(
            result,
            Err(OriginalCellQualificationErrorV1::Publication(
                OriginalProductQualificationErrorV1::Owner(LearningOriginalOwnerErrorV1::Pending)
            ))
        ));
    }
    drop(publication);
    assert_eq!(checked(fs::read(path.join("publication"))), bytes);
    assert_eq!(fixture.provider_calls, (1, 1));
}

struct CountedWitness {
    inner: FileAnchorWitnessStore,
    reads: Rc<Cell<u64>>,
    reject_at: Rc<Cell<Option<u64>>>,
}
impl AnchorWitnessStore for CountedWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        let read = self.reads.get() + 1;
        self.reads.set(read);
        if self.reject_at.get().is_some_and(|limit| read >= limit) {
            return Err(WitnessStoreError::Indeterminate);
        }
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn cell_bridge_checks_publication_again_after_its_journal_postcheck() {
    let fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let (mut fixture, source_before) = fixture.snapshot_source_bytes();
    initialize_publication(&path);
    let mut initial = recover_publication(&path);
    let original = checked(fixture.publish(&mut initial));
    drop(initial);
    let before = publication_bytes(&path);
    let reads = Rc::new(Cell::new(0));
    let reject_at = Rc::new(Cell::new(None));
    let mut publication = checked(OriginalProductQualificationOwnerV1::recover(
        existing(&path.join("publication")),
        CountedWitness {
            inner: witness(existing(&path.join("publication-witness"))),
            reads: Rc::clone(&reads),
            reject_at: Rc::clone(&reject_at),
        },
        digest("publication-namespace"),
    ));
    let start = reads.get();
    assert_eq!(checked(fixture.readback(&mut publication)), original);
    let per_readback = reads.get() - start;
    assert!(per_readback > 0);
    // Allow the first complete original read; reject the second read after the
    // bridge's Cell journal postcheck. This is a witness response fault, not a
    // claim that the cached file witness detects arbitrary filesystem writes.
    reject_at.set(Some(reads.get() + per_readback + 1));
    assert!(matches!(
        readback(&mut fixture, &mut publication),
        Err(OriginalCellQualificationErrorV1::Publication(_))
    ));
    drop(publication);
    assert_eq!(publication_bytes(&path), before);
    let (_fixture, source_after) = fixture.snapshot_source_bytes();
    assert_eq!(source_after, source_before);
}
