use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::io::{self, Read, Write};
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, mpsc};
use std::thread;
use std::time::{Duration, Instant};

use dpi::PhysicalSize;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use servo::{
    EventLoopWaker, JSValue, LoadStatus, NavigationRequest, PermissionRequest, RenderingContext,
    Servo, ServoBuilder, SoftwareRenderingContext, WebView, WebViewBuilder, WebViewDelegate,
};
use sha2::{Digest, Sha256};
use url::Url;

const SCHEMA: &str = "hepta.browser.worker-frame.v1";
const PROTOCOL_VERSION: u32 = 1;
const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
const MIN_SEMANTIC_OBSERVATION_BYTES: usize = 512;
const MAX_SEMANTIC_OBSERVATION_BYTES: usize = 262_144;

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Frame {
    schema: String,
    protocol_version: u32,
    session_id: String,
    generation: u64,
    sequence: u64,
    kind: String,
    request_id: String,
    payload_digest: String,
    payload: Value,
}

#[derive(Debug)]
enum HostEvent {
    Wake,
    Command(Frame),
    Fatal(String),
    Eof,
}

#[derive(Clone)]
struct Waker(mpsc::Sender<HostEvent>);

impl EventLoopWaker for Waker {
    fn clone_box(&self) -> Box<dyn EventLoopWaker> {
        Box::new(self.clone())
    }

    fn wake(&self) {
        let _ = self.0.send(HostEvent::Wake);
    }
}

struct Delegate {
    frame_ready: Arc<AtomicBool>,
    navigation_epoch: Arc<AtomicU64>,
    allowed_origins: HashSet<String>,
}

impl WebViewDelegate for Delegate {
    fn notify_new_frame_ready(&self, _webview: WebView) {
        self.frame_ready.store(true, Ordering::Release);
    }

    fn request_navigation(&self, _webview: WebView, request: NavigationRequest) {
        let allowed = request.url.as_str() == "about:blank"
            || origin(&request.url).is_some_and(|value| self.allowed_origins.contains(&value));
        if allowed {
            self.navigation_epoch.fetch_add(1, Ordering::AcqRel);
            request.allow();
        } else {
            request.deny();
        }
    }

    fn request_permission(&self, _webview: WebView, request: PermissionRequest) {
        request.deny();
    }
}

#[derive(Clone)]
struct StoredOperation {
    payload_digest: String,
    terminal: Option<(String, String)>,
}

struct Browser {
    servo: Servo,
    context: Rc<SoftwareRenderingContext>,
    webview: WebView,
    frame_ready: Arc<AtomicBool>,
    navigation_epoch: Arc<AtomicU64>,
    observed_navigation_epoch: Option<u64>,
    last_document_digest: Option<String>,
    last_action_surface_digest: Option<String>,
    last_observation_budget: Option<usize>,
    allowed_origins: HashSet<String>,
    page_generation: u64,
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
        let navigation_epoch = Arc::new(AtomicU64::new(0));
        let delegate = Rc::new(Delegate {
            frame_ready: frame_ready.clone(),
            navigation_epoch: navigation_epoch.clone(),
            allowed_origins: allowed_origins.clone(),
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
            navigation_epoch,
            observed_navigation_epoch: None,
            last_document_digest: None,
            last_action_surface_digest: None,
            last_observation_budget: None,
            allowed_origins,
            page_generation: 0,
            operations: HashMap::new(),
        };
        browser.pump();
        Ok(browser)
    }

    fn pump(&mut self) {
        self.servo.spin_event_loop();
        if self.frame_ready.swap(false, Ordering::AcqRel) {
            self.webview.paint();
            self.context.present();
        }
    }

    fn current_url(&self) -> Result<Url, String> {
        self.webview
            .url()
            .ok_or_else(|| "WebView has no current URL".to_string())
    }

