//! Hepta's secondary console, rendered by the same Makepad widget tree as Robrix.
//! Authentication and runtime observations belong to the headless native facade.
use makepad_widgets::*;

script_mod! {
    use mod.prelude.widgets.*
    use mod.widgets.*

    mod.widgets.HeptaConsole = #(HeptaConsole::register_widget(vm)) {
        width: Fill, height: Fill
        flow: Down
        padding: 24
        spacing: 16
        show_bg: true
        draw_bg.color: (COLOR_PRIMARY)
        scroll_bars: mod.widgets.ScrollBars {
            show_scroll_x: false, show_scroll_y: true
        }
        Label {
            text: "Console"
            draw_text +: {color: (COLOR_TEXT), text_style: theme.font_bold {font_size: 22}}
        }
        refresh := Button { text: "Refresh authenticated status" }
        status := Label {
            width: Fill, height: Fit
            text: "Console is not configured."
            draw_text +: {color: (COLOR_TEXT)}
        }
        detail := Label {
            width: Fill, height: Fit
            text: "Select an explicitly provisioned Hepta console configuration. Matrix login does not grant console authority."
            draw_text +: {color: (COLOR_TEXT)}
        }
    }
}

#[derive(Script, ScriptHook, Widget)]
pub struct HeptaConsole {
    #[deref]
    view: View,
}

impl Widget for HeptaConsole {
    fn handle_event(&mut self, cx: &mut Cx, event: &Event, scope: &mut Scope) {
        self.view.handle_event(cx, event, scope);
        if let Event::Actions(actions) = event {
            if self.view.button(cx, ids!(refresh)).clicked(actions) {
                request_refresh(cx);
            }
        }
    }

    fn draw_walk(&mut self, cx: &mut Cx2d, scope: &mut Scope, walk: Walk) -> DrawStep {
        let (status, detail, enabled) = {
            let host = cx.global::<ConsoleHost>();
            (host.status.clone(), host.detail.clone(), host.can_refresh())
        };
        self.view.label(cx, ids!(status)).set_text(cx, &status);
        self.view.label(cx, ids!(detail)).set_text(cx, &detail);
        self.view.button(cx, ids!(refresh)).set_enabled(cx, enabled);
        self.view.draw_walk(cx, scope, walk)
    }
}

/// One owner shared by the dock, compact page and pre-login setup screen.
pub struct ConsoleHost {
    status: String,
    detail: String,
    busy: bool,
    started: bool,
    closed: bool,
    epoch: u64,
    pub show_without_matrix: bool,
    #[cfg(not(target_arch = "wasm32"))]
    worker: Option<std::sync::mpsc::SyncSender<()>>,
}
impl Default for ConsoleHost {
    fn default() -> Self {
        Self {
            status: "Console is not configured.".into(),
            detail: "Use --console-config with an explicitly provisioned read-only console configuration. Matrix login grants no console authority. Platform operations and update activation are not available in this port yet.".into(),
            busy: false,
            started: false,
            closed: false,
            epoch: 0,
            show_without_matrix: false,
            #[cfg(not(target_arch = "wasm32"))]
            worker: None,
        }
    }
}
impl ConsoleHost {
    #[cfg(feature = "ui-fixture")]
    pub(crate) fn set_fixture_unconfigured(&mut self) {
        self.status = "UI fixture: Console is not configured".into();
        self.detail = "Account-free fixture of the actual Robrix/Makepad dock. No Matrix, Agentd, keyring or console connection was created.".into();
    }

    fn accept(&mut self, update: &ConsoleUpdate) -> bool {
        if !self.started || self.closed || update.epoch != self.epoch {
            return false;
        }
        self.status.clone_from(&update.status);
        self.detail.clone_from(&update.detail);
        self.busy = false;
        if update.terminal {
            #[cfg(not(target_arch = "wasm32"))]
            {
                self.worker = None;
            }
        }
        true
    }

    fn stop(&mut self) {
        self.closed = true;
        self.epoch = self.epoch.saturating_add(1);
        self.busy = false;
        #[cfg(not(target_arch = "wasm32"))]
        {
            self.worker = None;
        }
    }

    #[cfg(not(target_arch = "wasm32"))]
    fn begin_refresh(&mut self) {
        if !self.can_refresh() {
            return;
        }
        match self.worker.as_ref().unwrap().try_send(()) {
            Ok(()) => {
                self.busy = true;
                self.status = "Refreshing authenticated observation…".into();
            }
            Err(std::sync::mpsc::TrySendError::Full(_)) => {
                self.busy = true;
            }
            Err(std::sync::mpsc::TrySendError::Disconnected(_)) => {
                self.worker = None;
                self.status = "Console worker disconnected; no current status".into();
                self.detail =
                    "Restart Hepta to reconnect to the explicitly configured owner.".into();
            }
        }
    }

