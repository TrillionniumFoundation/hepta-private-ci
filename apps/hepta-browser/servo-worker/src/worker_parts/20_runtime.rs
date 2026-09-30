impl Browser {
    fn invalidate_observation_after_effect(&mut self, action: &str) -> Result<(), String> {
        if action != "navigate" {
            self.page_generation = self
                .page_generation
                .checked_add(1)
                .ok_or_else(|| "page generation exhausted".to_string())?;
        }
        self.last_document_digest = None;
        self.last_action_surface_digest = None;
        self.last_observation_budget = None;
        self.last_action_handles.clear();
        self.observed_navigation_epoch = None;
        Ok(())
    }

    fn navigate(&mut self, action: &Map<String, Value>) -> Result<Value, String> {
        let target = action
            .get("url")
            .and_then(Value::as_str)
            .ok_or_else(|| "navigate.url must be a string".to_string())?;
        let url = Url::parse(target).map_err(|error| format!("navigate URL invalid: {error}"))?;
        let target_origin = origin(&url).ok_or_else(|| "navigate URL must use HTTP(S)".to_string())?;
        if !self.allowed_origins.contains(&target_origin) {
            return Ok(failed("navigate", "origin_not_allowed"));
        }
        self.navigation_epoch.fetch_add(1, Ordering::AcqRel);
        self.page_generation = self
            .page_generation
            .checked_add(1)
            .ok_or_else(|| "page generation exhausted".to_string())?;
        self.webview.load(url);
        self.pump();
        if self.webview.load_status() == LoadStatus::Complete {
            Ok(succeeded("navigate", &self.outcome_digest("navigate")))
        } else {
            Ok(json!({"terminalObserved": false}))
        }
    }

    fn fixed_script(&mut self, script: String, action: &str) -> Result<Value, String> {
        if self.page_generation == 0 {
            return Ok(failed(action, "no_loaded_document"));
        }
        if self.evaluate_bool(script, Duration::from_secs(5))? {
            Ok(succeeded(action, &self.outcome_digest(action)))
        } else {
            Ok(failed(action, "target_not_found_or_not_actionable"))
        }
    }

    fn wait(&mut self, action: &Map<String, Value>) -> Result<Value, String> {
        if action.get("condition").and_then(Value::as_str) != Some("load-complete") {
            return Ok(failed("wait", "condition_not_registered"));
        }
        let timeout_ms = action
            .get("timeoutMs")
            .and_then(Value::as_u64)
            .ok_or_else(|| "wait.timeoutMs must be a positive integer".to_string())?
            .min(120_000);
        let deadline = Instant::now() + Duration::from_millis(timeout_ms);
        loop {
            self.pump();
            if self.webview.load_status() == LoadStatus::Complete {
                return Ok(succeeded("wait", &self.outcome_digest("wait")));
            }
            if Instant::now() >= deadline {
                return Ok(failed("wait", "load_not_complete_before_timeout"));
            }
            thread::sleep(Duration::from_millis(2));
        }
    }

    fn evaluate_bool(&mut self, script: String, timeout: Duration) -> Result<bool, String> {
        let result = Rc::new(RefCell::new(None));
        let callback_result = result.clone();
        self.webview.evaluate_javascript(script, move |value| {
            *callback_result.borrow_mut() = Some(value);
        });
        let deadline = Instant::now() + timeout;
        loop {
            self.pump();
            if let Some(value) = result.borrow_mut().take() {
                return match value {
                    Ok(JSValue::Boolean(value)) => Ok(value),
                    Ok(_) => Err("fixed worker script returned an unexpected value".to_string()),
                    Err(error) => Err(format!("fixed worker script evaluation failed: {error:?}")),
                };
            }
            if Instant::now() >= deadline {
                return Err("fixed worker script evaluation timed out".to_string());
            }
            thread::sleep(Duration::from_millis(2));
        }
    }

    fn evaluate_json(&mut self, script: String, timeout: Duration) -> Result<Value, String> {
        let result = Rc::new(RefCell::new(None));
        let callback_result = result.clone();
        self.webview.evaluate_javascript(script, move |value| {
            *callback_result.borrow_mut() = Some(value);
        });
        let deadline = Instant::now() + timeout;
        loop {
            self.pump();
            if let Some(value) = result.borrow_mut().take() {
                return match value {
                    Ok(JSValue::String(value)) => serde_json::from_str(&value)
                        .map_err(|error| format!("semantic observation JSON invalid: {error}")),
                    Ok(_) => Err("semantic observation script returned an unexpected value".to_string()),
                    Err(error) => Err(format!("semantic observation evaluation failed: {error:?}")),
                };
            }
            if Instant::now() >= deadline {
                return Err("semantic observation evaluation timed out".to_string());
            }
            thread::sleep(Duration::from_millis(2));
        }
    }

    fn reconcile(&mut self, frame: &Frame) -> Result<Value, String> {
        let operation_id = string_field(&frame.payload, "operationId")?;
        let prior = self
            .operations
            .get(operation_id)
            .cloned()
            .ok_or_else(|| "operation is unknown to worker".to_string())?;
        if prior.payload_digest != frame.payload_digest {
            return Err("reconciliation payload drifted from dispatch".to_string());
        }
        if let Some((status, outcome_digest)) = prior.terminal {
            return Ok(json!({
                "terminalObserved": true,
                "status": status,
                "outcomeDigest": outcome_digest,
            }));
        }
        self.pump();
        let kind = frame
            .payload
            .get("typedAction")
            .and_then(Value::as_object)
            .and_then(|value| value.get("kind"))
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        if kind == "navigate" && self.webview.load_status() == LoadStatus::Complete {
            let outcome = self.outcome_digest("navigate");
            if let Some(stored) = self.operations.get_mut(operation_id) {
                stored.terminal = Some(("succeeded".to_string(), outcome.clone()));
            }
            return Ok(json!({
                "terminalObserved": true,
                "status": "succeeded",
                "outcomeDigest": outcome,
            }));
        }
        Ok(json!({"terminalObserved": false}))
    }

    fn outcome_digest(&self, action: &str) -> String {
        let url = self
            .webview
            .url()
            .map(|value| value.to_string())
            .unwrap_or_else(|| "<none>".to_string());
        sha256_hex(
            format!(
                "{}\0{}\0{:?}\0{}",
                action,
                url,
                self.webview.load_status(),
                self.page_generation
            )
            .as_bytes(),
        )
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-servo-worker fatal: {error}");
        std::process::exit(64);
    }
}

