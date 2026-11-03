//! Controlled real jobs acceptance, deliberately separate from normal tests.
//! The SSH transport is a fixture and Linux detached fallback is explicit.
//! Production writer/FinalUse, runtime job registry, helper, supervisor, child,
//! output fsync, terminal publication, and cancellation are real code paths.
//! This does not qualify SSH, systemd/jobctl, or controller process restart.

use pretty_assertions::assert_ne;

use std::path::Path;
use std::path::PathBuf;

use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_native_agent::ToolPort;
use codex_hepta_types::Generation;
use hepta_runtime::native::NativeJobOutcome;
use pretty_assertions::assert_eq;
use serde_json::Value;

use super::*;
use crate::NativeTurnAdmission;
use crate::native_ports::NativeProductionPorts;

#[path = "native_runtime_acceptance_fixture.rs"]
mod support;

#[path = "native_runtime_full_turn_tests.rs"]
mod full_turn;

#[path = "native_runtime_context_tests.rs"]
mod long_context;

struct OwnedCompiler {
    work: PathBuf,
}

impl NativeToolCompiler for OwnedCompiler {
    fn compile(&self, call: &ToolCall) -> Result<ProcessStartParams> {
        ensure!(
            call.name == "owned_process"
                && call.arguments == b"{}"
                && matches!(
                    call.call_id.as_str(),
                    "success"
                        | "cancel"
                        | "terminal-race"
                        | "fresh-blocked"
                        | "full-turn"
                        | "continuation-raw"
                        | "continuation-reconcile"
                        | "context-first"
                        | "context-second"
                ),
            "fixture compiler refuses unrelated commands"
        );
        Ok(serde_json::from_value(json!({
            "host":"controlled", "executable":"/usr/bin/python3",
            "args":[self.work.join("worker.py"), self.work, call.call_id],
            "cwd":self.work, "timeout_seconds":30
        }))?)
    }
}

// Share the exact controlled process owner with the separate signed-Objective
// acceptance test. Existing four cases and their command allowlist are unchanged.
pub(super) async fn objective_process_environment() -> Result<Option<PathBuf>> {
    ensure!(
        std::env::var(support::OPT_IN).as_deref() == Ok("1"),
        "held: explicit real-process opt-in is required"
    );
    if std::env::var(support::CHILD).as_deref() != Ok("1") {
        support::isolated_objective_subprocess().await?;
        return Ok(None);
    }
    let root = PathBuf::from(support::ROOT);
    support::initialize(&root).await?;
    Ok(Some(root))
}

pub(super) async fn checkpoint_continuation_environment() -> Result<Option<PathBuf>> {
    ensure!(
        std::env::var(support::OPT_IN).as_deref() == Ok("1"),
        "held: explicit real-process opt-in is required"
    );
    if std::env::var(support::CHILD).as_deref() != Ok("1") {
        support::isolated_checkpoint_continuation_subprocess().await?;
        return Ok(None);
    }
    let root = PathBuf::from(support::ROOT);
    support::initialize(&root).await?;
    Ok(Some(root))
}

pub(super) async fn daemon_environment() -> Result<Option<(PathBuf, codex_arg0::Arg0DispatchPaths)>>
{
    ensure!(
        std::env::var(support::OPT_IN).as_deref() == Ok("1"),
        "held: explicit daemon acceptance opt-in is required"
    );
    if std::env::var(support::CHILD).as_deref() != Ok("1") {
        support::isolated_daemon_subprocess().await?;
        return Ok(None);
    }
    let root = PathBuf::from(support::ROOT);
    support::initialize(&root).await?;
    Ok(Some((
        root,
        codex_arg0::Arg0DispatchPaths {
            codex_self_exe: Some(PathBuf::from(support::CODEX_HELPER)),
            ..codex_arg0::Arg0DispatchPaths::default()
        },
    )))
}

pub(super) fn owned_fixture_compiler(root: &Path) -> Arc<dyn NativeToolCompiler> {
    Arc::new(OwnedCompiler {
        work: root.join("work"),
    })
}

async fn wait_for_marker(root: &Path, kind: &str) -> Result<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        while !tokio::fs::try_exists(root.join("work").join(format!("{kind}.marker"))).await? {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        Ok::<_, anyhow::Error>(())
    })
    .await
    .context("real child never produced its marker")??;
    Ok(())
}

async fn wait_for_terminal(
    ports: &NativeProductionPorts,
    intent: &codex_hepta_types::RuntimeToolIntentV1,
) -> Result<ToolObservation> {
    tokio::time::timeout(Duration::from_secs(15), async {
        loop {
            let observed = ports.observe(intent).await?;
            if matches!(observed, ToolObservation::Terminal { .. }) {
                return Ok(observed);
            }
            tokio::time::sleep(Duration::from_millis(30)).await;
        }
    })
    .await
    .context("original real process has no complete terminal publication")?
}

