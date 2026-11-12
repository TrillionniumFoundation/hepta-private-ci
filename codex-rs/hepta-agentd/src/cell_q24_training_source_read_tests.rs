//! Actual Source, native and Generator reads, with explicit fixture transport.
//! These do not provision a deployed role or claim ordinary qualification.
use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_readonly_source_transaction_keeps_thirty_two_reads_within_same_upstream_budget()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (owner, stage, peers) = shared_owner(&fixture, /*create*/ true).await?;
    let (client, channel) = transport::client(
        context(&fixture),
        /*readback_only*/ false,
        /*retained*/ None,
    )?;
    let server = transport::serve(Arc::clone(&owner), channel);
    let completed = client
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    let before = fixture.bytes()?;
    for _ in 0..32 {
        assert_eq!(client.readback().await?, completed);
    }
    assert_eq!(fixture.bytes()?, before);
    drop(client);
    assert_eq!(
        server.join().expect("actual original readonly Trainer")?,
        33
    );
    drop(owner);
    drop(stage);
    let counts = finish(peers)?;
    assert_eq!(counts[0], counts[1]);
    assert!(counts[0] >= 64 && counts[0] < 128);
    // Previously the 32 reads alone consumed 128 frames, before setup or
    // training. These same original evidence peers enforce the existing cap.
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}

struct ReadWitness {
    witness: FileAnchorWitnessStore,
    armed: Arc<AtomicUsize>,
    action: ReadAction,
}

enum ReadAction {
    Withdraw {
        source: Arc<source::Source>,
        run: StableId,
    },
    CorruptNative {
        journal: PathBuf,
    },
    Hold {
        entered: Arc<tokio::sync::Notify>,
        released: Mutex<std::sync::mpsc::Receiver<()>>,
    },
}

impl AnchorWitnessStore for ReadWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        let original = self.witness.current()?;
        if self
            .armed
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |remaining| {
                remaining.checked_sub(1)
            })
            == Ok(1)
        {
            match &self.action {
                ReadAction::Withdraw { source, run } => {
                    source
                        .withdraw_source(run)
                        .expect("actual Source withdrawal during original native read");
                }
                ReadAction::Hold { entered, released } => {
                    entered.notify_one();
                    released
                        .lock()
                        .expect("fixture gate lock")
                        .recv()
                        .expect("release actual original native read");
                }
                ReadAction::CorruptNative { journal } => {
                    let mut changed = fs::read(journal).expect("original native journal bytes");
                    changed.push(0xff);
                    fs::write(journal, changed)
                        .expect("fixture mutates actual original native journal");
                }
            }
        }
        Ok(original)
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.witness.compare_and_swap(expected, next)
    }
}

type ObservedStage = Arc<SourceBoundCellQ24TrainingStageV1<ReadWitness, FileAnchorWitnessStore>>;
type ObservedOwner =
    Arc<OriginalCellQ24TrainingCommandOwnerV1<ReadWitness, FileAnchorWitnessStore>>;

