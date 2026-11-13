//! Whole-process cold cases. Original successful wait/pidfd objects remain
//! alive across the actual lease retirement; none are reconstructed from JSON.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_protocol::OriginalQ24CompletedHistoryDataV1;
use serde_json::json;

use super::b_evaluate::OriginalBusinessCase;
use super::cold_acceptance_data::OriginalColdAcceptanceData;
use super::cold_launch::RunningOrdinaryCold;
use super::cold_phase::OriginalColdPhase;
use super::cold_recipient_data::OriginalColdRecipientData;
use super::cold_successor_data::OriginalColdSuccessorData;
use super::cold_successor_data::OriginalFinalizedColdData;
use super::post_a_completed_data::OriginalCompletedCData;
use super::post_a_retained::RetainedOrdinaryQ24Fixture;
use crate::authority_host_service::generation_publication::RootCompletedSuccessorDataV1;
use crate::authority_host_service::generation_publication::head_digest;

#[test]
#[ignore = "actual UID0, exact product binaries, original 60s/300s retirement and <=120s cold read; no retries"]
fn ordinary_main_cold_recovers_completed_c_after_actual_daemon_and_root_retirement()
-> anyhow::Result<()> {
    run_whole_original_cold(OriginalBusinessCase::Adopt)
}

#[test]
#[ignore = "actual UID0, exact product binaries, original 60s/300s retirement and <=120s cold read; no retries"]
fn ordinary_main_cold_recovers_evaluated_no_update_c_after_actual_daemon_and_root_retirement()
-> anyhow::Result<()> {
    run_whole_original_cold(OriginalBusinessCase::EvaluatedNoUpdate)
}

fn run_whole_original_cold(case: OriginalBusinessCase) -> anyhow::Result<()> {
    // SAFETY: these calls only inspect the test process's real kernel UIDs.
    anyhow::ensure!(
        unsafe { (libc::getuid(), libc::geteuid()) } == (0, 0),
        "whole cold qualification requires actual UID0"
    );
    let end = Instant::now()
        .checked_add(Duration::from_secs(480))
        .ok_or_else(|| anyhow::anyhow!("whole cold harness deadline overflow"))?;
    let original = super::post_a_process::run_original_business_case(case)?;
    let report = original
        .plan
        .resources
        .original
        .plan
        .protected
        .path()
        .join("ordinary-whole-cold-result.json");
    let result = run_original_cold(&original, end);
    // Archive the real first two incarnations on failure as well as success.
    // Child Drop preserves complete raw output for failed new processes.
    let archived = original.archive_actual_phase();
    let record = json!({
        "schema":1,
        "business_case":format!("{case:?}"),
        "source_commit":std::env::var("HEPTA_ORDINARY_SOURCE_COMMIT")?,
        "source_tree":std::env::var("HEPTA_ORDINARY_SOURCE_TREE")?,
        "cold_recovery_completed":result.is_ok() && archived.is_ok(),
        "cold_error":result.as_ref().err().map(|error| format!("{error:#}")),
        "archive_error":archived.as_ref().err().map(|error| format!("{error:#}")),
        "actual":result.as_ref().ok(),
    });
    let written = super::root::write_json(&report, &record);
    eprintln!("ORDINARY_Q24_WHOLE_COLD_RESULT={}", report.display());
    // The first actual business/cold failure remains the test's failure even
    // if a later archive operation also fails; all statuses are retained above.
    result?;
    archived?;
    written?;
    anyhow::ensure!(
        Instant::now() < end,
        "whole cold observed after harness deadline"
    );
    Ok(())
}

