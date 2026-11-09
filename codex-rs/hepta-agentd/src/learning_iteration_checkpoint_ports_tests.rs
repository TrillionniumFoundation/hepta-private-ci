//! Persistence composition tests use the existing file/fsync fixture. They do
//! not establish production Root custody or actual training/evaluation results.

use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use pretty_assertions::assert_eq;

use super::*;
use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::PreparedLearningIterationProposalV1;

use crate::learning_iteration_checkpoint::test_support as support;
use support::Decision;
use support::FileCas;
use support::OWNER;
use support::owner;
use support::snapshots;

pub(super) struct StageOwners {
    snapshots: Vec<LearningIterationSnapshotV1>,
    calls: std::sync::atomic::AtomicUsize,
    pub(super) recoveries: std::sync::atomic::AtomicUsize,
    pub(super) unavailable: std::sync::atomic::AtomicBool,
}

impl StageOwners {
    pub(super) fn new(snapshots: Vec<LearningIterationSnapshotV1>) -> Self {
        Self {
            snapshots,
            calls: std::sync::atomic::AtomicUsize::new(/*v*/ 0),
            recoveries: std::sync::atomic::AtomicUsize::new(/*v*/ 0),
            unavailable: std::sync::atomic::AtomicBool::new(/*v*/ false),
        }
    }
}

impl LearningIterationStageOwnerPortsV1 for StageOwners {
    fn validate_recovery<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, ()> {
        Box::pin(async move {
            self.recoveries.fetch_add(/*val*/ 1, Ordering::SeqCst);
            if self.unavailable.load(Ordering::SeqCst) || !self.snapshots.contains(snapshot) {
                return Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                    "recovery",
                ));
            }
            Ok(())
        })
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            self.calls.fetch_add(/*val*/ 1, Ordering::SeqCst);
            let next = self.snapshots.get(snapshot.receipts.len() + 1);
            let receipt = next.and_then(|value| value.receipts.last());
            match receipt {
                Some(receipt) if receipt.observation.stage() == stage => Ok(receipt.clone()),
                _ => Err(LearningIterationRuntimeErrorV1::OwnerUnavailable("stage")),
            }
        })
    }

    fn prepare_proposal<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async {
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "proposal",
            ))
        })
    }

    fn receipt_attestation<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
        _receipt: &'a LearningIterationReceiptV1,
        _now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async {
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "attestation",
            ))
        })
    }
}

#[tokio::test]
async fn scoped_checkpoint_ports_keep_the_registered_scope_across_reopen() -> anyhow::Result<()> {
    let cuts = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &cuts[0];
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request, &initial.owners,
        codex_hepta_learning_artifacts::LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"rule"),
    )?;
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("scoped-frontier");
    let vacant = LearningIterationCheckpointRecordV1::vacant_scoped_v2(
        initial.request.clone(), initial.owners.clone(), &scope,
    )?;
    FileCas::create(&path, &vacant)?;
    let stages = Arc::new(StageOwners::new(cuts.clone()));
    for _ in 0..2 {
        let store = Arc::new(FileCas::reopen(&path)?);
        let original = LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(
            store, OWNER.into(), initial.request.clone(), initial.owners.clone(), scope.clone(),
        )?;
        let ports = original.with_stage_owners(stages.clone());
        assert_eq!(ports.frozen_scope_binding(), Some(scope.binding()));
        assert_eq!(ports.checkpoint(Digest32::ZERO, initial).await?, initial.head_digest);
        assert_eq!(ports.restore(&initial.request).await?, Some(initial.clone()));
    }
    Ok(())
}

