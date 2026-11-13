//! Same-host capability behavior using actual owner/journal reads. These
//! mechanisms do not claim a Fresh Root or public three-UID task completed.

use super::*;
use anyhow::Context as _;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_s_c_complete_same_actual_c_and_cold_observer_stays_readonly() -> anyhow::Result<()> {
    let mut case = Box::pin(SameHostCase::completed_selection()).await?;
    let result: anyhow::Result<()> = async {
        let before = case.original_bytes()?;
        case.export_selection(Duration::from_secs(300)).await?;
        anyhow::ensure!(
            case.original_bytes()? == before,
            "export reads the same completed S without a new signature or journal write"
        );
        case.install_completion().await?;
        anyhow::ensure!(
            case.readiness
                .as_ref()
                .context("same local C readiness")?
                .read_current()
                .await?
                .is_none(),
            "unexecuted actual C remains NotReady"
        );
        anyhow::ensure!(
            case.task()?
                .cell
                .snapshot(&case.fixture()?.source_c.scope)?
                .revision
                == 0,
            "capability construction and readiness do not dispatch C"
        );

        // This is the existing actual Session mechanism, not the new daemon
        // state or a claim of a public Root/UID lifecycle.
        let publication = execute(case.task()?, 1).await?;
        let original_c = read_receipt(case.task()?, &case.fixture()?.definition, &publication)?;
        anyhow::ensure!(
            original_c.bundle_digest == case.fixture()?.bundle.digest()?,
            "actual C ran the retained original baseline"
        );
        let observed = case
            .readiness
            .as_ref()
            .context("same C readiness backend")?
            .read_current()
            .await?
            .context("actual C must now be completed")?;
        anyhow::ensure!(
            matches!(observed.observation(),
            LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
            if *retained_bundle == case.fixture()?.bundle.digest()?),
            "same original C observation"
        );

        let completed = case
            .completion
            .as_ref()
            .context("actual Observer command client")?
            .attest_completed_task()
            .await?;
        let whole = LearningIterationCoordinatorV1::from_snapshot(completed.snapshot().clone())?;
        anyhow::ensure!(
            completed.snapshot().receipts.len() == 6 && whole.next_stage().is_none(),
            "the actual original evaluated chain has all six receipts"
        );
        let selected = case.selection()?;
        anyhow::ensure!(
            &completed.snapshot().receipts[..5] == selected.snapshot().receipts.as_slice()
                && completed.selection_attestation() == selected.attestation(),
            "C keeps the entire same original five-cut and S signature"
        );
        anyhow::ensure!(
            matches!(
                case.completion
                    .as_ref()
                    .context("same original command client")?
                    .attest_completed_task()
                    .await,
                Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired)
            ),
            "completed command cannot dispatch twice"
        );
        let after = case.original_bytes()?;

        case.recover_completed_observer().await?;
        // Do not let a read-only client mask a missing recovered-owner guard:
        // this separate actual channel sends Execute from a fresh client.
        let recovered_host = Arc::clone(
            case.observer_host
                .as_ref()
                .context("same recovered original Observer host")?,
        );
        let context = OriginalCircuitNextUseCommandContextV1::from_original_evaluated_selection(
            &case.selection()?,
        )?;
        let (fresh_client, channel) = completion_commands::client(
            context, /*readback_only*/ false, /*retained*/ None,
        )?;
        let peer = completion_commands::serve(recovered_host, channel);
        let attempted = fresh_client.attest_completed_task().await;
        drop(fresh_client);
        let served = peer
            .join()
            .map_err(|_| anyhow::anyhow!("recovered Observer rejection peer panicked"));
        anyhow::ensure!(
            matches!(
                attempted,
                Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired)
            ),
            "the recovered original owner itself refuses a real fresh Execute request"
        );
        served??;
        anyhow::ensure!(
            matches!(
                case.completion
                    .as_ref()
                    .context("same recovered original Observer")?
                    .attest_completed_task()
                    .await,
                Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired)
            ),
            "recovered original custody remains permanently read-only"
        );
        let recovered = case
            .completion
            .as_ref()
            .context("recovered readback client")?
            .readback()
            .await?;
        anyhow::ensure!(
            recovered == completed,
            "cold read preserves the entire original completed command result and opaque binding"
        );
        anyhow::ensure!(
            case.original_bytes()? == after,
            "cold readback neither repeats C nor rewrites the enumerated original evidence"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn identical_signed_cuts_cannot_substitute_other_actual_t_e_clients() -> anyhow::Result<()> {
    let mut case = Box::pin(SameHostCase::with_distinct_original_connections()).await?;
    let result: anyhow::Result<()> = async {
        let shared = case.shared()?;
        let other = case.alternate_shared.as_ref()
            .context("other actual Version's independently bound original clients")?.clone();
        let context = case.fixture()?.context()?;
        OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(&shared, &context)?;
        OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(&other, &context)?;
        anyhow::ensure!(!shared.fixture_same_original_clients(&other),
            "the full original signed cut is identical but both retained clients are not the same objects");
        let before = case.original_bytes()?;
        let local = Version::open_original_evaluated_selection_local_read(
            case.host()?, Duration::from_millis(500), Duration::from_secs(300),
        ).await?;
        let live = OriginalCircuitLearningReadClientV1::from_original_evaluated_local_selection(
            local, context,
        )?;
        OriginalCircuitLearningReadClientV1::require_original_local_shared_readbacks(&live, &shared)?;
        let rejected = OriginalCircuitLearningReadClientV1::require_original_local_shared_readbacks(
            &live, &other,
        );
        anyhow::ensure!(matches!(rejected,
            Err(crate::OriginalCircuitLearningReadErrorV1::Owner(crate::AgentdError::Invalid(message)))
            if message.ends_with("same Version local T/E readback owners")
        ), "Version rejects actual client substitution independently of the identical signatures");
        let extra_s_home = tempfile::tempdir()?;
        let extra_s = case.create_selector(&extra_s_home)?;
        let attempted_s = Selector::into_evaluated_local_shared_command_owner(extra_s, live, other.clone());
        anyhow::ensure!(attempted_s.is_err(),
            "the concrete S factory cannot bypass the Version's actual client identity");

        case.export_selection(Duration::from_secs(300)).await?;
        let local_s = case.local_s.as_ref().context("first Version's actual S capability")?.clone();
        OriginalCircuitSelectionLocalReadbackV1::require_original_shared_predecessors(
            &local_s, &shared,
        )?;
        anyhow::ensure!(matches!(
            OriginalCircuitSelectionLocalReadbackV1::require_original_shared_predecessors(&local_s, &other),
            Err(OriginalCircuitSelectionCommandErrorV1::Binding("same original local Selector T/E clients"))
        ), "C cannot substitute a distinct but authentic T/E pair for this S");

        let selected = case.selection()?;
        let local_c = Version::open_original_evaluated_next_use_local_read(
            case.host()?, selected.clone(), Duration::from_millis(500), Duration::from_secs(300),
        ).await?;
        let live_c = OriginalCircuitLearningReadClientV1::from_original_evaluated_local_next_use(
            local_c, selected.clone(),
        )?;
        let extra_c_home = tempfile::tempdir()?;
        let extra_c = Observer::create_evaluated(
            opened(extra_c_home.path(), "observer.journal", /*create*/ true)?,
            receipt_witness(&extra_c_home, "observer.witness", case.fixture()?, WitnessOrigin::New)?,
            OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
                selection: selected,
                signer: case.fixture()?.host.original.credentials.observer.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            SigningKey::from_bytes(&[43; 32]),
        )?;
        let attempted_c = Observer::into_evaluated_local_shared_command_owner(
            extra_c, live_c, other, local_s,
        );
        anyhow::ensure!(attempted_c.is_err(),
            "the concrete C factory also requires the same Version/S T/E instances");
        anyhow::ensure!(case.original_bytes()? == before,
            "all identity checks leave existing original receipts and evidence unchanged");
        anyhow::ensure!(case.task()?.cell.snapshot(&case.fixture()?.source_c.scope)?.revision == 0,
            "a rejected authentic foreign client set does not dispatch C");
        Ok(())
    }.await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn missing_original_s_cannot_export_a_local_predecessor() -> anyhow::Result<()> {
    let case = Box::pin(SameHostCase::missing_selection()).await?;
    let result: anyhow::Result<()> = async {
        let before = case.original_bytes()?;
        let attempted = SelectorHost::open_original_evaluated_local_readback(
            case.selector_host()?,
            Duration::from_millis(500),
            Duration::from_secs(300),
        )
        .await;
        anyhow::ensure!(
            attempted.is_err(),
            "a valid original context and published Version do not fabricate a missing S"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "failed S export never signs, executes or initializes a replacement receipt"
        );
        anyhow::ensure!(
            case.task()?
                .cell
                .snapshot(&case.fixture()?.source_c.scope)?
                .revision
                == 0,
            "missing S cannot start C"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_s_aliases_refuse_real_overlapping_owner_reads() -> anyhow::Result<()> {
    let mut case = Box::pin(SameHostCase::completed_selection()).await?;
    let result: anyhow::Result<()> =
        async {
            case.export_selection(Duration::from_secs(300)).await?;
            let before = case.original_bytes()?;
            let original = case.selection()?;
            let cap = case.local_s.as_ref().context("actual local S")?.clone();
            let alias = cap.clone();
            let mut gate = cap.fixture_pause_next_original_selection_read()?;
            let mut request = Box::pin(cap.read_original_selection());
            let first_poll = std::future::poll_fn(|cx| {
                std::task::Poll::Ready(std::future::Future::poll(request.as_mut(), cx))
            })
            .await;
            let pending = first_poll.is_pending();
            let body: anyhow::Result<()> = async {
            anyhow::ensure!(pending, "actual S read was dispatched before pausing");
            gate.wait_for_actual_read().await?;
            anyhow::ensure!(matches!(alias.read_original_selection().await,
                Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)),
                "an alias cannot dispatch a second S read while the same original slot is absent");
            Ok(())
        }.await;
            gate.release();
            // Even if an assertion failed, observe the actual original operation,
            // then observe its join result; never abandon it to make cleanup pass.
            let read = match first_poll {
                std::task::Poll::Ready(read) => read,
                std::task::Poll::Pending => request.await,
            };
            let terminal = gate.wait_for_operation_terminal().await;
            if !pending {
                // Preserve an early original rejection; a completed future must
                // never be polled again, including during assertion cleanup.
                read.context("the first original S poll completed before the pause")?;
                return body.and(terminal);
            }
            body?;
            terminal?;
            let read = read?;
            anyhow::ensure!(
                (read.snapshot(), read.receipt(), read.attestation())
                    == (
                        original.snapshot(),
                        original.receipt(),
                        original.attestation()
                    ),
                "the winning original operation returns the complete same S"
            );
            anyhow::ensure!(
                case.original_bytes()? == before,
                "both aliases are read-only"
            );
            Ok(())
        }
        .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancelling_local_s_read_fences_all_aliases_after_actual_work_terminates()
-> anyhow::Result<()> {
    let mut case = Box::pin(SameHostCase::completed_selection()).await?;
    let result: anyhow::Result<()> = async {
        case.export_selection(Duration::from_secs(300)).await?;
        let before = case.original_bytes()?;
        let cap = case.local_s.as_ref().context("actual local S")?.clone();
        let alias = cap.clone();
        let mut gate = cap.fixture_pause_next_original_selection_read()?;
        let mut request = Box::pin(cap.read_original_selection());
        let first_poll = std::future::poll_fn(|cx| {
            std::task::Poll::Ready(std::future::Future::poll(request.as_mut(), cx))
        })
        .await;
        let pending = first_poll.is_pending();
        let body: anyhow::Result<()> = async {
            anyhow::ensure!(pending, "actual original S operation is pending");
            gate.wait_for_actual_read().await?;
            anyhow::ensure!(
                matches!(
                    alias.read_original_selection().await,
                    Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)
                ),
                "all aliases see the absent original slot before cancellation"
            );
            Ok(())
        }
        .await;
        // The actual blocking owner read has returned but the original async
        // delivery is deliberately dropped. Its result is Unknown to this
        // caller, not a claim that already dispatched owner I/O was cancelled.
        drop(request);
        gate.release();
        let terminal = gate.wait_for_operation_terminal().await;
        if let std::task::Poll::Ready(read) = first_poll {
            // An already returned result is not a cancelled delivery. Retain
            // its actual error and still complete the original peer cleanup.
            read.context("the first original S poll completed before cancellation")?;
            return body.and(terminal);
        }
        body?;
        terminal?;
        anyhow::ensure!(
            matches!(
                alias.read_original_selection().await,
                Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)
            ),
            "observing the old work's terminal cannot restore a cancelled slot"
        );
        anyhow::ensure!(
            matches!(
                cap.read_original_selection().await,
                Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)
            ),
            "the original alias cannot reopen or retry the cancelled capability"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "completed read-only work does not grant a replacement S or C"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_s_revalidates_withdrawn_b_and_consumes_the_failed_slot() -> anyhow::Result<()> {
    let mut case = Box::pin(SameHostCase::completed_selection()).await?;
    let result: anyhow::Result<()> = async {
        case.export_selection(Duration::from_secs(300)).await?;
        let cap = case
            .local_s
            .as_ref()
            .context("already admitted local S")?
            .clone();
        let alias = cap.clone();
        case.fixture
            .as_deref_mut()
            .context("same original B owner")?
            .host
            .retention_b
            .withdraw_target()?;
        let before = case.original_bytes()?;
        let read = cap.read_original_selection().await;
        anyhow::ensure!(
            read.is_err(),
            "an earlier authentic S is not a substitute for a current independent B read"
        );
        anyhow::ensure!(
            matches!(
                alias.read_original_selection().await,
                Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)
            ),
            "failed original current validation consumes the same shared S slot"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "withdrawal rejection does not rewrite original receipts"
        );
        anyhow::ensure!(
            case.task()?
                .cell
                .snapshot(&case.fixture()?.source_c.scope)?
                .revision
                == 0,
            "failed S cannot dispatch the actual C"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_s_clone_keeps_the_original_absolute_expiry() -> anyhow::Result<()> {
    let mut case = Box::pin(SameHostCase::completed_selection()).await?;
    let result: anyhow::Result<()> = async {
        case.export_selection(Duration::from_secs(1)).await?;
        let exported = std::time::Instant::now();
        let before = case.original_bytes()?;
        let cap = case
            .local_s
            .as_ref()
            .context("actual finite S capability")?
            .clone();
        tokio::time::sleep_until(tokio::time::Instant::from_std(
            exported + Duration::from_millis(1100),
        ))
        .await;
        let late_clone = cap.clone();
        anyhow::ensure!(
            matches!(
                late_clone.read_original_selection().await,
                Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)
            ),
            "a late clone cannot renew the original absolute lifetime"
        );
        anyhow::ensure!(
            matches!(
                cap.read_original_selection().await,
                Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)
            ),
            "expiry is shared and no alias can reopen the original capability"
        );
        anyhow::ensure!(
            case.original_bytes()? == before,
            "expiry issues no original evidence"
        );
        Ok(())
    }
    .await;
    finish_case(result, case).await
}