async fn observed_owner(
    fixture: &Harness,
    armed: Arc<AtomicUsize>,
    action: ReadAction,
) -> anyhow::Result<(ObservedOwner, ObservedStage, Peers)> {
    let (capture, peers) = fixture.capture().await?;
    let training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", /*create*/ true)?,
        ReadWitness {
            witness: fixture.witness("native-witness", /*create*/ true)?,
            armed,
            action,
        },
        capture,
    )?;
    let original = OriginalCellQ24TrainingStageV1::from_original_owners(
        training,
        fixture.receipts(/*create*/ true)?,
    )
    .await?;
    let stage = Arc::new(SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?);
    let owner = Arc::new(
        OriginalCellQ24TrainingCommandOwnerV1::from_original_stage(
            Arc::clone(&stage),
            context(fixture),
            Arc::new(AtomicBool::new(/*v*/ false)),
        )
        .await?,
    );
    Ok((owner, stage, peers))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_readonly_source_transaction_rechecks_withdrawal_after_actual_native_read()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let armed = Arc::new(AtomicUsize::new(/*v*/ 0));
    let (owner, stage, peers) = observed_owner(
        &fixture,
        Arc::clone(&armed),
        ReadAction::Withdraw {
            source: Arc::clone(&fixture.source),
            run: fixture.config.dataset.request.source_run_id.clone(),
        },
    )
    .await?;
    let (client, channel) = transport::client(
        context(&fixture),
        /*readback_only*/ false,
        /*retained*/ None,
    )?;
    let server = transport::serve(Arc::clone(&owner), channel);
    client
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    let before = fixture.bytes()?;
    // Skip both witness reads in the original pair/scope preflight; trigger on the first native
    // read after the transaction's actual initial Source evidence read.
    armed.store(3, Ordering::Release);
    assert!(matches!(
        client.readback().await,
        Err(CommandError::CommitUncertain)
    ));
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Unavailable)
    ));
    assert!(stage.readback(&fixture.config.dataset).await.is_err());
    assert_eq!(fixture.bytes()?, before);
    drop(client);
    assert_eq!(
        server
            .join()
            .expect("original read after actual withdrawal")?,
        2
    );
    drop(owner);
    drop(stage);
    finish(peers)?;
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_readonly_source_transaction_cancel_keeps_occupied_lane_and_consumed_channel()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let armed = Arc::new(AtomicUsize::new(/*v*/ 0));
    let entered = Arc::new(tokio::sync::Notify::new());
    let (release, released) = std::sync::mpsc::channel();
    let (owner, stage, peers) = observed_owner(
        &fixture,
        Arc::clone(&armed),
        ReadAction::Hold {
            entered: Arc::clone(&entered),
            released: Mutex::new(released),
        },
    )
    .await?;
    let (client, channel) = transport::client(
        context(&fixture),
        /*readback_only*/ false,
        /*retained*/ None,
    )?;
    let server = transport::serve(Arc::clone(&owner), channel);
    client
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    let before = fixture.bytes()?;
    let client = Arc::new(client);
    let waiting = entered.notified();
    armed.store(3, Ordering::Release);
    let reader = Arc::clone(&client);
    let pending = tokio::spawn(async move { reader.readback().await });
    waiting.await;
    pending.abort();
    assert!(
        pending
            .await
            .expect_err("fixture requester cancelled")
            .is_cancelled()
    );
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Unavailable)
    ));
    assert!(matches!(
        stage.readback(&fixture.config.dataset).await,
        Err(crate::OriginalCellQ24TrainingStageErrorV1::Busy)
    ));
    release.send(())?;
    drop(client);
    assert_eq!(
        tokio::task::spawn_blocking(move || server
            .join()
            .expect("original read completes naturally"))
        .await??,
        2
    );
    drop(owner);
    drop(stage);
    finish(peers)?;
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_readonly_source_transaction_refuses_mid_read_native_journal_change()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let armed = Arc::new(AtomicUsize::new(/*v*/ 0));
    let (owner, stage, peers) = observed_owner(
        &fixture,
        Arc::clone(&armed),
        ReadAction::CorruptNative {
            journal: fixture.root.join("native-training"),
        },
    )
    .await?;
    let (client, channel) = transport::client(
        context(&fixture),
        /*readback_only*/ false,
        /*retained*/ None,
    )?;
    let server = transport::serve(Arc::clone(&owner), channel);
    client
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    let mut expected = fixture.bytes()?;
    expected[0].push(0xff);
    armed.store(3, Ordering::Release);
    assert!(matches!(
        client.readback().await,
        Err(CommandError::CommitUncertain)
    ));
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Unavailable)
    ));
    assert!(stage.readback(&fixture.config.dataset).await.is_err());
    assert_eq!(fixture.bytes()?, expected);
    drop(client);
    assert_eq!(server.join().expect("original journal change readback")?, 2);
    drop(owner);
    drop(stage);
    finish(peers)?;
    assert_eq!(
        fixture.bytes()?,
        expected,
        "no repair or renewed Generator signature"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_readonly_source_proof_rejects_same_bytes_after_original_source_drop()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (first, first_peers) = fixture.capture().await?;
    let (second_owners, second_peers) = fixture.clients(
        fixture.config.experience_evidence.clone(),
        fixture.config.dataset_evidence.clone(),
    )?;
    let config = fixture.config.clone();
    let first_binding = first.source_capture_binding();
    let runtime = tokio::runtime::Handle::current();
    tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
        let lane = Arc::new(tokio::sync::Semaphore::new(/*permits*/ 1));
        let permit = lane.try_acquire_owned()?;
        let proof = first.begin_readonly_in_lane(&permit)?;
        drop(first);
        let second = runtime.block_on(capture_original_cell_q24_training_source_v1(
            second_owners,
            config,
        ))?;
        assert_eq!(first_binding, second.source_capture_binding());
        assert!(matches!(
            second.finish_readonly_in_lane(proof),
            Err(OriginalCellQ24TrainingSourceErrorV1::Binding(
                "same original readonly source instance"
            ))
        ));
        drop(second);
        Ok(())
    })
    .await??;
    assert_eq!(finish(first_peers)?, [3, 3]);
    assert_eq!(finish(second_peers)?, [2, 2]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_source_read_keeps_legacy_missing_then_permanent_native_refusal()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let plan = fixture.material.training_plan(
        fixture.config.dataset.clone(),
        fixture.config.scope.clone(),
        Arc::clone(&fixture.baseline),
        fixture.config.optimizer,
    )?;
    let training = CellQ24TrainingOwnerV1::create(
        fixture.file("native-training", /*create*/ true)?,
        fixture.witness("native-witness", /*create*/ true)?,
        plan,
        fixture.material.batch().clone(),
        fixture.config.optimizer,
    )?;
    let original = Arc::new(
        OriginalCellQ24TrainingStageV1::from_original_owners(
            training,
            fixture.receipts(/*create*/ true)?,
        )
        .await?,
    );
    let unchanged = fixture.bytes()?;
    let missing = Arc::clone(&original);
    tokio::task::spawn_blocking(move || {
        assert!(matches!(
            missing.read_candidate_material(),
            Err(crate::OriginalCellQ24TrainingStageErrorV1::Receipt(
                crate::OriginalCellQ24TrainingReceiptErrorV1::Training(
                    CellQ24TrainingOwnerErrorV1::Store(
                        ProductEvaluationExecutionStoreErrorV1::Missing
                    )
                ),
            ))
        ));
    })
    .await?;
    assert_eq!(fixture.bytes()?, unchanged);
    original
        .execute_training(
            &fixture.config.dataset,
            Arc::new(AtomicBool::new(/*v*/ false)),
        )
        .await?;
    let completed = fixture.bytes()?;
    let refusal = Arc::clone(&original);
    tokio::task::spawn_blocking(move || {
        assert!(matches!(
            refusal.read_candidate_material(),
            Err(crate::OriginalCellQ24TrainingStageErrorV1::CommitUncertain)
        ));
    })
    .await?;
    assert!(matches!(
        original.readback(&fixture.config.dataset).await,
        Err(crate::OriginalCellQ24TrainingStageErrorV1::Training(
            CellQ24TrainingOwnerErrorV1::CommitUncertain
        ))
    ));
    assert_eq!(
        fixture.bytes()?,
        completed,
        "no Source admission, new fit or renewed signature after refusal"
    );
    Ok(())
}