#[tokio::test]
async fn registered_checkpoint_ports_reopen_every_stage_and_preserve_owner_errors()
-> anyhow::Result<()> {
    for decision in [
        Decision::Update,
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
    ] {
        let snapshots = snapshots(decision)?;
        let initial = &snapshots[0];
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("original-frontier");
        let vacant = LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?;
        let stages = Arc::new(StageOwners::new(snapshots.clone()));
        let store = Arc::new(FileCas::create(&path, &vacant)?);
        let ports = owner(store.clone(), initial).with_stage_owners(stages.clone());
        assert_eq!(ports.restore(&initial.request).await?, None);
        assert_eq!(stages.recoveries.load(Ordering::SeqCst), 0);
        assert_eq!(
            ports.checkpoint(Digest32::ZERO, initial).await?,
            initial.head_digest
        );
        drop(ports);
        for pair in snapshots.windows(/*size*/ 2) {
            let ports =
                owner(Arc::new(FileCas::reopen(&path)?), initial).with_stage_owners(stages.clone());
            assert_eq!(
                ports.restore(&initial.request).await?,
                Some(pair[0].clone())
            );
            let receipt = pair[1].receipts.last().unwrap();
            assert_eq!(
                ports
                    .execute_stage(&pair[0], receipt.observation.stage())
                    .await?,
                *receipt
            );
            // Persistence does not fabricate a missing owner signature/proposal.
            assert!(matches!(
                ports
                    .receipt_attestation(&pair[0], receipt, /*now_unix_seconds*/ 20)
                    .await,
                Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                    "attestation"
                ))
            ));
            assert!(matches!(
                ports.prepare_proposal(&pair[0]).await,
                Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                    "proposal"
                ))
            ));
            assert_eq!(
                ports.checkpoint(pair[0].head_digest, &pair[1]).await?,
                pair[1].head_digest
            );
        }
        let ports =
            owner(Arc::new(FileCas::reopen(&path)?), initial).with_stage_owners(stages.clone());
        assert_eq!(
            ports.restore(&initial.request).await?,
            snapshots.last().cloned()
        );
        assert_eq!(stages.calls.load(Ordering::SeqCst), snapshots.len() - 1);
        assert_eq!(stages.recoveries.load(Ordering::SeqCst), snapshots.len());
        stages.unavailable.store(/*val*/ true, Ordering::SeqCst);
        assert!(matches!(
            ports.restore(&initial.request).await,
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "recovery"
            ))
        ));
        let mut foreign = initial.request.clone();
        foreign.operation_id = codex_hepta_types::StableId::new("other-operation")?;
        assert!(matches!(
            ports.restore(&foreign).await,
            Err(LearningIterationRuntimeErrorV1::Checkpoint(
                Error::WrongScope
            ))
        ));
        let mut foreign_snapshot = initial.clone();
        foreign_snapshot.request = foreign;
        assert!(matches!(
            ports
                .execute_stage(&foreign_snapshot, LearningIterationStageV1::Experience)
                .await,
            Err(LearningIterationRuntimeErrorV1::WrongScope)
        ));
        assert!(matches!(
            ports.prepare_proposal(&foreign_snapshot).await,
            Err(LearningIterationRuntimeErrorV1::WrongScope)
        ));
        assert!(matches!(
            ports
                .receipt_attestation(
                    &foreign_snapshot,
                    &snapshots[1].receipts[0],
                    /*now_unix_seconds*/ 20
                )
                .await,
            Err(LearningIterationRuntimeErrorV1::WrongScope)
        ));
        assert_eq!(stages.calls.load(Ordering::SeqCst), snapshots.len() - 1);
    }
    Ok(())
}