fn run_original_cold(
    original: &RetainedOrdinaryQ24Fixture,
    end: Instant,
) -> anyhow::Result<serde_json::Value> {
    anyhow::ensure!(
        Instant::now() < end,
        "whole cold predecessor exceeded original harness"
    );
    let accepted = OriginalColdAcceptanceData::observe(original)?;
    let accepted_attempt_before = accepted.require_unchanged()?;
    let successor = OriginalColdSuccessorData::observe_registered(original)?;
    let phase = OriginalColdPhase::observe_original_completion(original, end)?;
    // These exact original process objects and their kernel pidfds stay owned
    // by `original` throughout the actual expired-lease wait.
    let (plan, evidence) = phase.wait_for_actual_expiry()?;
    accepted.require_unchanged()?;
    let recipient = OriginalColdRecipientData::observe(&plan)?;
    super::root::write_json(
        &evidence.directory.join("original-first-acceptance.json"),
        &accepted.accepted,
    )?;
    let work: anyhow::Result<serde_json::Value> = (|| {
        let running = RunningOrdinaryCold::start(plan)?;
        let read_end = running.plan.administration.end;
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()?;
        let observed = runtime.block_on(async {
            tokio::time::timeout_at(tokio::time::Instant::from_std(read_end), async {
                running.promote_when_initialized().await?;
                running.require_live()?;
                let client = running.client()?;
                let first = client
                    .original_q24_completed_history()
                    .await?
                    .ok_or_else(|| {
                        anyhow::anyhow!("actual new daemon has no completed-history result")
                    })?;
                running.require_live()?;
                let finalized = successor.observe_finalized(original)?.ok_or_else(|| {
                    anyhow::anyhow!("actual new Root has not finalized original C")
                })?;
                let expected = expected_data(&running, &recipient, &accepted, &finalized)?;
                anyhow::ensure!(
                    first == expected,
                    "actual new Root completion DATA differs: actual={first:?} expected={expected:?}"
                );
                let first_attempt = accepted.require_unchanged()?;
                anyhow::ensure!(
                    first_attempt > accepted_attempt_before,
                    "no actual cold acceptance verification"
                );
                evidence.require_unchanged(original)?;
                recipient.require_unchanged()?;
                // The second query invokes the same opaque holder's actual
                // Root ReadFinalized path. It cannot reuse the first JSON.
                let second = client
                    .original_q24_completed_history()
                    .await?
                    .ok_or_else(|| {
                        anyhow::anyhow!("new daemon lost the actual completed history")
                    })?;
                running.require_live()?;
                anyhow::ensure!(second == first, "same new session returned a different completed cut");
                let again = successor
                    .observe_finalized(original)?
                    .ok_or_else(|| anyhow::anyhow!("actual Root Finalized C disappeared"))?;
                anyhow::ensure!(
                    (&again.record_digest, &again.cut) == (&finalized.record_digest, &finalized.cut),
                    "ReadFinalized changed the original C record or complete cut"
                );
                anyhow::ensure!(
                    again.refusal_attempt > finalized.refusal_attempt,
                    "second query did not complete a new original C read"
                );
                anyhow::ensure!(
                    accepted.require_unchanged()? > first_attempt,
                    "second query did not complete a new acceptance verification"
                );
                Ok::<_, anyhow::Error>((first, again))
            })
            .await
            .map_err(|error| anyhow::anyhow!("original cold read-only phase deadline: {error}"))?
        })?;
        let (plan, daemon, root) = running.stop_after_original_readback()?;
        for (name, process) in [("cold-daemon", &daemon), ("cold-root", &root)] {
            process.require_dead()?;
            let directory = evidence.directory.join(name);
            std::fs::create_dir(&directory)?;
            super::super::owned_mode(&directory, 0, 0, 0o700)?;
            process.archive_original_logs(&directory)?;
        }
        original.source.require_dead()?;
        let terminal = original
            .terminal
            .snapshot
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("actual old terminal absent"))?;
        let physical = OriginalCompletedCData::observe_after_original_exit(
            &original.plan,
            &original.selected,
            &original.target,
            terminal,
            &original.daemon,
            &original.root,
        )?;
        anyhow::ensure!(
            physical == original.completed,
            "cold recovery changed complete original C data"
        );
        let final_cut = successor
            .observe_finalized(original)?
            .ok_or_else(|| anyhow::anyhow!("Finalized C missing after new processes exited"))?;
        anyhow::ensure!(
            (&final_cut.record_digest, &final_cut.cut)
                == (&observed.1.record_digest, &observed.1.cut),
            "new process exit changed Finalized C data"
        );
        let actual = |child: &crate::ordinary_q24_process_child_tests::ExitedOriginalProcess| {
            let life = child.lifetime();
            json!({"pid":life.pid,"start_ticks":life.start_ticks,"boot_id":life.boot_id})
        };
        anyhow::ensure!(
            Instant::now() < plan.administration.end,
            "cold exit/readback exceeded original phase"
        );
        Ok(json!({
            "completion":observed.0,"finalized":final_cut,
            "daemon":actual(&daemon),"root":actual(&root),
            "original_independent_source":actual(&original.source),
            "cell_revision":physical.cell.snapshot.revision,
            "actual_c_publication":physical.source.publication_digest().to_string(),
            "actual_c_checkpoint":physical.source.checkpoint_digest().to_string(),
        }))
    })();
    // Every failure still gets the immutable old business and first-fact
    // postchecks. Mutable refusal records are checked separately and may fail.
    let business_after = evidence.require_unchanged(original);
    let acceptance_after = accepted.require_unchanged();
    let recipient_after = recipient.require_unchanged();
    super::root::write_json(
        &evidence.directory.join("cold-postchecks.json"),
        &json!({
            "business_error":business_after.as_ref().err().map(|e| format!("{e:#}")),
            "acceptance_error":acceptance_after.as_ref().err().map(|e| format!("{e:#}")),
            "recipient_error":recipient_after.as_ref().err().map(|e| format!("{e:#}")),
            "work_error":work.as_ref().err().map(|e| format!("{e:#}")),
        }),
    )?;
    let observed = work?;
    business_after?;
    acceptance_after?;
    recipient_after?;
    anyhow::ensure!(
        Instant::now() < end,
        "whole cold final observation deadline"
    );
    Ok(observed)
}

fn expected_data(
    running: &RunningOrdinaryCold<'_>,
    recipient: &OriginalColdRecipientData,
    accepted: &OriginalColdAcceptanceData,
    finalized: &OriginalFinalizedColdData,
) -> anyhow::Result<OriginalQ24CompletedHistoryDataV1> {
    let original = running.plan.original;
    let successor = RootCompletedSuccessorDataV1 {
        record_digest: finalized.record_digest.clone(),
        cut: finalized.cut.clone(),
    };
    let data = OriginalQ24CompletedHistoryDataV1 {
        schema: 1,
        identity_digest: crate::neuron_generation_process_identity_digest_v1(
            &running.plan.administration.successor.identity,
        )?
        .to_string(),
        root_profile: recipient.profile.binding.clone(),
        initial: original
            .plan
            .profile
            .original_initial_data()?
            .head_digest
            .to_string(),
        frozen_scope: original.terminal.scope_binding.to_string(),
        terminal_head: original.completed.terminal.head_digest.to_string(),
        acceptance: accepted.digest.clone(),
        current_head: head_digest(&original.completed.current)?,
        successor_record: finalized.record_digest.clone(),
        successor_cut: successor.original_cut_digest()?.to_string(),
    };
    data.validate_data().map_err(anyhow::Error::msg)?;
    Ok(data)
}
