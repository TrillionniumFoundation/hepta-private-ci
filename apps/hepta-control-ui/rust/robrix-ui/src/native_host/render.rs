use super::*;
use crate::native_status::NativeStatusWidgetRefExt;
use makepad_widgets::*;
use std::cell::Cell;
use std::cell::RefCell;
use std::rc::Rc;

#[derive(Default)]
struct RunOutcome {
    adopted: bool,
    exited: bool,
}

type ConfigureResources = Box<dyn FnOnce(&mut Cx)>;

struct Setup {
    host: Box<dyn NativeHost>,
    resources: Option<ConfigureResources>,
    outcome: Rc<RefCell<RunOutcome>>,
}

thread_local! {
    static RUNNING: Cell<bool> = const { Cell::new(false) };
    static PENDING: RefCell<Option<Setup>> = const { RefCell::new(None) };
}

#[derive(Default)]
struct HostSlot(Option<Setup>);

/// A Linux development runner. The stock Windows loop terminates the process;
/// it cannot yet preserve the native main's post-loop update-helper handoff.
#[cfg(target_os = "linux")]
pub fn run_native(host: Box<dyn NativeHost>, resources: ConfigureResources) -> Result<(), String> {
    if RUNNING.with(|running| running.replace(true)) {
        return Err("a native Robrix host is already running on this thread".into());
    }
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            PENDING.with(|slot| slot.borrow_mut().take());
            RUNNING.with(|running| running.set(false));
        }
    }
    let _reset = Reset;
    let outcome = Rc::new(RefCell::new(RunOutcome::default()));
    PENDING.with(|slot| {
        *slot.borrow_mut() = Some(Setup {
            host,
            resources: Some(resources),
            outcome: Rc::clone(&outcome),
        });
    });
    crate::app::app_main();
    let outcome = outcome.borrow();
    if !outcome.adopted || !outcome.exited {
        return Err("native Robrix host did not complete its renderer lifecycle".into());
    }
    Ok(())
}

pub(crate) fn configure(cx: &mut Cx) {
    if let Some(mut setup) = PENDING.with(|slot| slot.borrow_mut().take()) {
        setup
            .resources
            .take()
            .expect("native resources are configured once")(cx);
        setup.host.set_waker(Arc::new(SignalToUI::set_ui_signal));
        cx.set_global(HostSlot(Some(setup)));
    }
}

#[derive(Default)]
pub(crate) struct RendererHost {
    host: Option<Box<dyn NativeHost>>,
    outcome: Option<Rc<RefCell<RunOutcome>>>,
    view: NativeHostView,
    callback: u64,
    pending_frame: Option<(NextFrame, NativeViewIdentity)>,
    backgrounded: bool,
    paused: bool,
    unfocused: bool,
    close_sent: bool,
    resource_failure: bool,
    poll_timer: Timer,
    last_readiness_block: Cell<Option<&'static str>>,
}

impl RendererHost {
    pub(crate) fn adopt(&mut self, cx: &mut Cx) {
        if let Some(setup) = cx.global::<HostSlot>().0.take() {
            setup.outcome.borrow_mut().adopted = true;
            self.host = Some(setup.host);
            self.outcome = Some(setup.outcome);
            // A completion signal can arrive just before JoinHandle becomes
            // finished. Keep the legacy 250 ms bounded nonblocking poll fallback.
            self.poll_timer = cx.start_interval(0.25);
        }
    }

