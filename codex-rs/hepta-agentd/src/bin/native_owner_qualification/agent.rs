use super::common::*;
use codex_hepta_agentd::*;
use codex_hepta_memory::*;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

/// Qualification loss injection wraps the actual native device. It withholds
/// the returned result, not the effect, and never invents a kernel receipt.
struct WithheldReply {
    native: AgentdHos2Device,
    installs: AtomicUsize,
    observations: AtomicUsize,
    observe_enabled: AtomicBool,
}
impl Hos2Device for WithheldReply {
    fn install(
        &self,
        request: &Hos2InstallBudgetV1,
    ) -> std::result::Result<Hos2InstallOutcome, String> {
        self.installs.fetch_add(1, Ordering::SeqCst);
        let result = self.native.install(request)?;
        if !matches!(
            result,
            Hos2InstallOutcome::Observed(Hos2DeliveryObservation::Applied { .. })
        ) {
            return Err(format!("native result was not Applied: {result:?}"));
        }
        println!("HEPTA_NATIVE_REPLY_WITHHELD actual_kernel_install=true replay=false");
        Err("qualification withheld actual native install reply".into())
    }
    fn observe(
        &self,
        request: &Hos2InstallBudgetV1,
    ) -> std::result::Result<Hos2InstallOutcome, String> {
        if !self.observe_enabled.load(Ordering::SeqCst) {
            return Err("qualification observation release pending".into());
        }
        self.observations.fetch_add(1, Ordering::SeqCst);
        self.native.observe(request)
    }
    fn query(
        &self,
        delivery: &Hos2DeliveryId,
    ) -> std::result::Result<Hos2DeliveryObservation, String> {
        self.native.query(delivery)
    }
    fn retire(
        &self,
        permit: &Hos2RetirementPermit,
    ) -> std::result::Result<Hos2RetirementObservation, String> {
        self.native.retire(permit)
    }
}

