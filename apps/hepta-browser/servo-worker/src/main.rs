use std::cell::RefCell;
use std::collections::HashMap;
use std::collections::HashSet;
use std::io::Read;
use std::io::Write;
use std::io::{self};
use std::rc::Rc;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use dpi::PhysicalSize;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Map;
use serde_json::Value;
use serde_json::json;
use servo::EventLoopWaker;
use servo::JSValue;
use servo::LoadStatus;
use servo::NavigationRequest;
use servo::PermissionRequest;
use servo::RenderingContext;
use servo::Servo;
use servo::ServoBuilder;
use servo::SoftwareRenderingContext;
use servo::WebView;
use servo::WebViewBuilder;
use servo::WebViewDelegate;
use sha2::Digest;
use sha2::Sha256;
use url::Url;

mod document_authority;

use document_authority::DocumentAuthority;
use document_authority::LoadPhase;
use document_authority::NavigationAttempt;

const SCHEMA: &str = "hepta.browser.worker-frame.v1";
const PROTOCOL_VERSION: u32 = 1;
const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
const MAX_QUEUED_HOST_EVENTS: usize = 16;
const MAX_NAVIGATION_URL_BYTES: usize = 16_384;
// Identities are retained for the worker lifetime so an old operation can never
// become a new effect after eviction. A full worker rejects new identities.
const MAX_STORED_OPERATIONS: usize = 4096;

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
struct Waker(mpsc::SyncSender<HostEvent>);

impl EventLoopWaker for Waker {
    fn clone_box(&self) -> Box<dyn EventLoopWaker> {
        Box::new(self.clone())
    }

    fn wake(&self) {
        // A full private command queue already causes the outer loop to pump.
        // Never block a renderer wake on the queue it is responsible for draining.
        let _ = self.0.try_send(HostEvent::Wake);
    }
}

struct Delegate {
    frame_ready: Arc<AtomicBool>,
    allowed_origins: HashSet<String>,
    document_authority: Rc<RefCell<DocumentAuthority>>,
}

impl WebViewDelegate for Delegate {
    fn notify_new_frame_ready(&self, _webview: WebView) {
        self.frame_ready.store(true, Ordering::Release);
    }

    fn request_navigation(&self, _webview: WebView, request: NavigationRequest) {
        let allowed = request.url.as_str() == "about:blank"
            || origin(&request.url).is_some_and(|value| self.allowed_origins.contains(&value));
        if allowed
            && self
                .document_authority
                .borrow_mut()
                .navigation_requested(request.url.as_str())
                .is_ok()
        {
            request.allow();
        } else {
            request.deny();
        }
    }

    fn request_permission(&self, _webview: WebView, request: PermissionRequest) {
        request.deny();
    }

    fn notify_url_changed(&self, _webview: WebView, url: Url) {
        self.document_authority
            .borrow_mut()
            .url_changed(url.as_str());
    }

    fn notify_load_status_changed(&self, webview: WebView, status: LoadStatus) {
        let url = webview.url().map(|url| url.to_string()).unwrap_or_default();
        self.document_authority
            .borrow_mut()
            .load_changed(load_phase(status), &url);
    }
}

#[derive(Clone)]
struct StoredOperation {
    payload_digest: String,
    terminal: Option<(String, String)>,
    navigation: Option<NavigationAttempt>,
}