async fn transport_observations(root: &Path, job_id: &str) -> Result<usize> {
    let trace = tokio::fs::read_to_string(root.join("transport.jsonl")).await?;
    let events = trace
        .lines()
        .map(serde_json::from_str::<Value>)
        .collect::<serde_json::Result<Vec<_>>>()?;
    Ok(events
        .iter()
        .filter(|event| event["job_id"] == job_id)
        .count())
}

async fn exercise(root: &Path, kind: &str) -> Result<Value> {
    let mut fixture = Fixture::new("http://127.0.0.1:9/v1/responses".to_owned()).await?;
    fixture.native.compiler = Arc::new(OwnedCompiler {
        work: root.join("work"),
    });
    let _active = fixture.state.dispatch_native_run(&fixture.run)?;
    let dispatched = fixture.state.native_run_receipt(&fixture.run.run_id)?;
    let admission = fixture.native.admission(
        fixture.anchor.checkpoint.clone(),
        fixture.scope.clone(),
        &dispatched,
    )?;
    let call = ToolCall {
        call_id: kind.to_owned(),
        name: "owned_process".to_owned(),
        arguments: b"{}".to_vec(),
    };
    let admitted = admission
        .admit_tool(&fixture.initial.binding, &call)
        .await?;
    let original_params: ProcessStartParams = serde_json::from_slice(&admitted.arguments)?;
    let key = admitted.intent.idempotency_key.as_str();
    let destination = fixture.native.runtime.destination_id();
    let original = fixture
        .writer
        .resolve_operation_request(key, destination)
        .await?;
    let ports = NativeProductionPorts {
        entry_owner: crate::native_ports::NativeEntryOwner::Agentd,
        admission,
        model: fixture.native.model.clone(),
        runtime: fixture.native.runtime.clone(),
    };
    let first = ports
        .execute_or_observe(&admitted.intent, &admitted.arguments)
        .await?;
    if kind == "terminal-race" {
        // The transport returns an actual running status only after this same
        // child has durably finished. Dispatch therefore first settles unknown;
        // the second observation must settle terminal before returning it here.
        assert!(matches!(&first, ToolObservation::Terminal { .. }));
        assert_eq!(
            fixture.writer.status(key).await?,
            LocalOutcomeState::Committed,
            "returning terminal must not strand the original writer indeterminate"
        );
    } else {
        assert!(matches!(&first, ToolObservation::Accepted));
        assert_eq!(
            fixture.writer.status(key).await?,
            LocalOutcomeState::Indeterminate
        );
    }
    wait_for_marker(root, kind).await?;
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 1);
    let observed: Value = serde_json::from_str(
        &hepta_runtime::native::observe_request(original_params.clone())
            .await?
            .context("original runtime binding")?,
    )?;
    let job_id = observed["job"]["id"]
        .as_str()
        .context("original job id")?
        .to_owned();
    assert_eq!(observed["job"]["system_jobctl"], false);
    let launch: Value = serde_json::from_slice(
        &tokio::fs::read(root.join("remote/jobs").join(&job_id).join("launch.json")).await?,
    )?;
    assert_eq!(
        launch["backend"], "detached",
        "fixture must not reach a systemd service"
    );
    if kind != "terminal-race" {
        // Duplicate refusal must hold while the original outcome is unknown,
        // not only after the writer has already committed a terminal receipt.
        assert!(
            fixture
                .native
                .host
                .begin_native_effect(destination, key)
                .await
                .is_err()
        );
        assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 1);
        let entries = Arc::new(AtomicUsize::new(0));
        let pending_entries = Arc::clone(&entries);
        let pending: Value = serde_json::from_str(
            &hepta_runtime::native::execute_or_observe_with_entry(
                original_params.clone(),
                move |_| -> Result<()> {
                    pending_entries.fetch_add(1, Ordering::SeqCst);
                    anyhow::bail!("an unresolved original job must not consume another entry")
                },
            )
            .await?,
        )?;
        assert_eq!(
            (
                &pending["job"]["id"],
                &pending["reused"],
                &pending["retried_launch"]
            ),
            (&json!(job_id), &json!(true), &json!(false))
        );
        assert_eq!(entries.load(Ordering::SeqCst), 0);
        assert_eq!(
            fixture.writer.status(key).await?,
            LocalOutcomeState::Indeterminate
        );
    }
    drop(ports);

    let terminal = if kind == "terminal-race" {
        let held: Value = serde_json::from_slice(
            &tokio::fs::read(root.join("work/terminal-race.first-status.json")).await?,
        )?;
        assert_eq!(held["job_id"], job_id);
        assert_eq!(
            held["state"], "running",
            "barrier must retain a real pre-terminal observation"
        );
        first
    } else if kind == "success" {
        // Rebuild an observer after the actual original run becomes unknown.
        // Original policy 7 remains correlation; current policy 8 grants no new effect.
        let unknown = fixture
            .state
            .observe_native_run(&fixture.run.run_id, RunPhase::Indeterminate)?;
        let gate = Arc::new(NativeEntryGate {
            state: Arc::downgrade(&fixture.state),
            policy_generation: 8,
        });
        let runtime = Arc::new(NativeRuntimeTarget::new(
            destination.to_owned(),
            /*max_output_bytes*/ 4096,
        )?);
        let recovered = AgentdNativeHost {
            gate,
            host: fixture.native.host.clone(),
            model: fixture.native.model.clone(),
            runtime,
            compiler: fixture.native.compiler.clone(),
        };
        let admission = recovered.admission_with_policy(
            fixture.anchor.checkpoint.clone(),
            fixture.scope.clone(),
            Generation::new(7)?,
            &unknown,
        )?;
        let fresh = ToolCall {
            call_id: "fresh-blocked".to_owned(),
            name: "owned_process".to_owned(),
            arguments: b"{}".to_vec(),
        };
        assert!(
            admission
                .admit_tool(&fixture.initial.binding, &fresh)
                .await
                .is_err()
        );
        let observing = NativeProductionPorts {
            entry_owner: crate::native_ports::NativeEntryOwner::Agentd,
            admission,
            model: recovered.model.clone(),
            runtime: recovered.runtime.clone(),
        };
        tokio::fs::write(root.join("work/success.release"), b"release original child").await?;
        wait_for_terminal(&observing, &admitted.intent).await?
    } else {
        // Real drain blocks new entry, but cancellation and observation retain
        // precisely the original request/key/job. No replacement is admitted.
        fixture.state.mark_draining()?;
        let observing = NativeProductionPorts {
            entry_owner: crate::native_ports::NativeEntryOwner::Agentd,
            admission: fixture.native.admission(
                fixture.anchor.checkpoint.clone(),
                fixture.scope.clone(),
                &dispatched,
            )?,
            model: fixture.native.model.clone(),
            runtime: fixture.native.runtime.clone(),
        };
        observing.cancel(&admitted.intent).await?;
        wait_for_terminal(&observing, &admitted.intent).await?
    };
    let ToolObservation::Terminal {
        receipt,
        stdout,
        stderr,
    } = terminal
    else {
        anyhow::bail!("terminal required")
    };
    receipt.validate_against(&admitted.intent)?;
    assert_eq!(stderr, format!("stderr {kind}\n").as_bytes());
    if kind != "cancel" {
        assert_eq!(stdout, format!("BEGIN {kind}\nEND {kind}\n").as_bytes());
        assert_eq!(receipt.tool_outcome.exit_code, Some(0));
    } else {
        assert_eq!(stdout, b"BEGIN cancel\n");
        assert_ne!(receipt.tool_outcome.exit_code, Some(0));
    }
    let terminal = fixture
        .native
        .runtime
        .observe_original(&original)
        .await?
        .context("real durable terminal")?;
    assert_eq!(terminal.job_id(), job_id);
    assert_eq!(
        terminal.outcome(),
        if kind == "cancel" {
            NativeJobOutcome::Cancelled
        } else {
            NativeJobOutcome::Succeeded
        }
    );

    // Compare against one actual complete observation of this same immutable
    // terminal. The port must settle and return that evidence, not fetch the
    // complete remote output a second time for the production receipt.
    let before = transport_observations(root, &job_id).await?;
    let evidence = fixture
        .native
        .runtime
        .observe_tool_evidence(&original, &admitted.intent)
        .await?
        .context("original terminal evidence")?;
    let one_observation = transport_observations(root, &job_id).await? - before;
    assert!(
        one_observation > 0,
        "reference observation must exercise the original runtime transport"
    );
    let current = fixture.state.native_run_receipt(&fixture.run.run_id)?;
    let observing = NativeProductionPorts {
        entry_owner: crate::native_ports::NativeEntryOwner::Agentd,
        admission: fixture.native.admission(
            fixture.anchor.checkpoint.clone(),
            fixture.scope.clone(),
            &current,
        )?,
        model: fixture.native.model.clone(),
        runtime: fixture.native.runtime.clone(),
    };
    let before = transport_observations(root, &job_id).await?;
    let ToolObservation::Terminal {
        receipt: again,
        stdout: output,
        stderr: errors,
    } = observing.observe(&admitted.intent).await?
    else {
        anyhow::bail!("original terminal changed while observing its production receipt");
    };
    assert_eq!(
        transport_observations(root, &job_id).await? - before,
        one_observation,
        "one port observation must not transfer the complete terminal output twice"
    );
    assert_eq!(
        (again, output, errors),
        (evidence.receipt, evidence.stdout, evidence.stderr)
    );
    assert_eq!(
        fixture.writer.status(key).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        fixture
            .writer
            .resolve_operation_request(key, destination)
            .await?,
        original
    );
    assert_eq!(
        fixture.issuer.grants.load(Ordering::SeqCst),
        1,
        "observation cannot mint another grant"
    );
    assert!(
        fixture
            .native
            .host
            .begin_native_effect(destination, key)
            .await
            .is_err(),
        "original production claim cannot be submitted twice"
    );
    assert_eq!(
        fixture.issuer.grants.load(Ordering::SeqCst),
        1,
        "duplicate claim cannot mint another grant"
    );
    let duplicate_entries = Arc::new(AtomicUsize::new(0));
    let reused_entries = Arc::clone(&duplicate_entries);
    let reused: Value = serde_json::from_str(
        &hepta_runtime::native::execute_or_observe_with_entry(
            original_params.clone(),
            move |_| -> Result<()> {
                reused_entries.fetch_add(1, Ordering::SeqCst);
                anyhow::bail!("duplicate original job must not reach physical entry")
            },
        )
        .await?,
    )?;
    assert_eq!(
        (
            &reused["job"]["id"],
            &reused["reused"],
            &reused["retried_launch"]
        ),
        (&json!(job_id), &json!(true), &json!(false))
    );
    let mut changed = original_params;
    changed.args.push("changed-payload".to_owned());
    let changed_entries = Arc::clone(&duplicate_entries);
    assert!(
        hepta_runtime::native::execute_or_observe_with_entry(changed, move |_| -> Result<()> {
            changed_entries.fetch_add(1, Ordering::SeqCst);
            anyhow::bail!("changed original payload must not reach physical entry")
        })
        .await
        .is_err()
    );
    assert_eq!(duplicate_entries.load(Ordering::SeqCst), 0);
    let attempts =
        tokio::fs::read_to_string(root.join("work").join(format!("{kind}.attempts"))).await?;
    assert_eq!(
        attempts.lines().count(),
        1,
        "the real workload must run exactly once"
    );
    let trace = tokio::fs::read_to_string(root.join("transport.jsonl")).await?;
    let events = trace
        .lines()
        .map(serde_json::from_str::<Value>)
        .collect::<serde_json::Result<Vec<_>>>()?;
    assert_eq!(
        events
            .iter()
            .filter(|event| event["launch"] == true && event["job_id"] == job_id)
            .count(),
        1
    );
    fixture.live.shutdown().await?;
    Ok(
        json!({"case":kind,"job_id":job_id,"original_operation":key,"real_child_attempts":1,
        "transport_launches":1,"final_use_grants":1,"writer":"committed",
        "stdout_sha256":Digest32::of_bytes(&stdout).to_string(),"stderr_sha256":Digest32::of_bytes(&stderr).to_string()}),
    )
}