#[tokio::test]
async fn checkpoint_ports_reconcile_lost_commit_ack_without_repeating_write() -> anyhow::Result<()>
{
    let snapshots = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &snapshots[0];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-frontier");
    let vacant = LearningIterationCheckpointRecordV1::vacant(
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let store = Arc::new(FileCas::create(&path, &vacant)?);
    let stages = Arc::new(StageOwners::new(snapshots.clone()));
    let ports = owner(store.clone(), initial).with_stage_owners(stages.clone());
    ports.checkpoint(Digest32::ZERO, initial).await?;
    stages.unavailable.store(/*val*/ true, Ordering::SeqCst);
    assert!(matches!(
        ports.restore(&initial.request).await,
        Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
            "recovery"
        ))
    ));
    stages.unavailable.store(/*val*/ false, Ordering::SeqCst);
    store.failure.store(/*val*/ 2, Ordering::SeqCst);
    assert!(matches!(
        ports.checkpoint(initial.head_digest, &snapshots[1]).await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_eq!(
        ports.restore(&initial.request).await?,
        Some(snapshots[1].clone())
    );
    assert_eq!(
        ports.checkpoint(initial.head_digest, &snapshots[1]).await?,
        snapshots[1].head_digest
    );
    assert_eq!(store.commits.load(Ordering::SeqCst), 2);
    assert!(matches!(
        ports.checkpoint(Digest32::ZERO, initial).await,
        Err(LearningIterationRuntimeErrorV1::Checkpoint(Error::Conflict))
    ));
    Ok(())
}

#[tokio::test]
async fn cancelled_checkpoint_waiter_keeps_the_original_persistence_lane() -> anyhow::Result<()> {
    type Gate = (
        tokio::sync::oneshot::Sender<()>,
        std::sync::mpsc::Receiver<()>,
    );
    struct GatedStore {
        store: Arc<FileCas>,
        gate: std::sync::Mutex<Option<Gate>>,
    }
    impl AuthorityFrontierStore<LearningIterationCheckpointRecordV1> for GatedStore {
        fn load(
            &self,
            owner: &str,
        ) -> Result<LearningIterationCheckpointRecordV1, AuthorityTrustError> {
            let gate = self.gate.lock().unwrap().take();
            if let Some((entered, release)) = gate {
                let _ = entered.send(());
                release
                    .recv_timeout(std::time::Duration::from_secs(/*secs*/ 5))
                    .map_err(|_| AuthorityTrustError::Unavailable)?;
            }
            self.store.load(owner)
        }
        fn compare_and_set(
            &self,
            owner: &str,
            expected: &LearningIterationCheckpointRecordV1,
            next: &LearningIterationCheckpointRecordV1,
        ) -> Result<(), AuthorityTrustError> {
            self.store.compare_and_set(owner, expected, next)
        }
    }
    let snapshots = snapshots(Decision::Update)?;
    let initial = snapshots[0].clone();
    let directory = tempfile::tempdir()?;
    let vacant = LearningIterationCheckpointRecordV1::vacant(
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let store = Arc::new(FileCas::create(
        &directory.path().join("original-frontier"),
        &vacant,
    )?);
    let (entered, waiting) = tokio::sync::oneshot::channel();
    let (release, blocked) = std::sync::mpsc::channel();
    let checkpoint = LearningIterationCheckpointOwnerV1 {
        owner_id: OWNER.into(),
        store: Store::Test(Arc::new(GatedStore {
            store: store.clone(),
            gate: std::sync::Mutex::new(Some((entered, blocked))),
        })),
        initial: initial.clone(),
    };
    let ports = checkpoint.with_stage_owners(Arc::new(StageOwners::new(snapshots)));
    let pending = tokio::spawn({
        let ports = ports.clone();
        let initial = initial.clone();
        async move { ports.checkpoint(Digest32::ZERO, &initial).await }
    });
    tokio::time::timeout(std::time::Duration::from_secs(/*secs*/ 2), waiting).await??;
    pending.abort();
    assert!(pending.await.unwrap_err().is_cancelled());
    assert!(matches!(
        ports.restore(&initial.request).await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_eq!(store.commits.load(Ordering::SeqCst), 0);
    release.send(())?;
    let restored = tokio::time::timeout(std::time::Duration::from_secs(/*secs*/ 2), async {
        loop {
            match ports.restore(&initial.request).await {
                Err(LearningIterationRuntimeErrorV1::CommitUncertain) => {
                    tokio::task::yield_now().await
                }
                result => return result,
            }
        }
    })
    .await??;
    assert_eq!(restored, Some(initial.clone()));
    assert_eq!(
        ports.checkpoint(Digest32::ZERO, &initial).await?,
        initial.head_digest
    );
    assert_eq!(store.commits.load(Ordering::SeqCst), 1);
    Ok(())
}
