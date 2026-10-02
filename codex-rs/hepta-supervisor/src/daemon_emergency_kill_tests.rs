//! Real constructor, Fleet/intent/lease files and daemon mutation admission.
//! Explicit shared process doubles record exact-owner delivery and real exit;
//! these cases do not claim native OS or production authority qualification.

use super::*;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use std::sync::Mutex as StdMutex;

#[derive(Clone, Copy)]
enum Role {
    Main,
    Matrix,
}

#[derive(Default)]
struct Lifetime {
    identity: Option<ProcessIdentity>,
    exited: bool,
    fail_next_kill: bool,
    signals: [usize; 3],
    spawns: usize,
}

#[derive(Default)]
struct World {
    main: Lifetime,
    matrix: Lifetime,
}

impl World {
    fn lifetime(&mut self, role: Role) -> &mut Lifetime {
        match role {
            Role::Main => &mut self.main,
            Role::Matrix => &mut self.matrix,
        }
    }
}

#[derive(Clone)]
struct SharedDriver(Arc<StdMutex<World>>);
struct SharedProcess {
    world: Arc<StdMutex<World>>,
    role: Role,
}

impl SharedDriver {
    fn spawn_role(
        &self,
        role: Role,
        generation: u64,
    ) -> Result<SpawnedProcess<SharedProcess>, ProcessDriverError> {
        let offset = match role {
            Role::Main => 100,
            Role::Matrix => 200,
        };
        let identity = ProcessIdentity::new(
            offset + generation,
            format!("kill-fixture-{offset}-{generation}"),
        )
        .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        let mut world = self
            .0
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?;
        let lifetime = world.lifetime(role);
        lifetime.identity = Some(identity.clone());
        lifetime.spawns += 1;
        Ok(SpawnedProcess {
            identity,
            process: SharedProcess {
                world: Arc::clone(&self.0),
                role,
            },
        })
    }

    fn adopt_role(
        &self,
        role: Role,
        identity: &ProcessIdentity,
    ) -> Result<Adoption<SharedProcess>, ProcessDriverError> {
        let mut world = self
            .0
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?;
        let lifetime = world.lifetime(role);
        if lifetime.exited || lifetime.identity.as_ref() != Some(identity) {
            return Ok(Adoption::Missing);
        }
        Ok(Adoption::Adopted(SharedProcess {
            world: Arc::clone(&self.0),
            role,
        }))
    }
}

impl ProcessDriver for SharedDriver {
    type Process = SharedProcess;
    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<SharedProcess>, ProcessDriverError> {
        self.spawn_role(Role::Main, spec.generation)
    }
    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<SharedProcess>, ProcessDriverError> {
        self.adopt_role(Role::Main, &spec.identity)
    }
    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<SharedProcess>, ProcessDriverError> {
        self.spawn_role(Role::Matrix, spec.agent_generation)
    }
    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<SharedProcess>, ProcessDriverError> {
        self.adopt_role(Role::Matrix, &spec.identity)
    }
}

impl ManagedProcess for SharedProcess {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let mut world = self
            .world
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?;
        let lifetime = world.lifetime(self.role);
        Ok(ProcessObservation {
            state: if lifetime.exited {
                ProcessState::Exited(ProcessExit {
                    success: true,
                    code: Some(0),
                })
            } else {
                ProcessState::Running {
                    healthy: true,
                    drained: false,
                }
            },
            logs: Vec::new(),
        })
    }
    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.world
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?
            .lifetime(self.role)
            .signals[0] += 1;
        Ok(())
    }
    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.world
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?
            .lifetime(self.role)
            .signals[1] += 1;
        Ok(())
    }
    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut world = self
            .world
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?;
        let lifetime = world.lifetime(self.role);
        lifetime.signals[2] += 1;
        if std::mem::take(&mut lifetime.fail_next_kill) {
            return Err(ProcessDriverError::new(
                "exact fixture kill failed after delivery",
            ));
        }
        Ok(())
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    world: Arc<StdMutex<World>>,
    supervisor: Supervisor<SharedDriver>,
    now: Instant,
}