#[tokio::test]
#[ignore = "requires explicit opt-in, Linux bwrap namespaces, and real owned processes"]
async fn controlled_native_process_acceptance() -> Result<()> {
    ensure!(
        std::env::var(support::OPT_IN).as_deref() == Ok("1"),
        "held: explicit real-process opt-in is required"
    );
    if std::env::var(support::CHILD).as_deref() != Ok("1") {
        return support::isolated_subprocess().await;
    }
    let root = Path::new(support::ROOT);
    support::initialize(root).await?;
    let success = exercise(root, "success").await?;
    let cancelled = exercise(root, "cancel").await?;
    let terminal_race = exercise(root, "terminal-race").await?;
    let full_turn = full_turn::exercise(root).await?;
    let long_context = long_context::exercise(root).await?;
    tokio::fs::write(root.join("report.json"), serde_json::to_vec_pretty(&json!({
        "schema":"hepta.native.controlled-real-runtime.v1", "passed":true,
        "scope":"NativeHost turn + original queue/checkpoint/history + production writer + FinalUse + original jobs owner + real helper/supervisor/child/output/cancel",
        "transport":"fixture executes unchanged runtime Python helper", "backend":"detached fallback",
        "model_provider":"localhost HTTP/SSE fixture, not a live production model",
        "full_native_tool_turn":true,
        "observer_rebuild":true, "runtime_controller_process_restart":false,
        "ssh_systemd_jobctl_qualification":"held", "cases":[success,cancelled,terminal_race,full_turn,long_context]
    }))?).await?;
    Ok(())
}
