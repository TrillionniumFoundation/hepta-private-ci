//! Original publication witness faults retain Pending/CommitUncertain semantics.

use std::cell::Cell;
use std::cell::RefCell;
use std::rc::Rc;

use pretty_assertions::assert_eq;

use super::*;

#[derive(Clone, Copy)]
enum LostAck {
    BeforeWrite,
    AfterWrite,
}
struct LostAckWitness {
    inner: FileAnchorWitnessStore,
    sequence: u64,
    fault: LostAck,
}
impl AnchorWitnessStore for LostAckWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if next.sequence == self.sequence {
            if matches!(self.fault, LostAck::AfterWrite) {
                self.inner.compare_and_swap(expected, next)?;
            }
            return Err(WitnessStoreError::Indeterminate);
        }
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn lost_claim_or_completion_ack_never_reexecutes_or_replaces_original_material() {
    for sequence in [2, 3] {
        for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
            let mut fixture = OriginalQualificationFixture::new();
            let path = fixture.directory.path().to_path_buf();
            let source_before = fixture.source_bytes();
            let mut owner = checked(OriginalProductQualificationOwnerV1::create(
                file(&path.join("publication")),
                LostAckWitness {
                    inner: witness(file(&path.join("publication-witness"))),
                    sequence,
                    fault,
                },
                digest("publication-namespace"),
            ));
            assert!(matches!(
                fixture.publish(&mut owner),
                Err(OriginalProductQualificationErrorV1::Owner(
                    LearningOriginalOwnerErrorV1::CommitUncertain
                ))
            ));
            assert!(matches!(
                fixture.readback(&mut owner),
                Err(OriginalProductQualificationErrorV1::Owner(
                    LearningOriginalOwnerErrorV1::CommitUncertain
                ))
            ));
            let original = checked(fs::read(path.join("publication")));
            drop(owner);
            let mut owner = checked(OriginalProductQualificationOwnerV1::recover(
                existing(&path.join("publication")),
                witness(existing(&path.join("publication-witness"))),
                digest("publication-namespace"),
            ));
            if sequence == 2 {
                assert!(matches!(
                    fixture.readback(&mut owner),
                    Err(OriginalProductQualificationErrorV1::Owner(
                        LearningOriginalOwnerErrorV1::Pending
                    ))
                ));
                assert!(matches!(
                    fixture.publish(&mut owner),
                    Err(OriginalProductQualificationErrorV1::Owner(
                        LearningOriginalOwnerErrorV1::Pending
                    ))
                ));
            } else {
                let first = checked(fixture.readback(&mut owner));
                assert_eq!(checked(fixture.readback(&mut owner)), first);
            }
            assert_eq!(checked(fs::read(path.join("publication"))), original);
            assert_eq!(fixture.source_bytes(), source_before);
        }
    }
}

struct AdvanceAfterCompletionReads {
    inner: RefCell<FileAnchorWitnessStore>,
    completed: Cell<bool>,
    reads: Cell<u32>,
    changed: Rc<Cell<bool>>,
}
impl AnchorWitnessStore for AdvanceAfterCompletionReads {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        let before = self.inner.borrow().current()?;
        if self.completed.get() {
            self.reads.set(self.reads.get() + 1);
            // The two commit readback checks complete first. The next own-head
            // check is after the cross-owner source and signature postchecks.
            if self.reads.get() == 3 {
                let old = before.ok_or(WitnessStoreError::Indeterminate)?;
                self.inner.borrow_mut().compare_and_swap(
                    Some(old),
                    JournalAnchor {
                        sequence: old.sequence + 1,
                        checkpoint_digest: digest("different-current-publication-head"),
                    },
                )?;
                self.changed.set(true);
            }
        }
        self.inner.borrow().current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.get_mut().compare_and_swap(expected, next)?;
        if next.sequence == 3 {
            self.completed.set(true);
        }
        Ok(())
    }
}

#[test]
fn final_publication_witness_change_rejects_after_durable_completion() {
    let mut fixture = OriginalQualificationFixture::new();
    let path = fixture.directory.path().to_path_buf();
    let source_before = fixture.source_bytes();
    let changed = Rc::new(Cell::new(false));
    let mut owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        AdvanceAfterCompletionReads {
            inner: RefCell::new(witness(file(&path.join("publication-witness")))),
            completed: Cell::new(false),
            reads: Cell::new(0),
            changed: changed.clone(),
        },
        digest("publication-namespace"),
    ));
    let empty = checked(fs::read(path.join("publication")));
    assert!(matches!(
        fixture.publish(&mut owner),
        Err(OriginalProductQualificationErrorV1::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    assert!(changed.get());
    assert_ne!(checked(fs::read(path.join("publication"))), empty);
    assert_eq!(fixture.source_bytes(), source_before);
    drop(owner);
    assert!(
        OriginalProductQualificationOwnerV1::recover(
            existing(&path.join("publication")),
            witness(existing(&path.join("publication-witness"))),
            digest("publication-namespace"),
        )
        .is_err()
    );
}