    fn observe(&mut self, observation_budget: usize) -> Result<Value, String> {
        self.pump();
        if self.page_generation == 0 {
            return Err("no authorized web document has been loaded".to_string());
        }
        if observation_budget < MIN_SEMANTIC_OBSERVATION_BYTES {
            return Err(format!(
                "observationBudget must be at least {MIN_SEMANTIC_OBSERVATION_BYTES} bytes for semantic observation"
            ));
        }
        let budget = observation_budget.min(MAX_SEMANTIC_OBSERVATION_BYTES);
        let url = self.current_url()?;
        let current_origin = origin(&url)
            .ok_or_else(|| "current document has no HTTP(S) origin".to_string())?;
        if !self.allowed_origins.contains(&current_origin) {
            return Err("current document origin is outside the admitted set".to_string());
        }
        let navigation_epoch_before = self.navigation_epoch.load(Ordering::Acquire);

        // Every admitted observation advances the host-visible generation.
        // Worker admission additionally revalidates the exact document,
        // navigation epoch and actionable surface before any later effect.
        self.page_generation = self
            .page_generation
            .checked_add(1)
            .ok_or_else(|| "page generation exhausted".to_string())?;

        let semantic_observation = self.evaluate_json(
            semantic_snapshot_script(budget),
            Duration::from_secs(5),
        )?;
        validate_safe_json(&semantic_observation, 0)?;
        let navigation_epoch_after = self.navigation_epoch.load(Ordering::Acquire);
        if navigation_epoch_after != navigation_epoch_before {
            return Err("document navigated during semantic observation".to_string());
        }
        let semantic_json = canonical_json(&semantic_observation);
        if semantic_json.as_bytes().len() > budget {
            return Err("semantic observation exceeded observationBudget".to_string());
        }
        let semantic_digest = sha256_hex(semantic_json.as_bytes());
        let document_digest = sha256_hex(
            format!(
                "{}\0{:?}\0{}\0{}",
                url,
                self.webview.load_status(),
                self.page_generation,
                semantic_digest
            )
            .as_bytes(),
        );
        self.observed_navigation_epoch = Some(navigation_epoch_after);
        self.last_document_digest = Some(document_digest.clone());
        self.last_action_surface_digest = Some(action_surface_digest(&semantic_observation)?);
        self.last_observation_budget = Some(budget);
        Ok(json!({
            "pageGeneration": self.page_generation,
            "documentDigest": document_digest,
            "semanticDigest": semantic_digest,
            "semanticObservation": semantic_observation,
            "origin": current_origin,
        }))
    }

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
            let observation = self.verify_action_surface()?;
            validate_action_target(action, &observation)?;
        }
        self.operations.insert(
            operation_id.to_string(),
            StoredOperation {
                payload_digest: frame.payload_digest.clone(),
                terminal: None,
            },
        );
        Ok(None)
    }

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
            "click" => fixed_click(action).and_then(|script| self.fixed_script(script, "click")),
            "type" => fixed_type(action).and_then(|script| self.fixed_script(script, "type")),
            "focus" => fixed_focus(action).and_then(|script| self.fixed_script(script, "focus")),
            "scroll" => fixed_scroll(action).and_then(|script| self.fixed_script(script, "scroll")),
            "wait" => self.wait(action),
            "credential" | "upload" | "download" => {
                Ok(failed(kind, "capability_not_connected"))
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

    fn verify_action_surface(&mut self) -> Result<Value, String> {
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
        let after = self.navigation_epoch.load(Ordering::Acquire);
        if after != expected_epoch {
            return Err("worker navigated during action-surface revalidation".to_string());
        }
        if action_surface_digest(&observation)? != expected {
            return Err("worker action surface drifted before dispatch".to_string());
        }
        Ok(observation)
    }

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
                        "observation": observation,
                    }),
                    Err(error) => json!({
                        "ok": false,
                        "requestKind": frame.kind,
                        "requestPayloadDigest": frame.payload_digest,
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

fn read_frames(sender: mpsc::Sender<HostEvent>) {
    let mut input = io::stdin().lock();
    let mut expected_sequence = 1_u64;
    loop {
        let mut prefix = [0_u8; 4];
        match input.read_exact(&mut prefix) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => {
                let _ = sender.send(HostEvent::Eof);
                return;
            }
            Err(error) => {
                let _ = sender.send(HostEvent::Fatal(format!("private channel read failed: {error}")));
                return;
            }
        }
        let length = u32::from_be_bytes(prefix) as usize;
        if length == 0 || length > MAX_FRAME_BYTES {
            let _ = sender.send(HostEvent::Fatal("private channel frame length invalid".to_string()));
            return;
        }
        let mut bytes = vec![0_u8; length];
        if let Err(error) = input.read_exact(&mut bytes) {
            let _ = sender.send(HostEvent::Fatal(format!("private channel frame truncated: {error}")));
            return;
        }
        let raw = match String::from_utf8(bytes) {
            Ok(value) => value,
            Err(_) => {
                let _ = sender.send(HostEvent::Fatal("private channel frame is not UTF-8".to_string()));
                return;
            }
        };
        let value: Value = match serde_json::from_str(&raw) {
            Ok(value) => value,
            Err(error) => {
                let _ = sender.send(HostEvent::Fatal(format!("private channel JSON invalid: {error}")));
                return;
            }
        };
        if let Err(error) = validate_safe_json(&value, 0) {
            let _ = sender.send(HostEvent::Fatal(error));
            return;
        }
        if canonical_json(&value) != raw {
            let _ = sender.send(HostEvent::Fatal("private channel JSON is not canonical".to_string()));
            return;
        }
        let frame: Frame = match serde_json::from_value(value) {
            Ok(frame) => frame,
            Err(error) => {
                let _ = sender.send(HostEvent::Fatal(format!("private channel frame schema invalid: {error}")));
                return;
            }
        };
        if let Err(error) = validate_frame(&frame, expected_sequence) {
            let _ = sender.send(HostEvent::Fatal(error));
            return;
        }
        expected_sequence += 1;
        if sender.send(HostEvent::Command(frame)).is_err() {
            return;
        }
    }
}

fn validate_frame(frame: &Frame, sequence: u64) -> Result<(), String> {
    if frame.schema != SCHEMA || frame.protocol_version != PROTOCOL_VERSION {
        return Err("private channel protocol is unsupported".to_string());
    }
    if frame.sequence != sequence || frame.sequence == 0 {
        return Err("private channel sequence is not monotonic".to_string());
    }
    if frame.generation == 0 || frame.generation > MAX_SAFE_INTEGER {
        return Err("private channel generation is invalid".to_string());
    }
    if !stable_id(&frame.session_id) || !stable_id(&frame.request_id) {
        return Err("private channel identity is invalid".to_string());
    }
    if !matches!(frame.kind.as_str(), "start" | "observe" | "dispatch" | "reconcile" | "stop") {
        return Err("private channel command kind is not registered".to_string());
    }
    if !is_digest(&frame.payload_digest)
        || sha256_hex(canonical_json(&frame.payload).as_bytes()) != frame.payload_digest
    {
        return Err("private channel payload digest mismatch".to_string());
    }
    Ok(())
}

fn write_worker_frame(
    output: &mut impl Write,
    request: &Frame,
    sequence: u64,
    kind: &str,
    payload: Value,
) -> Result<(), String> {
    if !matches!(kind, "dispatch_boundary" | "response") {
        return Err("worker attempted to emit an unregistered frame kind".to_string());
    }
    let frame = json!({
        "schema": SCHEMA,
        "protocolVersion": PROTOCOL_VERSION,
        "sessionId": request.session_id,
        "generation": request.generation,
        "sequence": sequence,
        "kind": kind,
        "requestId": request.request_id,
        "payloadDigest": sha256_hex(canonical_json(&payload).as_bytes()),
        "payload": payload,
    });
    let body = canonical_json(&frame);
    if body.len() > MAX_FRAME_BYTES {
        return Err("response frame exceeds byte limit".to_string());
    }
    output
        .write_all(&(body.len() as u32).to_be_bytes())
        .and_then(|_| output.write_all(body.as_bytes()))
        .and_then(|_| output.flush())
        .map_err(|error| format!("private channel response failed: {error}"))
}

fn write_response(
    output: &mut impl Write,
    request: &Frame,
    sequence: u64,
    payload: Value,
) -> Result<(), String> {
    write_worker_frame(output, request, sequence, "response", payload)
}

fn semantic_snapshot_script(budget: usize) -> String {
    let script = r#"(()=>{
const budget=__BUDGET__;
const enc=new TextEncoder();
const clean=(value,max)=>String(value??"").replace(/\s+/g," ").trim().slice(0,max);
const selectorFor=(el)=>{
  const parts=[];
  let node=el;
  for(let depth=0;node&&node.nodeType===1&&depth<64;depth+=1,node=node.parentElement){
    const tag=node.tagName.toLowerCase();
    let index=1;
    for(let sibling=node.previousElementSibling;sibling;sibling=sibling.previousElementSibling){
      if(sibling.tagName===node.tagName) index+=1;
    }
    parts.push(`${tag}:nth-of-type(${index})`);
  }
  const selector=parts.reverse().join(">");
  if(!selector||selector.length>2048) return "";
  try{return document.querySelector(selector)===el?selector:"";}catch{return "";}
};
const visible=(el)=>{
  if(!el||typeof el.getClientRects!=="function"||el.getClientRects().length===0) return false;
  const style=getComputedStyle(el);
  return style.display!=="none"&&style.visibility!=="hidden"&&style.visibility!=="collapse";
};
const links=[];
for(const a of Array.from(document.querySelectorAll("a[href]")).slice(0,128)){
  if(!visible(a)) continue;
  const selector=selectorFor(a);
  if(!selector) continue;
  try{
    const u=new URL(a.href,document.baseURI);
    if(u.protocol!=="http:"&&u.protocol!=="https:") continue;
    links.push({text:clean(a.innerText||a.textContent,512),href:u.href.slice(0,4096),selector});
  }catch{}
}
const controls=[];
const nodes=document.querySelectorAll("a[href],button,input:not([type=password]),textarea,select,[role=button],[tabindex]");
for(const el of Array.from(nodes).slice(0,256)){
  if(!visible(el)) continue;
  const selector=selectorFor(el);
  if(!selector) continue;
  const type=clean(el.getAttribute("type"),64).toLowerCase();
  if(type==="password") continue;
  controls.push({
    selector,
    tag:clean(el.tagName,32).toLowerCase(),
    role:clean(el.getAttribute("role"),64),
    type,
    name:clean(el.getAttribute("name"),128),
    ariaLabel:clean(el.getAttribute("aria-label"),512),
    placeholder:clean(el.getAttribute("placeholder"),512),
    disabled:Boolean(el.disabled),
    checked:Boolean(el.checked)
  });
}
const forms=[];
for(const form of Array.from(document.forms).slice(0,64)){
  if(!visible(form)) continue;
  const selector=selectorFor(form);
  if(!selector) continue;
  let action="";
  try{const u=new URL(form.action||document.URL,document.baseURI);if(u.protocol==="http:"||u.protocol==="https:") action=u.href.slice(0,4096);}catch{}
  forms.push({method:clean(form.method||"get",16).toLowerCase(),action,controlCount:Math.min(form.elements?.length||0,4096),selector});
}
const out={
  schema:"hepta.browser.semantic-observation.v1",
  title:clean(document.title,1024),
  visibleText:clean(document.body?.innerText||"",Math.min(65536,Math.max(0,Math.floor(budget/2)))),
  links,
  controls,
  forms,
  viewport:{width:Math.max(0,Math.floor(innerWidth||0)),height:Math.max(0,Math.floor(innerHeight||0))},
  truncated:false
};
const bytes=()=>enc.encode(JSON.stringify(out)).byteLength;
if(bytes()>budget){out.forms=[];out.truncated=true;}
if(bytes()>budget){out.links=out.links.slice(0,32);out.controls=out.controls.slice(0,64);out.truncated=true;}
while(bytes()>budget&&out.visibleText.length>0){out.visibleText=out.visibleText.slice(0,Math.floor(out.visibleText.length/2));out.truncated=true;}
if(bytes()>budget){out.links=[];out.controls=[];out.forms=[];out.title="";out.visibleText="";out.truncated=true;}
return JSON.stringify(out);
})()"#;
    script.replace("__BUDGET__", &budget.to_string())
}