impl Fixture {
    fn new() -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().canonicalize()?.join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let program = temp.path().join("program");
        std::fs::write(&program, b"#!/bin/sh\nexit 0\n")?;
        let release_id = ReleaseId::parse("emergency-owned-pair")?;
        registry.install_release_bundle(
            release_id.clone(),
            &program,
            Vec::new(),
            Some(&program),
            Vec::new(),
        )?;
        registry.allow_release(&agent, &release_id)?;
        let record = registry.load_agent(&agent)?;
        let binding = serde_json::json!({
            "schema_version": 1, "agent_id": agent, "revision": 1,
            "homeserver": "https://matrix.example.test", "expected_mxid": "@hepta:example.test",
            "expected_device_id": "HEPTA1", "allowed_rooms": ["!room:example.test"],
            "allowed_senders": ["@operator:example.test"], "require_explicit_mention": true
        });
        std::fs::write(
            record.layout.matrix_public_binding(),
            serde_json::to_vec(&binding)?,
        )?;
        let world = Arc::new(StdMutex::new(World::default()));
        let now = Instant::now();
        let (mut supervisor, report) = Supervisor::recover(
            registry.clone(),
            SharedDriver(Arc::clone(&world)),
            SupervisorConfig::local_default(),
            now,
        )?;
        assert_eq!(report, TickReport::default());
        supervisor.start_release(
            &agent,
            crate::AgentRelease::try_from(registry.resolve_release(&agent, &release_id)?)?,
            now,
        )?;
        for _ in 0..3 {
            assert_eq!(supervisor.tick(now), TickReport::default());
        }
        assert_eq!(
            supervisor.record(&agent)?.lifecycle.lifecycle,
            AgentLifecycle::Running
        );
        assert!(
            supervisor
                .snapshot(&agent)
                .ok_or_else(|| anyhow::anyhow!("healthy pair missing"))?
                .matrix
                .healthy
        );
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            world,
            supervisor,
            now,
        })
    }

    fn quarantine(&self) -> Result<()> {
        let record = self.supervisor.record(&self.agent)?;
        let intent = crate::SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(b"persisted emergency-recovery fixture grant"),
            self.agent.to_string(),
            H7H89ProductionTransition::Upgrade,
            "emergency-owned-pair",
            "emergency-target",
            /*control_revision*/ 0,
            record.lifecycle.generation,
            /*authority_epoch*/ 1,
            crate::SignedIntentStatus::Queued,
        )?;
        crate::signed_intent::write_intent(record.layout.run_root(), &intent)?;
        Ok(())
    }

    fn into_recovered_state(
        self,
    ) -> Result<(
        tempfile::TempDir,
        Arc<DaemonState<SharedDriver>>,
        TickReport,
    )> {
        let Self {
            _temp,
            registry,
            agent: _,
            world,
            supervisor,
            now,
        } = self;
        drop(supervisor);
        let (supervisor, report) = Supervisor::recover(
            registry.clone(),
            SharedDriver(world),
            SupervisorConfig::local_default(),
            now,
        )?;
        let instance = SingleInstanceLock::acquire(registry.layout().supervisor_lock())?;
        Ok((
            _temp,
            Arc::new(DaemonState {
                registry,
                supervisor: Mutex::new(supervisor),
                supervisor_epoch: SupervisorEpoch::new(),
                production_grant_verifier: None,
                observed_faults: AtomicU64::new(/*v*/ 0),
                execution: execution::Execution::new(CancellationToken::new()),
                _instance: instance,
            }),
            report,
        ))
    }
}

