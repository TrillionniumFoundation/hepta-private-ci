//! Native turn retention inside the existing Agent-local TaskFlow database.
//!
//! The adapter neither creates a store nor claims a lease. Its caller supplies
//! the existing owner fence and a context compiler backed by the existing V2
//! context owner. Model/provider and tool final-use checks remain at their
//! original dispatch boundaries; observing this cursor grants no authority.

use std::future::Future;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCursor;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowRun;
use codex_hepta_automation::TaskFlowRunState;
use serde::Deserialize;
use serde::Serialize;

use crate::*;

#[path = "taskflow_owner_snapshot.rs"]
mod snapshot;
use snapshot::RetainedBounds;
use snapshot::Snapshot;

/// Full loop observation, including provider continuation receipts and usage.
/// A prepared successor request is retained before it can be dispatched.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RetainedObservation {
    pub transition: Transition,
    pub prepared_next: Option<ModelRequest>,
}

/// Existing context-owner integration. Implementations are bounded, read-only
/// and idempotent for an identical binding/initial request/history. They may
/// resolve existing provider continuation receipts and invoke the existing V2
/// compiler/preparation API; they must not dispatch a model/tool, mint grants,
/// change a generation, or independently create conversation storage.
pub trait TaskFlowContextPreparer: Send + Sync {
    fn prepare_next(
        &mut self,
        binding: &TurnBinding,
        initial: &ModelRequest,
        history: &[RetainedObservation],
    ) -> impl Future<Output = Result<ModelRequest>> + Send;
}

/// A read-only view. Frame and observation history come from one cursor commit;
/// the separately verified TaskFlow projection can be newer than that commit.
pub struct ObservedTaskFlowTurn {
    pub frame: Frame,
    pub history: Vec<RetainedObservation>,
    pub cursor: TaskFlowCursor,
    pub taskflow_run: TaskFlowRun,
}

pub struct TaskFlowTurnOwner<'a, P> {
    store: &'a AutomationStore,
    fence: TaskFlowFence,
    binding: TurnBinding,
    initial: ModelRequest,
    limits: Limits,
    preparer: P,
}

impl<'a, P: TaskFlowContextPreparer> TaskFlowTurnOwner<'a, P> {
    /// Attach to the original run/turn, or persist its initial frozen request.
    /// Reopening must present the same binding, request and budget limits.
    /// No TaskFlow run, lease, model dispatch or effect is created here.
    pub async fn open(
        store: &'a AutomationStore,
        fence: TaskFlowFence,
        binding: TurnBinding,
        initial: ModelRequest,
        limits: Limits,
        preparer: P,
    ) -> Result<Self> {
        if binding.admission_digest.is_zero()
            || binding.deadline_unix_ms == 0
            || binding.generation.get() != fence.generation
        {
            return Err(Error::Contract("TaskFlow turn admission or generation"));
        }
        let owner = Self {
            store,
            fence,
            binding,
            initial,
            limits,
            preparer,
        };
        if let Some(cursor) = owner.read_cursor().await? {
            owner.decode(&cursor)?;
        } else {
            let now = now_ms()?;
            if now >= owner.binding.deadline_unix_ms {
                return Err(Error::Limit("expired initial TaskFlow turn"));
            }
            let saved = Snapshot::initial(&owner.binding, &owner.initial, &owner.limits)?;
            let encoded = saved.encode(false)?;
            let cursor = owner
                .store
                .commit_taskflow_cursor(
                    owner.binding.run_id.as_str(),
                    owner.binding.turn_id.as_str(),
                    &owner.fence,
                    None,
                    &encoded,
                    now,
                )
                .await
                .map_err(store_error)?;
            owner.decode(&cursor)?;
        }
        Ok(owner)
    }

    /// Observe retained data even when a terminal TaskFlow forbids execution.
    pub async fn observe(&self) -> Result<ObservedTaskFlowTurn> {
        let cursor = self
            .read_cursor()
            .await?
            .ok_or(Error::Contract("TaskFlow turn cursor disappeared"))?;
        let (saved, frame) = self.decode(&cursor)?;
        let run = self
            .store
            .taskflow_run(self.binding.run_id.as_str())
            .await
            .map_err(store_error)?
            .ok_or(Error::Contract("TaskFlow run disappeared"))?;
        self.check_current_owner(&run)?;
        if cursor.run_revision > run.revision {
            return Err(Error::Contract(
                "TaskFlow cursor precedes observed run projection",
            ));
        }
        Ok(ObservedTaskFlowTurn {
            frame,
            history: saved.history,
            cursor,
            taskflow_run: run,
        })
    }