fn parse_allowed_origins(payload: &Value) -> Result<HashSet<String>, String> {
    let values = payload
        .get("allowedOrigins")
        .and_then(Value::as_array)
        .ok_or_else(|| "start.allowedOrigins must be an array".to_string())?;
    if values.len() > 128 {
        return Err("start.allowedOrigins exceeds bound".to_string());
    }
    let mut allowed = HashSet::new();
    for value in values {
        let raw = value
            .as_str()
            .ok_or_else(|| "allowed origin must be a string".to_string())?;
        let url = Url::parse(raw).map_err(|error| format!("allowed origin invalid: {error}"))?;
        let normalized = origin(&url).ok_or_else(|| "allowed origin must use HTTP(S)".to_string())?;
        if raw.trim_end_matches('/') != normalized || !allowed.insert(normalized) {
            return Err("allowed origin is non-canonical or duplicated".to_string());
        }
    }
    Ok(allowed)
}

fn origin(url: &Url) -> Option<String> {
    matches!(url.scheme(), "http" | "https").then(|| url.origin().ascii_serialization())
}

fn stored_receipt(value: &StoredOperation) -> Value {
    match &value.terminal {
        Some((status, outcome)) => json!({
            "terminalObserved": true,
            "status": status,
            "outcomeDigest": outcome,
        }),
        None => json!({"terminalObserved": false}),
    }
}

