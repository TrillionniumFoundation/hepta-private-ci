impl Browser {
    fn prepare_dispatch(&mut self, frame: &Frame) -> Result<Option<Value>, String> {
        let operation_id = string_field(&frame.payload, "operationId")?;
        if let Some(prior) = self.operations.get(operation_id) {
            if prior.payload_digest != frame.payload_digest {
                return Err("operation identity was reused with changed worker payload".to_string());
            }
            return Ok(Some(stored_receipt(prior)));
        }
        self.pump();
        let action = frame
            .payload
            .get("typedAction")
            .and_then(Value::as_object)
            .ok_or_else(|| "typedAction must be an object".to_string())?;
        let kind = action
            .get("kind")
            .and_then(Value::as_str)
            .ok_or_else(|| "typedAction.kind must be a string".to_string())?;
        if matches!(kind, "credential" | "upload" | "download") {
            return Err("typedAction capability is not connected".to_string());
        }
        let mut prepared_action_handle = None;
        validate_dispatch_snapshot_state(
            &frame.payload,
            kind,
            self.page_generation,
            self.last_document_digest.as_deref(),
            self.observed_navigation_epoch,
            self.navigation_epoch.load(Ordering::Acquire),
        )?;
        if frame
            .payload
            .get("pageGeneration")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            != 0
        {
            let (observation, action_handles) = self.verify_action_surface()?;
            validate_action_target(action, &observation)?;
            if matches!(kind, "click" | "type" | "focus") {
                let selector = action
                    .get("selector")
                    .and_then(Value::as_str)
                    .ok_or_else(|| format!("{kind}.selector must be a string"))?;
                prepared_action_handle = Some(
                    action_handles
                        .get(selector)
                        .cloned()
                        .ok_or_else(|| {
                            "typed action selector lacks a private node handle".to_string()
                        })?,
                );
            }
        }

        let destination_origin = string_field(&frame.payload, "destinationOrigin")?;
        let destination_url = Url::parse(destination_origin)
            .map_err(|error| format!("dispatch destinationOrigin invalid: {error}"))?;
        let normalized_destination = origin(&destination_url)
            .ok_or_else(|| "dispatch destinationOrigin must use HTTP(S)".to_string())?;
        if normalized_destination != destination_origin
            || !self.allowed_origins.contains(&normalized_destination)
        {
            return Err("dispatch destinationOrigin is outside the admitted profile".to_string());
        }
        if kind == "navigate" {
            let target = action
                .get("url")
                .and_then(Value::as_str)
                .ok_or_else(|| "navigate.url must be a string".to_string())?;
            let target_url =
                Url::parse(target).map_err(|error| format!("navigate URL invalid: {error}"))?;
            if origin(&target_url).as_deref() != Some(normalized_destination.as_str()) {
                return Err(
                    "navigate action destination does not match dispatch destinationOrigin"
                        .to_string(),
                );
            }
        }
        *self
            .effect_navigation_origin
            .lock()
            .map_err(|_| "effect navigation origin lock is poisoned".to_string())? =
            Some(normalized_destination);

        self.operations.insert(
            operation_id.to_string(),
            StoredOperation {
                payload_digest: frame.payload_digest.clone(),
                terminal: None,
            },
        );
        if let Some(handle) = prepared_action_handle {
            self.prepared_action_handles
                .insert(operation_id.to_string(), handle);
        }
        Ok(None)
    }

}
impl Browser {
    fn execute_prepared_dispatch(&mut self, frame: &Frame) -> Result<Value, String> {
        let operation_id = string_field(&frame.payload, "operationId")?;
        let action = frame
            .payload
            .get("typedAction")
            .and_then(Value::as_object)
            .ok_or_else(|| "typedAction must be an object".to_string())?;
        let kind = action
            .get("kind")
            .and_then(Value::as_str)
            .ok_or_else(|| "typedAction.kind must be a string".to_string())?;
        let receipt_result = match kind {
            "navigate" => self.navigate(action),
            "click" | "type" | "focus" => {
                let handle = self
                    .prepared_action_handles
                    .remove(operation_id)
                    .ok_or_else(|| "prepared private action handle is missing".to_string())?;
                self.atomic_dom_action(action, kind, &handle)
            }
            "scroll" => fixed_scroll(action).and_then(|script| self.fixed_script(script, "scroll")),
            "wait" => self.wait(action),
            "credential" | "upload" | "download" => {
                Err("future capability crossed worker admission unexpectedly".to_string())
            }
            _ => Err("typedAction.kind is not registered by worker".to_string()),
        };
        let invalidation_result = self.invalidate_observation_after_effect(kind);
        let receipt = receipt_result?;
        invalidation_result?;
        let terminal = receipt
            .get("terminalObserved")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            .then(|| {
                (
                    receipt
                        .get("status")
                        .and_then(Value::as_str)
                        .unwrap_or("failed")
                        .to_string(),
                    receipt
                        .get("outcomeDigest")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string(),
                )
            });
        let stored = self
            .operations
            .get_mut(operation_id)
            .ok_or_else(|| "prepared worker operation reservation is missing".to_string())?;
        stored.terminal = terminal;
        Ok(receipt)
    }