    fn can_refresh(&self) -> bool {
        #[cfg(not(target_arch = "wasm32"))]
        {
            !self.closed && !self.busy && self.worker.is_some()
        }
        #[cfg(target_arch = "wasm32")]
        {
            false
        }
    }
}

#[derive(Debug)]
struct ConsoleUpdate {
    epoch: u64,
    status: String,
    detail: String,
    terminal: bool,
}

pub fn observe(cx: &mut Cx, event: &Event) {
    if cx.global::<ConsoleHost>().closed {
        return;
    }
    if let Event::Actions(actions) = event {
        for action in actions {
            if let Some(update) = action.downcast_ref::<ConsoleUpdate>() {
                if cx.global::<ConsoleHost>().accept(update) {
                    cx.redraw_all();
                }
            }
        }
    }
}

fn request_refresh(cx: &mut Cx) {
    #[cfg(not(target_arch = "wasm32"))]
    cx.global::<ConsoleHost>().begin_refresh();
    cx.redraw_all();
}

/// Startup never constructs a console owner from Matrix credentials or defaults.
/// All filesystem, keyring and network operations stay on a bounded owner thread.
pub fn start_configured(cx: &mut Cx) {
    let host = cx.global::<ConsoleHost>();
    if host.started || host.closed {
        return;
    }
    host.started = true;
    host.epoch = host.epoch.saturating_add(1);
    #[cfg(not(target_arch = "wasm32"))]
    let epoch = host.epoch;
    #[cfg(not(target_arch = "wasm32"))]
    {
        let args: Vec<_> = std::env::args().skip(1).collect();
        let path = match config_path(&args) {
            Ok(Some(path)) => path,
            Ok(None) => return,
            Err(error) => {
                let host = cx.global::<ConsoleHost>();
                host.status = "Console configuration rejected".into();
                host.detail = error;
                return;
            }
        };
        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        let host = cx.global::<ConsoleHost>();
        host.worker = Some(sender);
        host.busy = true;
        host.status = "Verifying console configuration…".into();
        let spawn = std::thread::Builder::new().name("hepta-console-owner".into()).spawn(move || {
            use hepta_native::console::{ConsoleConfig, ConsoleRuntime};
            let mut exit = WorkerExit { epoch, reported: false };
            let result = ConsoleConfig::load(&path).map_err(|e| e.to_string())
                .and_then(|config| ConsoleRuntime::open(config).map_err(|e| e.to_string()));
            let mut runtime = match result {
                Ok(runtime) => runtime,
                Err(error) => {
                    exit.reported = true;
                    crate::ui_dispatch::post_action(ConsoleUpdate { epoch, status: "Console admission failed".into(), detail: format!("{error}\n\nRestart Hepta after correcting the provisioned configuration. Refresh does not reconnect."), terminal: true });
                    return;
                }
            };
            loop {
                match runtime.refresh() {
                    Ok(snapshot) => crate::ui_dispatch::post_action(ConsoleUpdate { epoch,
                        status: "Authenticated read-only runtime observation".into(),
                        detail: format!("Session: {} / {}\nObserved generation: {}\nView revision: {}\nDigest: {}\n\nPlatform operations and update activation remain unavailable in this port.", snapshot.session.session_id, snapshot.session.generation, snapshot.status.pointer("/state/runtime_snapshot_generation").and_then(serde_json::Value::as_u64).map(|generation| generation.to_string()).unwrap_or_else(|| "unavailable".into()), snapshot.presentation.revision, snapshot.presentation.digest),
                        terminal: false,
                    }),
                    Err(error) => crate::ui_dispatch::post_action(ConsoleUpdate { epoch, status: "Observation failed; no current status".into(), detail: error.to_string(), terminal: false }),
                }
                if receiver.recv().is_err() { break; }
            }
            exit.reported = true;
            if let Err(error) = runtime.close() {
                log!("Console owner could not close cleanly: {error}");
            }
        });
        if let Err(error) = spawn {
            let host = cx.global::<ConsoleHost>();
            host.worker = None;
            host.busy = false;
            host.status = "Console worker could not start".into();
            host.detail = error.to_string();
        }
    }
    #[cfg(target_arch = "wasm32")]
    {
        cx.global::<ConsoleHost>().detail = "Native signed-loopback console is unavailable in the browser. Browser console capability transport is not configured.".into();
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn config_path(args: &[String]) -> Result<Option<std::path::PathBuf>, String> {
    let mut selected = None;
    let mut args = args.iter();
    while let Some(arg) = args.next() {
        let value = if arg == "--console-config" {
            Some(
                args.next()
                    .ok_or("--console-config requires one absolute JSON path")?
                    .as_str(),
            )
        } else {
            arg.strip_prefix("--console-config=")
        };
        if let Some(value) = value {
            if selected.is_some() || !std::path::Path::new(value).is_absolute() {
                return Err("--console-config requires exactly one absolute JSON path".into());
            }
            selected = Some(std::path::PathBuf::from(value));
        }
    }
    Ok(selected)
}

#[cfg(all(test, not(target_arch = "wasm32")))]
mod tests {
    use super::{config_path, ConsoleHost, ConsoleUpdate};
    #[test]
    fn repeated_refresh_is_bounded_and_shutdown_fences_late_callbacks() {
        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        let mut host = ConsoleHost {
            worker: Some(sender),
            started: true,
            epoch: 1,
            ..Default::default()
        };
        host.begin_refresh();
        host.begin_refresh();
        assert_eq!(receiver.try_recv(), Ok(()));
        assert!(receiver.try_recv().is_err());
        let response = ConsoleUpdate {
            epoch: 1,
            status: "observed".into(),
            detail: "fixture".into(),
            terminal: false,
        };
        assert!(host.accept(&response));
        host.stop();
        let state = (host.status.clone(), host.detail.clone());
        assert!(!host.accept(&response));
        assert_eq!((host.status.clone(), host.detail.clone()), state);
        assert!(!host.can_refresh());
    }

    #[test]
    fn terminal_worker_exit_clears_busy_without_reusing_old_status() {
        let (sender, _receiver) = std::sync::mpsc::sync_channel(1);
        let mut host = ConsoleHost {
            worker: Some(sender),
            started: true,
            busy: true,
            epoch: 3,
            ..Default::default()
        };
        assert!(host.accept(&ConsoleUpdate {
            epoch: 3,
            status: "Worker stopped; no current status".into(),
            detail: "restart".into(),
            terminal: true
        }));
        assert!(!host.busy);
        assert!(host.worker.is_none());
        assert!(host.status.contains("no current status"));
        assert!(!host.accept(&ConsoleUpdate {
            epoch: 2,
            status: "stale success".into(),
            detail: String::new(),
            terminal: false
        }));
    }

    #[test]
    fn worker_disconnect_invalidates_old_observation() {
        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        let mut host = ConsoleHost {
            worker: Some(sender),
            started: true,
            epoch: 1,
            ..Default::default()
        };
        drop(receiver);
        host.begin_refresh();
        assert!(host.worker.is_none());
        assert!(host.status.contains("no current status"));
        assert!(!host.can_refresh());
    }

    #[test]
    fn console_selection_is_explicit_absolute_and_unique() {
        let args = |items: &[&str]| {
            items
                .iter()
                .map(|value| (*value).to_owned())
                .collect::<Vec<_>>()
        };
        assert_eq!(config_path(&[]).unwrap(), None);
        assert!(config_path(&args(&["--console-config"])).is_err());
        assert!(config_path(&args(&["--console-config", "relative.json"])).is_err());
        let path = std::env::temp_dir().join("hepta-console-fixture.json");
        let path = path.to_str().unwrap();
        assert_eq!(
            config_path(&args(&["--console-config", path])).unwrap(),
            Some(path.into())
        );
        assert!(config_path(&args(&["--console-config", path, "--console-config", path])).is_err());
    }
}

/// Stop accepting callbacks immediately and release the owner channel. Its
/// bounded in-flight read may finish, then the worker closes the admitted
/// session. Never block the Makepad event/render thread waiting for network I/O.
pub fn shutdown(cx: &mut Cx) {
    cx.global::<ConsoleHost>().stop();
}

#[cfg(not(target_arch = "wasm32"))]
struct WorkerExit {
    epoch: u64,
    reported: bool,
}
#[cfg(not(target_arch = "wasm32"))]
impl Drop for WorkerExit {
    fn drop(&mut self) {
        if !self.reported {
            crate::ui_dispatch::post_action(ConsoleUpdate {
                epoch: self.epoch,
                status: "Console worker stopped; no current status".into(),
                detail: "Restart Hepta to reconnect to the explicitly configured owner.".into(),
                terminal: true,
            });
        }
    }
}