fn run() -> Result<(), String> {
    rustls::crypto::aws_lc_rs::default_provider()
        .install_default()
        .map_err(|_| "failed to install rustls crypto provider".to_string())?;
    let (sender, receiver) = mpsc::channel();
    let reader = sender.clone();
    thread::Builder::new()
        .name("hepta-browser-private-channel".to_string())
        .spawn(move || read_frames(reader))
        .map_err(|error| format!("private channel thread failed: {error}"))?;
    let waker = Waker(sender);
    let mut output = io::stdout().lock();
    let mut browser: Option<Browser> = None;
    let mut session: Option<String> = None;
    let mut generation: Option<u64> = None;
    let mut response_sequence = 1_u64;

    loop {
        match receiver.recv_timeout(Duration::from_millis(5)) {
            Ok(HostEvent::Wake) | Err(mpsc::RecvTimeoutError::Timeout) => {
                if let Some(browser) = browser.as_mut() {
                    browser.pump();
                }
            }
            Err(mpsc::RecvTimeoutError::Disconnected) | Ok(HostEvent::Eof) => return Ok(()),
            Ok(HostEvent::Fatal(error)) => return Err(error),
            Ok(HostEvent::Command(frame)) => {
                if session.as_deref().is_some_and(|value| value != frame.session_id) {
                    return Err("frame crossed worker session".to_string());
                }
                if generation.is_some_and(|value| value != frame.generation) {
                    return Err("frame crossed worker generation".to_string());
                }
                let stop = frame.kind == "stop";
                let result = match frame.kind.as_str() {
                    "start" => {
                        if browser.is_some() {
                            Err("worker is already started".to_string())
                        } else {
                            let allowed = parse_allowed_origins(&frame.payload)?;
                            browser = Some(Browser::new(allowed, waker.clone())?);
                            session = Some(frame.session_id.clone());
                            generation = Some(frame.generation);
                            Ok(json!({"started": true}))
                        }
                    }
                    "observe" => {
                        let budget = frame
                            .payload
                            .get("observationBudget")
                            .and_then(Value::as_u64)
                            .ok_or_else(|| "observe.observationBudget must be a positive integer".to_string())?;
                        if budget == 0 || budget > MAX_SAFE_INTEGER {
                            return Err("observe.observationBudget is outside the safe range".to_string());
                        }
                        browser
                            .as_mut()
                            .ok_or_else(|| "worker is not started".to_string())?
                            .observe(budget as usize)
                    }
                    "dispatch" => {
                        let active = browser
                            .as_mut()
                            .ok_or_else(|| "worker is not started".to_string())?;
                        match active.prepare_dispatch(&frame) {
                            Ok(replay) => {
                                write_worker_frame(
                                    &mut output,
                                    &frame,
                                    response_sequence,
                                    "dispatch_boundary",
                                    json!({
                                        "localDispatchCrossed": true,
                                        "requestKind": frame.kind,
                                        "requestPayloadDigest": frame.payload_digest,
                                        "requestSequence": frame.sequence,
                                    }),
                                )?;
                                response_sequence = response_sequence
                                    .checked_add(1)
                                    .ok_or_else(|| "response sequence exhausted".to_string())?;
                                match replay {
                                    Some(receipt) => Ok(receipt),
                                    None => active.execute_prepared_dispatch(&frame),
                                }
                            }
                            Err(error) => Err(error),
                        }
                    }
                    "reconcile" => browser
                        .as_mut()
                        .ok_or_else(|| "worker is not started".to_string())?
                        .reconcile(&frame),
                    "stop" => Ok(json!({"stopped": true})),
                    _ => Err("host sent a non-command frame".to_string()),
                };
                let payload = match result {
                    Ok(observation) => json!({
                        "ok": true,
                        "requestKind": frame.kind,
                        "requestPayloadDigest": frame.payload_digest,
                        "requestSequence": frame.sequence,
                        "observation": observation,
                    }),
                    Err(error) => json!({
                        "ok": false,
                        "requestKind": frame.kind,
                        "requestPayloadDigest": frame.payload_digest,
                        "requestSequence": frame.sequence,
                        "error": error,
                    }),
                };
                write_response(&mut output, &frame, response_sequence, payload)?;
                response_sequence = response_sequence
                    .checked_add(1)
                    .ok_or_else(|| "response sequence exhausted".to_string())?;
                if stop {
                    return Ok(());
                }
            }
        }
    }
}