    fn verify_action_surface(
        &mut self,
    ) -> Result<(Value, HashMap<String, String>), String> {
        let expected = self
            .last_action_surface_digest
            .clone()
            .ok_or_else(|| "worker has no admitted action surface for dispatch".to_string())?;
        let budget = self
            .last_observation_budget
            .ok_or_else(|| "worker has no admitted observation budget for dispatch".to_string())?;
        let expected_epoch = self
            .observed_navigation_epoch
            .ok_or_else(|| "worker has no admitted navigation epoch for dispatch".to_string())?;
        let before = self.navigation_epoch.load(Ordering::Acquire);
        if before != expected_epoch {
            return Err("worker navigation epoch drifted before action-surface check".to_string());
        }
        let observation =
            self.evaluate_json(semantic_snapshot_script(budget), Duration::from_secs(5))?;
        validate_safe_json(&observation, 0)?;
        let after_snapshot = self.navigation_epoch.load(Ordering::Acquire);
        if after_snapshot != expected_epoch {
            return Err("worker navigated during action-surface revalidation".to_string());
        }
        if action_surface_digest(&observation)? != expected {
            return Err("worker action surface drifted before dispatch".to_string());
        }
        let handles = self.bind_action_handles(&observation)?;
        let after_handles = self.navigation_epoch.load(Ordering::Acquire);
        if after_handles != expected_epoch {
            return Err("worker navigated while rebinding private action handles".to_string());
        }
        if handles != self.last_action_handles {
            return Err("worker action target identity drifted before dispatch".to_string());
        }
        Ok((observation, handles))
    }

    fn bind_action_handles(
        &mut self,
        observation: &Value,
    ) -> Result<HashMap<String, String>, String> {
        let controls = observation
            .get("controls")
            .and_then(Value::as_array)
            .ok_or_else(|| "semantic observation lacks controls".to_string())?;
        if controls.len() > 256 {
            return Err("semantic observation control count exceeds worker bound".to_string());
        }
        let mut selectors = Vec::with_capacity(controls.len());
        for control in controls {
            let selector = control
                .get("selector")
                .and_then(Value::as_str)
                .ok_or_else(|| "semantic observation control lacks selector".to_string())?;
            if selector.is_empty() || selector.len() > 2048 {
                return Err("semantic observation selector is outside the worker bound".to_string());
            }
            selectors.push(Value::String(selector.to_string()));
        }
        let response = self.call_private_bridge(
            json!({"kind": "bind", "selectors": selectors}),
            Duration::from_secs(5),
        )?;
        parse_private_action_handles(&response, controls.len())
    }

    fn atomic_dom_action(
        &mut self,
        action: &Map<String, Value>,
        kind: &str,
        handle: &str,
    ) -> Result<Value, String> {
        if self.page_generation == 0 {
            return Ok(failed(kind, "no_loaded_document"));
        }
        let selector = action
            .get("selector")
            .and_then(Value::as_str)
            .ok_or_else(|| format!("{kind}.selector must be a string"))?;
        let mut request = json!({
            "kind": "act",
            "action": kind,
            "selector": selector,
            "handle": handle,
        });
        if kind == "type" {
            let text = action
                .get("text")
                .and_then(Value::as_str)
                .ok_or_else(|| "type.text must be a string".to_string())?;
            request
                .as_object_mut()
                .expect("literal bridge request is an object")
                .insert("text".to_string(), Value::String(text.to_string()));
        }
        let response = self.call_private_bridge(request, Duration::from_secs(5))?;
        if response.get("ok").and_then(Value::as_bool) == Some(true)
            && response.get("acted").and_then(Value::as_bool) == Some(true)
        {
            return Ok(succeeded(kind, &self.outcome_digest(kind)));
        }
        let error = response
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("private_bridge_invalid_response");
        if matches!(
            error,
            "target_identity_drift"
                | "target_not_actionable"
                | "target_type_not_allowed"
                | "target_missing"
                | "capability_not_connected"
        ) {
            return Ok(failed(kind, error));
        }
        Err(format!("private action bridge failed: {error}"))
    }

    fn call_private_bridge(
        &mut self,
        request: Value,
        timeout: Duration,
    ) -> Result<Value, String> {
        validate_safe_json(&request, 0)?;
        let script = private_bridge_request_script(
            &self.bridge_name,
            &self.bridge_secret,
            &request,
        )?;
        self.evaluate_json(script, timeout)
    }

}