async fn assert_rejected_without_delivery(
    state: &Arc<DaemonState<SharedDriver>>,
    agent: &AgentId,
    world: &Arc<StdMutex<World>>,
    method: SupervisordMethod,
    expected: &str,
) -> Result<()> {
    let before = agent_status(state, agent).await?;
    let signals = {
        let world = world
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?;
        (world.main.signals, world.matrix.signals)
    };
    let rejected = handle_request(Arc::clone(state), method).await;
    assert!(
        matches!(rejected, SupervisordPayload::Error { ref code, .. } if code == expected),
        "{rejected:?}"
    );
    assert_eq!(agent_status(state, agent).await?, before);
    let world = world
        .lock()
        .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?;
    assert_eq!((world.main.signals, world.matrix.signals), signals);
    Ok(())
}

#[tokio::test]
async fn emergency_kill_rpc_reaches_fenced_main_after_signed_constructor_generation_drift()
-> Result<()> {
    let f = Fixture::new()?;
    f.quarantine()?;
    f.world
        .lock()
        .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?
        .main
        .fail_next_kill = true;
    let agent = f.agent.clone();
    let world = Arc::clone(&f.world);
    let record = f.supervisor.record(&agent)?;
    let main_bytes = std::fs::read(
        record
            .layout
            .run_root()
            .join(crate::lease::PROCESS_LEASE_FILE),
    )?;
    let matrix_bytes = std::fs::read(record.layout.matrixd_process_lease())?;
    let (_temp, state, report) = f.into_recovered_state()?;
    assert_eq!(report, TickReport::default());
    let before = agent_status(&state, &agent).await?;
    assert_eq!(before.lifecycle, AgentLifecycle::Failed);
    assert!(before.active && before.matrix.active);
    assert_ne!(before.runtime_generation, Some(before.lifecycle_generation));
    assert_eq!(
        world
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?
            .main
            .signals,
        [0, 0, 1]
    );
    assert_rejected_without_delivery(
        &state,
        &agent,
        &world,
        SupervisordMethod::Stop {
            fence: before.control_fence.clone(),
        },
        "signed_intent_recovery_required",
    )
    .await?;
    let mut stale = before.control_fence.clone();
    stale.state_digest = ControlStateDigest::from_bytes([91; 32]);
    assert_rejected_without_delivery(
        &state,
        &agent,
        &world,
        SupervisordMethod::Kill { fence: stale },
        "stale_control_fence",
    )
    .await?;
    let revision = state
        .supervisor
        .lock()
        .await
        .snapshot(&agent)
        .expect("retained owner")
        .control_revision;
    let killed = handle_request(
        Arc::clone(&state),
        SupervisordMethod::Kill {
            fence: before.control_fence.clone(),
        },
    )
    .await;
    assert!(
        matches!(killed, SupervisordPayload::Error { ref code, .. } if code == "operation_indeterminate"),
        "{killed:?}"
    );
    let snapshot = state
        .supervisor
        .lock()
        .await
        .snapshot(&agent)
        .expect("retained owner");
    assert_eq!(snapshot.control_revision, revision + 1);
    assert!(snapshot.active && snapshot.matrix.active && snapshot.runtime_fenced);
    assert_eq!(
        world
            .lock()
            .map_err(|_| ProcessDriverError::new("shared process world lock poisoned"))?
            .main
            .signals,
        [0, 0, 2]
    );
    assert_eq!(
        std::fs::read(
            record
                .layout
                .run_root()
                .join(crate::lease::PROCESS_LEASE_FILE)
        )?,
        main_bytes
    );
    assert_eq!(
        std::fs::read(record.layout.matrixd_process_lease())?,
        matrix_bytes
    );
    assert_rejected_without_delivery(
        &state,
        &agent,
        &world,
        SupervisordMethod::Kill {
            fence: before.control_fence,
        },
        "stale_control_fence",
    )
    .await?;
    assert!(
        state
            .supervisor
            .lock()
            .await
            .production_recovery_required(&agent)?
    );
    Ok(())
}
