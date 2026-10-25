//! Actual original Root/SQLite assembly with an explicit no-application target.
//! This is qualification, not GUI/native execution or production provisioning.
use codex_hepta_agentd::*;
use codex_hepta_memory::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

struct FixtureTarget {
    destination: String,
    receipt: String,
    effects: AtomicUsize,
    retired: AtomicUsize,
}
impl ProductionOutboxTarget for FixtureTarget {
    fn dispatch<'a>(&'a self, _: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        self.effects.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            ProductionTargetOutcome::Indeterminate {
                reason: "explicit fixture withheld reply".into(),
            }
        })
    }
}
impl FinalUseProductionOutboxTarget for FixtureTarget {
    fn destination_id(&self) -> &str {
        &self.destination
    }
    fn observe_terminal<'a>(
        &'a self,
        _: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            ProductionTerminalObservation::Applied {
                receipt: self.receipt.clone(),
            }
        })
    }
    fn retire_notes_receipt(&self, _: &NotesRetirementPermit) -> Result<(), String> {
        self.retired.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

pub(super) fn qualify(
    observation: UnixStream,
    issuer: UnixStream,
    checkpoint: UnixStream,
    device: UnixStream,
    notes: UnixStream,
    bundle: HostAuthorityPublicBootstrapV1,
) -> Result<(), Box<dyn std::error::Error>> {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    runtime.block_on(async move {
        let registered = &bundle.registered_identity;
        let fleet = codex_hepta_paths::HeptaFleetRoot::parse(registered.fleet_root.clone())?;
        let layout = fleet.layout().agent(&registered.agent_id);
        let mut config = AgentdConfig::load(
            registered.fleet_root.clone(), registered.agent_id.clone(), registered.spawn_generation,
            layout.home_root().to_owned(), layout.run_root().to_owned(), layout.home_root().to_owned(),
            registered.workspace.clone(),
        )?;
        let identity = config.identity().clone();
        for slot in [&bundle.consumers.device, &bundle.consumers.notes] {
            std::fs::DirBuilder::new().mode(0o700).create(&slot.local_state_dir)?;
        }
        let fd: i32 = std::env::var("HEPTA_SERVICE_ROOT_PIDFD")?.parse()?;
        assert_eq!(fd, 198);
        // SAFETY: the root qualification parent transferred one owned pre-held
        // root pidfd at this fixed descriptor; this is not PID path discovery.
        let root_pidfd = unsafe { OwnedFd::from_raw_fd(fd) };
        let golden: serde_json::Value = serde_json::from_str(include_str!("../../tests/fixtures/notes-recovery-v1.json"))?;
        let payload = golden["request_utf8"].as_str().ok_or("missing payload")?.to_owned();
        let request: serde_json::Value = serde_json::from_str(&payload)?;
        let target_identity: NotesTargetIdentity = serde_json::from_value(request["target"].clone())?;
        let target = Arc::new(FixtureTarget {
            destination: target_identity.destination_id(),
            receipt: golden["application_response_utf8"].as_str().ok_or("missing receipt")?.into(),
            effects: AtomicUsize::new(0), retired: AtomicUsize::new(0),
        });
        let attachment = attach_root_production_host(&mut config, AgentdRootProductionInputs {
            bootstrap: bundle,
            lanes: AgentdRootAuthorityLanes { observation, issuer, checkpoint, device_frontier: device, notes_frontier: notes, root_pidfd },
            target: AgentdRootPrimaryTarget::Notes(target.clone()), timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(20), reconcile_interval: Duration::from_millis(100),
        }).await?;
        attachment.verify_live()?;
        // Use the same original attach_target operation as Agentd runtime.
        // This clones only a wrapper over the existing writer, never a ledger.
        let host = attachment.writer_host().as_ref().clone().attach_target(
            attachment.notes_final_use(), target.clone(), attachment.issuer(),
        )?;
        let writer = host.writer();
        let intent = notes_operation_intent(&target_identity, &payload, StableId::new(identity.agent_id.as_str())?, Generation::new(1)?)?;
        let queued = writer.prepare_operation(intent, NOTES_REPLACE_TOPIC_V1, payload).await?;
        let operation = queued.occurrence_key.clone();
        assert_eq!(host.dispatch_with_grant_provider(queued).await?.state, LocalOutcomeState::Indeterminate);
        assert_eq!(target.effects.load(Ordering::SeqCst), 1);
        assert_eq!(host.reconcile(1).await?, 1);
        assert_eq!(writer.status(&operation).await?, LocalOutcomeState::Committed);
        assert_eq!(target.retired.load(Ordering::SeqCst), 1);
        let current = writer.recovery_anchor().await?;
        attachment.verify_live()?;
        let report = serde_json::json!({
            "qualification":"original_root_five_lane_sqlite_owner", "production_ready":false,
            "real_application":false, "native_hos2":false, "uid":60001,
            "dispatch_count":target.effects.load(Ordering::SeqCst), "receipt_retired":target.retired.load(Ordering::SeqCst),
            "terminal":"committed", "original_current_cut":current,
        });
        drop(writer); drop(host); drop(config);
        attachment.close().await?;
        let path = std::path::PathBuf::from(std::env::var_os("HEPTA_SERVICE_OWNER_REPORT").ok_or("missing report path")?);
        let mut file = std::fs::OpenOptions::new().create_new(true).write(true).mode(0o600).open(&path)?;
        file.write_all(&serde_json::to_vec(&report)?)?; file.sync_all()?;
        std::fs::File::open(path.parent().ok_or("missing report parent")?)?.sync_all()?;
        Ok(())
    })
}
