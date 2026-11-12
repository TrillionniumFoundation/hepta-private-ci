//! Ordinary binary process qualification. Private setup modules provide
//! explicit input data; no setup routine certifies a task or learning result.

#[path = "ordinary_q24_b_publication_observer_tests.rs"]
mod b_publication_observer;
#[path = "ordinary_q24_process_deployment_tests.rs"]
mod deployment;
#[path = "ordinary_q24_process_fixture_tests.rs"]
mod fixture;
#[path = "ordinary_q24_process_inputs_tests.rs"]
mod inputs;
#[path = "ordinary_q24_process_launch_tests.rs"]
mod launch;
#[path = "ordinary_q24_process_observer_tests.rs"]
mod observer;
#[path = "ordinary_q24_post_a_artifact_inputs_tests.rs"]
mod post_a_artifact_inputs;
#[path = "ordinary_q24_post_a_c_inputs_tests.rs"]
mod post_a_c_inputs;
#[path = "ordinary_q24_post_a_deployment_tests.rs"]
mod post_a_deployment;
#[path = "ordinary_q24_post_a_file_tests.rs"]
mod post_a_file;
#[path = "ordinary_q24_post_a_launch_tests.rs"]
mod post_a_launch;
#[path = "ordinary_q24_post_a_owner_tests.rs"]
mod post_a_owner;
#[path = "ordinary_q24_post_a_plan_tests.rs"]
mod post_a_plan;
#[path = "ordinary_q24_post_a_selection_tests.rs"]
mod post_a_selection;
#[path = "ordinary_q24_post_a_trust_tests.rs"]
mod post_a_trust;
#[path = "ordinary_q24_process_recovery_tests.rs"]
mod recovery;
#[path = "ordinary_q24_process_root_tests.rs"]
mod root;
#[path = "ordinary_q24_root_pair_tests.rs"]
mod root_pair;
#[path = "ordinary_q24_source_keeper_tests.rs"]
mod source_keeper;

use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_types::Digest32;
use serde_json::json;

use crate::ordinary_q24_process_child_tests::ExitedOriginalProcess;
use crate::ordinary_q24_process_child_tests::OriginalChild;
use crate::ordinary_q24_process_child_tests::OriginalChildDescriptors;

/// Real first-A results and retired processes. This is a test evidence holder,
/// not a Dataset, an adoption receipt or a historical admission capability.
pub(crate) struct RetainedOriginalAPhase {
    plan: fixture::OrdinaryAPlan,
    daemon: ExitedOriginalProcess,
    root: ExitedOriginalProcess,
    observer: ExitedOriginalProcess,
    admission: crate::ObjectiveRunAdmission,
    outcome: observer::ObservedOriginalOutcome,
    source_pin: Digest32,
}

#[test]
#[ignore = "actual UID0/protected Root bind and both production binaries; ordinary A phase only"]
fn ordinary_main_a_records_independent_outcome_and_retires_original_processes() -> anyhow::Result<()>
{
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    let retained = run_original_a(&runtime, /*independent business value*/ 2_i64 << 32)?;
    retained.archive_phase()
}

