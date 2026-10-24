use super::NativeChatComposition;
use super::OwnedComposition;
use super::bounded_console;
use super::chat_controls::ChatIntent;
use super::chat_controls::Controls;
use crate::native_launch::LaunchMode;
use crate::native_launch::RunOutcome;
use crate::presentation::RoomKey;
use hepta_control_core::chat::WorkspaceTab;
use makepad_widgets::*;
use std::cell::RefCell;
use std::rc::Rc;

/// Run the original App with the caller's sole draft/state owner. This Linux
/// development mode is neither a NativeHost witness nor production chat send.
/// Resources are configured before the original script registers/loads them.
#[cfg(target_os = "linux")]
pub fn run_native_presentation(
    composition: Box<dyn NativeChatComposition>,
    resources: Box<dyn FnOnce(&mut Cx)>,
) -> Result<(), String> {
    let composition = OwnedComposition::new(composition);
    if cfg!(feature = "ui-fixtures") {
        return Err("native presentation cannot adopt live state with ui-fixtures enabled".into());
    }
    crate::native_launch::run(LaunchMode::Presentation(composition), resources)
}

#[derive(Default)]
pub(crate) struct RendererPresentation {
    outcome: Option<Rc<RefCell<RunOutcome>>>,
    timer: Timer,
    closed: bool,
    checked_resources: bool,
    failed: bool,
    #[cfg(target_os = "linux")]
    accessibility: Option<super::accessibility::NativeAccessibility>,
}

impl RendererPresentation {
    pub(crate) fn adopt(&mut self, cx: &mut Cx, outcome: Rc<RefCell<RunOutcome>>) {
        outcome.borrow_mut().adopted = true;
        self.outcome = Some(outcome);
        // Completion signals are coalesced by the SDK. The bounded timer also
        // reevaluates age when the session is silent; it never renews a sample.
        self.timer = cx.start_interval(0.25);
        #[cfg(target_os = "linux")]
        {
            self.accessibility = Some(super::accessibility::NativeAccessibility::new());
        }
    }

    pub(crate) fn before_event(
        &mut self,
        cx: &mut Cx,
        ui: &WidgetRef,
        event: &Event,
        composition: &mut OwnedComposition,
    ) -> bool {
        if matches!(event, Event::Draw(_)) {
            return self.failed;
        }
        let window_id = ui.window(cx, ids!(main_window)).window_id();
        let shutting_down = matches!(event, Event::Shutdown);
        let window_closed =
            matches!(event, Event::WindowClosed(closed) if Some(closed.window_id) == window_id);
        if shutting_down || window_closed {
            #[cfg(target_os = "linux")]
            {
                self.accessibility = None;
            }
            composition.exit();
            self.closed = true;
            cx.stop_timer(self.timer);
            self.timer = Timer::default();
            if shutting_down && let Some(outcome) = &self.outcome {
                outcome.borrow_mut().exited = true;
            }
            return false;
        }
        #[cfg(target_os = "linux")]
        if let Some(accessibility) = &mut self.accessibility {
            accessibility.before_event(cx, ui, event, composition.inner.workspace_mut());
        }
        if matches!(event, Event::LiveEdit | Event::ScriptReapply) {
            self.checked_resources = false;
        }
        if !self.closed && !self.checked_resources {
            use makepad_widgets::makepad_platform::script::res::CxScriptResourceData;
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
                self.failed = true;
                self.closed = true;
                composition.exit();
                cx.stop_timer(self.timer);
                self.timer = Timer::default();
                if let Some(outcome) = &self.outcome {
                    outcome.borrow_mut().error = Some(format!(
                        "Native presentation resource unavailable: {missing}"
                    ));
                }
                // A missing font/resource cannot be reported as a usable App.
                // This closes only the UI event loop, never a runtime owner.
                cx.quit();
                return true;
            }
            self.checked_resources = true;
        }
        false
    }

    pub(crate) fn after_event(
        &mut self,
        cx: &mut Cx,
        ui: &WidgetRef,
        event: &Event,
        composition: &mut OwnedComposition,
    ) {
        #[cfg(target_os = "linux")]
        if matches!(event, Event::Draw(_))
            && !self.closed
            && let Some(accessibility) = &mut self.accessibility
        {
            accessibility.after_draw(cx, ui, composition.inner.workspace());
        }
        if self.closed || matches!(event, Event::Draw(_)) {
            return;
        }
        if let Event::Actions(actions) = event {
            for action in actions.iter() {
                let controls = cx.global::<Controls>().clone();
                let result = match action.as_widget_action().cast::<ChatIntent>() {
                    ChatIntent::Submit(room)
                        if controls.permits_submit(room, composition.inner.workspace()) =>
                    {
                        composition.inner.request_send(room)
                    }
                    ChatIntent::Interrupt(room)
                        if controls.permits_interrupt(room, composition.inner.workspace()) =>
                    {
                        composition.inner.request_interrupt(room)
                    }
                    ChatIntent::EarlierHistory(room)
                        if controls
                            .permits_earlier_history(room, composition.inner.workspace()) =>
                    {
                        composition.inner.request_earlier_history(room)
                    }
                    ChatIntent::LatestHistory(room)
                        if controls.permits_latest_history(room, composition.inner.workspace()) =>
                    {
                        composition.inner.request_latest_history(room)
                    }
                    ChatIntent::Approval(room, id, decision)
                        if controls.permits_approval(
                            room,
                            &id,
                            decision,
                            composition.inner.workspace(),
                        ) =>
                    {
                        composition.inner.request_approval(room, &id, decision)
                    }
                    _ => continue,
                };
                if let Err(error) = result {
                    composition.inner.workspace_mut().presentation_note = Some(error);
                }
            }
        }
        let availability = composition.inner.poll_chat();
        let approval = composition.inner.pending_approval();
        let workspace = composition.inner.workspace();
        let controls = Controls {
            room: Some(RoomKey {
                epoch: workspace.presentation_epoch(),
                local_id: workspace.active_id(),
            }),
            availability,
            approval,
        };
        if *cx.global::<Controls>() != controls {
            *cx.global::<Controls>() = controls;
            ui.redraw(cx);
        }
        if matches!(event, Event::Signal) || self.timer.is_event(event).is_some() {
            // Timeline deltas need a repaint even while capabilities remain
            // unchanged. This uses the existing bounded poll/signal cadence.
            ui.redraw(cx);
        }
        // Inspect refresh only after the original ImeRouter/widget dispatch.
        // No second key/IME pipeline is installed by the Desktop adapter.
        let workspace = composition.inner.workspace();
        let refresh_visible = workspace.tab == WorkspaceTab::Console
            && !workspace.navigation_open
            && !workspace.composing;
        let refresh = refresh_visible
            && matches!(event, Event::Actions(actions)
            if ui.button(cx, ids!(owner_refresh)).clicked(actions)
            || ui.button(cx, ids!(mobile_owner_refresh)).clicked(actions));
        if refresh {
            composition.inner.request_refresh();
        }
        if refresh
            || matches!(event, Event::Startup | Event::Signal)
            || self.timer.is_event(event).is_some()
        {
            let observation = bounded_console(composition.inner.poll_console());
            crate::runtime_status::publish_native(cx, ui, observation);
        }
    }
}