fn connect(path: &Path) -> Result<UnixStream> {
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        match UnixStream::connect(path) {
            Ok(stream) => return Ok(stream),
            Err(error) => {
                anyhow::ensure!(
                    Instant::now() < deadline,
                    "Root lane {}: {error}",
                    path.display()
                );
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    }
}

pub fn run(boot: Boot) -> Result<()> {
    wait_file(Path::new("/dev/hepta-control"))?;
    wait_file(Path::new("/proc/self/status"))?;
    let control = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open("/dev/hepta-control")?;
    let native =
        AgentdHos2Device::from_bootstrap(control, &boot.bytes).map_err(anyhow::Error::msg)?;
    let root_pidfd = pidfd(boot.root_pid)?;
    drop_agent_credentials()?;
    println!(
        "HEPTA_NATIVE_AGENT_CREDENTIALS uid=60002 capabilities=0 no_new_privs=true same_image=true"
    );
    let mode = super::history::read_case()?;
    if mode == super::history::Case::Historical {
        return super::history::historical_agent(&boot, native);
    }
    let handoff = Path::new(RUN).join("bootstrap.json");
    wait_file(&handoff)?;
    let bundle: HostAuthorityPublicBootstrapV1 = read_json(&handoff, 0)?;
    anyhow::ensure!(
        bundle.root.pid == boot.root_pid && bundle.consumer.pid == boot.agent_pid,
        "actual sealed peer differs"
    );
    let observation = connect(&bundle.sockets.observation)?;
    let issuer = connect(&bundle.sockets.issuer)?;
    let checkpoint = connect(&bundle.sockets.checkpoint)?;
    let device_frontier = connect(&bundle.sockets.device_frontier)?;
    let notes_frontier = connect(&bundle.sockets.notes_frontier)?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    runtime.block_on(async move {
        let registered = &bundle.registered_identity;
        let fleet = codex_hepta_paths::HeptaFleetRoot::parse(registered.fleet_root.clone())?;
        let layout = fleet.layout().agent(&registered.agent_id);
        let mut config = AgentdConfig::load(registered.fleet_root.clone(), registered.agent_id.clone(), registered.spawn_generation,
            layout.home_root().to_owned(), layout.run_root().to_owned(), layout.home_root().to_owned(), registered.workspace.clone())?;
        let identity = config.identity().clone();
        let before = native.read_usage(1).map_err(anyhow::Error::msg)?;
        let revision = initial_revision(&before, &boot.bytes)?;
        let resulting_revision = next_revision(revision)?;
        let planned_payload: String = read_json(&Path::new(RUN).join("native-intent.json"), 0)?;
        let request = Hos2InstallBudgetV1::from_json(&planned_payload).map_err(anyhow::Error::msg)?;
        anyhow::ensure!(request == native.install_request(1, revision, 25_000_000).map_err(anyhow::Error::msg)?
            && request.to_json().map_err(anyhow::Error::msg)? == planned_payload,
            "Root intent differs from independent native initial observation");
        let device = Arc::new(WithheldReply { native, installs:AtomicUsize::new(0), observations:AtomicUsize::new(0), observe_enabled:AtomicBool::new(false) });
        let target = Arc::new(ProductionHos2Target::new(device.clone()));
        let attachment = attach_root_production_host(&mut config, AgentdRootProductionInputs {
            bootstrap:bundle,lanes:AgentdRootAuthorityLanes { observation,issuer,checkpoint,device_frontier,notes_frontier,root_pidfd },
            target:AgentdRootPrimaryTarget::Device(target.clone()),timeout:Duration::from_millis(500),lifetime:Duration::from_secs(180),reconcile_interval:Duration::from_millis(100),
        }).await?;
        let host = attachment.writer_host().as_ref().clone().attach_target(attachment.device_final_use(),target.clone(),attachment.issuer())?;
        // This is the original daemon and its in-process original AppServer.
        // A wrapper over the same retained writer drives the fixed qualification
        // intent; it does not open a second database or substitute a task ledger.
        let daemon = tokio::spawn(codex_hepta_agentd::run(config, codex_arg0::Arg0DispatchPaths::default()));
        let client = AgentdClient::new(identity.control_socket.clone(),identity.agent_id.clone(),identity.spawn_generation)?;
        let deadline = tokio::time::Instant::now() + Duration::from_secs(60);
        loop {
            anyhow::ensure!(!daemon.is_finished(), "original Agentd exited before readiness");
            if let Ok(health) = client.health().await
                && health.promotion_ready { break; }
            anyhow::ensure!(tokio::time::Instant::now() < deadline, "original Agentd readiness deadline");
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        let lifecycle = client.lifecycle().await?;
        anyhow::ensure!(lifecycle.app_server_ready, "original AppServer not ready");
        println!("HEPTA_NATIVE_ORIGINAL_DAEMON_READY original_app_server=true original_sqlite=true");
        let payload = request.to_json().map_err(anyhow::Error::msg)?;
        let issuer = attachment.issuer();
        let denied_binding = codex_hepta_contracts::FinalUseBinding {
            subject_id: OWNER.into(), destination_id: HOS2_DESTINATION_V1.into(),
            scope_sha256: [9; 32], request_sha256: [1; 32],
            payload_sha256: *Digest32::of_bytes(payload.as_bytes()).as_array(),
        };
        anyhow::ensure!(tokio::task::spawn_blocking(move || issuer.request_grant(&denied_binding)).await?.is_err(), "Root accepted a foreign native scope");
        anyhow::ensure!(device.native.read_usage(2).map_err(anyhow::Error::msg)?.revision == revision
            && device.installs.load(Ordering::SeqCst) == 0, "denied scope entered the native device");
        let intent = OperationIntentV1::new(StableId::new("native:g2:original:1")?,StableId::new(OWNER)?,StableId::new(HOS2_DESTINATION_V1)?,
            Digest32::of_bytes(payload.as_bytes()),request.scope_digest(),Generation::new(1)?,None)?;
        let writer = host.writer();
        let queued = writer.prepare_operation(intent,HOS2_INSTALL_TOPIC_V1,payload).await?;
        let operation = queued.occurrence_key.clone();
        let dispatched = host.dispatch_with_grant_provider(queued).await?;
        anyhow::ensure!(dispatched.state == LocalOutcomeState::Indeterminate && device.installs.load(Ordering::SeqCst) == 1, "withheld reply state differs");
        let independently_observed = device.native.query(&request.delivery).map_err(anyhow::Error::msg)?;
        anyhow::ensure!(matches!(independently_observed,Hos2DeliveryObservation::Applied {previous_revision,revision:actual,..}
            if previous_revision == revision && actual == resulting_revision), "native independent history differs");
        if mode == super::history::Case::CrashAfterApplied {
            anyhow::ensure!(unsafe { libc::kill(std::process::id() as i32,libc::SIGTERM) } == 0, "daemon stop signal");
            tokio::time::timeout(Duration::from_secs(15),daemon).await???;
            anyhow::ensure!(device.installs.load(Ordering::SeqCst) == 1
                && writer.status(&operation).await? == LocalOutcomeState::Indeterminate,
                "crash boundary changed original operation");
            return super::history::stop_at_crash_boundary(&writer, &request, independently_observed).await;
        }
        device.observe_enabled.store(true,Ordering::SeqCst);
        let terminal_deadline = tokio::time::Instant::now() + Duration::from_secs(10);
        loop {
            anyhow::ensure!(device.installs.load(Ordering::SeqCst) == 1, "native effect was entered again");
            let state = writer.status(&operation).await?;
            if state == LocalOutcomeState::Committed { break; }
            anyhow::ensure!(state == LocalOutcomeState::Indeterminate
                && tokio::time::Instant::now() < terminal_deadline, "original terminal observation did not settle");
            // The actual daemon also owns an observer. A concurrent observer
            // may return zero while it holds the original in-flight claim.
            // Reconcile only observes; this loop never regrants or dispatches.
            host.reconcile(1).await?;
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        let after = device.native.read_usage(3).map_err(anyhow::Error::msg)?;
        anyhow::ensure!(after.revision == resulting_revision && after.active_cap_ns == 25_000_000, "native resource did not change once");
        let retired = writer.retire_hos2_through(&target,&request.delivery).await?;
        anyhow::ensure!(retired.retired_through == 1 && matches!(device.native.query(&request.delivery).map_err(anyhow::Error::msg)?,Hos2DeliveryObservation::Retired), "native retirement readback");
        anyhow::ensure!(unsafe { libc::kill(std::process::id() as i32,libc::SIGTERM) } == 0, "daemon stop signal");
        tokio::time::timeout(Duration::from_secs(15),daemon).await???;
        // All original daemon workers have stopped before taking the final
        // independent-comparison cut. Shutdown cannot race this observation.
        let current_cut = writer.recovery_anchor().await?;
        let report = serde_json::json!({"qualification":"original_root_agentd_sqlite_native_hos2","production_ready":false,
            "original_daemon_initialized":true,"original_app_server_ready":true,"supervisor_promoted":false,"fleet_lifecycle":"starting","native_hos2":true,"uid":60002,
            "foreign_scope_grant_refused":true,"refused_scope_effect_entries":0,
            "initial_native_revision":revision,"final_native_revision":resulting_revision,
            "dispatch_count":device.installs.load(Ordering::SeqCst),"native_observation_count":device.observations.load(Ordering::SeqCst),
            "terminal":"committed","native_retired_through":retired.retired_through,"current_cut":current_cut,
            "loss_injection":"wrapper_withheld_actual_ioctl_reply","physical_power_loss":false,"cross_boot_qualified":false});
        drop(writer); drop(host); drop(client); drop(target); drop(device);
        attachment.close().await?;
        write_json(&Path::new(DATA).join("report.json"),&report,0o600)?;
        println!("HEPTA_NATIVE_OWNER_REPORT {report}");
        Ok(())
    })
}
