//! Volatile drain observations from the sole generation journal owner. No
//! projection can clear durable pending work or acknowledge an output chunk.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::Generation;
use tokio::sync::Notify;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use crate::neuron_generation_runtime::GenerationCommand;

#[derive(Clone, Copy, Eq, PartialEq)]
enum Phase {
    Unstarted,
    Running,
    Quarantined,
    Retired,
}

struct Observation {
    phase: Phase,
    host_draining: bool,
    retiring: bool,
    owner_clear: bool,
    retirement_ready: bool,
    admission_cancellation: Option<CancellationToken>,
}

pub(crate) struct NeuronGenerationProjection {
    pub(crate) generation: Generation,
    pub(crate) predecessor: Option<Generation>,
    pub(crate) command_sender: mpsc::WeakSender<GenerationCommand>,
    observation: Mutex<Observation>,
    notify: Notify,
}

impl NeuronGenerationProjection {
    pub(crate) fn new(
        generation: Generation,
        predecessor: Option<Generation>,
        command_sender: mpsc::WeakSender<GenerationCommand>,
    ) -> Self {
        Self {
            generation,
            predecessor,
            command_sender,
            observation: Mutex::new(Observation {
                phase: Phase::Unstarted,
                host_draining: false,
                retiring: false,
                owner_clear: false,
                retirement_ready: false,
                admission_cancellation: None,
            }),
            notify: Notify::new(),
        }
    }

    pub(crate) fn activate(
        &self,
        admission_cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let mut observed = self.observation.lock().map_err(poisoned_state)?;
        if observed.phase != Phase::Unstarted {
            return Err(AgentdError::Protocol(
                "generation service already started".into(),
            ));
        }
        observed.phase = Phase::Running;
        observed.admission_cancellation = Some(admission_cancellation);
        Ok(())
    }

    pub(crate) fn close_for_host_drain(&self) -> Result<(), AgentdError> {
        let mut observed = self.observation.lock().map_err(poisoned_state)?;
        if !observed.host_draining {
            observed.host_draining = true;
            // The owner must observe closure before an earlier idle sample can
            // acknowledge host drain. A queued fresh request is still fenced.
            observed.owner_clear = false;
            self.notify.notify_one();
        }
        Ok(())
    }

    pub(crate) fn close_for_retirement(&self) -> Result<(), AgentdError> {
        let mut observed = self.observation.lock().map_err(poisoned_state)?;
        observed.retiring = true;
        observed.owner_clear = false;
        Ok(())
    }

    pub(crate) fn admission_open(&self) -> Result<bool, AgentdError> {
        let observed = self.observation.lock().map_err(poisoned_state)?;
        Ok(observed.phase == Phase::Running
            && !observed.host_draining
            && !observed.retiring
            && self.command_sender.upgrade().is_some()
            && observed
                .admission_cancellation
                .as_ref()
                .is_some_and(|token| !token.is_cancelled()))
    }

    pub(crate) fn begin_command(&self) -> Result<(), AgentdError> {
        self.observation.lock().map_err(poisoned_state)?.owner_clear = false;
        Ok(())
    }

    pub(crate) fn observe_owner(&self, clear: bool) -> Result<(), AgentdError> {
        let mut observed = self.observation.lock().map_err(poisoned_state)?;
        if observed.phase != Phase::Running {
            return Err(AgentdError::Protocol(
                "generation service observation is unavailable".into(),
            ));
        }
        observed.owner_clear = clear;
        Ok(())
    }

    pub(crate) fn prepare_retirement(&self) -> Result<(), AgentdError> {
        let mut observed = self.observation.lock().map_err(poisoned_state)?;
        if observed.phase != Phase::Running || !observed.retiring || !observed.owner_clear {
            return Err(AgentdError::Protocol(
                "generation owner retirement remains unacknowledged".into(),
            ));
        }
        observed.retirement_ready = true;
        Ok(())
    }

    pub(crate) fn retire(&self) -> Result<(), AgentdError> {
        let mut observed = self.observation.lock().map_err(poisoned_state)?;
        if !observed.retirement_ready || observed.phase != Phase::Running {
            return Err(AgentdError::Protocol(
                "generation owner was not drained for retirement".into(),
            ));
        }
        observed.phase = Phase::Retired;
        Ok(())
    }

    pub(crate) fn quarantine(&self) {
        if let Ok(mut observed) = self.observation.lock() {
            if observed.phase != Phase::Retired {
                observed.phase = Phase::Quarantined;
                observed.owner_clear = false;
                observed.retirement_ready = false;
            }
        }
    }

    fn is_retired(&self) -> Result<bool, AgentdError> {
        Ok(self.observation.lock().map_err(poisoned_state)?.phase == Phase::Retired)
    }

    pub(crate) async fn changed(&self) {
        self.notify.notified().await;
    }

    fn drain_blockers(&self) -> Result<u32, AgentdError> {
        let observed = self.observation.lock().map_err(poisoned_state)?;
        Ok(u32::from(
            !matches!(observed.phase, Phase::Retired)
                && !(observed.phase == Phase::Running
                    && observed.host_draining
                    && observed.owner_clear
                    && self.command_sender.upgrade().is_some()),
        ))
    }
}

impl AgentdState {
    pub(crate) fn attach_neuron_generation(
        &self,
        projection: Arc<NeuronGenerationProjection>,
    ) -> Result<(), AgentdError> {
        let mut attached = self.neuron_generation.lock().map_err(poisoned_state)?;
        if let Some(previous) = attached.as_ref() {
            if Arc::ptr_eq(previous, &projection) {
                return Ok(());
            }
            if !previous.is_retired()?
                || projection.predecessor != Some(previous.generation)
                || projection.generation <= previous.generation
            {
                return Err(AgentdError::Protocol(
                    "generation service predecessor is not retired".into(),
                ));
            }
        } else if projection.predecessor.is_some() {
            return Err(AgentdError::Protocol(
                "generation service predecessor is missing".into(),
            ));
        }
        *attached = Some(projection);
        Ok(())
    }

    pub(crate) fn close_neuron_generation_admission(&self) -> Result<(), AgentdError> {
        if let Some(projection) = self
            .neuron_generation
            .lock()
            .map_err(poisoned_state)?
            .as_ref()
        {
            projection.close_for_host_drain()?;
        }
        Ok(())
    }

    pub(crate) fn neuron_generation_drain_blockers(&self) -> Result<u32, AgentdError> {
        let projection = self
            .neuron_generation
            .lock()
            .map_err(poisoned_state)?
            .clone();
        match projection {
            Some(projection) => {
                self.require_neuron_generation_recovery()?;
                projection.drain_blockers()
            }
            None => Ok(0),
        }
    }

    pub(crate) fn require_neuron_generation_recovery(&self) -> Result<(), AgentdError> {
        self.refresh_generation()?;
        if self.is_fenced()? {
            return Err(AgentdError::GenerationFenced(
                "generation service owner is fenced".into(),
            ));
        }
        Ok(())
    }

    pub(crate) fn neuron_generation_admission_ready(&self) -> Result<bool, AgentdError> {
        if !self.automation_admission_ready()? {
            return Ok(false);
        }
        match self
            .neuron_generation
            .lock()
            .map_err(poisoned_state)?
            .as_ref()
        {
            Some(projection) => projection.admission_open(),
            None => Ok(false),
        }
    }
}