    pub(crate) fn before_event(&mut self, cx: &mut Cx, ui: &WidgetRef, event: &Event) -> bool {
        // Defer owner polling, widget setters and redraw requests to callbacks
        // outside Draw dispatch. Root owns the current draw traversal.
        if matches!(event, Event::Draw(_)) {
            return false;
        }
        let Some(host) = self.host.as_mut() else {
            return false;
        };
        let window_id = ui.window(cx, ids!(main_window)).window_id();
        let invalidated = match event {
            Event::Background => {
                self.backgrounded = true;
                true
            }
            Event::Foreground => {
                self.backgrounded = false;
                true
            }
            Event::Pause => {
                self.paused = true;
                true
            }
            Event::Resume => {
                self.paused = false;
                true
            }
            Event::WindowLostFocus(id) if Some(*id) == window_id => {
                self.unfocused = true;
                true
            }
            Event::WindowGotFocus(id) if Some(*id) == window_id => {
                self.unfocused = false;
                true
            }
            Event::WindowGeomChange(change) => Some(change.window_id) == window_id,
            Event::WindowClosed(closed) => Some(closed.window_id) == window_id,
            Event::LiveEdit | Event::ScriptReapply => true,
            _ => false,
        };
        if invalidated {
            self.pending_frame = None;
            host.invalidate_rendered();
        }
        if !self.resource_failure {
            use makepad_platform::script::res::CxScriptResourceData;
            let missing = cx
                .script_data
                .resources
                .resources
                .borrow()
                .iter()
                .find(|resource| !matches!(resource.data, CxScriptResourceData::Loaded(_)))
                .map(|resource| {
                    resource
                        .dependency_path
                        .clone()
                        .unwrap_or_else(|| resource.abs_path.clone())
                });
            if let Some(missing) = missing {
                self.resource_failure = true;
                host.rendering_failed(&format!("Native embedded resource unavailable: {missing}"));
            }
        }
        let mut consume = false;
        match event {
            Event::WindowCloseRequested(request) if window_id == Some(request.window_id) => {
                request.accept_close.set(false);
                host.request_close();
                host.observe_renderer(NativeRendererObservation::CloseRequested { cause: "os" });
            }
            Event::QuitRequested(request) => {
                request.handle();
                host.request_close();
                host.observe_renderer(NativeRendererObservation::CloseRequested { cause: "quit" });
            }
            Event::Actions(actions) => {
                // Stock Window caption buttons queue CloseWindow directly,
                // bypassing WindowCloseRequested. Consume before Root sees it.
                if ui
                    .desktop_button(cx, ids!(main_window.windows_buttons.close))
                    .clicked(actions)
                {
                    host.request_close();
                    host.observe_renderer(NativeRendererObservation::CloseRequested {
                        cause: "caption",
                    });
                    consume = true;
                } else if ui.button(cx, ids!(native_retry_close)).clicked(actions) {
                    host.retry_close();
                }
            }
            Event::Shutdown => {
                host.on_exit();
                cx.stop_timer(self.poll_timer);
                if let Some(outcome) = &self.outcome {
                    outcome.borrow_mut().exited = true;
                }
            }
            _ => {}
        }
        let observed = host.poll();
        if observed != self.view {
            self.pending_frame = None;
            host.invalidate_rendered();
            self.view = observed;
            ui.view(cx, ids!(native_host_panel)).set_visible(cx, true);
            ui.widget(cx, ids!(native_host_status))
                .set_text(cx, &self.view.status);
            let missing = "Linux development host: authenticated startup status and safe close are connected. Operation binding, final-use actions, reconciliation/history controls, update staging/activation controls and accessibility settings are not yet composed here. Chat Send remains unavailable without its independent writer owner.";
            ui.label(cx, ids!(console_status)).set_text(cx, missing);
            ui.label(cx, ids!(mobile_console_status))
                .set_text(cx, missing);
            ui.button(cx, ids!(native_retry_close))
                .set_visible(cx, self.view.can_retry_close);
            ui.view(cx, ids!(native_content)).set_visible(
                cx,
                !matches!(
                    self.view.phase,
                    NativeHostPhase::Closing | NativeHostPhase::Closed
                ),
            );
            ui.redraw(cx);
        }
        if self.view.phase == NativeHostPhase::Closed && !self.close_sent {
            self.close_sent = true;
            ui.window(cx, ids!(main_window)).close(cx);
        }
        if self.poll_timer.is_event(event).is_some()
            && self.view.needs_rendered_callback
            && self.pending_frame.is_none()
            && !self.backgrounded
            && !self.paused
            && !self.unfocused
        {
            // A clipped or unsupported glyph path must not create an unbounded
            // NextFrame/redraw loop. Reuse the retained 250 ms owner poll cadence.
            ui.redraw(cx);
        }
        if let Some((token, identity)) = &self.pending_frame
            && token.is_event(event).is_some()
        {
            let identity = identity.clone();
            self.pending_frame = None;
            if self.view.identity.as_ref() == Some(&identity)
                && let Some(callback) = self.observe(&identity)
            {
                self.host.as_ref().unwrap().observe_renderer(
                    NativeRendererObservation::LaterCallback { identity, callback },
                );
            }
        }
        consume
    }