fn succeeded(action: &str, digest: &str) -> Value {
    json!({
        "terminalObserved": true,
        "status": "succeeded",
        "outcomeDigest": digest,
        "action": action,
    })
}

fn failed(action: &str, reason: &str) -> Value {
    json!({
        "terminalObserved": true,
        "status": "failed",
        "outcomeDigest": sha256_hex(format!("failed\0{action}\0{reason}").as_bytes()),
        "action": action,
    })
}

fn fixed_click(action: &Map<String, Value>) -> Result<String, String> {
    let selector = json_string(action, "selector")?;
    Ok(format!("(()=>{{const e=document.querySelector({selector});if(!e||e.disabled===true||e.getClientRects().length===0)return false;const s=getComputedStyle(e);if(s.display===\"none\"||s.visibility===\"hidden\"||s.visibility===\"collapse\")return false;e.click();return true;}})()"))
}

fn fixed_focus(action: &Map<String, Value>) -> Result<String, String> {
    let selector = json_string(action, "selector")?;
    Ok(format!("(()=>{{const e=document.querySelector({selector});if(!e||e.disabled===true||e.getClientRects().length===0)return false;const s=getComputedStyle(e);if(s.display===\"none\"||s.visibility===\"hidden\"||s.visibility===\"collapse\")return false;e.focus();return true;}})()"))
}

