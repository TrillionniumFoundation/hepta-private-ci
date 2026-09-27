use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
#[cfg(unix)]
use std::fs::File;
use std::io::{self, Read, Write};
#[cfg(unix)]
use std::net::{TcpListener, TcpStream};
#[cfg(unix)]
use std::os::unix::net::UnixStream;
#[cfg(unix)]
use std::path::Path;
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, mpsc};
use std::thread;
use std::time::{Duration, Instant};

use dpi::PhysicalSize;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use servo::{
    EventLoopWaker, JSValue, LoadStatus, NavigationRequest, PermissionRequest, Preferences,
    RenderingContext, Servo, ServoBuilder, SoftwareRenderingContext, UserContentManager,
    UserScript, WebView, WebViewBuilder, WebViewDelegate,
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
    effect_navigation_origin: Arc<Mutex<Option<String>>>,
}

impl WebViewDelegate for Delegate {
    fn notify_new_frame_ready(&self, _webview: WebView) {
        self.frame_ready.store(true, Ordering::Release);
    }

    fn request_navigation(&self, _webview: WebView, request: NavigationRequest) {
        let effect_origin = self
            .effect_navigation_origin
            .lock()
            .ok()
            .and_then(|value| value.clone());
        let allowed = navigation_request_allowed(
            &request.url,
            &self.allowed_origins,
            effect_origin.as_deref(),
        );
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

fn navigation_request_allowed(
    url: &Url,
    allowed_origins: &HashSet<String>,
    effect_origin: Option<&str>,
) -> bool {
    if url.as_str() == "about:blank" {
        return true;
    }
    origin(url).is_some_and(|value| {
        allowed_origins.contains(&value) && effect_origin == Some(value.as_str())
    })
}

#[derive(Clone)]
struct StoredOperation {
    payload_digest: String,
    terminal: Option<(String, String)>,
}

const EGRESS_SOCKET_PATH: &str = "/hepta-profile/.hepta-egress.sock";

#[cfg(unix)]
fn start_egress_relay() -> Result<Option<String>, String> {
    if !Path::new(EGRESS_SOCKET_PATH).exists() {
        return Ok(None);
    }
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("egress relay loopback bind failed: {error}"))?;
    let address = listener
        .local_addr()
        .map_err(|error| format!("egress relay address failed: {error}"))?;
    thread::Builder::new()
        .name("hepta-browser-egress-relay".to_string())
        .spawn(move || {
            for incoming in listener.incoming() {
                let Ok(stream) = incoming else {
                    break;
                };
                let _ = thread::Builder::new()
                    .name("hepta-browser-egress-stream".to_string())
                    .spawn(move || {
                        let _ = relay_egress_stream(stream);
                    });
            }
        })
        .map_err(|error| format!("egress relay thread failed: {error}"))?;
    Ok(Some(format!("http://127.0.0.1:{}", address.port())))
}

#[cfg(unix)]
fn relay_egress_stream(mut browser: TcpStream) -> Result<(), String> {
    let mut broker = UnixStream::connect(EGRESS_SOCKET_PATH)
        .map_err(|error| format!("egress broker connect failed: {error}"))?;
    let mut browser_read = browser
        .try_clone()
        .map_err(|error| format!("egress browser stream clone failed: {error}"))?;
    let mut broker_write = broker
        .try_clone()
        .map_err(|error| format!("egress broker stream clone failed: {error}"))?;
    let request = thread::spawn(move || io::copy(&mut browser_read, &mut broker_write));
    io::copy(&mut broker, &mut browser)
        .map_err(|error| format!("egress broker response relay failed: {error}"))?;
    request
        .join()
        .map_err(|_| "egress request relay thread panicked".to_string())?
        .map_err(|error| format!("egress browser request relay failed: {error}"))?;
    Ok(())
}

#[cfg(not(unix))]
fn start_egress_relay() -> Result<Option<String>, String> {
    Ok(None)
}

struct Browser {
    servo: Servo,
    context: Rc<SoftwareRenderingContext>,
    webview: WebView,
    frame_ready: Arc<AtomicBool>,
    navigation_epoch: Arc<AtomicU64>,
    effect_navigation_origin: Arc<Mutex<Option<String>>>,
    observed_navigation_epoch: Option<u64>,
    last_document_digest: Option<String>,
    last_action_surface_digest: Option<String>,
    last_observation_budget: Option<usize>,
    last_action_handles: HashMap<String, String>,
    prepared_action_handles: HashMap<String, String>,
    bridge_name: String,
    bridge_secret: String,
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
        let mut preferences = Preferences::default();
        if let Some(proxy_uri) = start_egress_relay()? {
            preferences.network_http_proxy_uri = proxy_uri.clone();
            preferences.network_https_proxy_uri = proxy_uri;
            preferences.network_http_no_proxy = String::new();
        }
        let servo = ServoBuilder::default()
            .preferences(preferences)
            .event_loop_waker(Box::new(waker))
            .build();
        servo.setup_logging();
        let bridge_name = format!("__hepta_browser_bridge_{}", secure_random_hex(16)?);
        let bridge_secret = secure_random_hex(32)?;
        let bridge_token_prefix = secure_random_hex(16)?;
        let user_content_manager = Rc::new(UserContentManager::new(&servo));
        user_content_manager.add_script(Rc::new(UserScript::from(
            private_action_bridge_script(
                &bridge_name,
                &bridge_secret,
                &bridge_token_prefix,
            ),
        )));
        let frame_ready = Arc::new(AtomicBool::new(false));
        let navigation_epoch = Arc::new(AtomicU64::new(0));
        let effect_navigation_origin = Arc::new(Mutex::new(None));
        let delegate = Rc::new(Delegate {
            frame_ready: frame_ready.clone(),
            navigation_epoch: navigation_epoch.clone(),
            allowed_origins: allowed_origins.clone(),
            effect_navigation_origin: effect_navigation_origin.clone(),
        });
        let webview = WebViewBuilder::new(&servo, context.clone())
            .url(Url::parse("about:blank").expect("literal about:blank is valid"))
            .delegate(delegate)
            .user_content_manager(user_content_manager)
            .build();
        let mut browser = Self {
            servo,
            context,
            webview,
            frame_ready,
            navigation_epoch,
            effect_navigation_origin,
            observed_navigation_epoch: None,
            last_document_digest: None,
            last_action_surface_digest: None,
            last_observation_budget: None,
            last_action_handles: HashMap::new(),
            prepared_action_handles: HashMap::new(),
            bridge_name,
            bridge_secret,
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

        // The private node handle must be stable across the authoritative
        // observation itself. A preliminary snapshot discovers the bounded
        // selectors, then the bridge binds engine-private node identities.
        // We take the returned observation only after those handles exist and
        // require the same actionable surface and exact node identities after
        // the authoritative snapshot.
        let preliminary_observation = self.evaluate_json(
            semantic_snapshot_script(budget),
            Duration::from_secs(5),
        )?;
        validate_safe_json(&preliminary_observation, 0)?;
        let preliminary_surface_digest =
            action_surface_digest(&preliminary_observation)?;
        let preliminary_handles =
            self.bind_action_handles(&preliminary_observation)?;
        if self.navigation_epoch.load(Ordering::Acquire)
            != navigation_epoch_before
        {
            return Err(
                "document navigated while preparing private action handles"
                    .to_string(),
            );
        }

        let semantic_observation = self.evaluate_json(
            semantic_snapshot_script(budget),
            Duration::from_secs(5),
        )?;
        validate_safe_json(&semantic_observation, 0)?;
        let navigation_epoch_after =
            self.navigation_epoch.load(Ordering::Acquire);
        if navigation_epoch_after != navigation_epoch_before {
            return Err("document navigated during semantic observation".to_string());
        }
        let semantic_json = canonical_json(&semantic_observation);
        if semantic_json.as_bytes().len() > budget {
            return Err("semantic observation exceeded observationBudget".to_string());
        }
        if action_surface_digest(&semantic_observation)?
            != preliminary_surface_digest
        {
            return Err(
                "worker action surface drifted during semantic observation"
                    .to_string(),
            );
        }
        let action_handles = self.bind_action_handles(&semantic_observation)?;
        let navigation_epoch_bound =
            self.navigation_epoch.load(Ordering::Acquire);
        if navigation_epoch_bound != navigation_epoch_before {
            return Err("document navigated while binding private action handles".to_string());
        }
        if action_handles != preliminary_handles {
            return Err(
                "worker action target identity drifted during semantic observation"
                    .to_string(),
            );
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
        self.last_action_handles = action_handles;
        Ok(json!({
            "pageGeneration": self.page_generation,
            "documentDigest": document_digest,
            "semanticDigest": semantic_digest,
            "semanticObservation": semantic_observation,
            "origin": current_origin,
        }))
    }

}
