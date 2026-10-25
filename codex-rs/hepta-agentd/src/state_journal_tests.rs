//! Same-activation construction/control qualification, not daemon restart,
//! instance identity, provider dispatch, or persistent trust qualification.
use super::*;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::lane_b_runtime::JournalOpenMode;
use std::fs::File;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

type Constructor = fn(
    AgentdIdentity,
    FleetRegistry,
    usize,
    &Path,
    JournalOpenMode,
) -> Result<AgentdState, AgentdError>;

struct Fixture {
    construct: Constructor,
    registry: FleetRegistry,
    state: Option<AgentdState>,
    _writer: File,
    path: PathBuf,
    _temp: tempfile::TempDir,
}

fn construct(
    identity: AgentdIdentity,
    registry: FleetRegistry,
    capacity: usize,
    path: &Path,
    mode: JournalOpenMode,
) -> Result<AgentdState, AgentdError> {
    AgentdState::new_with_run_owner(identity, registry, capacity, |composition| {
        AgentRunCoordinator::open_journaled(composition, path, mode)
    })
}

impl Fixture {
    fn new() -> anyhow::Result<Self> {
        Self::using(construct)
    }

    fn using(constructor: Constructor) -> anyhow::Result<Self> {
        let mut writer = None;
        let mut path = None;
        let (temp, registry, state) =
            isolation_tests::fixture_with_constructor(|identity, registry, capacity| {
                // Retain the actual daemon lock before composing either
                // subordinate journal or prompt owner, as runtime.rs does.
                let lock = std::fs::OpenOptions::new()
                    .create(true)
                    .truncate(false)
                    .read(true)
                    .write(true)
                    .open(identity.layout.writer_lock())?;
                lock.try_lock().map_err(|error| {
                    AgentdError::Invalid(format!("qualification writer lock: {error}"))
                })?;
                let home = identity.home_root.join("lifecycle-qualification");
                std::fs::create_dir(&home)?;
                std::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o700))?;
                let file = home.join("runs.json");
                let state =
                    constructor(identity, registry, capacity, &file, JournalOpenMode::Create)?;
                writer = Some(lock);
                path = Some(file);
                Ok(state)
            })?;
        Ok(Self {
            construct: constructor,
            _temp: temp,
            registry,
            state: Some(state),
            _writer: writer.ok_or_else(|| anyhow::anyhow!("missing writer lock"))?,
            path: path.ok_or_else(|| anyhow::anyhow!("missing journal path"))?,
        })
    }

    fn state(&self) -> anyhow::Result<&AgentdState> {
        self.state
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("fixture state was consumed"))
    }

    fn recompose_same_activation(&mut self) -> anyhow::Result<()> {
        let old = self
            .state
            .take()
            .ok_or_else(|| anyhow::anyhow!("fixture state was consumed"))?;
        let identity = old.identity.clone();
        drop(old);
        let state = (self.construct)(
            identity,
            self.registry.clone(),
            16,
            &self.path,
            JournalOpenMode::Reopen,
        )?;
        state.refresh_generation()?;
        state.mark_app_server_ready()?;
        self.state = Some(state);
        Ok(())
    }
}

fn snapshot(state: &AgentdState) -> crate::AgentRunSnapshot {
    crate::AgentRunSnapshot {
        run_id: "run.journal.control".into(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 7,
        generation: 2,
        fence_digest: objective_run_fence(&state.identity, 2),
        deadline_ms: u64::MAX - 1,
    }
}

async fn call(state: &AgentdState, method: AgentdMethod) -> anyhow::Result<AgentdPayload> {
    Ok(state
        .response(1, state.identity.spawn_generation, method)
        .await?
        .payload)
}

async fn attach(state: &AgentdState) -> anyhow::Result<crate::AgentRunReceipt> {
    let snapshot = snapshot(state);
    let AgentdPayload::RunReceipt(started) = call(
        state,
        AgentdMethod::RunStart {
            snapshot: snapshot.clone(),
        },
    )
    .await?
    else {
        panic!("run receipt")
    };
    let AgentdPayload::RunReceipt(attached) = call(
        state,
        AgentdMethod::RunAttachContext {
            expected_revision: started.revision,
            attachment: crate::AgentContextAttachment {
                run_id: snapshot.run_id,
                request_digest: snapshot.request_digest,
                objective_digest: snapshot.objective_digest,
                body_digest: snapshot.body_digest,
                artifact_set_digest: snapshot.artifact_set_digest,
                authority_epoch: snapshot.authority_epoch,
                generation: snapshot.generation,
                fence_digest: snapshot.fence_digest,
                deadline_ms: snapshot.deadline_ms,
                context_digest: "5".repeat(64),
                compilation_receipt_digest: "6".repeat(64),
            },
        },
    )
    .await?
    else {
        panic!("context receipt")
    };
    Ok(attached)
}

async fn status(state: &AgentdState) -> anyhow::Result<Option<crate::AgentRunReceipt>> {
    let AgentdPayload::RunStatus { run } = call(
        state,
        AgentdMethod::RunStatus {
            run_id: "run.journal.control".into(),
        },
    )
    .await?
    else {
        panic!("run status")
    };
    Ok(run)
}

#[tokio::test]
async fn actual_control_preserves_context_cancel_and_release_across_recomposition()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let attached = attach(fixture.state()?).await?;
    fixture.recompose_same_activation()?;
    assert_eq!(status(fixture.state()?).await?, Some(attached.clone()));
    let AgentdPayload::RunCancellation(cancelled) = call(
        fixture.state()?,
        AgentdMethod::RunCancel {
            run_id: attached.run_id,
            expected_revision: attached.revision,
            reason: "stop".into(),
        },
    )
    .await?
    else {
        panic!("cancel receipt")
    };
    assert_eq!(cancelled.receipt.phase, crate::AgentRunPhase::Cancelled);
    fixture.recompose_same_activation()?;
    assert_eq!(
        status(fixture.state()?).await?,
        Some(cancelled.receipt.clone())
    );
    let AgentdPayload::RunReceipt(released) = call(
        fixture.state()?,
        AgentdMethod::RunReleaseClosed {
            run_id: cancelled.receipt.run_id,
            expected_revision: cancelled.receipt.revision,
        },
    )
    .await?
    else {
        panic!("release receipt")
    };
    assert_eq!(released.phase, crate::AgentRunPhase::Cancelled);
    fixture.recompose_same_activation()?;
    assert_eq!(status(fixture.state()?).await?, None);
    Ok(())
}