fn fixed_type(action: &Map<String, Value>) -> Result<String, String> {
    let selector = json_string(action, "selector")?;
    let text = json_string(action, "text")?;
    Ok(format!("(()=>{{const e=document.querySelector({selector});if(!e||!(\"value\" in e)||e.disabled===true||String(e.type||\"\").toLowerCase()===\"password\"||e.getClientRects().length===0)return false;const s=getComputedStyle(e);if(s.display===\"none\"||s.visibility===\"hidden\"||s.visibility===\"collapse\")return false;e.focus();e.value={text};e.dispatchEvent(new Event(\"input\",{{bubbles:true}}));e.dispatchEvent(new Event(\"change\",{{bubbles:true}}));return true;}})()"))
}

fn fixed_scroll(action: &Map<String, Value>) -> Result<String, String> {
    let x = action
        .get("deltaX")
        .and_then(Value::as_i64)
        .ok_or_else(|| "scroll.deltaX must be an integer".to_string())?;
    let y = action
        .get("deltaY")
        .and_then(Value::as_i64)
        .ok_or_else(|| "scroll.deltaY must be an integer".to_string())?;
    Ok(format!("(()=>{{window.scrollBy({x},{y});return true;}})()"))
}

fn json_string(action: &Map<String, Value>, name: &str) -> Result<String, String> {
    let value = action
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("typedAction.{name} must be a string"))?;
    serde_json::to_string(value).map_err(|error| error.to_string())
}