    fn observe(&mut self, identity: &NativeViewIdentity) -> Option<u64> {
        let host = self.host.as_mut()?;
        let Some(callback) = self.callback.checked_add(1) else {
            host.rendering_failed("GUI callback identity exhausted");
            return None;
        };
        self.callback = callback;
        host.observe_rendered(identity, callback);
        Some(callback)
    }

    pub(crate) fn after_draw(&mut self, cx: &mut Cx, ui: &WidgetRef) {
        macro_rules! reject {
            ($reason:literal) => {{
                if self.last_readiness_block.replace(Some($reason)) != Some($reason)
                    && let Some(host) = self.host.as_ref()
                {
                    host.observe_renderer(NativeRendererObservation::ReadinessBlocked {
                        reason: $reason,
                    });
                }
                return;
            }};
        }
        let Some(identity) = self.view.identity.clone() else {
            reject!("owner_identity_missing");
        };
        if self.view.phase != NativeHostPhase::Connected || !self.view.needs_rendered_callback {
            reject!("owner_callback_not_requested");
        }
        // A new draw can change attachment or clipping without changing owner
        // identity. It must obtain its own later callback, never complete the
        // previous draw's witness by itself.
        self.pending_frame = None;
        self.host.as_mut().unwrap().invalidate_rendered();
        if self.backgrounded || self.paused || self.unfocused {
            reject!("window_inactive");
        }
        let window = ui.window(cx, ids!(main_window));
        let Some(window_id) = window.window_id() else {
            reject!("window_id_missing");
        };
        let Some(pass) = cx.windows[window_id].main_pass_id else {
            reject!("main_pass_missing");
        };
        let label_ref = ui.native_status(cx, ids!(native_host_status));
        let Some(label) = label_ref.borrow() else {
            reject!("status_widget_missing");
        };
        if label.text() != self.view.status {
            reject!("status_text_mismatch");
        }
        let area = label.draw_text.draw_vars.area;
        let Some(instance) = area.valid_instance(cx).copied() else {
            reject!("status_instances_missing");
        };
        if label.expected_ink != Some(instance.instance_count) {
            reject!("glyph_count_mismatch");
        }
        let Some(shader_id) = label.draw_text.draw_vars.draw_shader_id else {
            reject!("shader_id_missing");
        };
        let Some(shader) = cx.draw_shaders.shaders.get(shader_id.index) else {
            reject!("shader_missing");
        };
        let stride = shader.mapping.instances.total_slots;
        let Some(dpi) = cx.passes[pass]
            .display_dpi_factor
            .or(cx.passes[pass].dpi_factor)
        else {
            reject!("dpi_missing");
        };
        let font_size = label.draw_text.text_style.font_size;
        let font_scale = label.draw_text.font_scale;
        if !font_size.is_finite()
            || font_size <= 0.0
            || !font_scale.is_finite()
            || font_scale <= 0.0
            || !dpi.is_finite()
            || dpi <= 0.0
        {
            reject!("invalid_font_metrics");
        }
        let dpx_per_em = font_size * (96.0 / 72.0) * dpi as f32;
        let Some(fonts) = cx.get_global_ref::<Rc<RefCell<makepad_draw::text::fonts::Fonts>>>()
        else {
            reject!("font_state_missing");
        };
        // A mixed SLUG/raster label may publish only its last raster batch.
        // This first native witness admits the complete ordinary raster path.
        if !dpx_per_em.is_finite() || fonts.borrow().should_use_slug_glyph(dpx_per_em) {
            reject!("unsupported_glyph_path");
        }
        let attached = cx.attached_draw_lists(pass);
        if stride == 0 || !area.is_attached(cx, &attached) {
            reject!("status_not_attached");
        }
        let size = window.get_inner_size(cx);
        let list = &cx.draw_lists[instance.draw_list_id];
        let shift = if list.draw_list_has_clip {
            let shift = list.draw_list_uniforms.view_shift;
            dvec2(shift.x as f64, shift.y as f64)
        } else {
            dvec2(0.0, 0.0)
        };
        for index in 0..instance.instance_count {
            let Some(offset) = index
                .checked_mul(stride)
                .and_then(|n| instance.instance_offset.checked_add(n))
            else {
                reject!("instance_offset_overflow");
            };
            let glyph = Area::Instance(InstanceArea {
                instance_offset: offset,
                instance_count: 1,
                ..instance
            });
            let rect = glyph.rect(cx).translate(shift);
            let clipped = glyph.clipped_rect(cx);
            let finite = [
                rect.pos.x,
                rect.pos.y,
                rect.size.x,
                rect.size.y,
                clipped.pos.x,
                clipped.pos.y,
                clipped.size.x,
                clipped.size.y,
                size.x,
                size.y,
            ]
            .into_iter()
            .all(f64::is_finite);
            if !finite
                || rect.size.x <= 0.0
                || rect.size.y <= 0.0
                || rect.pos.x < 0.0
                || rect.pos.y < 0.0
                || rect.pos.x + rect.size.x > size.x + 0.01
                || rect.pos.y + rect.size.y > size.y + 0.01
                || (rect.pos.x - clipped.pos.x).abs() > 0.01
                || (rect.pos.y - clipped.pos.y).abs() > 0.01
                || (rect.size.x - clipped.size.x).abs() > 0.01
                || (rect.size.y - clipped.size.y).abs() > 0.01
            {
                reject!("glyph_clipped_or_invalid");
            }
        }
        drop(label);
        // Root has returned and its draw lists are attached. Record this exact
        // visible identity now; only our matching later NextFrame can witness
        // callback return. Neither event is a GPU-success acknowledgement.
        let Some(callback) = self.observe(&identity) else {
            reject!("callback_failed");
        };
        let caption = ui.desktop_button(cx, ids!(main_window.windows_buttons.close));
        let caption_area = caption.area();
        let rect = caption_area.clipped_rect(cx);
        let caption_close_rect = (caption_area.is_attached(cx, &attached)
            && rect.size.x > 0.0
            && rect.size.y > 0.0
            && [rect.pos.x, rect.pos.y, rect.size.x, rect.size.y]
                .into_iter()
                .all(f64::is_finite))
        .then_some([rect.pos.x, rect.pos.y, rect.size.x, rect.size.y]);
        self.host
            .as_ref()
            .unwrap()
            .observe_renderer(NativeRendererObservation::StatusDrawList {
                identity: identity.clone(),
                callback,
                glyph_count: instance.instance_count,
                status: self.view.status.clone(),
                status_rect: {
                    let rect = area.clipped_rect_union_attached(cx);
                    [rect.pos.x, rect.pos.y, rect.size.x, rect.size.y]
                },
                caption_close_rect,
                inner_size: [size.x, size.y],
                dpi,
            });
        self.last_readiness_block.set(None);
        self.pending_frame = Some((cx.new_next_frame(), identity));
    }
}
