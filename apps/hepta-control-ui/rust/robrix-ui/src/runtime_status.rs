//! Read-only observations never admit a chat owner or grant mutation authority.
use hepta_control_core::owner_view::OwnerReadState;
use hepta_control_core::runtime_view::RuntimeReadState;
use hepta_control_core::runtime_view::RuntimeUnavailable;

pub(crate) struct RuntimeDisplay {
    pub(crate) text: String,
    pub(crate) busy: bool,
}
impl Default for RuntimeDisplay {
    fn default() -> Self {
        if !cfg!(target_arch = "wasm32") {
            return Self {
                text: "Read-only metadata is unavailable in this native product port. No native owner bridge is installed; chat and commands remain unavailable.".to_owned(),
                busy: false,
            };
        }
        Self {
            text: format!(
                "{}\n\nLegacy runtime observation\n{}",
                OwnerReadState::Unavailable(RuntimeUnavailable::NotConnected).display_text(),
                RuntimeReadState::Unavailable(RuntimeUnavailable::NotConnected).display_text()
            ),
            busy: false,
        }
    }
}

#[cfg(target_arch = "wasm32")]
mod web {
    use super::RuntimeDisplay;
    use hepta_control_core::owner_view::MAX_OWNER_STATUS_BYTES;
    use hepta_control_core::owner_view::OwnerReader;
    use hepta_control_core::runtime_view::MAX_RUNTIME_JSON_BYTES;
    use hepta_control_core::runtime_view::RuntimeReader;
    use hepta_control_core::runtime_view::RuntimeUnavailable;
    use makepad_widgets::*;

    #[derive(Clone, Copy)]
    enum Channel {
        Owner,
        Legacy,
    }
    #[derive(Clone, Copy)]
    struct Flight {
        channel: Channel,
        ticket: u64,
        request: LiveId,
    }

    #[derive(Default)]
    pub(crate) struct RuntimeClient {
        owner: OwnerReader,
        legacy: RuntimeReader,
        active: Option<Flight>,
        next_request: u64,
        deadline: Timer,
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
            let refresh = matches!(event,Event::Actions(actions) if ui.button(cx,ids!(owner_refresh)).clicked(actions)||ui.button(cx,ids!(mobile_owner_refresh)).clicked(actions));
            if !self.visible {
                self.visible = true;
                self.publish(cx, ui);
            }
            if refresh && self.active.is_none() {
                self.owner.disconnect();
                self.legacy.disconnect();
                self.start(cx, ui, Channel::Owner);
            }
            if self.deadline.is_event(event).is_some()
                && let Some(flight) = self.active.take()
            {
                let _ = cx.net.http_cancel(flight.request);
                self.fail(flight, RuntimeUnavailable::TimedOut);
                self.deadline = Timer::default();
                self.publish(cx, ui);
                if matches!(flight.channel, Channel::Owner) {
                    self.start(cx, ui, Channel::Legacy);
                }
            }
            if let (Some(flight), Event::NetworkResponses(responses)) = (self.active, event) {
                for response in responses {
                    let completed = match response {
                        NetworkResponse::HttpResponse {
                            request_id,
                            response,
                        } if *request_id == flight.request => {
                            let body = response.body.as_deref().unwrap_or(&[]);
                            match flight.channel {
                                Channel::Owner => {
                                    self.owner
                                        .complete(flight.ticket, response.status_code, body)
                                }
                                Channel::Legacy => {
                                    self.legacy
                                        .complete(flight.ticket, response.status_code, body)
                                }
                            }
                        }
                        NetworkResponse::HttpError { request_id, .. }
                            if *request_id == flight.request =>
                        {
                            self.fail(flight, RuntimeUnavailable::Transport)
                        }
                        _ => false,
                    };
                    if completed {
                        self.active = None;
                        cx.stop_timer(self.deadline);
                        self.deadline = Timer::default();
                        self.publish(cx, ui);
                        if matches!(flight.channel, Channel::Owner) {
                            self.start(cx, ui, Channel::Legacy);
                        }
                        break;
                    }
                }
            }
        }
        fn fail(&mut self, flight: Flight, reason: RuntimeUnavailable) -> bool {
            match flight.channel {
                Channel::Owner => self.owner.fail(flight.ticket, reason),
                Channel::Legacy => self.legacy.fail(flight.ticket, reason),
            }
        }
        fn start(&mut self, cx: &mut Cx, ui: &WidgetRef, channel: Channel) {
            let (ticket, url, limit) = match channel {
                Channel::Owner => (
                    self.owner.begin(),
                    "/api/hepta/owner-status",
                    MAX_OWNER_STATUS_BYTES,
                ),
                Channel::Legacy => (
                    self.legacy.begin(),
                    "/api/hepta/runtime",
                    MAX_RUNTIME_JSON_BYTES,
                ),
            };
            let Some(ticket) = ticket else {
                self.publish(cx, ui);
                return;
            };
            let Some(next_request) = self.next_request.checked_add(1) else {
                match channel {
                    Channel::Owner => {
                        self.owner
                            .fail(ticket, RuntimeUnavailable::CounterExhausted);
                    }
                    Channel::Legacy => {
                        self.legacy
                            .fail(ticket, RuntimeUnavailable::CounterExhausted);
                    }
                }
                self.publish(cx, ui);
                return;
            };
            self.next_request = next_request;
            let flight = Flight {
                channel,
                ticket,
                request: LiveId(id!(hepta_read_only_observation_request).0 ^ next_request),
            };
            let mut request = HttpRequest::new(url.to_owned(), Default::default());
            request.max_response_body_bytes = limit as u64;
            request.set_header("Accept".to_owned(), "application/json".to_owned());
            match cx.net.http_start(flight.request, request) {
                Ok(()) => {
                    self.active = Some(flight);
                    self.deadline = cx.start_timeout(5.0);
                }
                Err(_) => {
                    self.fail(flight, RuntimeUnavailable::Transport);
                    if matches!(channel, Channel::Owner) {
                        self.start(cx, ui, Channel::Legacy);
                    }
                }
            }
            self.publish(cx, ui);
        }
        fn cancel(&mut self, cx: &mut Cx) {
            if let Some(flight) = self.active.take() {
                let _ = cx.net.http_cancel(flight.request);
            }
            self.owner.disconnect();
            self.legacy.disconnect();
            cx.stop_timer(self.deadline);
            self.deadline = Timer::default();
        }
        fn publish(&self, cx: &mut Cx, ui: &WidgetRef) {
            let text = format!(
                "{}\n\nLegacy runtime observation\n{}",
                self.owner.state().display_text(),
                self.legacy.state().display_text()
            );
            let busy = self.active.is_some();
            if cx.global::<RuntimeDisplay>().text != text
                || cx.global::<RuntimeDisplay>().busy != busy
            {
                cx.global::<RuntimeDisplay>().text = text.clone();
                cx.global::<RuntimeDisplay>().busy = busy;
                ui.button(cx, ids!(owner_refresh)).set_enabled(cx, !busy);
                ui.button(cx, ids!(mobile_owner_refresh))
                    .set_enabled(cx, !busy);
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
