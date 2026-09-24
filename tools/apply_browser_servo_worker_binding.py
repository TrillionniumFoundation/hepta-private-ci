from pathlib import Path

path = Path("apps/hepta-browser/servo-worker/src/main.rs")
text = path.read_text(encoding="utf-8")
start = text.index("struct Delegate {")
end = text.index("\nfn main() {", start)
block = r'''#[derive(Clone, Debug, Default)]
struct PageSignals {
    revision: u64,
    url: Option<String>,
    overflowed: bool,
}

struct Delegate {
    frame_ready: Arc<AtomicBool>,
    allowed_origins: HashSet<String>,
    page_signals: Rc<RefCell<PageSignals>>,
}

impl WebViewDelegate for Delegate {
    fn notify_new_frame_ready(&self, _webview: WebView) {
        self.frame_ready.store(true, Ordering::Release);
    }

    fn notify_url_changed(&self, _webview: WebView, url: Url) {
        self.page_signals.borrow_mut().url = Some(url.to_string());
    }

    fn notify_load_status_changed(&self, _webview: WebView, status: LoadStatus) {
        if !matches!(status, LoadStatus::Started) {
            return;
        }
        let mut signals = self.page_signals.borrow_mut();
        match signals.revision.checked_add(1) {
            Some(revision) if revision <= MAX_SAFE_INTEGER => signals.revision = revision,
            _ => signals.overflowed = true,
        }
    }

    fn request_navigation(&self, _webview: WebView, request: NavigationRequest) {
        let allowed = request.url.as_str() == "about:blank"
            || origin(&request.url).is_some_and(|value| self.allowed_origins.contains(&value));
        if allowed {
            request.allow();
        } else {
            request.deny();
        }
    }

    fn request_permission(&self, _webview: WebView, request: PermissionRequest) {
        request.deny();
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct DocumentIdentity {
    page_generation: u64,
    document_digest: String,
    url: String,
    origin: String,
}

impl DocumentIdentity {
    fn from_url(page_generation: u64, url: &Url) -> Option<Self> {
        let origin = origin(url)?;
        let canonical_url = url.to_string();
        let document_digest = sha256_hex(
            format!(
                "hepta.browser.document.v1\0{page_generation}\0{canonical_url}\0{origin}"
            )
            .as_bytes(),
        );
        Some(Self {
            page_generation,
            document_digest,
            url: canonical_url,
            origin,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum OperationBinding {
    Navigate {
        source_page_generation: u64,
        source_document_digest: Option<String>,
        target_page_generation: u64,
        target_url: String,
    },
    DocumentAction {
        source: DocumentIdentity,
        action: String,
    },
    Rejected {
        action: String,
        reason: String,
    },
}

impl OperationBinding {
    fn digest_material(&self) -> String {
        match self {
            Self::Navigate {
                source_page_generation,
                source_document_digest,
                target_page_generation,
                target_url,
            } => format!(
                "navigate\0{source_page_generation}\0{}\0{target_page_generation}\0{target_url}",
                source_document_digest.as_deref().unwrap_or("<bootstrap>"),
            ),
            Self::DocumentAction { source, action } => format!(
                "document\0{action}\0{}\0{}\0{}",
                source.page_generation, source.document_digest, source.url,
            ),
            Self::Rejected { action, reason } => format!("rejected\0{action}\0{reason}"),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct TerminalReceipt {
    status: String,
    outcome_digest: String,
    reason: String,
    observed_page_generation: u64,
    observed_document_digest: Option<String>,
}

#[derive(Clone)]
struct StoredOperation {
    payload_digest: String,
    binding: OperationBinding,
    terminal: Option<TerminalReceipt>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum NavigationDecision {
    Indeterminate,
    Succeeded,
    FailedSuperseded,
    FailedTargetMismatch,
}

fn navigation_decision(
    current_page_generation: u64,
    current_url: Option<&str>,
    load_complete: bool,
    target_page_generation: u64,
    target_url: &str,
) -> NavigationDecision {
    if current_page_generation > target_page_generation {
        return NavigationDecision::FailedSuperseded;
    }
    if current_page_generation < target_page_generation || !load_complete {
        return NavigationDecision::Indeterminate;
    }
    if current_url != Some(target_url) {
        return NavigationDecision::FailedTargetMismatch;
    }
    NavigationDecision::Succeeded
}

fn source_document_matches(
    current: Option<&DocumentIdentity>,
    page_generation: u64,
    document_digest: Option<&str>,
) -> bool {
    match (current, page_generation, document_digest) {
        (None, 0, None) => true,
        (Some(current), generation, Some(digest)) => {
            generation == current.page_generation && digest == current.document_digest.as_str()
        }
        _ => false,
    }
}

struct Browser {
    servo: Servo,
    context: Rc<SoftwareRenderingContext>,
    webview: WebView,
    frame_ready: Arc<AtomicBool>,
    allowed_origins: HashSet<String>,
    page_signals: Rc<RefCell<PageSignals>>,
    seen_signal_revision: u64,
    seen_url: Option<String>,
    page_generation: u64,
    document: Option<DocumentIdentity>,
    operations: HashMap<String, StoredOperation>,
}

impl Browser {
    fn new(allowed_origins: HashSet<String>, waker: Waker) -> Result<Self, String> {
        let context = Rc::new(
            SoftwareRenderingContext::new(PhysicalSize::new(1280, 720))
                .map_err(|error| format!("software rendering context failed: {error:?}"))?,
        );
        context
            .make_current()
            .map_err(|error| format!("make_current failed: {error:?}"))?;
        let servo = ServoBuilder::default()
            .event_loop_waker(Box::new(waker))
            .build();
        servo.setup_logging();
        let frame_ready = Arc::new(AtomicBool::new(false));
        let page_signals = Rc::new(RefCell::new(PageSignals::default()));
        let delegate = Rc::new(Delegate {
            frame_ready: frame_ready.clone(),
            allowed_origins: allowed_origins.clone(),
            page_signals: page_signals.clone(),
        });
        let webview = WebViewBuilder::new(&servo, context.clone())
            .url(Url::parse("about:blank").expect("literal about:blank is valid"))
            .delegate(delegate)
            .build();
        let mut browser = Self {
            servo,
            context,
            webview,
            frame_ready,
            allowed_origins,
            page_signals,
            seen_signal_revision: 0,
            seen_url: None,
            page_generation: 0,
            document: None,
            operations: HashMap::new(),
        };
        browser.pump_raw();
        let initial = browser.page_signals.borrow().clone();
        browser.seen_signal_revision = initial.revision;
        browser.seen_url = initial.url;
        Ok(browser)
    }

    fn pump_raw(&mut self) {
        self.servo.spin_event_loop();
        if self.frame_ready.swap(false, Ordering::AcqRel) {
            self.webview.paint();
            self.context.present();
        }
    }

    fn pump(&mut self) -> Result<(), String> {
        self.pump_raw();
        self.sync_document_identity()
    }

    fn sync_document_identity(&mut self) -> Result<(), String> {
        let signals = self.page_signals.borrow().clone();
        if signals.overflowed || signals.revision > MAX_SAFE_INTEGER {
            return Err("page signal revision exhausted".to_string());
        }
        if signals.revision < self.seen_signal_revision {
            return Err("page signal revision regressed".to_string());
        }
        let revision_advanced = signals.revision > self.seen_signal_revision;
        if revision_advanced {
            let delta = signals.revision - self.seen_signal_revision;
            self.page_generation = self
                .page_generation
                .checked_add(delta)
                .filter(|value| *value <= MAX_SAFE_INTEGER)
                .ok_or_else(|| "page generation exhausted".to_string())?;
            self.seen_signal_revision = signals.revision;
        }
        let url_changed = signals.url != self.seen_url;
        if url_changed {
            self.seen_url = signals.url.clone();
        }
        if self.page_generation == 0 {
            self.document = None;
        } else if revision_advanced || url_changed {
            self.document = signals
                .url
                .as_deref()
                .and_then(|value| Url::parse(value).ok())
                .and_then(|url| DocumentIdentity::from_url(self.page_generation, &url));
        }
        Ok(())
    }

    fn observe(&mut self) -> Result<Value, String> {
        self.pump()?;
        if self.webview.load_status() != LoadStatus::Complete {
            return Err("current document has not reached load-complete".to_string());
        }
        let document = self
            .document
            .as_ref()
            .ok_or_else(|| "no authorized web document has been loaded".to_string())?;
        Ok(json!({
            "pageGeneration": document.page_generation,
            "documentDigest": document.document_digest,
            "origin": document.origin,
        }))
    }

    fn dispatch(&mut self, frame: &Frame) -> Result<Value, String> {
        self.pump()?;
        let operation_id = string_field(&frame.payload, "operationId")?.to_string();
        if let Some(prior) = self.operations.get(&operation_id) {
            if prior.payload_digest != frame.payload_digest {
                return Err("operation identity was reused with changed worker payload".to_string());
            }
            return Ok(operation_receipt(
                &operation_id,
                prior,
                self.page_generation,
                self.document.as_ref(),
            ));
        }
        let action = frame
            .payload
            .get("typedAction")
            .and_then(Value::as_object)
            .ok_or_else(|| "typedAction must be an object".to_string())?;
        let kind = action
            .get("kind")
            .and_then(Value::as_str)
            .ok_or_else(|| "typedAction.kind must be a string".to_string())?
            .to_string();
        let allow_bootstrap = kind == "navigate";
        let source = match self.admit_source_document(&frame.payload, allow_bootstrap) {
            Ok(source) => source,
            Err(reason) => {
                self.operations.insert(
                    operation_id.clone(),
                    StoredOperation {
                        payload_digest: frame.payload_digest.clone(),
                        binding: OperationBinding::Rejected {
                            action: kind,
                            reason: reason.clone(),
                        },
                        terminal: None,
                    },
                );
                return self.finish_operation(&operation_id, "failed", &reason);
            }
        };

        if kind == "navigate" {
            let target = action
                .get("url")
                .and_then(Value::as_str)
                .ok_or_else(|| "navigate.url must be a string".to_string())?;
            let url = Url::parse(target).map_err(|error| format!("navigate URL invalid: {error}"))?;
            let target_origin = origin(&url)
                .ok_or_else(|| "navigate URL must use HTTP(S)".to_string())?;
            if !self.allowed_origins.contains(&target_origin) {
                self.operations.insert(
                    operation_id.clone(),
                    StoredOperation {
                        payload_digest: frame.payload_digest.clone(),
                        binding: OperationBinding::Rejected {
                            action: kind,
                            reason: "origin_not_allowed".to_string(),
                        },
                        terminal: None,
                    },
                );
                return self.finish_operation(&operation_id, "failed", "origin_not_allowed");
            }
            let target_page_generation = self
                .page_generation
                .checked_add(1)
                .filter(|value| *value <= MAX_SAFE_INTEGER)
                .ok_or_else(|| "page generation exhausted".to_string())?;
            self.operations.insert(
                operation_id.clone(),
                StoredOperation {
                    payload_digest: frame.payload_digest.clone(),
                    binding: OperationBinding::Navigate {
                        source_page_generation: source.as_ref().map_or(0, |value| value.page_generation),
                        source_document_digest: source
                            .as_ref()
                            .map(|value| value.document_digest.clone()),
                        target_page_generation,
                        target_url: url.to_string(),
                    },
                    terminal: None,
                },
            );
            self.webview.load(url);
            self.pump()?;
            return self.settle_navigation(&operation_id);
        }

        let source = source.ok_or_else(|| "document action cannot use bootstrap identity".to_string())?;
        let destination_origin = string_field(&frame.payload, "destinationOrigin")?;
        if destination_origin != source.origin {
            self.operations.insert(
                operation_id.clone(),
                StoredOperation {
                    payload_digest: frame.payload_digest.clone(),
                    binding: OperationBinding::Rejected {
                        action: kind,
                        reason: "destination_origin_does_not_match_current_document".to_string(),
                    },
                    terminal: None,
                },
            );
            return self.finish_operation(
                &operation_id,
                "failed",
                "destination_origin_does_not_match_current_document",
            );
        }
        self.operations.insert(
            operation_id.clone(),
            StoredOperation {
                payload_digest: frame.payload_digest.clone(),
                binding: OperationBinding::DocumentAction {
                    source: source.clone(),
                    action: kind.clone(),
                },
                terminal: None,
            },
        );
        match kind.as_str() {
            "click" => self.execute_fixed_action(
                &operation_id,
                &source,
                fixed_click(action, &source.url)?,
                "click",
            ),
            "type" => self.execute_fixed_action(
                &operation_id,
                &source,
                fixed_type(action, &source.url)?,
                "type",
            ),
            "focus" => self.execute_fixed_action(
                &operation_id,
                &source,
                fixed_focus(action, &source.url)?,
                "focus",
            ),
            "scroll" => self.execute_fixed_action(
                &operation_id,
                &source,
                fixed_scroll(action, &source.url)?,
                "scroll",
            ),
            "wait" => self.wait(&operation_id, &source, action),
            "credential" | "upload" | "download" => {
                self.finish_operation(&operation_id, "failed", "capability_not_connected")
            }
            _ => Err("typedAction.kind is not registered by worker".to_string()),
        }
    }

    fn admit_source_document(
        &self,
        payload: &Value,
        allow_bootstrap: bool,
    ) -> Result<Option<DocumentIdentity>, String> {
        let page_generation = non_negative_u64_field(payload, "pageGeneration")?;
        let document_digest = optional_string_field(payload, "documentDigest")?;
        if page_generation == 0 {
            if !allow_bootstrap || document_digest.is_some() {
                return Err("bootstrap document identity is not permitted for this action".to_string());
            }
            if self.page_generation != 0 || self.document.is_some() {
                return Err("bootstrap navigation raced a live document".to_string());
            }
            return Ok(None);
        }
        let document_digest = document_digest
            .ok_or_else(|| "documentDigest is required for a live document".to_string())?;
        if !source_document_matches(
            self.document.as_ref(),
            page_generation,
            Some(document_digest),
        ) {
            return Err("source document identity is stale".to_string());
        }
        Ok(self.document.clone())
    }

    fn execute_fixed_action(
        &mut self,
        operation_id: &str,
        source: &DocumentIdentity,
        script: String,
        action: &str,
    ) -> Result<Value, String> {
        if !source_document_matches(
            self.document.as_ref(),
            source.page_generation,
            Some(&source.document_digest),
        ) {
            return self.finish_operation(operation_id, "failed", "source_document_changed_before_action");
        }
        let matched = self.evaluate_bool(script, Duration::from_secs(5))?;
        self.pump()?;
        if !source_document_matches(
            self.document.as_ref(),
            source.page_generation,
            Some(&source.document_digest),
        ) {
            return self.finish_operation(operation_id, "failed", "source_document_changed_during_action");
        }
        if matched {
            self.finish_operation(operation_id, "succeeded", action)
        } else {
            self.finish_operation(operation_id, "failed", "target_not_found_or_not_actionable")
        }
    }

    fn wait(
        &mut self,
        operation_id: &str,
        source: &DocumentIdentity,
        action: &Map<String, Value>,
    ) -> Result<Value, String> {
        if action.get("condition").and_then(Value::as_str) != Some("load-complete") {
            return self.finish_operation(operation_id, "failed", "condition_not_registered");
        }
        let timeout_ms = action
            .get("timeoutMs")
            .and_then(Value::as_u64)
            .ok_or_else(|| "wait.timeoutMs must be a positive integer".to_string())?
            .min(120_000);
        let deadline = Instant::now() + Duration::from_millis(timeout_ms);
        loop {
            self.pump()?;
            if !source_document_matches(
                self.document.as_ref(),
                source.page_generation,
                Some(&source.document_digest),
            ) {
                return self.finish_operation(operation_id, "failed", "source_document_changed_during_wait");
            }
            if self.webview.load_status() == LoadStatus::Complete {
                return self.finish_operation(operation_id, "succeeded", "wait_load_complete");
            }
            if Instant::now() >= deadline {
                return self.finish_operation(operation_id, "failed", "load_not_complete_before_timeout");
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
            self.pump()?;
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

    fn reconcile(&mut self, frame: &Frame) -> Result<Value, String> {
        self.pump()?;
        let operation_id = string_field(&frame.payload, "operationId")?.to_string();
        let prior = self
            .operations
            .get(&operation_id)
            .cloned()
            .ok_or_else(|| "operation is unknown to worker".to_string())?;
        if prior.payload_digest != frame.payload_digest {
            return Err("reconciliation payload drifted from dispatch".to_string());
        }
        if prior.terminal.is_some() {
            return Ok(operation_receipt(
                &operation_id,
                &prior,
                self.page_generation,
                self.document.as_ref(),
            ));
        }
        match prior.binding {
            OperationBinding::Navigate { .. } => self.settle_navigation(&operation_id),
            OperationBinding::DocumentAction { source, .. } => {
                if !source_document_matches(
                    self.document.as_ref(),
                    source.page_generation,
                    Some(&source.document_digest),
                ) {
                    self.finish_operation(
                        &operation_id,
                        "failed",
                        "source_document_changed_before_terminal_observation",
                    )
                } else {
                    Ok(operation_receipt(
                        &operation_id,
                        &prior,
                        self.page_generation,
                        self.document.as_ref(),
                    ))
                }
            }
            OperationBinding::Rejected { ref reason, .. } => {
                self.finish_operation(&operation_id, "failed", reason)
            }
        }
    }

    fn settle_navigation(&mut self, operation_id: &str) -> Result<Value, String> {
        self.pump()?;
        let prior = self
            .operations
            .get(operation_id)
            .cloned()
            .ok_or_else(|| "operation is unknown to worker".to_string())?;
        let (target_page_generation, target_url) = match &prior.binding {
            OperationBinding::Navigate {
                target_page_generation,
                target_url,
                ..
            } => (*target_page_generation, target_url.as_str()),
            _ => return Err("operation is not a navigation".to_string()),
        };
        let decision = navigation_decision(
            self.page_generation,
            self.document.as_ref().map(|value| value.url.as_str()),
            self.webview.load_status() == LoadStatus::Complete,
            target_page_generation,
            target_url,
        );
        match decision {
            NavigationDecision::Indeterminate => Ok(operation_receipt(
                operation_id,
                &prior,
                self.page_generation,
                self.document.as_ref(),
            )),
            NavigationDecision::Succeeded => {
                self.finish_operation(operation_id, "succeeded", "navigation_target_complete")
            }
            NavigationDecision::FailedSuperseded => {
                self.finish_operation(operation_id, "failed", "navigation_superseded_by_newer_document")
            }
            NavigationDecision::FailedTargetMismatch => {
                self.finish_operation(operation_id, "failed", "navigation_completed_at_different_document")
            }
        }
    }

    fn finish_operation(
        &mut self,
        operation_id: &str,
        status: &str,
        reason: &str,
    ) -> Result<Value, String> {
        let prior = self
            .operations
            .get(operation_id)
            .cloned()
            .ok_or_else(|| "operation is unknown to worker".to_string())?;
        if prior.terminal.is_some() {
            return Ok(operation_receipt(
                operation_id,
                &prior,
                self.page_generation,
                self.document.as_ref(),
            ));
        }
        let observed_document_digest = self
            .document
            .as_ref()
            .map(|value| value.document_digest.clone());
        let outcome_digest = sha256_hex(
            format!(
                "hepta.browser.operation-outcome.v1\0{operation_id}\0{}\0{}\0{status}\0{reason}\0{}\0{}",
                prior.payload_digest,
                prior.binding.digest_material(),
                self.page_generation,
                observed_document_digest.as_deref().unwrap_or("<none>"),
            )
            .as_bytes(),
        );
        let terminal = TerminalReceipt {
            status: status.to_string(),
            outcome_digest,
            reason: reason.to_string(),
            observed_page_generation: self.page_generation,
            observed_document_digest,
        };
        self.operations
            .get_mut(operation_id)
            .expect("operation exists while terminal receipt is stored")
            .terminal = Some(terminal);
        let stored = self
            .operations
            .get(operation_id)
            .expect("operation exists after terminal receipt is stored");
        Ok(operation_receipt(
            operation_id,
            stored,
            self.page_generation,
            self.document.as_ref(),
        ))
    }
}

fn operation_receipt(
    operation_id: &str,
    stored: &StoredOperation,
    current_page_generation: u64,
    current_document: Option<&DocumentIdentity>,
) -> Value {
    match &stored.terminal {
        Some(terminal) => json!({
            "terminalObserved": true,
            "status": terminal.status,
            "outcomeDigest": terminal.outcome_digest,
            "terminalReason": terminal.reason,
            "operationId": operation_id,
            "operationPayloadDigest": stored.payload_digest,
            "observedPageGeneration": terminal.observed_page_generation,
            "observedDocumentDigest": terminal.observed_document_digest,
        }),
        None => json!({
            "terminalObserved": false,
            "operationId": operation_id,
            "operationPayloadDigest": stored.payload_digest,
            "observedPageGeneration": current_page_generation,
            "observedDocumentDigest": current_document.map(|value| value.document_digest.clone()),
        }),
    }
}

fn non_negative_u64_field(value: &Value, name: &str) -> Result<u64, String> {
    value
        .get(name)
        .and_then(Value::as_u64)
        .filter(|number| *number <= MAX_SAFE_INTEGER)
        .ok_or_else(|| format!("{name} must be a non-negative safe integer"))
}

fn optional_string_field<'a>(value: &'a Value, name: &str) -> Result<Option<&'a str>, String> {
    match value.get(name) {
        Some(Value::Null) => Ok(None),
        Some(Value::String(text)) => Ok(Some(text)),
        _ => Err(format!("{name} must be a string or null")),
    }
}
'''
text = text[:start] + block + text[end:]
text = text.replace(
    """                if let Some(browser) = browser.as_mut() {
                    browser.pump();
                }
""",
    """                if let Some(browser) = browser.as_mut() {
                    browser.pump()?;
                }
""",
    1,
)
helper_start = text.index("\nfn stored_receipt(")
helper_end = text.index("\nfn json_string(", helper_start)
helpers = r'''
fn fixed_click(action: &Map<String, Value>, expected_url: &str) -> Result<String, String> {
    let selector = json_string(action, "selector")?;
    let expected_url = serde_json::to_string(expected_url).map_err(|error| error.to_string())?;
    Ok(format!(
        "(()=>{{if(location.href!=={expected_url})return false;const e=document.querySelector({selector});if(!e)return false;e.click();return true;}})()"
    ))
}

fn fixed_focus(action: &Map<String, Value>, expected_url: &str) -> Result<String, String> {
    let selector = json_string(action, "selector")?;
    let expected_url = serde_json::to_string(expected_url).map_err(|error| error.to_string())?;
    Ok(format!(
        "(()=>{{if(location.href!=={expected_url})return false;const e=document.querySelector({selector});if(!e)return false;e.focus();return true;}})()"
    ))
}

fn fixed_type(
    action: &Map<String, Value>,
    expected_url: &str,
) -> Result<String, String> {
    let selector = json_string(action, "selector")?;
    let text = json_string(action, "text")?;
    let expected_url = serde_json::to_string(expected_url).map_err(|error| error.to_string())?;
    Ok(format!(
        "(()=>{{if(location.href!=={expected_url})return false;const e=document.querySelector({selector});if(!e||!(\"value\" in e))return false;e.focus();e.value={text};e.dispatchEvent(new Event(\"input\",{{bubbles:true}}));e.dispatchEvent(new Event(\"change\",{{bubbles:true}}));return true;}})()"
    ))
}

fn fixed_scroll(action: &Map<String, Value>, expected_url: &str) -> Result<String, String> {
    let x = action
        .get("deltaX")
        .and_then(Value::as_i64)
        .ok_or_else(|| "scroll.deltaX must be an integer".to_string())?;
    let y = action
        .get("deltaY")
        .and_then(Value::as_i64)
        .ok_or_else(|| "scroll.deltaY must be an integer".to_string())?;
    let expected_url = serde_json::to_string(expected_url).map_err(|error| error.to_string())?;
    Ok(format!(
        "(()=>{{if(location.href!=={expected_url})return false;window.scrollBy({x},{y});return true;}})()"
    ))
}
'''
text = text[:helper_start] + helpers + text[helper_end:]
text += r'''

#[cfg(test)]
mod tests {
    use super::*;

    fn document(page_generation: u64, url: &str) -> DocumentIdentity {
        DocumentIdentity::from_url(page_generation, &Url::parse(url).unwrap()).unwrap()
    }

    #[test]
    fn navigation_terminality_binds_exact_target_generation_and_url() {
        assert_eq!(
            navigation_decision(2, Some("https://example.com/b"), true, 2, "https://example.com/b"),
            NavigationDecision::Succeeded,
        );
        assert_eq!(
            navigation_decision(1, Some("https://example.com/a"), true, 2, "https://example.com/b"),
            NavigationDecision::Indeterminate,
        );
        assert_eq!(
            navigation_decision(2, Some("https://example.com/b"), false, 2, "https://example.com/b"),
            NavigationDecision::Indeterminate,
        );
        assert_eq!(
            navigation_decision(2, Some("https://example.com/redirect"), true, 2, "https://example.com/b"),
            NavigationDecision::FailedTargetMismatch,
        );
    }

    #[test]
    fn newer_navigation_cannot_complete_an_older_operation() {
        assert_eq!(
            navigation_decision(3, Some("https://example.com/b"), false, 2, "https://example.com/a"),
            NavigationDecision::FailedSuperseded,
        );
        assert_eq!(
            navigation_decision(3, Some("https://example.com/b"), true, 2, "https://example.com/a"),
            NavigationDecision::FailedSuperseded,
        );
    }

    #[test]
    fn document_actions_require_the_exact_observed_document_identity() {
        let first = document(7, "https://example.com/a");
        let second = document(8, "https://example.com/b");
        assert!(source_document_matches(
            Some(&first),
            first.page_generation,
            Some(&first.document_digest),
        ));
        assert!(!source_document_matches(
            Some(&second),
            first.page_generation,
            Some(&first.document_digest),
        ));
        assert!(!source_document_matches(
            Some(&first),
            first.page_generation,
            Some(&second.document_digest),
        ));
    }

    #[test]
    fn fixed_action_templates_recheck_the_observed_url() {
        let mut click = Map::new();
        click.insert("selector".to_string(), Value::String("#submit".to_string()));
        let script = fixed_click(&click, "https://example.com/form").unwrap();
        assert!(script.contains("location.href!==\"https://example.com/form\""));
    }
}
'''
path.write_text(text, encoding="utf-8")