pub(crate) fn run_original_a(
    runtime: &tokio::runtime::Runtime,
    independent_value: i64,
) -> anyhow::Result<RetainedOriginalAPhase> {
    let plan = fixture::OrdinaryAPlan::prepare(runtime)?;
    // This independent fixture measurement is fixed before A executes. It is
    // never computed from its score, success, exit status or publication.
    let fact_path = plan.protected.path().join("original-business-fact.json");
    root::write_json(
        &fact_path,
        &observer::OriginalBusinessFact {
            schema: 1,
            episode_id: "ordinary-original-a-episode".into(),
            unit_profile_digest: Digest32::from_array(deployment::digest(
                "ordinary-observed-scalar-q24",
            ))
            .to_string(),
            expected_delay_profile_digest: Digest32::from_array(deployment::digest(
                "ordinary-immediate-external-observation",
            ))
            .to_string(),
            value_raw_q32: independent_value,
        },
    )?;
    let running = launch::RunningOrdinaryA::start(plan)?;
    runtime.block_on(running.promote_when_initialized())?;
    let client = running.client()?;
    let reply = runtime.block_on(client.objective_start_once_until(
        running.plan.objective.request.clone(),
        tokio::time::Instant::from_std(running.end),
    ))?;
    let crate::client::ObjectiveStartReplyV1::Completed(crate::ObjectiveStartOutcome::Admitted {
        receipt: admission,
    }) = reply
    else {
        anyhow::bail!(
            "ordinary original Objective returned conflict or uncertain ACK; no inferred execution"
        );
    };
    anyhow::ensure!(
        admission.run_id == inputs::RUN
            && admission.objective_digest.parse::<Digest32>()? == running.plan.objective.objective
            && admission.disposition == "circuit_succeeded"
            && !admission.idempotent
            && !admission.publication_digest.parse::<Digest32>()?.is_zero()
            && !admission.chain_digest.parse::<Digest32>()?.is_zero(),
        "actual original ordinary Circuit admission/result required"
    );
    running.require_live()?;
    let result_path = running
        .plan
        .protected
        .path()
        .join("original-observer-result.json");
    let observer_plan_path = running
        .plan
        .protected
        .path()
        .join("original-observer-plan.json");
    root::write_json(
        &observer_plan_path,
        &observer::ObserverPlan {
            schema: 1,
            control: running.plan.identity.control_socket.clone(),
            agent: running.plan.identity.agent_id.to_string(),
            spawn: running.plan.identity.spawn_generation,
            daemon_pid: running.daemon.lifetime().pid,
            run_id: inputs::RUN.into(),
            objective: running.plan.objective.objective.to_string(),
            trust: running.plan.observer_payload.clone(),
            key: running.plan.observer_key.clone(),
            fact: fact_path.clone(),
            result: result_path.clone(),
            expires_at_millis: running.plan.objective.request.expires_at_ms,
        },
    )?;
    let mut command = Command::new(std::env::current_exe()?);
    command
        .args(["--ignored", "--exact", observer::CHILD_TEST, "--nocapture"])
        .env(observer::PLAN_ENV, &observer_plan_path);
    let observer_child = OriginalChild::spawn(&mut command, OriginalChildDescriptors::default())?;
    anyhow::ensure!(
        observer_child.lifetime() != running.daemon.lifetime()
            && observer_child.lifetime() != running.root.lifetime(),
        "independent actual Observer process"
    );
    let observer_exit = observer_child.wait_success_until(running.end)?;
    let outcome: observer::ObservedOriginalOutcome =
        serde_json::from_slice(&observer::read_private(&result_path, 64 * 1024)?)?;
    anyhow::ensure!(
        outcome.original_fact_digest.parse::<Digest32>()?
            == Digest32::of_bytes(&observer::read_private(&fact_path, 4096)?),
        "original independent measurement binding"
    );
    pretty_assertions::assert_eq!(
        runtime.block_on(client.original_q24_task_observation())?,
        outcome.observed
    );
    running.require_live()?;
    running.daemon.request_original_shutdown()?;
    let launch::RunningOrdinaryA {
        plan,
        daemon,
        root,
        end,
    } = running;
    let daemon = daemon.wait_success_until(end)?;
    let root = root.wait_success_until(end)?;
    daemon.require_dead()?;
    root.require_dead()?;
    let directory = RootAuthorityDirectory::open(&plan.root.current)?;
    let pin = crate::authority_host_service::generation_initial::historical_source_pin::RootHistoricalSourcePinV1::open_existing(
        Arc::clone(&directory), &plan.deployment.target)?;
    let source_pin = pin.readback_digest()?;
    anyhow::ensure!(
        !source_pin.is_zero() && pin.readback_digest()? == source_pin,
        "actual Root retained original Source cut required after process exit"
    );
    // The successor's real historical route must still join Finalized handoff,
    // Cell, RunStart and Ledger, and authorize its own new recipient. This
    // retained Source observation alone is deliberately not that permission.
    Ok(RetainedOriginalAPhase {
        plan,
        daemon,
        root,
        observer: observer_exit,
        admission,
        outcome,
        source_pin,
    })
}

impl RetainedOriginalAPhase {
    pub(crate) fn business_files(&self) -> Vec<PathBuf> {
        let mut paths = self.plan.files.business_files();
        paths.extend([
            self.plan.target_journal.clone(),
            self.plan.target_witness.clone(),
            self.plan
                .identity
                .home_root
                .join("objective-run-start-v1/journal.bin"),
            self.plan.objective_trust.clone(),
            self.plan.objective_profile.clone(),
        ]);
        paths
    }

    pub(crate) fn original_processes(&self) -> (&ExitedOriginalProcess, &ExitedOriginalProcess) {
        (&self.daemon, &self.root)
    }

    fn archive_phase(self) -> anyhow::Result<()> {
        self.daemon.require_dead()?;
        self.root.require_dead()?;
        self.observer.require_dead()?;
        for (name, child) in [
            ("daemon", &self.daemon),
            ("root", &self.root),
            ("observer", &self.observer),
        ] {
            let directory = self.plan.protected.path().join(name);
            std::fs::create_dir(&directory)?;
            super::owned_mode(&directory, 0, 0, 0o700)?;
            child.archive_original_logs(&directory)?;
        }
        let process = |child: &ExitedOriginalProcess| {
            let actual = child.lifetime();
            json!({"pid":actual.pid,"start_ticks":actual.start_ticks,"boot_id":actual.boot_id})
        };
        root::write_json(
            &self.plan.protected.path().join("actual-a-phase.json"),
            &json!({
                "phase":"ordinary_original_a_only", "admission":self.admission,
                "independent_observer":self.outcome,"root_source_pin":self.source_pin.to_string(),
                "original_daemon":process(&self.daemon),"original_root":process(&self.root),
                "original_observer":process(&self.observer),"business_files":self.business_files()
            }),
        )?;
        eprintln!(
            "ORDINARY_Q24_ACTUAL_A_EVIDENCE={}",
            self.plan.protected.path().display()
        );
        // Keep exact input/output bytes and complete logs for subsequent cold
        // phases and review. These paths are not a proof that learning passed.
        let _ = self.plan.protected.keep();
        let _ = self.plan.runtime.keep();
        Ok(())
    }
}