    async fn read_cursor(&self) -> Result<Option<TaskFlowCursor>> {
        self.store
            .taskflow_cursor(
                self.binding.run_id.as_str(),
                self.binding.turn_id.as_str(),
                &self.fence,
            )
            .await
            .map_err(store_error)
    }

    fn decode(&self, cursor: &TaskFlowCursor) -> Result<(Snapshot, Frame)> {
        let saved: Snapshot = serde_json::from_str(&cursor.payload)
            .map_err(|_| Error::Contract("TaskFlow native snapshot encoding"))?;
        if saved.initial.binding != self.binding
            || saved.initial.phase != Phase::Model(self.initial.clone())
            || saved.bounds != RetainedBounds::from(&self.limits)
            || cursor.run_id != self.binding.run_id.as_str()
            || cursor.turn_key != self.binding.turn_id.as_str()
        {
            return Err(Error::Contract("TaskFlow frozen initial request or scope"));
        }
        let frame = saved.replay(&self.limits)?;
        if cursor.revision
            != frame
                .revision
                .checked_add(1)
                .ok_or(Error::Contract("TaskFlow native revision overflow"))?
        {
            return Err(Error::Contract("TaskFlow native cursor revision"));
        }
        Ok((saved, frame))
    }

    fn check_current_owner(&self, run: &TaskFlowRun) -> Result<()> {
        if run.owner_id.is_some()
            && (run.owner_id.as_deref() != Some(self.fence.owner_id.as_str())
                || run.owner_epoch != Some(self.fence.owner_epoch)
                || run.generation != Some(self.fence.generation)
                || run.fencing_token.as_deref() != Some(self.fence.fencing_token.as_str()))
        {
            return Err(Error::Contract(
                "TaskFlow owner changed after cursor observation",
            ));
        }
        Ok(())
    }

    fn require_cancelable(&self, observed: &ObservedTaskFlowTurn) -> Result<()> {
        let native_terminal = matches!(observed.frame.phase, Phase::Complete(_) | Phase::Cancelled);
        let matches_terminal = matches!(
            (&observed.taskflow_run.state, &observed.frame.phase),
            (TaskFlowRunState::Succeeded, Phase::Complete(_))
                | (TaskFlowRunState::Cancelled, Phase::Cancelled)
        );
        if terminal(observed.taskflow_run.state) {
            if matches_terminal {
                return Ok(());
            }
            return Err(Error::Owner(
                "terminal TaskFlow permits observation only".into(),
            ));
        }
        if !native_terminal
            && (observed.taskflow_run.owner_id.is_none()
                || observed
                    .taskflow_run
                    .lease_expires_at_ms
                    .is_none_or(|deadline| deadline <= now_ms().unwrap_or(u64::MAX)))
        {
            return Err(Error::Owner(
                "inactive TaskFlow lease permits observation only".into(),
            ));
        }
        Ok(())
    }

    fn require_driveable(&self, observed: &ObservedTaskFlowTurn) -> Result<()> {
        self.require_cancelable(observed)?;
        if matches!(observed.frame.phase, Phase::Model(_) | Phase::Tools { .. })
            && (observed.taskflow_run.state != TaskFlowRunState::Running
                || observed.taskflow_run.cancel_requested)
        {
            return Err(Error::Owner(
                "inactive TaskFlow state permits observation only".into(),
            ));
        }
        Ok(())
    }

    fn require_transition(
        &self,
        observed: &ObservedTaskFlowTurn,
        transition: &Transition,
    ) -> Result<()> {
        if matches!(
            transition,
            Transition::CancelRequested | Transition::Cancelled
        ) {
            self.require_cancelable(observed)
        } else {
            self.require_driveable(observed)
        }
    }
}

