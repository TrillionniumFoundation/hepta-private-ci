//! Linux development composition of the retained native owner into Robrix.
//! The adapter grants no chat writer capability and creates no second runtime.

use super::*;
use hepta_robrix_ui::native_host::NativeHost;
use hepta_robrix_ui::native_host::NativeHostPhase;
use hepta_robrix_ui::native_host::NativeHostView;
use hepta_robrix_ui::native_host::NativeRendererObservation;
use hepta_robrix_ui::native_host::NativeViewIdentity;

struct RobrixHost {
    app: HeptaNativeApp,
}

fn observation(value: serde_json::Value) {
    if std::env::var("HEPTA_NATIVE_PREVIEW_OBSERVE").as_deref() == Ok("1") {
        eprintln!("HEPTA_NATIVE_PREVIEW {value}");
    }
}

fn observation_identity(identity: NativeViewIdentity) -> serde_json::Value {
    serde_json::json!({
        "sessionId": identity.session_id, "sessionGeneration": identity.session_generation,
        "generation": identity.generation, "revision": identity.revision,
        "digest": identity.digest, "modules": identity.modules,
    })
}

fn identity(view: &RuntimeView) -> NativeViewIdentity {
    NativeViewIdentity {
        session_id: view.session_id.clone(),
        session_generation: view.session_generation,
        generation: view.generation,
        revision: view.revision,
        digest: view.digest.clone(),
        modules: view.modules.clone(),
    }
}

impl NativeHost for RobrixHost {
    fn set_waker(&mut self, wake: Arc<dyn Fn() + Send + Sync>) {
        let failed = self
            .app
            .repaint
            .lock()
            .map(|mut state| state.signal = Some(wake))
            .is_err();
        if failed {
            self.app
                .fail_readiness("native renderer wake is poisoned".into());
        }
    }

    fn poll(&mut self) -> NativeHostView {
        self.app.poll_tasks();
        if self.app.shutdown.requested() {
            if self.app.shutdown.runtime_closed && self.app.all_tasks_idle() {
                return NativeHostView {
                    status: "Runtime close confirmed".into(),
                    phase: NativeHostPhase::Closed,
                    ..NativeHostView::default()
                };
            }
            self.app.advance_shutdown_owner();
            return NativeHostView {
                status: self.app.shutdown.failure.clone().unwrap_or_else(|| {
                    "Closing safely: waiting for owned workers and runtime cleanup".into()
                }),
                phase: NativeHostPhase::Closing,
                can_retry_close: self.app.all_tasks_idle(),
                ..NativeHostView::default()
            };
        }
        let current = self.app.ready_view.as_ref().filter(|_| {
            self.app.connected
                && self.app.status_rendered.is_some()
                && self.app.last_error.is_none()
        });
        let status = match current {
            Some(view) => format!(
                "Verified runtime · session {} · generation {} · revision {} · {} modules",
                view.session_id,
                view.generation,
                view.revision,
                view.modules.len()
            ),
            None => self
                .app
                .last_error
                .clone()
                .unwrap_or_else(|| "Verifying runtime view".into()),
        };
        NativeHostView {
            identity: current.map(identity),
            status,
            phase: if current.is_some() {
                NativeHostPhase::Connected
            } else {
                NativeHostPhase::Loading
            },
            can_retry_close: false,
            needs_rendered_callback: current.is_some()
                && (self.app.startup_recorder.is_some() || self.app.update_handoff.is_some()),
        }
    }

    fn observe_rendered(&mut self, rendered: &NativeViewIdentity, callback: u64) {
        if self.app.ready_view.as_ref().map(identity).as_ref() != Some(rendered) {
            self.app.readiness_frames.reset();
            return;
        }
        self.app.gui_frame = callback;
        // The existing witness still binds all six view axes and rechecks the
        // actual NativeShellRuntime on the supervised readiness worker.
        self.app.confirm_rendered_update_owner();
    }

    fn observe_renderer(&self, event: NativeRendererObservation) {
        observation(match event {
            NativeRendererObservation::StatusDrawList {
                identity,
                callback,
                glyph_count,
                status,
                status_rect,
                caption_close_rect,
                inner_size,
                dpi,
            } => serde_json::json!({
                "event": "status_draw_list", "identity": observation_identity(identity),
                "callback": callback, "glyphCount": glyph_count,
                "status": status, "statusRect": status_rect,
                "captionCloseRect": caption_close_rect, "innerSize": inner_size, "dpi": dpi,
            }),
            NativeRendererObservation::LaterCallback { identity, callback } => serde_json::json!({
                "event": "later_callback", "identity": observation_identity(identity), "callback": callback,
            }),
            NativeRendererObservation::CloseRequested { cause } => serde_json::json!({
                "event": "close_requested", "cause": cause,
            }),
        });
    }

    fn invalidate_rendered(&mut self) {
        self.app.readiness_frames.reset();
    }

    fn request_close(&mut self) {
        // This first vertical path exposes no file-picker/operation controls.
        // There is no renderer-local input intent to cancel in this adapter.
        self.app.request_shutdown_owner(|| {});
    }

    fn retry_close(&mut self) {
        if self.app.shutdown.requested()
            && !self.app.shutdown.runtime_closed
            && self.app.all_tasks_idle()
        {
            self.app.shutdown.close_started = false;
            self.app.shutdown.update_requested = false;
        }
    }

    fn rendering_failed(&mut self, detail: &str) {
        let reason_code = if detail.starts_with("Native embedded resource unavailable:") {
            "embedded_resource_unavailable"
        } else if detail == "GUI callback identity exhausted" {
            "callback_counter_exhausted"
        } else {
            "renderer_contract_failed"
        };
        // Emit a bounded code only. The detailed owner-facing error can contain
        // runtime paths and must not be copied into qualification artifacts.
        observation(serde_json::json!({
            "event": "renderer_failure", "reasonCode": reason_code,
        }));
        self.app.fail_readiness(detail.to_owned());
    }

    fn on_exit(&mut self) {
        self.app.finish_renderer_exit();
        observation(serde_json::json!({
            "event": "renderer_exit", "runtimeClosed": self.app.shutdown.runtime_closed,
            "allTasksIdle": self.app.all_tasks_idle(),
            "activationRequested": self.app.activate_update_on_exit.load(Ordering::Acquire),
        }));
    }
}

pub fn run_robrix(
    app: HeptaNativeApp,
    font_override: Option<Vec<u8>>,
) -> Result<(), Box<dyn std::error::Error>> {
    hepta_robrix_ui::native_host::run_native(
        Box::new(RobrixHost { app }),
        Box::new(move |cx| crate::native_assets::configure(cx, font_override)),
    )
    .map_err(Into::into)
}

#[cfg(test)]
#[path = "robrix_host_tests.rs"]
mod tests;
