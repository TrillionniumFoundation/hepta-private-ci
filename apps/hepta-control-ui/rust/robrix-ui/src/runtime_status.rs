//! Read-only runtime observations stay separate from chat owner admission.
use hepta_control_core::runtime_view::RuntimeReadState;
use hepta_control_core::runtime_view::RuntimeUnavailable;

pub(crate) struct RuntimeDisplay {
    pub(crate) text: String,
}
impl Default for RuntimeDisplay {
    fn default() -> Self {
        Self {
            text: RuntimeReadState::Unavailable(RuntimeUnavailable::NotConnected).display_text(),
        }
    }
}

#[cfg(target_arch = "wasm32")]
mod web {
    use super::RuntimeDisplay;
    use hepta_control_core::runtime_view::MAX_RUNTIME_JSON_BYTES;
    use hepta_control_core::runtime_view::RuntimeReader;
    use hepta_control_core::runtime_view::RuntimeUnavailable;
    use makepad_widgets::*;

    #[derive(Default)]
    pub(crate) struct RuntimeClient {
        reader: RuntimeReader,
        active: Option<(u64, LiveId)>,
        deadline: Timer,
        refresh: Timer,
        visible: bool,
        background: bool,
        closed: bool,
        epoch: Option<u64>,
    }

    impl RuntimeClient {
        pub(crate) fn handle_event(
            &mut self,
            cx: &mut Cx,
            ui: &WidgetRef,
            event: &Event,
            requested_visible: bool,
            epoch: u64,
        ) {
            match event {
                Event::Shutdown => self.closed = true,
                Event::Background => self.background = true,
                Event::Foreground => self.background = false,
                _ => {}
            }
            let visible = requested_visible && !self.background && !self.closed;
            if !visible || self.epoch != Some(epoch) {
                self.cancel(cx);
                self.visible = false;
                self.epoch = Some(epoch);
                self.publish(cx, ui);
            }
            if !visible {
                return;
            }
            if !self.visible {
                self.visible = true;
                self.start(cx, ui);
            }
            if self.refresh.is_event(event).is_some() {
                self.refresh = Timer::default();
                self.start(cx, ui);
            }
            if self.deadline.is_event(event).is_some()
                && let Some((ticket, request)) = self.active.take()
            {
                let _ = cx.net.http_cancel(request);
                self.reader.fail(ticket, RuntimeUnavailable::TimedOut);
                self.deadline = Timer::default();
                self.refresh = cx.start_timeout(15.0);
                self.publish(cx, ui);
            }
            if let (Some((ticket, request)), Event::NetworkResponses(responses)) =
                (self.active, event)
            {
                for response in responses {
                    let completed = match response {
                        NetworkResponse::HttpResponse {
                            request_id,
                            response,
                        } if *request_id == request => self.reader.complete(
                            ticket,
                            response.status_code,
                            response.body.as_deref().unwrap_or(&[]),
                        ),
                        NetworkResponse::HttpError { request_id, .. } if *request_id == request => {
                            self.reader.fail(ticket, RuntimeUnavailable::Transport)
                        }
                        _ => false,
                    };
                    if completed {
                        self.active = None;
                        cx.stop_timer(self.deadline);
                        self.deadline = Timer::default();
                        self.refresh = cx.start_timeout(15.0);
                        self.publish(cx, ui);
                        break;
                    }
                }
            }
        }

        fn start(&mut self, cx: &mut Cx, ui: &WidgetRef) {
            let Some(ticket) = self.reader.begin() else {
                return;
            };
            let request_id = LiveId(id!(hepta_read_only_runtime_status).0 ^ ticket);
            let mut request = HttpRequest::new("/api/hepta/runtime".to_owned(), Default::default());
            request.max_response_body_bytes = MAX_RUNTIME_JSON_BYTES as u64;
            request.set_header("Accept".to_owned(), "application/json".to_owned());
            match cx.net.http_start(request_id, request) {
                Ok(()) => {
                    self.active = Some((ticket, request_id));
                    self.deadline = cx.start_timeout(5.0);
                }
                Err(_) => {
                    self.reader.fail(ticket, RuntimeUnavailable::Transport);
                    self.refresh = cx.start_timeout(15.0);
                }
            }
            self.publish(cx, ui);
        }

        fn cancel(&mut self, cx: &mut Cx) {
            if let Some((_, request)) = self.active.take() {
                let _ = cx.net.http_cancel(request);
            }
            self.reader.disconnect();
            cx.stop_timer(self.deadline);
            cx.stop_timer(self.refresh);
            self.deadline = Timer::default();
            self.refresh = Timer::default();
        }

        fn publish(&self, cx: &mut Cx, ui: &WidgetRef) {
            let text = self.reader.state().display_text();
            if cx.global::<RuntimeDisplay>().text != text {
                cx.global::<RuntimeDisplay>().text = text.clone();
                ui.label(cx, ids!(console_status)).set_text(cx, &text);
                ui.label(cx, ids!(mobile_console_status))
                    .set_text(cx, &text);
                ui.redraw(cx);
            }
        }
    }
}

#[cfg(target_arch = "wasm32")]
pub(crate) use web::RuntimeClient;