impl<P: TaskFlowContextPreparer> TurnOwner for TaskFlowTurnOwner<'_, P> {
    async fn load(&mut self, binding: &TurnBinding) -> Result<Frame> {
        if binding != &self.binding {
            return Err(Error::Contract("TaskFlow turn binding"));
        }
        let observed = self.observe().await?;
        // An existing nonterminal TaskFlow cancellation intent is translated
        // into a durable native intent. The runner then asks only the original
        // inference/effect owners to stop. Terminal or expired owners cannot
        // use this path, and no acknowledgement is invented on write failure.
        if observed.taskflow_run.cancel_requested
            && matches!(observed.frame.phase, Phase::Model(_) | Phase::Tools { .. })
        {
            self.require_cancelable(&observed)?;
            return self
                .commit(&observed.frame, Transition::CancelRequested)
                .await;
        }
        self.require_driveable(&observed)?;
        Ok(observed.frame)
    }

    async fn load_for_cancel(&mut self, binding: &TurnBinding) -> Result<Frame> {
        if binding != &self.binding {
            return Err(Error::Contract("TaskFlow cancellation binding"));
        }
        let observed = self.observe().await?;
        self.require_cancelable(&observed)?;
        Ok(observed.frame)
    }

    async fn commit(&mut self, previous: &Frame, transition: Transition) -> Result<Frame> {
        if previous.binding != self.binding {
            return Err(Error::Contract("TaskFlow successor binding"));
        }
        let observed = self.observe().await?;
        let (mut saved, current) = self.decode(&observed.cursor)?;
        // A lost commit acknowledgement must not invoke context preparation
        // again or replace the already frozen successor request.
        if current.revision
            == previous
                .revision
                .checked_add(1)
                .ok_or(Error::Contract("TaskFlow successor overflow"))?
            && saved
                .history
                .last()
                .is_some_and(|row| row.transition == transition)
        {
            saved
                .history
                .pop()
                .ok_or(Error::Contract("missing successor history"))?;
            let retained_previous = saved.replay(&self.limits)?;
            if retained_previous == *previous {
                // This is an observation of an existing successor, never a write.
                self.require_transition(&observed, &transition)?;
                return Ok(current);
            }
            return Err(Error::Contract("TaskFlow replay predecessor"));
        }
        if current != *previous {
            return Err(Error::Owner("TaskFlow cursor CAS conflict".into()));
        }
        self.require_transition(&observed, &transition)?;
        let needs_context = snapshot::needs_next_request(previous, &transition)?;
        let mut row = RetainedObservation {
            transition,
            prepared_next: None,
        };
        if needs_context {
            // Validate the exact original call/key before invoking even a
            // read-only compiler; no model/tool dispatch occurs before CAS.
            snapshot::check_tool_completion(previous, &row.transition, &self.limits)?;
            let mut history = saved.history.clone();
            history.push(row.clone());
            row.prepared_next = Some(
                self.preparer
                    .prepare_next(&self.binding, &self.initial, &history)
                    .await?,
            );
        }
        let next = snapshot::advance(previous, &row, &self.limits)?;
        let cancellation = matches!(
            row.transition,
            Transition::CancelRequested | Transition::Cancelled
        );
        saved.history.push(row);
        if saved.replay(&self.limits)? != next {
            return Err(Error::Contract("TaskFlow successor replay mismatch"));
        }
        let encoded = saved.encode(cancellation)?;
        let receipt = self
            .store
            .commit_taskflow_cursor(
                self.binding.run_id.as_str(),
                self.binding.turn_id.as_str(),
                &self.fence,
                Some(&observed.cursor),
                &encoded,
                now_ms()?,
            )
            .await
            .map_err(store_error)?;
        let (_, retained) = self.decode(&receipt)?;
        if retained != next {
            return Err(Error::Contract("TaskFlow retained successor mismatch"));
        }
        Ok(retained)
    }
}

fn terminal(state: TaskFlowRunState) -> bool {
    matches!(
        state,
        TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
    )
}

fn now_ms() -> Result<u64> {
    let value = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::Contract("TaskFlow native clock"))?
        .as_millis();
    u64::try_from(value).map_err(|_| Error::Contract("TaskFlow native clock overflow"))
}

fn store_error(error: codex_hepta_automation::TaskFlowError) -> Error {
    Error::Owner(format!("TaskFlow native cursor: {error}"))
}
