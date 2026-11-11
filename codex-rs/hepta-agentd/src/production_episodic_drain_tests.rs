//! Actual App Server drain, retained original SQLite owner, and cancelled reply.
//! Source observations and authority are explicit test fixtures, not production.
use std::error::Error;
use std::process::Command;
use std::sync::Arc;
use std::sync::Condvar;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_arg0::Arg0DispatchPaths;
use codex_hepta_automation::AutomationStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::EpisodicSnapshotAdmission;
use codex_hepta_memory::EpisodicSnapshotVerifier;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

use super::Fixture;
use super::FixtureSource;
use super::SNAPSHOT;
use super::assert_no_issuer_request;
use super::attach_production_operation_host;
use super::observed_source;

const CASE_ENV: &str = "HEPTA_EPISODIC_DRAIN_REGRESSION_CASE";
const WAIT: Duration = Duration::from_secs(10);

struct PausedSource {
    original: Arc<FixtureSource>,
    checks: AtomicUsize,
    entered: Notify,
    queued: Notify,
    released: Mutex<bool>,
    release: Condvar,
    case: String,
}

impl EpisodicSnapshotVerifier for PausedSource {
    fn verify_current(&self, snapshot: &str) -> Result<EpisodicSnapshotAdmission, String> {
        let check = self.checks.fetch_add(1, Ordering::SeqCst) + 1;
        if check == 3 {
            self.queued.notify_one();
        }
        if check == 2 {
            // The second read is inside the real canonical write transaction.
            self.entered.notify_one();
            let released = self.released.lock().map_err(|error| error.to_string())?;
            let (released, timeout) = self.release.wait_timeout_while(
                released, WAIT, |released| !*released,
            ).map_err(|error| error.to_string())?;
            if timeout.timed_out() || !*released {
                return Err("test source barrier timed out".into());
            }
            if self.case == "panic" {
                panic!("test-only source owner panicked before settlement");
            }
            if self.case == "revoke" {
                return Err("test-only source owner withdrew its observation".into());
            }
        }
        self.original.verify_current(snapshot)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn episodic_import_cancellation_cannot_overtake_owner_settlement() -> Result<(), Box<dyn Error>> {
    let case = match std::env::var(CASE_ENV) {
        Ok(case) => case,
        Err(std::env::VarError::NotPresent) => {
            // The real App Server owns a process-global Codex home. Isolate
            // each case in this exact test, without changing the parent home.
            let name = format!("{}::episodic_import_cancellation_cannot_overtake_owner_settlement", module_path!());
            let (_, name) = name.split_once("::").expect("crate-qualified test name");
            for case in ["commit", "revoke", "panic"] {
                let output = Command::new(std::env::current_exe()?)
                    .args(["--exact", name, "--nocapture"]).env(CASE_ENV, case).output()?;
                assert!(output.status.success(), "{case}: stdout={} stderr={}",
                    String::from_utf8_lossy(&output.stdout), String::from_utf8_lossy(&output.stderr));
                assert!(String::from_utf8_lossy(&output.stdout)
                    .contains(&format!("episodic-drain-case-complete:{case}")),
                    "child did not execute the expected case");
            }
            return Ok(());
        }
        Err(error) => return Err(error.into()),
    };
    assert!(matches!(case.as_str(), "commit" | "revoke" | "panic"));
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let host = config.production_writer_host().expect("original recovered writer");
    let source = Arc::new(PausedSource {
        original: observed_source(), checks: AtomicUsize::new(0), entered: Notify::new(), queued: Notify::new(),
        released: Mutex::new(false), release: Condvar::new(), case: case.clone(),
    });
    let mut config = config.with_episodic_snapshot_import("bridge-fixture".into(), source.clone())?;
    let ingress = config.take_episodic_snapshot_import().expect("configured source");
    let (identity, registry, _writer_lock) = config.into_parts();
    let state = Arc::new(crate::state::AgentdState::new(
        identity.clone(), registry.clone(), /*event_capacity*/ 32,
    )?);
    state.attach_cognitive_store(host.cognitive_runtime().available_store().unwrap().clone())?;
    state.episodic_snapshot_import.set(ingress).ok().expect("single original owner");
    let automation = AutomationStore::open(&identity.layout).await?;
    state.attach_automation_store(automation.clone())?;
    let running = registry.compare_and_transition(&identity.agent_id, 1, AgentLifecycle::Running)?;
    state.refresh_generation()?;
    state.mark_runtime_prerequisites_ready()?;
    std::fs::write(identity.home_root.join("config.toml"), r#"
model = "episodic-drain-fixture"
approval_policy = "never"
sandbox_mode = "read-only"
model_provider = "drain_fixture"
[model_providers.drain_fixture]
name = "No inference in drain regression"
base_url = "http://127.0.0.1:9/v1"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
"#)?;
    codex_utils_home_dir::set_process_codex_home_override(
        AbsolutePathBuf::from_absolute_path(&identity.home_root)?,
    )?;
    let app = tokio::spawn(crate::app_runtime::run_app_server(
        identity.clone(), Arg0DispatchPaths::default(), host.cognitive_runtime(),
        Arc::clone(&state), Some(Arc::clone(&host)),
        crate::app_runtime::AppServerSocket::Bind,
        crate::app_runtime::AppServerModelToolProfile::Standard,
    ));
    tokio::time::timeout(WAIT, async {
        while !identity.app_server_socket.exists() {
            assert!(!app.is_finished(), "App Server exited before readiness");
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await?;
    state.mark_app_server_ready()?;
    let cancellation = CancellationToken::new();
    let control = crate::AgentdControlServer::bind(
        identity.control_socket.clone(), Arc::clone(&state), cancellation.clone(),
    ).await?;
    let control_task = tokio::spawn(control.run());
    let client = crate::AgentdClient::new(
        identity.control_socket.clone(), identity.agent_id.clone(), /*spawn_generation*/ 1,
    )?;
    assert!(client.health().await?.ready);
    let app_drain = state.app_server_drain_handle();
    let before = host.writer().recovery_anchor().await?;
    let response_state = Arc::clone(&state);
    let response = tokio::spawn(async move {
        response_state.import_episodic_snapshot(SNAPSHOT).await
    });
    tokio::time::timeout(WAIT, source.entered.notified()).await?;
    // Model the control timeout dropping the actual dispatch future. The
    // retained owner task must keep the transaction and pending guard alive.
    response.abort();
    assert!(response.await.expect_err("reply future cancelled").is_cancelled());
    assert_eq!(state.episodic_import_pending_count(), 1);
    let mut app = Some(app);
    if case == "panic" {
        let queued_state = Arc::clone(&state);
        let queued = tokio::spawn(async move {
            queued_state.import_episodic_snapshot(SNAPSHOT).await
        });
        tokio::time::timeout(WAIT, source.queued.notified()).await?;
        queued.abort();
        assert!(queued.await.expect_err("second reply cancelled").is_cancelled());
        assert_eq!(state.episodic_import_pending_count(), 2);
    } else {
        registry.compare_and_transition(&identity.agent_id, running.generation, AgentLifecycle::Draining)?;
        assert!(!state.request_drain(Some(&automation)).await?.drained);
        tokio::time::timeout(WAIT, app.take().unwrap()).await???;
        assert!(app_drain.drained());
        assert_eq!(app_drain.running_turns(), 0);
        assert!(!state.request_drain(Some(&automation)).await?.drained);
    }

    *source.released.lock().unwrap() = true;
    source.release.notify_all();
    tokio::time::timeout(WAIT, async {
        while state.episodic_import_pending_count() != 0 {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await?;
    if case == "panic" {
        // Both reply futures are gone. The queued import must observe the
        // original pool fence before BEGIN; ordinary Health must publish the
        // unresolved owner even while the supervisor still says Running.
        assert_eq!(source.checks.load(Ordering::SeqCst), 3);
        assert!(host.writer().checkpoint_fenced());
        // Existing recovery observation explicitly uses a read transaction
        // and rollback after a whole-owner fence; ordinary context stays denied.
        assert_eq!(host.writer().recovery_anchor().await?, before);
        let health = client.health().await?;
        assert_eq!(health.lifecycle, AgentLifecycle::Running);
        assert!(!health.ready);
        assert!(health.fenced);
        assert!(client.cognitive_context("café".into(), /*limit*/ 4).await.is_err());
        assert!(client.import_episodic_snapshot(SNAPSHOT.into()).await.is_err());
        registry.compare_and_transition(&identity.agent_id, running.generation, AgentLifecycle::Draining)?;
        state.refresh_generation()?;
        state.mark_draining()?;
        tokio::time::timeout(WAIT, app.take().unwrap()).await???;
        assert!(app_drain.drained());
        assert!(state.request_drain(Some(&automation)).await.is_err());
    } else {
        assert!(state.request_drain(Some(&automation)).await?.drained);
        let settled = host.writer().recovery_anchor().await?;
        if case == "revoke" {
            assert_eq!(settled, before);
        } else {
            assert_ne!(settled, before);
            host.import_episodic_snapshot(
                &CognitiveAccess::agent_private(identity.agent_id.clone()),
                &CognitiveScope::AgentPrivate, SNAPSHOT, source.as_ref(),
            ).await?;
            assert_eq!(host.writer().recovery_anchor().await?, settled);
        }
    }
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_no_issuer_request(peer)?;
    cancellation.cancel();
    control_task.await??;
    println!("episodic-drain-case-complete:{case}");
    Ok(())
}
