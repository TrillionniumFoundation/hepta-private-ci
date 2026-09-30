use anyhow::Result;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::AdoptSpec;
use crate::Adoption;
use crate::ManagedProcess;
use crate::ProcessDriverError;
use crate::ProcessExit;
use crate::ProcessIdentity;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::SpawnSpec;
use crate::driver::SpawnedProcess;

struct Driver;

struct Process {
    stopped: bool,
}

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        Ok(SpawnedProcess {
            identity: ProcessIdentity::new(
                100 + spec.generation,
                format!("authority-fixture-{}", spec.generation),
            )
            .map_err(|error| ProcessDriverError::new(error.to_string()))?,
            process: Process { stopped: false },
        })
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Ok(Adoption::Missing)
    }
}

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        Ok(ProcessObservation {
            state: if self.stopped {
                ProcessState::Exited(ProcessExit {
                    success: true,
                    code: Some(0),
                })
            } else {
                ProcessState::Running {
                    healthy: true,
                    drained: true,
                }
            },
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        Ok(())
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.stopped = true;
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.stopped = true;
        Ok(())
    }
}

#[tokio::test]
async fn production_stop_then_start_cannot_bypass_signed_release_transition() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = HeptaFleetRoot::parse(temp.path().canonicalize()?.join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = temp.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    let source = temp.path().join("source");
    std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
    let selected = ReleaseId::parse("selected-v1")?;
    let alternative = ReleaseId::parse("allowed-v2")?;
    for release_id in [&selected, &alternative] {
        registry.install_release(release_id.clone(), &source, Vec::new())?;
        registry.allow_release(&agent_id, release_id)?;
    }
    let (supervisor, report) = Supervisor::recover(
        registry.clone(),
        Driver,
        SupervisorConfig::local_default(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty());
    let instance = SingleInstanceLock::acquire(registry.layout().supervisor_lock())?;
    // Public deterministic fixture key, never a provisioned trust anchor.
    let verifier = H7H89ProductionGrantVerifier::from_bytes(
        "authority-fixture",
        1,
        SigningKey::from_bytes(&[124; 32])
            .verifying_key()
            .to_bytes(),
    )?;
    let state = Arc::new(DaemonState {
        registry,
        supervisor: Mutex::new(supervisor),
        supervisor_epoch: SupervisorEpoch::new(),
        production_grant_verifier: Some(verifier),
        observed_faults: AtomicU64::new(0),
        execution: execution::Execution::new(CancellationToken::new()),
        _instance: instance,
    });
    let initial = agent_status(&state, &agent_id).await?;
    assert_eq!(initial.current_release, None);
    let boot = handle_request(
        Arc::clone(&state),
        SupervisordMethod::Start {
            fence: initial.control_fence,
            release_id: selected.clone(),
        },
    )
    .await;
    assert!(matches!(boot, SupervisordPayload::MutationAccepted { .. }));
    assert!(
        state
            .supervisor
            .lock()
            .await
            .tick(Instant::now())
            .faults
            .is_empty()
    );
    let running = agent_status(&state, &agent_id).await?;
    assert_eq!(running.lifecycle, AgentLifecycle::Running);
    let stopped = handle_request(
        Arc::clone(&state),
        SupervisordMethod::Stop {
            fence: running.control_fence,
        },
    )
    .await;
    assert!(matches!(
        stopped,
        SupervisordPayload::MutationAccepted { .. }
    ));
    assert!(
        state
            .supervisor
            .lock()
            .await
            .tick(Instant::now())
            .faults
            .is_empty()
    );
    let inactive = agent_status(&state, &agent_id).await?;
    assert_eq!(inactive.lifecycle, AgentLifecycle::Stopped);
    assert_eq!(inactive.current_release, Some(selected.clone()));
    let rejected = handle_request(
        Arc::clone(&state),
        SupervisordMethod::Start {
            fence: inactive.control_fence.clone(),
            release_id: alternative,
        },
    )
    .await;
    assert!(matches!(
        rejected,
        SupervisordPayload::Error { ref code, .. } if code == "signed_release_authority_required"
    ));
    assert_eq!(agent_status(&state, &agent_id).await?, inactive);
    let restarted = handle_request(
        Arc::clone(&state),
        SupervisordMethod::Start {
            fence: inactive.control_fence,
            release_id: selected.clone(),
        },
    )
    .await;
    let SupervisordPayload::MutationAccepted { agent, .. } = restarted else {
        panic!("selected release was not restartable: {restarted:?}");
    };
    let stopped = handle_request(
        Arc::clone(&state),
        SupervisordMethod::Stop {
            fence: agent.control_fence,
        },
    )
    .await;
    assert!(matches!(
        stopped,
        SupervisordPayload::MutationAccepted { .. }
    ));
    assert!(
        state
            .supervisor
            .lock()
            .await
            .tick(Instant::now())
            .faults
            .is_empty()
    );
    state.registry.revoke_release(&agent_id, &selected)?;
    let (recovered, report) = Supervisor::recover(
        state.registry.clone(),
        Driver,
        SupervisorConfig::local_default(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty());
    *state.supervisor.lock().await = recovered;
    let revoked = agent_status(&state, &agent_id).await?;
    assert_eq!(revoked.current_release, None);
    let rejected = handle_request(
        state,
        SupervisordMethod::Start {
            fence: revoked.control_fence,
            release_id: ReleaseId::parse("allowed-v2")?,
        },
    )
    .await;
    assert!(matches!(
        rejected,
        SupervisordPayload::Error { ref code, .. } if code == "signed_release_authority_required"
    ));
    Ok(())
}
