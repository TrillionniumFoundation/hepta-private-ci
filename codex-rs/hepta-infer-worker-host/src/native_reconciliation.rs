//! Reconcile an existing durable operation without reserving or dispatching.

use super::*;

impl AppServerModelDriver {
    /// Inspect exact stored evidence or reconcile it through the existing
    /// authenticated App Server history adapter. This API cannot create a
    /// reservation, call turn/start, accept caller-supplied terminality, or
    /// turn missing usage into zero. `None` and nonterminal outputs do not
    /// release held reservations and do not authorize a replacement request.
    ///
    /// Callers supply the original admission inputs, including the original
    /// context query and intelligence envelope, even after their expiry. They
    /// identify a historical fact; they do not authorize a new model effect.
    pub async fn reconcile_only(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        prompt: &str,
        context_query: Option<String>,
        intelligence: Option<&NativeIntelligenceRunBinding>,
    ) -> Result<Option<NativeRunOutput>> {
        if request_id.is_empty() || request_id.len() > 128 {
            return Err("invalid reconciliation request identity".into());
        }
        if prompt.is_empty() || prompt.len() > super::super::MAX_PROMPT_BYTES {
            return Err("prompt must contain 1..32768 bytes".into());
        }
        if context_query
            .as_ref()
            .is_some_and(|query| query.is_empty() || query.len() > 2048)
        {
            return Err("context query must contain 1..2048 bytes".into());
        }
        if intelligence.is_some_and(|binding| {
            binding.run_id.is_empty()
                || binding.run_id.len() > 128
                || binding.context_digest.len() != 64
                || binding.envelope_digest.len() != 64
        }) {
            return Err("invalid reconciliation intelligence binding".into());
        }
        let record = control
            .native_record(request_id)
            .cloned()
            .ok_or("reconciliation requires an existing durable request")?;
        let expected_payload = native_source_payload_digest(
            prompt,
            &context_query,
            &self.config.agentd_socket,
            self.config.timeout.as_millis(),
            intelligence,
        )?;
        if record.request.principal_id != self.config.agent_id.to_string()
            || record.request.worker_generation != self.config.generation
            || record.request.model != self.config.model
            || record.request.payload_digest != expected_payload
        {
            return Err("reconciliation admission identity drifted".into());
        }
        if let Some(output) = record
            .observation
            .as_ref()
            .filter(|output| output.terminal_observed)
        {
            return Ok(Some(output.clone()));
        }
        if record.state == NativeReservationState::Reserved
            || record.pre_dispatch_stop.is_some()
            || record.dispatch_rejection.is_some()
        {
            return Ok(record.observation);
        }
        let Some(observed) = self.reconcile_existing(&record, prompt).await? else {
            return Ok(record.observation);
        };
        let settled = control.settle_native(request_id, observed)?;
        let output = settled
            .observation
            .ok_or("durable reconciliation omitted its normalized observation")?;
        Ok(Some(output))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::native_app_server::NativeWorkerConfig;
    use codex_hepta_contracts::AgentId;
    use std::time::Duration;

    fn fixture() -> (tempfile::TempDir, AppServerModelDriver, DurableInferenceControl) {
        let directory = tempfile::tempdir().expect("private directory");
        let driver = AppServerModelDriver::new(NativeWorkerConfig {
            agentd_socket: directory.path().join("nonexistent.sock"),
            agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001").expect("id"),
            generation: 1,
            model: "model".to_string(),
            timeout: Duration::from_secs(5),
        })
        .expect("driver");
        let control = DurableInferenceControl::open(directory.path().join("journal"), 8)
            .expect("control");
        (directory, driver, control)
    }

    fn reserve(driver: &AppServerModelDriver, control: &mut DurableInferenceControl) {
        control
            .reserve_native(
                NativeRequest {
                    request_id: "request.1".to_string(),
                    principal_id: driver.config.agent_id.to_string(),
                    worker_generation: 1,
                    model: "model".to_string(),
                    payload_digest: native_source_payload_digest(
                        "prompt",
                        &None,
                        &driver.config.agentd_socket,
                        driver.config.timeout.as_millis(),
                        None,
                    )
                    .expect("digest"),
                },
                1,
            )
            .expect("reserve");
    }

    #[tokio::test]
    async fn unknown_request_cannot_be_admitted_by_reconciliation() {
        let (_directory, driver, mut control) = fixture();
        assert!(
            driver
                .reconcile_only(&mut control, "request.1", "prompt", None, None)
                .await
                .is_err()
        );
        assert!(control.native_record("request.1").is_none());
    }

    #[tokio::test]
    async fn reserved_request_is_not_dispatched_or_released() {
        let (_directory, driver, mut control) = fixture();
        reserve(&driver, &mut control);
        let before = control.native_record("request.1").cloned();
        assert!(
            driver
                .reconcile_only(&mut control, "request.1", "prompt", None, None)
                .await
                .expect("read only")
                .is_none()
        );
        assert_eq!(control.native_record("request.1").cloned(), before);
    }

    #[tokio::test]
    async fn changed_prompt_or_context_cannot_consume_historical_evidence() {
        let (_directory, driver, mut control) = fixture();
        reserve(&driver, &mut control);
        let before = control.native_record("request.1").cloned();
        for (prompt, query) in [
            ("changed", None),
            ("prompt", Some("changed context".to_string())),
        ] {
            assert!(
                driver
                    .reconcile_only(&mut control, "request.1", prompt, query, None)
                    .await
                    .is_err()
            );
        }
        assert_eq!(control.native_record("request.1").cloned(), before);
    }

    #[tokio::test]
    async fn changed_generation_cannot_read_or_settle_another_owner_operation() {
        let (_directory, mut driver, mut control) = fixture();
        reserve(&driver, &mut control);
        driver.config.generation = 2;
        let before = control.native_record("request.1").cloned();
        assert!(
            driver
                .reconcile_only(&mut control, "request.1", "prompt", None, None)
                .await
                .is_err()
        );
        assert_eq!(control.native_record("request.1").cloned(), before);
    }
}