#[tokio::test]
async fn actual_control_recovers_possible_dispatch_only_for_reconciliation() -> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let attached = attach(fixture.state()?).await?;
    let AgentdPayload::RunReceipt(dispatched) = call(
        fixture.state()?,
        AgentdMethod::RunMarkDispatched {
            run_id: attached.run_id,
            expected_revision: attached.revision,
        },
    )
    .await?
    else {
        panic!("dispatch receipt")
    };
    fixture.recompose_same_activation()?;
    let uncertain = status(fixture.state()?).await?.unwrap();
    assert_eq!(uncertain.phase, crate::AgentRunPhase::Indeterminate);
    assert_eq!(uncertain.revision, dispatched.revision + 1);
    assert!(
        fixture
            .state()?
            .response(
                1,
                1,
                AgentdMethod::RunMarkDispatched {
                    run_id: uncertain.run_id.clone(),
                    expected_revision: uncertain.revision,
                }
            )
            .await
            .is_err()
    );
    let AgentdPayload::RunReceipt(terminal) = call(
        fixture.state()?,
        AgentdMethod::RunObserveTerminal {
            run_id: uncertain.run_id,
            expected_revision: uncertain.revision,
            phase: crate::AgentRunPhase::Succeeded,
            terminal_observed: true,
        },
    )
    .await?
    else {
        panic!("terminal receipt")
    };
    fixture.recompose_same_activation()?;
    assert_eq!(status(fixture.state()?).await?, Some(terminal));
    Ok(())
}

#[test]
fn changed_activation_refuses_reopen_and_failed_composition_releases_journal_lock()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let state = fixture.state.take().unwrap();
    let identity = state.identity.clone();
    drop(state);
    let mut wrong = identity.clone();
    wrong.spawn_generation += 1;
    assert!(
        construct(
            wrong,
            fixture.registry.clone(),
            16,
            &fixture.path,
            JournalOpenMode::Reopen
        )
        .is_err()
    );
    let state = construct(
        identity.clone(),
        fixture.registry.clone(),
        16,
        &fixture.path,
        JournalOpenMode::Reopen,
    )
    .unwrap();
    // The first successful owner retains the journal writer lock.
    assert!(
        construct(
            identity,
            fixture.registry.clone(),
            16,
            &fixture.path,
            JournalOpenMode::Reopen
        )
        .is_err()
    );
    drop(state);
    Ok(())
}

#[test]
fn real_state_fence_persists_admission_close_without_claiming_durable_trust() -> anyhow::Result<()>
{
    let mut fixture = Fixture::new()?;
    fixture.state()?.mark_fenced();
    assert!(!fixture.state()?.runs.lock().unwrap().admissions_open());
    fixture.recompose_same_activation()?;
    assert!(!fixture.state()?.runs.lock().unwrap().admissions_open());
    Ok(())
}

#[test]
fn later_constructor_failure_releases_the_already_opened_journal() -> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let state = fixture.state.take().unwrap();
    let identity = state.identity.clone();
    drop(state);
    let prompt = identity.home_root.join("prompt-registry");
    let saved = identity.home_root.join("prompt-registry-saved");
    std::fs::rename(&prompt, &saved).unwrap();
    std::fs::write(&prompt, b"not a directory").unwrap();
    let failure = match construct(
        identity.clone(),
        fixture.registry.clone(),
        16,
        &fixture.path,
        JournalOpenMode::Reopen,
    ) {
        Err(error) => error,
        Ok(_) => panic!("invalid prompt owner unexpectedly opened"),
    };
    assert!(matches!(failure, AgentdError::Protocol(message)
        if message.contains("prompt pipeline durable owners failed to open")));
    std::fs::remove_file(&prompt).unwrap();
    std::fs::rename(&saved, &prompt).unwrap();
    let state = construct(
        identity,
        fixture.registry.clone(),
        16,
        &fixture.path,
        JournalOpenMode::Reopen,
    )
    .expect("later initialization error released journal lock");
    drop(state);
    Ok(())
}

#[tokio::test]
async fn failed_real_state_close_denies_local_control_and_corrupt_reopen() -> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let request = snapshot(fixture.state()?);
    std::fs::write(&fixture.path, b"corrupt journal").unwrap();
    fixture.state()?.mark_fenced();
    assert!(fixture.state()?.is_fenced().unwrap());
    assert!(!fixture.state()?.runs.lock().unwrap().admissions_open());
    assert!(
        fixture
            .state()?
            .response(1, 1, AgentdMethod::RunStart { snapshot: request })
            .await
            .is_err()
    );
    let old = fixture.state.take().unwrap();
    let identity = old.identity.clone();
    drop(old);
    assert!(
        construct(
            identity,
            fixture.registry.clone(),
            16,
            &fixture.path,
            JournalOpenMode::Reopen
        )
        .is_err()
    );
    Ok(())
}

#[path = "state_instance_tests.rs"]
mod instance_tests;