fn string_field<'a>(value: &'a Value, name: &str) -> Result<&'a str, String> {
    value
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{name} must be a string"))
}

fn action_surface_digest(observation: &Value) -> Result<String, String> {
    let object = observation
        .as_object()
        .ok_or_else(|| "semantic observation must be an object".to_string())?;
    let links = object
        .get("links")
        .cloned()
        .ok_or_else(|| "semantic observation lacks links".to_string())?;
    let controls = object
        .get("controls")
        .cloned()
        .ok_or_else(|| "semantic observation lacks controls".to_string())?;
    let forms = object
        .get("forms")
        .cloned()
        .ok_or_else(|| "semantic observation lacks forms".to_string())?;
    let surface = json!({
        "links": links,
        "controls": controls,
        "forms": forms,
    });
    validate_safe_json(&surface, 0)?;
    Ok(sha256_hex(canonical_json(&surface).as_bytes()))
}

fn observed_control<'a>(
    observation: &'a Value,
    selector: &str,
) -> Result<Option<&'a Map<String, Value>>, String> {
    let controls = observation
        .get("controls")
        .and_then(Value::as_array)
        .ok_or_else(|| "semantic observation lacks controls".to_string())?;
    for value in controls {
        let control = value
            .as_object()
            .ok_or_else(|| "semantic observation control must be an object".to_string())?;
        if control.get("selector").and_then(Value::as_str) == Some(selector) {
            return Ok(Some(control));
        }
    }
    Ok(None)
}

fn validate_action_target(
    action: &Map<String, Value>,
    observation: &Value,
) -> Result<(), String> {
    let kind = action
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| "typedAction.kind must be a string".to_string())?;
    if !matches!(kind, "click" | "type" | "focus") {
        return Ok(());
    }
    let selector = action
        .get("selector")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{kind}.selector must be a string"))?;
    let control = observed_control(observation, selector)?
        .ok_or_else(|| "typed action selector is not in the admitted action surface".to_string())?;
    let disabled = control
        .get("disabled")
        .and_then(Value::as_bool)
        .ok_or_else(|| "semantic observation control.disabled must be boolean".to_string())?;
    if disabled {
        return Err("typed action selector is disabled in the admitted action surface".to_string());
    }
    if kind == "type" {
        let tag = control
            .get("tag")
            .and_then(Value::as_str)
            .ok_or_else(|| "semantic observation control.tag must be a string".to_string())?;
        let input_type = control
            .get("type")
            .and_then(Value::as_str)
            .ok_or_else(|| "semantic observation control.type must be a string".to_string())?;
        if !matches!(tag, "input" | "textarea") {
            return Err("type action target is not a text-entry control".to_string());
        }
        if input_type.eq_ignore_ascii_case("password") {
            return Err("generic type action cannot target a password control".to_string());
        }
    }
    Ok(())
}