enum PreparedEffect {
    Navigate(Url),
    Script(String),
    Wait(Duration),
    Failed(&'static str),
}

struct Browser {
    servo: Servo,
    context: Rc<SoftwareRenderingContext>,
    webview: WebView,
    frame_ready: Arc<AtomicBool>,
    allowed_origins: HashSet<String>,
    document_authority: Rc<RefCell<DocumentAuthority>>,
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
        let document_authority = Rc::new(RefCell::new(DocumentAuthority::default()));
        let delegate = Rc::new(Delegate {
            frame_ready: frame_ready.clone(),
            allowed_origins: allowed_origins.clone(),
            document_authority: document_authority.clone(),
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
            document_authority,
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

    fn observe(&mut self) -> Result<Value, String> {
        self.pump();
        if self.webview.load_status() != LoadStatus::Complete {
            return Err("current document has not completed loading".to_string());
        }
        let url = self.current_url()?;
        if url.as_str().len() > MAX_NAVIGATION_URL_BYTES {
            return Err("current document URL exceeds byte limit".to_string());
        }
        let current_origin =
            origin(&url).ok_or_else(|| "current document has no HTTP(S) origin".to_string())?;
        if !self.allowed_origins.contains(&current_origin) {
            return Err("current document origin is not allowed".to_string());
        }
        let observation = self.document_authority.borrow_mut().observe(
            url.as_str(),
            &current_origin,
            |page_generation, navigation_epoch| {
                sha256_hex(format!("{url}\0{navigation_epoch}\0{page_generation}").as_bytes())
            },
        )?;
        Ok(json!({
            "pageGeneration": observation.page_generation,
            "documentDigest": observation.document_digest,
            "origin": observation.origin,
        }))
    }

    fn dispatch(&mut self, frame: &Frame) -> Result<Value, String> {
        let operation_id = string_field(&frame.payload, "operationId")?;
        if !stable_id(operation_id) {
            return Err("worker operation identity is invalid".to_string());
        }
        if let Some(prior) = self.operations.get(operation_id) {
            if prior.payload_digest != frame.payload_digest {
                return Err("operation identity was reused with changed worker payload".to_string());
            }
            return Ok(stored_receipt(prior));
        }
        if self.operations.len() >= MAX_STORED_OPERATIONS {
            return Err("worker operation identity capacity exhausted".to_string());
        }
        let action = frame
            .payload
            .get("typedAction")
            .and_then(Value::as_object)
            .ok_or_else(|| "typedAction must be an object".to_string())?;
        let kind = action
            .get("kind")
            .and_then(Value::as_str)
            .ok_or_else(|| "typedAction.kind must be a string".to_string())?;
        let effect = match kind {
            "navigate" => {
                let target = action
                    .get("url")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "navigate.url must be a string".to_string())?;
                if target.len() > MAX_NAVIGATION_URL_BYTES {
                    return Err("navigate URL exceeds byte limit".to_string());
                }
                let target =
                    Url::parse(target).map_err(|error| format!("navigate URL invalid: {error}"))?;
                if target.as_str().len() > MAX_NAVIGATION_URL_BYTES {
                    return Err("canonical navigate URL exceeds byte limit".to_string());
                }
                PreparedEffect::Navigate(target)
            }
            "click" => PreparedEffect::Script(fixed_click(action)?),
            "type" => PreparedEffect::Script(fixed_type(action)?),
            "focus" => PreparedEffect::Script(fixed_focus(action)?),
            "scroll" => PreparedEffect::Script(fixed_scroll(action)?),
            "wait" => {
                if action.get("condition").and_then(Value::as_str) != Some("load-complete") {
                    PreparedEffect::Failed("condition_not_registered")
                } else {
                    let timeout_ms = action
                        .get("timeoutMs")
                        .and_then(Value::as_u64)
                        .filter(|timeout| (1..=120_000).contains(timeout))
                        .ok_or_else(|| "wait.timeoutMs must be between 1 and 120000".to_string())?;
                    PreparedEffect::Wait(Duration::from_millis(timeout_ms))
                }
            }
            "credential" | "upload" | "download" => {
                PreparedEffect::Failed("capability_not_connected")
            }
            _ => return Err("typedAction.kind is not registered by worker".to_string()),
        };
        self.pump();
        let current_url = self.current_url()?;
        if current_url.as_str().len() > MAX_NAVIGATION_URL_BYTES {
            return Err("current document URL exceeds byte limit".to_string());
        }
        let page_generation = frame
            .payload
            .get("pageGeneration")
            .and_then(Value::as_u64)
            .filter(|generation| *generation <= MAX_SAFE_INTEGER)
            .ok_or_else(|| "pageGeneration must be a safe nonnegative integer".to_string())?;
        let destination_origin = string_field(&frame.payload, "destinationOrigin")?;
        let expected_origin = match &effect {
            PreparedEffect::Navigate(target) => origin(target),
            PreparedEffect::Script(_) | PreparedEffect::Wait(_) | PreparedEffect::Failed(_) => {
                origin(&current_url)
            }
        }
        .ok_or_else(|| "effect destination must have an HTTP(S) origin".to_string())?;
        if destination_origin != expected_origin
            || !self.allowed_origins.contains(destination_origin)
        {
            return Err(
                "effect destination does not match its allowed document origin".to_string(),
            );
        }
        let bootstrap = matches!(&effect, PreparedEffect::Navigate(_))
            && page_generation == 0
            && frame
                .payload
                .get("documentDigest")
                .is_some_and(Value::is_null)
            && self
                .document_authority
                .borrow()
                .bootstrap_allowed(current_url.as_str());
        if !bootstrap {
            if self.webview.load_status() != LoadStatus::Complete {
                return Err("current document is not settled for this effect".to_string());
            }
            self.document_authority.borrow().validate_observation(
                page_generation,
                string_field(&frame.payload, "documentDigest")?,
                current_url.as_str(),
            )?;
        }
        let deadline_ms = frame
            .payload
            .get("deadlineMs")
            .and_then(Value::as_u64)
            .filter(|deadline| *deadline <= MAX_SAFE_INTEGER)
            .ok_or_else(|| "deadlineMs must be a safe positive integer".to_string())?;
        remaining_deadline(deadline_ms)?;
        let navigation = if let PreparedEffect::Navigate(target) = &effect {
            Some(
                self.document_authority
                    .borrow_mut()
                    .begin_navigation(target.as_str(), current_url.as_str())?,
            )
        } else {
            None
        };
        self.document_authority.borrow_mut().consume_observation();
        // Reserve before executing: a lost script callback or navigation error
        // must remain indeterminate and must never redispatch the same effect.
        self.operations.insert(
            operation_id.to_string(),
            StoredOperation {
                payload_digest: frame.payload_digest.clone(),
                terminal: None,
                navigation: navigation.clone(),
            },
        );
        let document_epoch = self.document_authority.borrow().navigation_epoch;
        let receipt = match effect {
            PreparedEffect::Navigate(target) => self.navigate(
                target,
                navigation.as_ref().expect("navigation was reserved"),
                deadline_ms,
            )?,
            PreparedEffect::Script(script) => {
                let authorized_url = serde_json::to_string(current_url.as_str())
                    .expect("URL string serialization cannot fail");
                let script = format!(
                    "(()=>{{if(location.href!=={authorized_url})return false;return {script};}})()"
                );
                self.fixed_script(script, kind, document_epoch, deadline_ms)?
            }
            PreparedEffect::Wait(timeout) => self.wait(timeout, document_epoch, deadline_ms)?,
            PreparedEffect::Failed(reason) => failed(kind, reason),
        };
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
        self.operations
            .get_mut(operation_id)
            .expect("operation was reserved")
            .terminal = terminal;
        Ok(receipt)
    }

    fn navigate(
        &mut self,
        url: Url,
        attempt: &NavigationAttempt,
        deadline_ms: u64,
    ) -> Result<Value, String> {
        remaining_deadline(deadline_ms)?;
        self.webview.load(url);
        self.pump();
        let current_url = self
            .webview
            .url()
            .map(|url| url.to_string())
            .unwrap_or_default();
        if self.document_authority.borrow().navigation_complete(
            attempt,
            &current_url,
            load_phase(self.webview.load_status()),
        ) {
            Ok(succeeded("navigate", &self.outcome_digest("navigate")))
        } else {
            Ok(json!({"terminalObserved": false}))
        }
    }

    fn fixed_script(
        &mut self,
        script: String,
        action: &str,
        document_epoch: u64,
        deadline_ms: u64,
    ) -> Result<Value, String> {
        let timeout = Duration::from_secs(5).min(remaining_deadline(deadline_ms)?);
        let actionable = self.evaluate_bool(script, timeout)?;
        if self.document_authority.borrow().navigation_epoch != document_epoch {
            return Ok(json!({"terminalObserved": false}));
        }
        if actionable {
            Ok(succeeded(action, &self.outcome_digest(action)))
        } else {
            Ok(failed(action, "target_not_found_or_not_actionable"))
        }
    }

    fn wait(
        &mut self,
        timeout: Duration,
        document_epoch: u64,
        deadline_ms: u64,
    ) -> Result<Value, String> {
        let timeout = timeout.min(remaining_deadline(deadline_ms)?);
        let deadline = Instant::now() + timeout;
        loop {
            self.pump();
            if self.document_authority.borrow().navigation_epoch != document_epoch {
                return Ok(json!({"terminalObserved": false}));
            }
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
        let current_url = self
            .webview
            .url()
            .map(|url| url.to_string())
            .unwrap_or_default();
        if prior.navigation.as_ref().is_some_and(|attempt| {
            self.document_authority.borrow().navigation_complete(
                attempt,
                &current_url,
                load_phase(self.webview.load_status()),
            )
        }) {
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
                self.document_authority.borrow().navigation_epoch
            )
            .as_bytes(),
        )
    }
}

fn load_phase(status: LoadStatus) -> LoadPhase {
    match status {
        LoadStatus::Started => LoadPhase::Started,
        LoadStatus::HeadParsed => LoadPhase::InProgress,
        LoadStatus::Complete => LoadPhase::Complete,
    }
}

fn remaining_deadline(deadline_ms: u64) -> Result<Duration, String> {
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("worker clock is before Unix epoch: {error}"))?
        .as_millis();
    if now_ms >= u128::from(deadline_ms) {
        return Err("worker effect deadline has expired".to_string());
    }
    Ok(Duration::from_millis(deadline_ms - now_ms as u64))
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
    let (sender, receiver) = mpsc::sync_channel(MAX_QUEUED_HOST_EVENTS);
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
                if session
                    .as_deref()
                    .is_some_and(|value| value != frame.session_id)
                {
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
                    "observe" => browser
                        .as_mut()
                        .ok_or_else(|| "worker is not started".to_string())?
                        .observe(),
                    "dispatch" => browser
                        .as_mut()
                        .ok_or_else(|| "worker is not started".to_string())?
                        .dispatch(&frame),
                    "reconcile" => browser
                        .as_mut()
                        .ok_or_else(|| "worker is not started".to_string())?
                        .reconcile(&frame),
                    "stop" => Ok(json!({"stopped": true})),
                    _ => Err("host sent a non-command frame".to_string()),
                };
                let payload = match result {
                    Ok(observation) => json!({"ok": true, "observation": observation}),
                    Err(error) => json!({"ok": false, "error": error}),
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

fn read_frames(sender: mpsc::SyncSender<HostEvent>) {
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
                let _ = sender.send(HostEvent::Fatal(format!(
                    "private channel read failed: {error}"
                )));
                return;
            }
        }
        let length = u32::from_be_bytes(prefix) as usize;
        if length == 0 || length > MAX_FRAME_BYTES {
            let _ = sender.send(HostEvent::Fatal(
                "private channel frame length invalid".to_string(),
            ));
            return;
        }
        let mut bytes = vec![0_u8; length];
        if let Err(error) = input.read_exact(&mut bytes) {
            let _ = sender.send(HostEvent::Fatal(format!(
                "private channel frame truncated: {error}"
            )));
            return;
        }
        let raw = match String::from_utf8(bytes) {
            Ok(value) => value,
            Err(_) => {
                let _ = sender.send(HostEvent::Fatal(
                    "private channel frame is not UTF-8".to_string(),
                ));
                return;
            }
        };
        let value: Value = match serde_json::from_str(&raw) {
            Ok(value) => value,
            Err(error) => {
                let _ = sender.send(HostEvent::Fatal(format!(
                    "private channel JSON invalid: {error}"
                )));
                return;
            }
        };
        if let Err(error) = validate_safe_json(&value, 0) {
            let _ = sender.send(HostEvent::Fatal(error));
            return;
        }
        if canonical_json(&value) != raw {
            let _ = sender.send(HostEvent::Fatal(
                "private channel JSON is not canonical".to_string(),
            ));
            return;
        }
        let frame: Frame = match serde_json::from_value(value) {
            Ok(frame) => frame,
            Err(error) => {
                let _ = sender.send(HostEvent::Fatal(format!(
                    "private channel frame schema invalid: {error}"
                )));
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
    if !matches!(
        frame.kind.as_str(),
        "start" | "observe" | "dispatch" | "reconcile" | "stop"
    ) {
        return Err("private channel command kind is not registered".to_string());
    }
    if !is_digest(&frame.payload_digest)
        || sha256_hex(canonical_json(&frame.payload).as_bytes()) != frame.payload_digest
    {
        return Err("private channel payload digest mismatch".to_string());
    }
    Ok(())
}

fn write_response(
    output: &mut impl Write,
    request: &Frame,
    sequence: u64,
    payload: Value,
) -> Result<(), String> {
    let frame = json!({
        "schema": SCHEMA,
        "protocolVersion": PROTOCOL_VERSION,
        "sessionId": request.session_id,
        "generation": request.generation,
        "sequence": sequence,
        "kind": "response",
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
        let normalized =
            origin(&url).ok_or_else(|| "allowed origin must use HTTP(S)".to_string())?;
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
    Ok(format!(
        "(()=>{{const e=document.querySelector({selector});if(!e)return false;e.click();return true;}})()"
    ))
}

fn fixed_focus(action: &Map<String, Value>) -> Result<String, String> {
    let selector = json_string(action, "selector")?;
    Ok(format!(
        "(()=>{{const e=document.querySelector({selector});if(!e)return false;e.focus();return true;}})()"
    ))
}

fn fixed_type(action: &Map<String, Value>) -> Result<String, String> {
    let selector = json_string(action, "selector")?;
    let text = json_string(action, "text")?;
    Ok(format!(
        "(()=>{{const e=document.querySelector({selector});if(!e||!(\"value\" in e))return false;e.focus();e.value={text};e.dispatchEvent(new Event(\"input\",{{bubbles:true}}));e.dispatchEvent(new Event(\"change\",{{bubbles:true}}));return true;}})()"
    ))
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
                || number
                    .as_u64()
                    .is_some_and(|value| value <= MAX_SAFE_INTEGER)
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
        Value::String(value) => {
            serde_json::to_string(value).expect("string serialization cannot fail")
        }
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(canonical_json)
                .collect::<Vec<_>>()
                .join(",")
        ),
        Value::Object(object) => {
            let mut keys: Vec<_> = object.keys().collect();
            keys.sort();
            let fields = keys
                .into_iter()
                .map(|key| {
                    format!(
                        "{}:{}",
                        serde_json::to_string(key).unwrap(),
                        canonical_json(&object[key])
                    )
                })
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
