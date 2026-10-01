use std::collections::BTreeMap;

use serde_json::Value;

use super::*;
use crate::fleet_lifecycle::FleetLifecycleOperation;
use crate::fleet_lifecycle::PendingLifecycle;
use crate::fleet_lifecycle::PendingLifecycleStore;
use crate::fleet_lifecycle::request_id;

pub(super) struct FleetLifecycleView {
    fences: BTreeMap<String, Value>,
}

impl FleetLifecycleView {
    pub(super) fn prepare(value: &Value) -> Result<Option<Self>, ShellError> {
        let Some(fleet) = crate::fleet_observation::FleetObservation::parse(value)? else {
            return Ok(None);
        };
        let mut fences = BTreeMap::new();
        for agent in &fleet.agents {
            let original = value["agents"]
                .as_array()
                .and_then(|agents| {
                    agents
                        .iter()
                        .find(|value| value["agent_id"] == agent.agent_id)
                })
                .ok_or_else(|| ShellError::Backend("missing original Agent fence".into()))?;
            let fence = original["control_fence"].clone();
            if fence["agent_id"] != agent.agent_id
                || fence["supervisor_epoch"] != fleet.health.supervisor_epoch
                || fence["lifecycle"] != original["lifecycle"]
                || fence["lifecycle_generation"] != original["lifecycle_generation"]
                || fence["current_release"] != original["current_release"]
                || fence["state_digest"].as_str().is_none()
            {
                return Err(ShellError::Security(
                    "Agent lifecycle fence differs from the displayed observation".into(),
                ));
            }
            validate_digest(
                fence["state_digest"].as_str().unwrap_or_default(),
                "Agent fence digest",
            )?;
            fences.insert(agent.agent_id.clone(), fence);
        }
        Ok(Some(Self { fences }))
    }
}

impl NativeShellRuntime {
    pub fn enable_fleet_lifecycle(
        mut self,
        root: crate::private_state::PrivateStateRoot,
    ) -> Result<Self, ShellError> {
        self.fleet_pending = Some(PendingLifecycleStore::open(root)?);
        Ok(self)
    }

    pub fn fleet_lifecycle_available(&self) -> bool {
        self.backend.fleet_lifecycle_available() && self.fleet_pending.is_some()
    }

    pub fn fleet_lifecycle_pending(&self) -> bool {
        self.fleet_pending
            .as_ref()
            .and_then(PendingLifecycleStore::pending)
            .is_some()
    }

    pub fn execute_fleet_lifecycle(
        &mut self,
        agent_id: &str,
        operation: FleetLifecycleOperation,
        expected_view_revision: u64,
    ) -> Result<(), ShellError> {
        let session = self.require_session()?.clone();
        if !self.fleet_lifecycle_available() || operation == FleetLifecycleOperation::Receipt {
            return Err(ShellError::State(
                "Agent lifecycle control is not enabled".into(),
            ));
        }
        if self.fleet_lifecycle_pending() {
            return Err(ShellError::State(
                "inspect the original lifecycle receipt before a new action".into(),
            ));
        }
        let view = self
            .view
            .as_ref()
            .filter(|view| view.revision == expected_view_revision)
            .ok_or_else(|| {
                ShellError::State("refresh the current Agent status before acting".into())
            })?;
        if view.session_id != session.session_id || view.session_generation != session.generation {
            return Err(ShellError::State(
                "Agent lifecycle view belongs to a previous session".into(),
            ));
        }
        let fence = self
            .fleet_current
            .as_ref()
            .and_then(|view| view.fences.get(agent_id))
            .cloned()
            .ok_or_else(|| {
                ShellError::State("Agent is absent from the current Fleet observation".into())
            })?;
        let id = request_id()?;
        let pending = PendingLifecycle {
            schema_version: 1,
            endpoint_id: session.endpoint_id,
            owner_epoch: fence["supervisor_epoch"]
                .as_str()
                .unwrap_or_default()
                .into(),
            agent_id: agent_id.into(),
            request_id: id,
            operation,
            accepted_state_digest: fence["state_digest"].as_str().unwrap_or_default().into(),
        };
        let method = serde_json::json!({"type":operation,"fence":fence});
        let body = serde_json::json!({"schema_version":1,"request_id":id,"method":method});
        self.fleet_pending
            .as_mut()
            .ok_or_else(|| ShellError::State("lifecycle reference store unavailable".into()))?
            .reserve(pending.clone())?;
        self.view = None;
        self.fleet_current = None;
        let outcome = self.backend.fleet_lifecycle(operation, &body)?;
        if outcome.value["type"] == "mutation_accepted"
            && outcome.value["operation"] == serde_json::to_value(operation)?
            && outcome.value["accepted_state_digest"] == pending.accepted_state_digest
            && outcome.value["agent"]["agent_id"] == pending.agent_id
            && outcome.value["production_receipt"].is_null()
        {
            self.fleet_pending
                .as_mut()
                .expect("reserved lifecycle store")
                .clear_terminal()?;
            return Ok(());
        }
        if outcome.value["type"] == "error"
            && matches!(
                outcome.value["code"].as_str(),
                Some(
                    "stale_control_fence"
                        | "invalid_frame"
                        | "unsupported_schema"
                        | "unknown_agent"
                        | "not_admitted_busy"
                        | "not_admitted_stopping"
                        | "signed_release_authority_required"
                        | "recovery_observation_required"
                        | "signed_intent_recovery_required"
                )
            )
        {
            self.fleet_pending
                .as_mut()
                .expect("reserved lifecycle store")
                .clear_terminal()?;
            return Err(ShellError::State(
                outcome.value["message"]
                    .as_str()
                    .unwrap_or("Agent action was rejected; refresh current status")
                    .into(),
            ));
        }
        Err(ShellError::State(
            "Agent action outcome is unconfirmed; inspect its original receipt".into(),
        ))
    }

    pub fn inspect_fleet_lifecycle_receipt(&mut self) -> Result<bool, ShellError> {
        let session = self.require_session()?.clone();
        let pending = self
            .fleet_pending
            .as_ref()
            .and_then(PendingLifecycleStore::pending)
            .cloned()
            .ok_or_else(|| ShellError::State("there is no pending Agent action".into()))?;
        if pending.endpoint_id != session.endpoint_id {
            return Err(ShellError::Security(
                "pending Agent action belongs to another endpoint".into(),
            ));
        }
        let outcome = self.backend.fleet_lifecycle(
            FleetLifecycleOperation::Receipt,
            &pending.receipt_request(request_id()?),
        )?;
        let terminal = pending.receipt_terminal(&outcome.value)?;
        if terminal {
            self.fleet_pending
                .as_mut()
                .expect("pending lifecycle store")
                .clear_terminal()?;
        }
        self.view = None;
        self.fleet_current = None;
        Ok(terminal)
    }
}