fn validate_dispatch_snapshot_state(
    payload: &Value,
    action_kind: &str,
    worker_page_generation: u64,
    last_document_digest: Option<&str>,
    observed_navigation_epoch: Option<u64>,
    current_navigation_epoch: u64,
) -> Result<(), String> {
    let requested_page_generation = payload
        .get("pageGeneration")
        .and_then(Value::as_u64)
        .filter(|value| *value <= MAX_SAFE_INTEGER)
        .ok_or_else(|| "dispatch.pageGeneration must be a safe non-negative integer".to_string())?;
    let document = payload
        .get("documentDigest")
        .ok_or_else(|| "dispatch.documentDigest is missing".to_string())?;
    let bootstrap_navigation = action_kind == "navigate" && requested_page_generation == 0;
    if bootstrap_navigation {
        if worker_page_generation != 0 || !document.is_null() {
            return Err("bootstrap navigation snapshot is stale".to_string());
        }
        return Ok(());
    }
    if requested_page_generation == 0 || requested_page_generation != worker_page_generation {
        return Err("worker page generation drifted before dispatch".to_string());
    }
    let requested_document_digest = document
        .as_str()
        .filter(|value| is_digest(value))
        .ok_or_else(|| "dispatch.documentDigest must be a non-zero SHA-256 digest".to_string())?;
    if last_document_digest != Some(requested_document_digest) {
        return Err("worker document digest drifted before dispatch".to_string());
    }
    let observed_epoch = observed_navigation_epoch
        .ok_or_else(|| "worker has no admitted semantic observation for dispatch".to_string())?;
    if observed_epoch != current_navigation_epoch {
        return Err("worker navigation epoch drifted before dispatch".to_string());
    }
    Ok(())
}

fn validate_safe_json(value: &Value, depth: usize) -> Result<(), String> {
    if depth > 32 {
        return Err("private channel JSON nesting exceeds limit".to_string());
    }
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(()),
        Value::Number(number) => {
            if number
                .as_i64()
                .is_some_and(|value| value.unsigned_abs() <= MAX_SAFE_INTEGER)
                || number.as_u64().is_some_and(|value| value <= MAX_SAFE_INTEGER)
            {
                Ok(())
            } else {
                Err("private channel numbers must be safe integers".to_string())
            }
        }
        Value::Array(values) => values
            .iter()
            .try_for_each(|value| validate_safe_json(value, depth + 1)),
        Value::Object(object) => object
            .values()
            .try_for_each(|value| validate_safe_json(value, depth + 1)),
    }
}

fn canonical_json(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::String(value) => serde_json::to_string(value).expect("string serialization cannot fail"),
        Value::Array(values) => format!(
            "[{}]",
            values.iter().map(canonical_json).collect::<Vec<_>>().join(",")
        ),
        Value::Object(object) => {
            let mut keys: Vec<_> = object.keys().collect();
            keys.sort();
            let fields = keys
                .into_iter()
                .map(|key| format!("{}:{}", serde_json::to_string(key).unwrap(), canonical_json(&object[key])))
                .collect::<Vec<_>>()
                .join(",");
            format!("{{{fields}}}")
        }
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}

fn stable_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
}

