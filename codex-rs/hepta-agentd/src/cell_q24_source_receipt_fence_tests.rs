//! Real original journals under controlled independent-witness faults. This
//! tests the witness trait's observed acknowledgement, not arbitrary edits
//! behind FileAnchorWitnessStore's locked, cached state.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;
use crate::LearningOriginalOwnerErrorV1;
use crate::OriginalCellQ24SourceReceiptErrorV1;

#[derive(Clone, Copy)]
enum Role {
    FailClaim,
    Experience,
    Dataset,
}
#[derive(Default)]
struct Drift {
    armed: AtomicBool,
    invalid: AtomicBool,
    reads: AtomicUsize,
}
struct Witness {
    original: FileAnchorWitnessStore,
    role: Role,
    drift: Arc<Drift>,
}

impl AnchorWitnessStore for Witness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        let value = self.original.current()?;
        match self.role {
            Role::Experience if self.drift.armed.load(Ordering::SeqCst) => {
                self.drift.reads.fetch_add(1, Ordering::SeqCst);
                self.drift.invalid.store(true, Ordering::SeqCst);
            }
            Role::Dataset if self.drift.invalid.load(Ordering::SeqCst) => return Ok(None),
            Role::FailClaim | Role::Experience | Role::Dataset => {}
        }
        Ok(value)
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if matches!(self.role, Role::FailClaim) && next.sequence == 2 {
            return Err(WitnessStoreError::Unavailable);
        }
        self.original.compare_and_swap(expected, next)?;
        if matches!(self.role, Role::Dataset) && next.sequence == 3 {
            self.drift.armed.store(true, Ordering::SeqCst);
        }
        Ok(())
    }
}

fn fault_owner(
    native: &OriginalQ24DatasetIngressFixture,
    root: &Path,
    name: &str,
    config: &Config,
    role: Role,
    drift: Arc<Drift>,
) -> anyhow::Result<SourceReceiptTestOwner<Witness>> {
    Ok(SourceReceiptTestOwner::create(
        file(root, name, OpenOwner::Create)?,
        Witness {
            original: witness(root, name, config, OpenOwner::Create)?,
            role,
            drift,
        },
        config.clone(),
        SigningKey::from_bytes(&[2; 32]),
        Arc::clone(&native.material),
    )?)
}

#[tokio::test]
async fn original_experience_pending_remains_pending_and_dataset_does_not_issue_it()
-> anyhow::Result<()> {
    let native = OriginalQ24DatasetIngressFixture::new(1_i64 << 32).await?;
    let root = tempfile::tempdir()?;
    let initial = initial(&native)?;
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    let mut original = owner(
        &native,
        root.path(),
        "experience",
        &initial,
        OpenOwner::Create,
    )?;
    let first = original.attest_experience(&ledger, &source, &native.identity)?;
    let config = dataset_config(&initial, &first)?;
    let mut dataset = owner(&native, root.path(), "dataset", &config, OpenOwner::Create)?;
    let mut pending = fault_owner(
        &native,
        root.path(),
        "pending",
        &initial,
        Role::FailClaim,
        Arc::new(Drift::default()),
    )?;
    assert!(
        pending
            .attest_experience(&ledger, &source, &native.identity)
            .is_err()
    );
    drop(pending);
    // Original recovery may acknowledge its own fsynced Pending claim; it cannot
    // convert it to Completed or choose a replacement operation identity.
    let mut pending = owner(
        &native,
        root.path(),
        "pending",
        &initial,
        OpenOwner::Recover,
    )?;
    let retained = fs::read(root.path().join("pending"))?;
    let dataset_before = bytes(root.path())?;
    assert!(matches!(
        pending.readback_experience(&ledger, &source, &native.identity),
        Err(OriginalCellQ24SourceReceiptErrorV1::Owner(
            LearningOriginalOwnerErrorV1::Pending
        ))
    ));
    assert!(
        pending
            .attest_experience(&ledger, &source, &native.identity)
            .is_err()
    );
    assert!(
        dataset
            .attest_dataset(&mut pending, &ledger, &source, &native.identity)
            .is_err()
    );
    assert_eq!(fs::read(root.path().join("pending"))?, retained);
    assert_eq!(bytes(root.path())?, dataset_before);
    Ok(())
}

#[tokio::test]
async fn dataset_rechecks_its_ack_after_the_original_experience_readback() -> anyhow::Result<()> {
    let native = OriginalQ24DatasetIngressFixture::new(1_i64 << 32).await?;
    let root = tempfile::tempdir()?;
    let initial = initial(&native)?;
    let ledger = native
        .ledger
        .lock()
        .map_err(|_| anyhow::anyhow!("ledger poisoned"))?;
    let source = native.original.readback();
    let drift = Arc::new(Drift::default());
    let source_before = native.source_bytes()?;
    let mut experience = fault_owner(
        &native,
        root.path(),
        "experience",
        &initial,
        Role::Experience,
        Arc::clone(&drift),
    )?;
    let first = experience.attest_experience(&ledger, &source, &native.identity)?;
    let config = dataset_config(&initial, &first)?;
    let mut dataset = fault_owner(
        &native,
        root.path(),
        "dataset",
        &config,
        Role::Dataset,
        Arc::clone(&drift),
    )?;
    assert!(
        dataset
            .attest_dataset(&mut experience, &ledger, &source, &native.identity)
            .is_err()
    );
    assert!(drift.reads.load(Ordering::SeqCst) > 0);
    let retained = bytes(root.path())?;
    drop(dataset);
    drift.armed.store(false, Ordering::SeqCst);
    drift.invalid.store(false, Ordering::SeqCst);
    // The completion is real and remains readable under its original witness.
    // No new fit/signature/task is needed to resolve the observation failure.
    let mut recovered = owner(&native, root.path(), "dataset", &config, OpenOwner::Recover)?;
    recovered.readback_dataset(&mut experience, &ledger, &source, &native.identity)?;
    assert_eq!(bytes(root.path())?, retained);
    assert_eq!(native.source_bytes()?, source_before);
    Ok(())
}
