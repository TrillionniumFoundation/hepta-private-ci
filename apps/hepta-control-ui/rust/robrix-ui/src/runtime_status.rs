//! Read-only observations never admit a chat owner or grant mutation authority.
use hepta_control_core::owner_view::OwnerReadState;
use hepta_control_core::runtime_view::RuntimeReadState;
use hepta_control_core::runtime_view::RuntimeUnavailable;

/// A display projection, not an owner or command-admission capability.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ObservationCardPresentation {
    pub(crate) headline: &'static str,
    pub(crate) detail: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RuntimeDisplay {
    pub(crate) owner: ObservationCardPresentation,
    pub(crate) legacy: ObservationCardPresentation,
    pub(crate) native_note: String,
    pub(crate) busy: bool,
}
impl RuntimeDisplay {
    fn from_observations(owner: &OwnerReadState, legacy: &RuntimeReadState) -> Self {
        Self {
            owner: ObservationCardPresentation {
                headline: owner.observation_headline(),
                // Preserve every validated field, bounded failure reason and caveat.
                // Never recover typed state by parsing this human-readable text.
                detail: owner.display_text(),
            },
            legacy: ObservationCardPresentation {
                headline: match legacy {
                    RuntimeReadState::Unavailable(RuntimeUnavailable::NotConnected) => {
                        "Not requested"
                    }
                    RuntimeReadState::Unavailable(_) => "Unavailable",
                    RuntimeReadState::Loading => "Reading…",
                    RuntimeReadState::Ready(_) => "Snapshot received",
                },
                detail: legacy.display_text(),
            },
            native_note: String::new(),
            busy: false,
        }
    }
}
impl Default for RuntimeDisplay {
    fn default() -> Self {
        let mut display = Self::from_observations(
            &OwnerReadState::Unavailable(RuntimeUnavailable::NotConnected),
            &RuntimeReadState::Unavailable(RuntimeUnavailable::NotConnected),
        );
        if !cfg!(target_arch = "wasm32") {
            display.owner = ObservationCardPresentation {
                headline: "Unavailable on native",
                detail: "No native owner metadata bridge is installed.".to_owned(),
            };
            display.legacy = ObservationCardPresentation {
                headline: "Unavailable on native",
                detail: "Read-only runtime metadata is unavailable in this native product port."
                    .to_owned(),
            };
        }
        display
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
            let mut display =
                RuntimeDisplay::from_observations(self.owner.state(), self.legacy.state());
            display.busy = self.active.is_some();
            // This wording reflects the actual owner-then-legacy sequence only.
            if matches!(
                self.active,
                Some(Flight {
                    channel: Channel::Owner,
                    ..
                })
            ) {
                display.legacy.headline = "Waiting";
                display.legacy.detail = "Waiting for the owner observation request to finish. No current legacy status is shown.".to_owned();
            }
            if *cx.global::<RuntimeDisplay>() != display {
                let busy = display.busy;
                *cx.global::<RuntimeDisplay>() = display;
                ui.button(cx, ids!(owner_refresh)).set_enabled(cx, !busy);
                ui.button(cx, ids!(mobile_owner_refresh))
                    .set_enabled(cx, !busy);
                let caption = if busy {
                    "Reading observations…"
                } else {
                    "Refresh observations"
                };
                ui.button(cx, ids!(owner_refresh)).set_text(cx, caption);
                ui.button(cx, ids!(mobile_owner_refresh))
                    .set_text(cx, caption);
                ui.redraw(cx);
            }
        }
    }
}
#[cfg(target_arch = "wasm32")]
pub(crate) use web::RuntimeClient;