fn is_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dispatch_snapshot_rejects_generation_document_and_navigation_drift() {
        let digest = "1".repeat(64);
        let payload = json!({
            "pageGeneration": 7,
            "documentDigest": digest,
        });
        assert!(
            validate_dispatch_snapshot_state(
                &payload,
                "click",
                7,
                Some(digest.as_str()),
                Some(11),
                11,
            )
            .is_ok()
        );
        assert!(
            validate_dispatch_snapshot_state(
                &payload,
                "click",
                8,
                Some(digest.as_str()),
                Some(11),
                11,
            )
            .unwrap_err()
            .contains("page generation")
        );
        assert!(
            validate_dispatch_snapshot_state(
                &payload,
                "click",
                7,
                Some(&"2".repeat(64)),
                Some(11),
                11,
            )
            .unwrap_err()
            .contains("document digest")
        );
        assert!(
            validate_dispatch_snapshot_state(
                &payload,
                "click",
                7,
                Some(digest.as_str()),
                Some(11),
                12,
            )
            .unwrap_err()
            .contains("navigation epoch")
        );
    }

    #[test]
    fn action_surface_digest_ignores_visible_text_but_tracks_actionable_drift() {
        let base = json!({
            "schema": "hepta.browser.semantic-observation.v1",
            "title": "Title A",
            "visibleText": "dynamic counter 1",
            "links": [{"text":"A","href":"https://example.com/a","selector":"a:nth-of-type(1)"}],
            "controls": [{"selector":"button:nth-of-type(1)","tag":"button","role":"","type":"","name":"","ariaLabel":"Go","placeholder":"","disabled":false,"checked":false}],
            "forms": [],
            "viewport": {"width":1280,"height":720},
            "truncated": false,
        });
        let text_changed = json!({
            "schema": "hepta.browser.semantic-observation.v1",
            "title": "Title B",
            "visibleText": "dynamic counter 2",
            "links": [{"text":"A","href":"https://example.com/a","selector":"a:nth-of-type(1)"}],
            "controls": [{"selector":"button:nth-of-type(1)","tag":"button","role":"","type":"","name":"","ariaLabel":"Go","placeholder":"","disabled":false,"checked":false}],
            "forms": [],
            "viewport": {"width":1280,"height":720},
            "truncated": false,
        });
        let control_changed = json!({
            "schema": "hepta.browser.semantic-observation.v1",
            "title": "Title B",
            "visibleText": "dynamic counter 2",
            "links": [{"text":"A","href":"https://example.com/a","selector":"a:nth-of-type(1)"}],
            "controls": [{"selector":"button:nth-of-type(1)","tag":"button","role":"","type":"","name":"","ariaLabel":"Go","placeholder":"","disabled":true,"checked":false}],
            "forms": [],
            "viewport": {"width":1280,"height":720},
            "truncated": false,
        });
        assert_eq!(
            action_surface_digest(&base).expect("base digest"),
            action_surface_digest(&text_changed).expect("text digest"),
        );
        assert_ne!(
            action_surface_digest(&base).expect("base digest"),
            action_surface_digest(&control_changed).expect("control digest"),
        );
    }

    #[test]
    fn page_local_action_selector_must_be_observed_and_sensitive_targets_fail_closed() {
        let observation = json!({
            "controls": [
                {"selector":"button:nth-of-type(1)","tag":"button","type":"","disabled":false},
                {"selector":"input:nth-of-type(1)","tag":"input","type":"text","disabled":false},
                {"selector":"input:nth-of-type(2)","tag":"input","type":"password","disabled":false},
                {"selector":"input:nth-of-type(3)","tag":"input","type":"text","disabled":true}
            ]
        });

        let click_value = json!({"kind":"click","selector":"button:nth-of-type(1)"});
        assert!(validate_action_target(
            click_value.as_object().expect("click object"),
            &observation,
        ).is_ok());

        let missing_value = json!({"kind":"click","selector":"#not-observed"});
        assert!(validate_action_target(
            missing_value.as_object().expect("missing object"),
            &observation,
        )
        .unwrap_err()
        .contains("not in the admitted action surface"));

        let password_value = json!({
            "kind":"type",
            "selector":"input:nth-of-type(2)",
            "text":"secret"
        });
        assert!(validate_action_target(
            password_value.as_object().expect("password object"),
            &observation,
        )
        .unwrap_err()
        .contains("password"));

        let disabled_value = json!({
            "kind":"type",
            "selector":"input:nth-of-type(3)",
            "text":"blocked"
        });
        assert!(validate_action_target(
            disabled_value.as_object().expect("disabled object"),
            &observation,
        )
        .unwrap_err()
        .contains("disabled"));
    }

    #[test]
    fn only_initial_navigation_may_dispatch_without_an_observation() {
        let payload = json!({
            "pageGeneration": 0,
            "documentDigest": null,
        });
        assert!(
            validate_dispatch_snapshot_state(&payload, "navigate", 0, None, None, 0)
                .is_ok()
        );
        assert!(
            validate_dispatch_snapshot_state(&payload, "click", 0, None, None, 0)
                .is_err()
        );
        assert!(
            validate_dispatch_snapshot_state(&payload, "navigate", 1, None, None, 1)
                .is_err()
        );
    }
}
