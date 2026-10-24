//! Read the original unresolved operation after an actual native boot change.
//! No admission, re-dispatch, terminal publication or history retirement occurs.
use super::*;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_memory::LocalOutcomeState;

fn operation_observation(value: &codex_hepta_operations::OperationIntentV1) -> serde_json::Value {
    // The original portable model deliberately has no serde contract. Copy
    // its public semantic fields without replacing or re-compiling the intent.
    serde_json::json!({"operation_id":value.operation_id().as_str(),
        "subject_id":value.subject_id().as_str(),"destination_id":value.destination_id().as_str(),
        "payload_digest":value.payload_digest().as_array(),"scope_digest":value.scope_digest().as_array(),
        "policy_generation":value.policy_generation().get(),
        "expected_predecessor":value.expected_predecessor().map(|digest| *digest.as_array())})
}

impl<T: codex_hepta_memory::CognitiveCheckpointTransport + 'static> Owner<T> {
    pub(super) fn transport_observation(&self) -> Result<serde_json::Value, crate::AgentdError> {
        use std::os::unix::fs::MetadataExt;
        let writer = self.host.writer();
        let database = writer.database_path();
        let metadata = std::fs::metadata(database)?;
        Ok(
            serde_json::json!({"pid":std::process::id(),"database_path":database,
            "database_device":metadata.dev(),"database_inode":metadata.ino(),
            "ioctl_counts":self.device.native_ioctl_counts().map_err(crate::AgentdError::Protocol)?,
            "startup_retained":self.startup_retained}),
        )
    }

    pub(super) async fn observe_previous_boot(
        &self,
        occurrence_key: &str,
    ) -> Result<serde_json::Value, crate::AgentdError> {
        let fail = |value: &str| crate::AgentdError::Protocol(value.into());
        let writer = self.host.writer();
        let before = writer
            .retained_operation(occurrence_key)
            .await?
            .ok_or_else(|| fail("original previous-boot operation absent"))?;
        let request = Hos2InstallBudgetV1::from_json(&before.payload_json)
            .map_err(crate::AgentdError::Protocol)?;
        if before.topic != codex_hepta_memory::HOS2_INSTALL_TOPIC_V1
            || before.state != LocalOutcomeState::Indeterminate
            || request.to_json().map_err(crate::AgentdError::Protocol)? != before.payload_json
            || request.delivery.boot_id == self.device.native_history_identity().0
        {
            return Err(fail("exact original unresolved prior-boot K/D required"));
        }
        let calls_before = self
            .device
            .native_ioctl_counts()
            .map_err(crate::AgentdError::Protocol)?;
        let refusal = match self.device.observe(&request) {
            Err(failure) => failure,
            Ok(_) => return Err(fail("old boot unexpectedly entered native history")),
        };
        let calls_after = self
            .device
            .native_ioctl_counts()
            .map_err(crate::AgentdError::Protocol)?;
        if refusal != "native boot changed; the old D remains unknown"
            || calls_before != calls_after
        {
            return Err(fail(
                "prior-boot refusal did not precede the original device ioctl",
            ));
        }
        let after = writer
            .retained_operation(occurrence_key)
            .await?
            .ok_or_else(|| fail("original previous-boot operation disappeared"))?;
        let before = serde_json::json!({"operation":operation_observation(&before.operation),"topic":before.topic,
            "payload_json":before.payload_json,"state":before.state});
        let after = serde_json::json!({"operation":operation_observation(&after.operation),"topic":after.topic,
            "payload_json":after.payload_json,"state":after.state});
        if before != after {
            return Err(fail("original retained operation changed across refusal"));
        }
        let blockers = writer.hos2_drain_blockers().await?;
        writer.verify_current_authority().await?;
        Ok(
            serde_json::json!({"pid":std::process::id(),"occurrence_key":occurrence_key,
            "request_json":request.to_json().map_err(crate::AgentdError::Protocol)?,
            "before":before,"after":after,"refusal":refusal,
            "calls_before":calls_before,"calls_after":calls_after,"drain_blockers":blockers,
            "device_frontier":self.device_owner.frontier().map_err(|e| fail(&e.to_string()))?,
            "notes_frontier":self.notes_owner.frontier().map_err(|e| fail(&e.to_string()))?}),
        )
    }
}
