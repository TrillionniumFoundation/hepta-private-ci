//! Cross-owner acknowledgement fence controls. The test witness changes its
//! observed current value during real source readback; this does not claim to
//! detect arbitrary physical edits behind a locked FileAnchorWitnessStore.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;

use super::*;

#[derive(Clone, Copy)]
enum WitnessRole {
    Recovery,
    RecoveryArmAfterCompletion,
    Source,
}

#[derive(Default)]
struct Drift {
    armed: AtomicBool,
    invalid: AtomicBool,
    source_reads: AtomicUsize,
}

struct DatasetDriftWitness {
    original: FileAnchorWitnessStore,
    drift: Arc<Drift>,
    role: WitnessRole,
}

impl AnchorWitnessStore for DatasetDriftWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        let current = self.original.current()?;
        match self.role {
            WitnessRole::Recovery | WitnessRole::RecoveryArmAfterCompletion => {
                if self.drift.invalid.load(Ordering::SeqCst) {
                    return Ok(None);
                }
            }
            WitnessRole::Source => {
                if self.drift.armed.load(Ordering::SeqCst) {
                    self.drift.source_reads.fetch_add(1, Ordering::SeqCst);
                    self.drift.invalid.store(true, Ordering::SeqCst);
                }
            }
        }
        Ok(current)
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.original.compare_and_swap(expected, next)?;
        // This one-operation fixture has create/claim/complete anchors 1/2/3.
        // Arm only after the original Completed acknowledgement is durable, so
        // commit_once's own read succeeds and the post-source check is tested.
        if matches!(self.role, WitnessRole::RecoveryArmAfterCompletion) && next.sequence == 3 {
            self.drift.armed.store(true, Ordering::SeqCst);
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
enum Operation {
    Retain,
    Restore,
}

async fn drift_during_source_read(operation: Operation) -> anyhow::Result<()> {
    let mut original = fixture::Fixture::new(fixture::Q / 2).await?;
    original.terminal(1_i64 << 32)?;
    let material = original.freeze()?;
    let plan = plan(&material);
    let root = original.directory.path().canonicalize()?;
    let drift = Arc::new(Drift::default());
    let role = match operation {
        Operation::Retain => WitnessRole::RecoveryArmAfterCompletion,
        Operation::Restore => WitnessRole::Recovery,
    };
    let mut owner = OriginalCellQ24DatasetRecoveryOwnerV1::create(
        original::opened(&root, "drift-material")?,
        DatasetDriftWitness {
            original: original::witness(&root, "drift-material-witness")?,
            drift: Arc::clone(&drift),
            role,
        },
        original.profile.clone(),
    )?;
    if matches!(operation, Operation::Restore) {
        owner.retain(
            &plan,
            &material,
            &original.writer,
            &original.source.readback(),
            &original.identity,
        )?;
    }
    drop(original.source);
    let registry =
        crate::CircuitCellRegistryV1::new(original.circuit.clone(), original.bindings.clone())?;
    let source = crate::DurableCircuitTaskSourceV1::recover(
        existing(&root, "source-journal")?,
        DatasetDriftWitness {
            original: FileAnchorWitnessStore::open(
                existing(&root, "source-witness")?,
                original.source_witness_scope,
                original.source_witness_generation,
                original.source_witness_limit,
            )?,
            drift: Arc::clone(&drift),
            role: WitnessRole::Source,
        },
        &original.identity,
        &original.fence,
        &registry,
        vec![original.source_input.clone()],
    )?;
    let source_before = [
        fs::read(root.join("source-journal"))?,
        fs::read(root.join("source-witness"))?,
    ];
    if matches!(operation, Operation::Restore) {
        drift.armed.store(true, Ordering::SeqCst);
    }
    let result = match operation {
        Operation::Retain => owner.retain(
            &plan,
            &material,
            &original.writer,
            &source.readback(),
            &original.identity,
        ),
        Operation::Restore => owner
            .restore(
                &plan,
                &original.writer,
                &source.readback(),
                &original.identity,
            )
            .map(|_| ()),
    };
    assert!(drift.source_reads.load(Ordering::SeqCst) > 0);
    assert!(matches!(
        result,
        Err(RecoveryError::Owner(
            LearningOriginalOwnerErrorV1::CommitUncertain
        ))
    ));
    assert_eq!(
        [
            fs::read(root.join("source-journal"))?,
            fs::read(root.join("source-witness"))?
        ],
        source_before
    );
    drift.armed.store(false, Ordering::SeqCst);
    drift.invalid.store(false, Ordering::SeqCst);
    let retained = owner.restore(
        &plan,
        &original.writer,
        &source.readback(),
        &original.identity,
    )?;
    assert_eq!(retained.dataset(), material.dataset());
    assert_eq!(retained.batch().encoded(), material.batch().encoded());
    assert_eq!(original.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn retain_rechecks_its_ack_after_source_readback() -> anyhow::Result<()> {
    drift_during_source_read(Operation::Retain).await
}
#[tokio::test]
async fn restore_rechecks_its_ack_after_source_readback() -> anyhow::Result<()> {
    drift_during_source_read(Operation::Restore).await
}
